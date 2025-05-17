# slack.py

import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urlencode
from dotenv import load_dotenv
import dateutil.parser

load_dotenv()

import aiohttp
from fastapi import HTTPException, Request
from redis_client import redis_client

from .integration_item import IntegrationItem

# HubSpot API configuration
HUBSPOT_CLIENT_ID = os.getenv("HUBSPOT_CLIENT_ID")
HUBSPOT_CLIENT_SECRET = os.getenv("HUBSPOT_CLIENT_SECRET")
HUBSPOT_REDIRECT_URI = os.getenv("HUBSPOT_REDIRECT_URI", "http://localhost:8000/integrations/hubspot/oauth2callback")
HUBSPOT_SCOPES = [
    "crm.objects.companies.read",
    "crm.objects.contacts.read",
    "crm.objects.contacts.write",
    "crm.schemas.contacts.read",
    "crm.schemas.contacts.write",
    "oauth"
]
HUBSPOT_AUTH_URL = "https://app.hubspot.com/oauth/authorize"
HUBSPOT_TOKEN_URL = "https://api.hubapi.com/oauth/v1/token"
HUBSPOT_API_BASE = "https://api.hubapi.com"

async def authorize_hubspot(user_id: str, org_id: str) -> Dict[str, str]:
    """
    Start the OAuth2 flow for HubSpot by generating the authorization URL.
    """
    if not HUBSPOT_CLIENT_ID or not HUBSPOT_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="HubSpot client configuration is missing")

    state = f"{user_id}:{org_id}"
    await redis_client.setex(f"hubspot_state:{state}", 3600, "1")  # Expires in 1 hour

    # Generate authorization URL
    params = {
        "client_id": HUBSPOT_CLIENT_ID,
        "redirect_uri": HUBSPOT_REDIRECT_URI,
        "scope": " ".join(HUBSPOT_SCOPES),
        "state": state,
    }
    auth_url = f"{HUBSPOT_AUTH_URL}?{urlencode(params)}"
    
    return {"auth_url": auth_url}

async def oauth2callback_hubspot(request: Request) -> Dict[str, str]:
    """
    Handle the OAuth2 callback from HubSpot.
    """
    # Get query parameters
    params = dict(request.query_params)
    code = params.get("code")
    state = params.get("state")
    error = params.get("error")

    if error:
        raise HTTPException(status_code=400, detail=f"HubSpot authorization error: {error}")

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing required parameters")

    # Verify state
    stored_state = await redis_client.get(f"hubspot_state:{state}")
    if not stored_state:
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    # Exchange code for access token
    async with aiohttp.ClientSession() as session:
        async with session.post(
            HUBSPOT_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": HUBSPOT_CLIENT_ID,
                "client_secret": HUBSPOT_CLIENT_SECRET,
                "redirect_uri": HUBSPOT_REDIRECT_URI,
                "code": code,
            },
        ) as response:
            if response.status != 200:
                raise HTTPException(status_code=400, detail="Failed to get access token")
            
            token_data = await response.json()

    # Store the credentials
    user_id, org_id = state.split(":")
    credentials = {
        "access_token": token_data["access_token"],
        "refresh_token": token_data.get("refresh_token"),
        "expires_in": token_data["expires_in"],
        "token_type": token_data["token_type"],
    }
    
    await redis_client.set(
        f"hubspot_credentials:{user_id}:{org_id}",
        json.dumps(credentials)
    )

    return {"message": "Successfully authenticated with HubSpot"}

async def get_hubspot_credentials(user_id: str, org_id: str) -> Optional[Dict[str, str]]:
    """
    Retrieve stored HubSpot credentials for a user/org.
    """
    credentials = await redis_client.get(f"hubspot_credentials:{user_id}:{org_id}")
    if not credentials:
        return None
    return json.loads(credentials)

async def refresh_access_token(refresh_token: str) -> Dict[str, str]:
    """
    Refresh the HubSpot access token using the refresh token.
    """
    async with aiohttp.ClientSession() as session:
        async with session.post(
            HUBSPOT_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": HUBSPOT_CLIENT_ID,
                "client_secret": HUBSPOT_CLIENT_SECRET,
                "refresh_token": refresh_token,
            },
        ) as response:
            if response.status != 200:
                raise HTTPException(status_code=400, detail="Failed to refresh access token")
            
            return await response.json()

async def get_items_hubspot(credentials_str: str) -> List[IntegrationItem]:
    """
    Fetch contacts and companies from HubSpot and return them as IntegrationItems.
    """
    print("\n=== FETCHING HUBSPOT DATA ===")
    
    credentials = json.loads(credentials_str)
    access_token = credentials["access_token"]
    
    items = []
    
    # Helper function to make authenticated requests
    async def make_request(endpoint: str) -> Dict:
        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
            async with session.get(f"{HUBSPOT_API_BASE}/{endpoint}", headers=headers) as response:
                if response.status == 401 and credentials.get("refresh_token"):
                    print("Token expired, refreshing...")
                    new_tokens = await refresh_access_token(credentials["refresh_token"])
                    headers["Authorization"] = f"Bearer {new_tokens['access_token']}"
                    async with session.get(f"{HUBSPOT_API_BASE}/{endpoint}", headers=headers) as retry_response:
                        return await retry_response.json()
                elif response.status != 200:
                    raise HTTPException(status_code=response.status, detail="Failed to fetch HubSpot data")
                return await response.json()

    # Helper function to parse ISO datetime
    def parse_datetime(date_str: str) -> datetime:
        return dateutil.parser.parse(date_str)

    # Fetch contacts
    print("\n--- Fetching Contacts ---")
    contacts_response = await make_request("crm/v3/objects/contacts")
    print(f"Found {len(contacts_response.get('results', []))} contacts")
    
    for contact in contacts_response.get("results", []):
        name = f"{contact['properties'].get('firstname', '')} {contact['properties'].get('lastname', '')}".strip()
        print(f"Contact: {name}")
        print(f"  ID: {contact['id']}")
        print(f"  Created: {contact['createdAt']}")
        print(f"  Updated: {contact['updatedAt']}")
        
        items.append(
            IntegrationItem(
                id=contact["id"],
                type="contact",
                name=name,
                creation_time=parse_datetime(contact["createdAt"]),
                last_modified_time=parse_datetime(contact["updatedAt"]),
                url=f"https://app.hubspot.com/contacts/{contact['id']}",
            )
        )

    # Fetch companies
    print("\n--- Fetching Companies ---")
    companies_response = await make_request("crm/v3/objects/companies")
    print(f"Found {len(companies_response.get('results', []))} companies")
    
    for company in companies_response.get("results", []):
        name = company["properties"].get("name", "Unnamed Company")
        print(f"Company: {name}")
        print(f"  ID: {company['id']}")
        print(f"  Created: {company['createdAt']}")
        print(f"  Updated: {company['updatedAt']}")
        
        items.append(
            IntegrationItem(
                id=company["id"],
                type="company",
                name=name,
                creation_time=parse_datetime(company["createdAt"]),
                last_modified_time=parse_datetime(company["updatedAt"]),
                url=f"https://app.hubspot.com/companies/{company['id']}",
            )
        )

    print("\n=== SUMMARY ===")
    print(f"Total items fetched: {len(items)}")
    print(f"Contacts: {len([i for i in items if i.type == 'contact'])}")
    print(f"Companies: {len([i for i in items if i.type == 'company'])}")
    print("==============\n")

    return items

async def create_integration_item_metadata_object(response_json):
    # TODO
    pass
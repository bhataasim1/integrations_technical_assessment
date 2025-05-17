# slack.py

import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urlencode

import aiohttp
from fastapi import HTTPException, Request
from redis_client import redis_client

from .integration_item import IntegrationItem

# HubSpot API configuration
HUBSPOT_CLIENT_ID = os.getenv("HUBSPOT_CLIENT_ID", "ed5ce25e-18ae-477e-bd0f-6e129defcd3f")
HUBSPOT_CLIENT_SECRET = os.getenv("HUBSPOT_CLIENT_SECRET", "ea9b2c0f-8fdb-4637-bf66-a58fc13ec461")
HUBSPOT_REDIRECT_URI = os.getenv("HUBSPOT_REDIRECT_URI", "http://localhost:8000/integrations/hubspot/oauth2callback")
HUBSPOT_SCOPES = ["contacts", "crm.objects.contacts.read", "crm.objects.companies.read"]
HUBSPOT_AUTH_URL = "https://app.hubspot.com/oauth/authorize"
HUBSPOT_TOKEN_URL = "https://api.hubapi.com/oauth/v1/token"
HUBSPOT_API_BASE = "https://api.hubapi.com"

async def authorize_hubspot(user_id: str, org_id: str) -> Dict[str, str]:
    """
    Start the OAuth2 flow for HubSpot by generating the authorization URL.
    """
    if not HUBSPOT_CLIENT_ID or not HUBSPOT_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="HubSpot client configuration is missing")

    # Store user_id and org_id in Redis for the callback
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
                    # Token expired, refresh it
                    new_tokens = await refresh_access_token(credentials["refresh_token"])
                    headers["Authorization"] = f"Bearer {new_tokens['access_token']}"
                    async with session.get(f"{HUBSPOT_API_BASE}/{endpoint}", headers=headers) as retry_response:
                        return await retry_response.json()
                elif response.status != 200:
                    raise HTTPException(status_code=response.status, detail="Failed to fetch HubSpot data")
                return await response.json()

    # Fetch contacts
    contacts_response = await make_request("crm/v3/objects/contacts")
    for contact in contacts_response.get("results", []):
        items.append(
            IntegrationItem(
                id=contact["id"],
                type="contact",
                name=f"{contact['properties'].get('firstname', '')} {contact['properties'].get('lastname', '')}".strip(),
                creation_time=datetime.fromtimestamp(int(contact["createdAt"]) / 1000),
                last_modified_time=datetime.fromtimestamp(int(contact["updatedAt"]) / 1000),
                url=f"https://app.hubspot.com/contacts/{contact['id']}",
            )
        )

    # Fetch companies
    companies_response = await make_request("crm/v3/objects/companies")
    for company in companies_response.get("results", []):
        items.append(
            IntegrationItem(
                id=company["id"],
                type="company",
                name=company["properties"].get("name", "Unnamed Company"),
                creation_time=datetime.fromtimestamp(int(company["createdAt"]) / 1000),
                last_modified_time=datetime.fromtimestamp(int(company["updatedAt"]) / 1000),
                url=f"https://app.hubspot.com/companies/{company['id']}",
            )
        )

    return items

async def create_integration_item_metadata_object(response_json):
    # TODO
    pass
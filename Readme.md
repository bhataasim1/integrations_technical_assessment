# HubSpot Integration

## Setup

1. Create a new app in HubSpot
2. Add the following scopes:
    - crm.objects.companies.read
    - crm.objects.contacts.read
    - crm.objects.contacts.write
    - crm.schemas.contacts.read
    - crm.schemas.contacts.write
    - oauth
3. Add the following redirect URIs:
    - http://localhost:8000/integrations/hubspot/oauth2callback
4. Add the following client ID and client secret to the `.env` file:
    - HUBSPOT_CLIENT_ID=your-client-id
    - HUBSPOT_CLIENT_SECRET=your-client-secret
5. Run the server:
    - `cd backend`
    - `python -m venv .venv`
    - `source .venv/bin/activate`
    - `pip install -r requirements.txt` *Note: Python version is 3.11.9*
    - `uvicorn backend.main:app --reload`
6. Run the frontend:
    - `cd frontend`
    - `npm install`
    - `npm start`
7. Go to `http://localhost:3000` to test the integration.
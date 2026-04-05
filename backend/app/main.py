import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import engine
from .models import Base
from .services.groq_service import gemini
import requests

# Create all tables
Base.metadata.create_all(bind=engine)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="LeadGen AI",
    version="2.0.0",
    description="""
AI-powered B2B lead generation platform for Indian businesses.

## Authentication
- **Bearer JWT**: Use `POST /auth/login` to get a token, pass as `Authorization: Bearer <token>`
- **API Key**: Pass as `X-Api-Key: lga_live_...` header (Enterprise feature)

## API Guide
Visit [/api-guide](/api-guide) for a full human-readable guide with examples.
    """,
    openapi_tags=[
        {"name": "auth",       "description": "Login, register, user management"},
        {"name": "leads",      "description": "Lead CRUD, enrichment, CSV import/export"},
        {"name": "campaigns",  "description": "Campaign create and management"},
        {"name": "outreach",   "description": "Message generation and sending"},
        {"name": "agent",      "description": "Autonomous agent runs and job management"},
        {"name": "messages",   "description": "Message approval queue"},
        {"name": "analytics",  "description": "Funnel metrics, costs, health scores"},
        {"name": "reports",    "description": "Weekly email reports"},
        {"name": "webhooks",   "description": "SendGrid, Gupshup, Razorpay inbound events"},
        {"name": "payments",   "description": "Razorpay subscriptions and billing"},
        {"name": "demo",       "description": "Free audit / demo pipeline"},
        {"name": "public",     "description": "Public endpoints (no auth required)"},
        {"name": "enterprise", "description": "API keys, white-label, client webhooks (Pro/Enterprise)"},
        {"name": "docs",       "description": "API guide and documentation"},
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all routers
from .routes.auth import router as auth_router
from .routes.leads import router as leads_router
from .routes.campaigns import router as campaigns_router
from .routes.messages import router as messages_router, approval_router
from .routes.analytics import router as analytics_router
from .routes.agent import router as agent_router
from .routes.webhooks import router as webhooks_router
from .routes.reports import router as reports_router
from .routes.payments import router as payments_router
from .routes.public import router as public_router
from .routes.demo import router as demo_router
from .routes.enterprise import router as enterprise_router
from .routes.api_guide import router as api_guide_router

app.include_router(auth_router)
app.include_router(approval_router)
app.include_router(leads_router)
app.include_router(campaigns_router)
app.include_router(messages_router)
app.include_router(webhooks_router)
app.include_router(analytics_router)
app.include_router(agent_router)
app.include_router(reports_router)
app.include_router(payments_router)
app.include_router(public_router)
app.include_router(demo_router)
app.include_router(enterprise_router)
app.include_router(api_guide_router)

# ---------------------------------------------------------------------------
# Root & test endpoints
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return {
        "status": "LeadGen AI Agent v2.0",
        "features": [
            "auth", "sqlite", "duplicate_detection", "auto_follow_ups",
            "scheduled_scraping", "memory", "csv_export", "agent_mode"
        ]
    }


@app.get("/test-osm")
def test_osm(industry: str = "retail", city: str = "Mumbai"):
    from .services.scraper_service import get_city_bbox, search_osm_businesses
    bbox = get_city_bbox(city)
    leads = search_osm_businesses(industry, city, 5)
    return {"bbox": bbox, "leads_found": len(leads), "leads": leads}


@app.get("/test-apollo")
def test_apollo(industry: str = "retail", city: str = "Mumbai"):
    api_key = os.getenv("APOLLO_API_KEY", "")
    headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
    # Test 1: with location
    p1 = {"organization_locations": [f"{city}, India"], "q_keywords": industry, "page": 1, "per_page": 5}
    r1 = requests.post("https://api.apollo.io/api/v1/accounts/search", json=p1, headers=headers, timeout=15)
    # Test 2: without location
    p2 = {"q_keywords": f"{industry} India", "page": 1, "per_page": 5}
    r2 = requests.post("https://api.apollo.io/api/v1/accounts/search", json=p2, headers=headers, timeout=15)
    # Test 3: contacts search
    p3 = {"q_keywords": f"{industry} {city} India", "page": 1, "per_page": 5}
    r3 = requests.post("https://api.apollo.io/api/v1/contacts/search", json=p3, headers=headers, timeout=15)
    return {
        "with_location": {
            "total": r1.json().get("pagination", {}).get("total_entries", 0),
            "sample": [a.get("name") for a in r1.json().get("accounts", [])]
        },
        "without_location": {
            "total": r2.json().get("pagination", {}).get("total_entries", 0),
            "sample": [a.get("name") for a in r2.json().get("accounts", [])]
        },
        "contacts": {
            "total": r3.json().get("pagination", {}).get("total_entries", 0),
            "sample": [f"{c.get('first_name')} {c.get('last_name')} @ {c.get('organization_name')}" for c in r3.json().get("contacts", [])]
        }
    }


@app.get("/test-gemini")
def test_gemini():
    try:
        result = gemini("Say hello in one sentence.")
        return {"success": True, "response": result}
    except Exception as e:
        return {"success": False, "error": str(e)}

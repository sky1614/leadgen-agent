import json
import logging
import time
from collections import defaultdict
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger("public")
router = APIRouter(prefix="/public", tags=["public"])

# ── Simple in-memory rate limiter (10 requests / IP / hour) ──────────────────
_rate_store: dict = defaultdict(list)
_RATE_LIMIT = 10
_RATE_WINDOW = 3600  # seconds

def _check_rate_limit(ip: str):
    now = time.time()
    window_start = now - _RATE_WINDOW
    _rate_store[ip] = [t for t in _rate_store[ip] if t > window_start]
    if len(_rate_store[ip]) >= _RATE_LIMIT:
        raise HTTPException(429, "Too many requests. Please try again in an hour.")
    _rate_store[ip].append(now)


class DemoRequestBody(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    company: str
    industry: str
    city: str
    target_description: Optional[str] = None


@router.post("/demo-request")
async def public_demo_request(body: DemoRequestBody, request: Request):
    """Public endpoint — no auth. Creates demo and notifies admin."""
    ip = request.client.host if request.client else "unknown"
    _check_rate_limit(ip)

    try:
        from ..services.demo_service import create_demo
        target = body.target_description or f"{body.industry} businesses in {body.city}"
        demo_id = create_demo(
            prospect_name=body.company,
            industry=body.industry,
            city=body.city,
            target_description=target,
            requester_email=body.email,
            requester_phone=body.phone,
        )

        logger.info(json.dumps({
            "event": "public_demo_request",
            "demo_id": demo_id,
            "company": body.company,
            "industry": body.industry,
            "city": body.city,
            "email": body.email,
            "ip": ip,
            "timestamp": datetime.utcnow().isoformat(),
        }))

        # Notify admin via email (non-blocking, best-effort)
        try:
            import os
            from ..services.email_service import send_email
            admin_email = os.getenv("ADMIN_EMAIL", "")
            if admin_email:
                send_email(
                    to_email=admin_email,
                    subject=f"New Demo Request: {body.company} ({body.industry}, {body.city})",
                    body_html=f"""<p><strong>New demo request received!</strong></p>
<ul>
  <li>Name: {body.name}</li>
  <li>Email: {body.email}</li>
  <li>Phone: {body.phone or '—'}</li>
  <li>Company: {body.company}</li>
  <li>Industry: {body.industry}</li>
  <li>City: {body.city}</li>
</ul>
<p><a href="{os.getenv('WEBHOOK_BASE_URL','http://localhost:8000')}/demo/{demo_id}/report">
View Demo Report →</a></p>""",
                    body_text=f"New demo: {body.company} | {body.email} | {body.industry}, {body.city}",
                    from_email="noreply@leadgenai.in",
                    from_name="LeadGen AI System",
                )
        except Exception:
            pass

        return {
            "success": True,
            "demo_id": demo_id,
            "message": "Your free audit request has been received. We'll share results within 48 hours.",
            "report_url": f"/demo/{demo_id}/report",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(json.dumps({
            "event": "public_demo_request_error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }))
        raise HTTPException(500, "Failed to process your request. Please try again.")


@router.get("/plans")
def public_plans():
    """Public pricing plans — no auth required."""
    return {
        "plans": [
            {"tier": "starter", "name": "Starter", "monthly_inr": 15000, "quarterly_inr": 40500,
             "leads": 500, "emails": 1000, "wa": 1000},
            {"tier": "growth", "name": "Growth", "monthly_inr": 35000, "quarterly_inr": 94500,
             "leads": 2000, "emails": 5000, "wa": 5000},
            {"tier": "pro", "name": "Pro", "monthly_inr": 75000, "quarterly_inr": 202500,
             "leads": 10000, "emails": 20000, "wa": 20000},
        ]
    }

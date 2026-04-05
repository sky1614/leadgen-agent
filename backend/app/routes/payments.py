import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user
from ..models import UserDB, SubscriptionDB, PaymentDB, ClientDB

logger = logging.getLogger("payments")
router = APIRouter(prefix="/payments", tags=["payments"])


class CreateSubscriptionRequest(BaseModel):
    tier: str = "starter"
    billing_cycle: str = "monthly"
    contact_email: Optional[str] = None
    contact_name: Optional[str] = None


@router.post("/create-subscription")
def create_subscription(
    req: CreateSubscriptionRequest,
    db: Session = Depends(get_db),
    cu: UserDB = Depends(get_current_user),
):
    """Create a Razorpay subscription for the current user's client."""
    try:
        if not cu.client_id:
            raise HTTPException(400, "No client associated with this account")
        if req.tier not in ("starter", "growth", "pro"):
            raise HTTPException(400, f"Invalid tier: {req.tier}. Choose starter/growth/pro")
        if req.billing_cycle not in ("monthly", "quarterly"):
            raise HTTPException(400, "billing_cycle must be 'monthly' or 'quarterly'")

        from ..services.payment_service import create_subscription as _create
        result = _create(
            client_id=cu.client_id,
            tier=req.tier,
            billing_cycle=req.billing_cycle,
            contact_email=req.contact_email or cu.email,
            contact_name=req.contact_name or cu.name,
        )
        if "error" in result:
            raise HTTPException(400, result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(json.dumps({"event": "create_subscription_route_error",
                                 "error": str(e), "timestamp": datetime.utcnow().isoformat()}))
        raise HTTPException(500, str(e))


@router.get("/status")
def subscription_status(
    db: Session = Depends(get_db),
    cu: UserDB = Depends(get_current_user),
):
    """Get current subscription status for logged-in client."""
    try:
        if not cu.client_id:
            return {"status": "no_client", "plan": cu.plan}
        sub = db.query(SubscriptionDB).filter(
            SubscriptionDB.client_id == cu.client_id
        ).order_by(SubscriptionDB.created_at.desc()).first()
        client = db.query(ClientDB).filter(ClientDB.id == cu.client_id).first()
        if not sub:
            return {"status": "no_subscription", "plan_tier": client.plan_tier if client else "free"}
        return {
            "status": sub.status,
            "plan_tier": sub.plan_tier,
            "billing_cycle": sub.billing_cycle,
            "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
            "trial_end": sub.trial_end.isoformat() if sub.trial_end else None,
            "grace_period_end": sub.grace_period_end.isoformat() if sub.grace_period_end else None,
            "razorpay_subscription_id": sub.razorpay_subscription_id,
        }
    except Exception as e:
        logger.error(json.dumps({"event": "subscription_status_error", "error": str(e)}))
        raise HTTPException(500, str(e))


@router.post("/{subscription_id}/cancel")
def cancel_subscription(
    subscription_id: str,
    at_period_end: bool = True,
    db: Session = Depends(get_db),
    cu: UserDB = Depends(get_current_user),
):
    """Cancel a subscription. at_period_end=True means it stays active until period ends."""
    try:
        sub = db.query(SubscriptionDB).filter(
            SubscriptionDB.id == subscription_id,
            SubscriptionDB.client_id == cu.client_id,
        ).first()
        if not sub:
            raise HTTPException(404, "Subscription not found")
        from ..services.payment_service import cancel_subscription as _cancel
        result = _cancel(cu.client_id, sub.razorpay_subscription_id, at_period_end)
        if "error" in result:
            raise HTTPException(400, result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/invoices/{client_id}")
def get_invoices(
    client_id: str,
    db: Session = Depends(get_db),
    cu: UserDB = Depends(get_current_user),
):
    """List all paid invoices for a client."""
    try:
        if cu.client_id and cu.client_id != client_id and cu.role != "superadmin":
            raise HTTPException(403, "Access denied")
        from ..services.payment_service import get_client_invoices
        return {"invoices": get_client_invoices(client_id)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/portal/{client_id}")
def payment_portal(
    client_id: str,
    db: Session = Depends(get_db),
    cu: UserDB = Depends(get_current_user),
):
    """Returns the Razorpay customer portal link for updating card/viewing invoices."""
    try:
        if cu.client_id and cu.client_id != client_id and cu.role != "superadmin":
            raise HTTPException(403, "Access denied")
        sub = db.query(SubscriptionDB).filter(
            SubscriptionDB.client_id == client_id
        ).order_by(SubscriptionDB.created_at.desc()).first()
        if not sub or not sub.razorpay_subscription_id:
            return {"portal_url": None, "message": "No active subscription found"}
        # Razorpay does not have a hosted portal URL — return the subscription page
        portal_url = f"https://dashboard.razorpay.com/app/subscriptions/{sub.razorpay_subscription_id}"
        return {"portal_url": portal_url, "subscription_id": sub.razorpay_subscription_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/plans")
def list_plans():
    """Returns all available plans and pricing. Public endpoint."""
    return {
        "plans": [
            {
                "tier": "starter", "name": "Starter",
                "monthly_inr": 15000, "quarterly_inr": 40500,
                "features": ["500 leads/month", "1,000 emails/month", "1,000 WA messages/month",
                             "AI enrichment", "Approval queue", "Weekly reports"]
            },
            {
                "tier": "growth", "name": "Growth",
                "monthly_inr": 35000, "quarterly_inr": 94500,
                "features": ["2,000 leads/month", "5,000 emails/month", "5,000 WA messages/month",
                             "All Starter features", "Priority support", "Cost analytics"]
            },
            {
                "tier": "pro", "name": "Pro",
                "monthly_inr": 75000, "quarterly_inr": 202500,
                "features": ["10,000 leads/month", "20,000 emails/month", "20,000 WA messages/month",
                             "All Growth features", "Dedicated onboarding", "Custom integrations"]
            },
        ],
        "trial": {"days": 7, "description": "7-day free trial — no credit card required for trial"},
    }

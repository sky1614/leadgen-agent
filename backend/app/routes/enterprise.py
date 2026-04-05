import hashlib
import json
import logging
import os
import secrets
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user
from ..models import UserDB, ClientDB, ClientWebhookDB

logger = logging.getLogger("enterprise")
router = APIRouter(prefix="/enterprise", tags=["enterprise"])

_PRO_TIERS = ("pro", "enterprise")


def _require_pro(cu: UserDB, db: Session):
    if not cu.client_id:
        raise HTTPException(403, "No client associated")
    client = db.query(ClientDB).filter(ClientDB.id == cu.client_id).first()
    if not client or client.plan_tier not in _PRO_TIERS:
        raise HTTPException(403, "White-label and webhook features require Pro or Enterprise plan")
    return client


# ── API Key management ────────────────────────────────────────────────────────
@router.post("/api-key/generate")
def generate_api_key(
    db: Session = Depends(get_db),
    cu: UserDB = Depends(get_current_user),
):
    """Generate a new API key for the client. Replaces existing key."""
    if not cu.client_id:
        raise HTTPException(400, "No client associated")
    client = db.query(ClientDB).filter(ClientDB.id == cu.client_id).first()
    if not client:
        raise HTTPException(404, "Client not found")

    raw_key = f"lga_live_{secrets.token_hex(24)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    prefix = raw_key[:16] + "..."

    client.api_key_hash = key_hash
    client.api_key_prefix = prefix
    db.commit()

    logger.info(json.dumps({
        "event": "api_key_generated", "client_id": client.id,
        "prefix": prefix, "timestamp": datetime.utcnow().isoformat(),
    }))

    return {
        "api_key": raw_key,           # shown ONCE — client must save it
        "prefix": prefix,
        "warning": "Save this key now. It will not be shown again.",
        "usage": "Pass as X-Api-Key header in every request.",
    }


@router.get("/api-key/status")
def api_key_status(
    db: Session = Depends(get_db),
    cu: UserDB = Depends(get_current_user),
):
    """Check if an API key exists (shows prefix only, never the full key)."""
    client = db.query(ClientDB).filter(ClientDB.id == cu.client_id).first()
    if not client:
        raise HTTPException(404, "Client not found")
    return {
        "has_api_key": bool(client.api_key_hash),
        "prefix": client.api_key_prefix,
    }


@router.delete("/api-key/revoke")
def revoke_api_key(
    db: Session = Depends(get_db),
    cu: UserDB = Depends(get_current_user),
):
    """Revoke the current API key."""
    client = db.query(ClientDB).filter(ClientDB.id == cu.client_id).first()
    if not client:
        raise HTTPException(404, "Client not found")
    client.api_key_hash = None
    client.api_key_prefix = None
    db.commit()
    return {"success": True, "message": "API key revoked"}


# ── White-label config ────────────────────────────────────────────────────────
class WhiteLabelConfig(BaseModel):
    brand_name: Optional[str] = None
    brand_logo_url: Optional[str] = None
    brand_color: Optional[str] = None
    brand_email_footer: Optional[str] = None
    white_label_enabled: Optional[bool] = None


@router.get("/white-label")
def get_white_label(
    db: Session = Depends(get_db),
    cu: UserDB = Depends(get_current_user),
):
    client = _require_pro(cu, db)
    return {
        "brand_name": client.brand_name,
        "brand_logo_url": client.brand_logo_url,
        "brand_color": client.brand_color,
        "brand_email_footer": client.brand_email_footer,
        "white_label_enabled": client.white_label_enabled,
    }


@router.put("/white-label")
def update_white_label(
    config: WhiteLabelConfig,
    db: Session = Depends(get_db),
    cu: UserDB = Depends(get_current_user),
):
    client = _require_pro(cu, db)
    if config.brand_name is not None:
        client.brand_name = config.brand_name
    if config.brand_logo_url is not None:
        client.brand_logo_url = config.brand_logo_url
    if config.brand_color is not None:
        if not config.brand_color.startswith("#") or len(config.brand_color) not in (4, 7):
            raise HTTPException(400, "brand_color must be a valid hex color e.g. #3b82f6")
        client.brand_color = config.brand_color
    if config.brand_email_footer is not None:
        client.brand_email_footer = config.brand_email_footer
    if config.white_label_enabled is not None:
        client.white_label_enabled = config.white_label_enabled
    db.commit()
    logger.info(json.dumps({
        "event": "white_label_updated", "client_id": client.id,
        "timestamp": datetime.utcnow().isoformat(),
    }))
    return {"success": True, "brand_name": client.brand_name}


# ── Webhook management ────────────────────────────────────────────────────────
class WebhookCreate(BaseModel):
    url: str
    events: List[str] = ["lead_found", "message_sent", "reply_received", "meeting_booked"]


@router.get("/webhooks")
def list_webhooks(
    db: Session = Depends(get_db),
    cu: UserDB = Depends(get_current_user),
):
    _require_pro(cu, db)
    hooks = db.query(ClientWebhookDB).filter(
        ClientWebhookDB.client_id == cu.client_id
    ).all()
    return {"webhooks": [
        {
            "id": h.id, "url": h.url, "events": h.events,
            "is_active": h.is_active, "failure_count": h.failure_count,
            "last_triggered_at": h.last_triggered_at.isoformat() if h.last_triggered_at else None,
        }
        for h in hooks
    ]}


@router.post("/webhooks")
def create_webhook(
    body: WebhookCreate,
    db: Session = Depends(get_db),
    cu: UserDB = Depends(get_current_user),
):
    _require_pro(cu, db)
    valid_events = {"lead_found", "message_sent", "reply_received", "meeting_booked"}
    bad = [e for e in body.events if e not in valid_events]
    if bad:
        raise HTTPException(400, f"Invalid events: {bad}. Valid: {list(valid_events)}")
    if not body.url.startswith("https://"):
        raise HTTPException(400, "Webhook URL must use HTTPS")

    secret = secrets.token_hex(32)
    hook = ClientWebhookDB(
        client_id=cu.client_id,
        url=body.url,
        secret=secret,
        events=body.events,
    )
    db.add(hook)
    db.commit()
    db.refresh(hook)

    return {
        "id": hook.id,
        "url": hook.url,
        "events": hook.events,
        "signing_secret": secret,
        "warning": "Save the signing_secret now — it won't be shown again. Use it to verify X-LeadGen-Signature headers.",
    }


@router.post("/webhooks/{hook_id}/test")
def test_webhook(
    hook_id: str,
    db: Session = Depends(get_db),
    cu: UserDB = Depends(get_current_user),
):
    """Send a test payload to the webhook URL."""
    _require_pro(cu, db)
    hook = db.query(ClientWebhookDB).filter(
        ClientWebhookDB.id == hook_id,
        ClientWebhookDB.client_id == cu.client_id,
    ).first()
    if not hook:
        raise HTTPException(404, "Webhook not found")

    from ..services.webhook_dispatcher import dispatch_event
    try:
        dispatch_event(cu.client_id, "message_sent", {
            "test": True,
            "message": "This is a test webhook from LeadGen AI",
        })
        return {"success": True, "message": "Test event dispatched"}
    except Exception as e:
        raise HTTPException(500, f"Delivery failed: {str(e)}")


@router.delete("/webhooks/{hook_id}")
def delete_webhook(
    hook_id: str,
    db: Session = Depends(get_db),
    cu: UserDB = Depends(get_current_user),
):
    _require_pro(cu, db)
    hook = db.query(ClientWebhookDB).filter(
        ClientWebhookDB.id == hook_id,
        ClientWebhookDB.client_id == cu.client_id,
    ).first()
    if not hook:
        raise HTTPException(404, "Webhook not found")
    db.delete(hook)
    db.commit()
    return {"success": True}

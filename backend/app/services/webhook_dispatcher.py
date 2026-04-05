import hashlib
import hmac
import json
import logging
import time
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger("webhook_dispatcher")

# ── Event type constants ───────────────────────────────────────────────────────
EVENT_LEAD_FOUND     = "lead_found"
EVENT_MESSAGE_SENT   = "message_sent"
EVENT_REPLY_RECEIVED = "reply_received"
EVENT_MEETING_BOOKED = "meeting_booked"

ALL_EVENTS = [EVENT_LEAD_FOUND, EVENT_MESSAGE_SENT, EVENT_REPLY_RECEIVED, EVENT_MEETING_BOOKED]


def sign_payload(secret: str, payload: bytes) -> str:
    """HMAC-SHA256 signature for webhook payload."""
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def build_event(event_type: str, data: dict, client_id: str) -> dict:
    return {
        "event": event_type,
        "timestamp": datetime.utcnow().isoformat(),
        "client_id": client_id,
        "data": data,
    }


def dispatch_event(client_id: str, event_type: str, data: dict):
    """
    Dispatch a webhook event to all registered URLs for this client.
    Called synchronously — for async use, call via Celery task.
    """
    from ..database import SessionLocal
    from ..models import ClientWebhookDB

    db = SessionLocal()
    try:
        hooks = db.query(ClientWebhookDB).filter(
            ClientWebhookDB.client_id == client_id,
            ClientWebhookDB.is_active == True,
        ).all()

        for hook in hooks:
            if event_type not in (hook.events or ALL_EVENTS):
                continue
            try:
                _deliver_with_retry(hook, event_type, data, client_id)
                hook.last_triggered_at = datetime.utcnow()
                hook.failure_count = 0
                db.commit()
            except Exception as e:
                hook.failure_count = (hook.failure_count or 0) + 1
                if hook.failure_count >= 10:
                    hook.is_active = False   # disable after 10 consecutive failures
                db.commit()
                logger.error(json.dumps({
                    "event": "webhook_delivery_failed",
                    "hook_id": hook.id,
                    "url": hook.url,
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat(),
                }))
    finally:
        db.close()


def _deliver_with_retry(hook, event_type: str, data: dict, client_id: str, max_attempts: int = 3):
    """Deliver with exponential backoff: 0s, 5s, 25s."""
    payload_dict = build_event(event_type, data, client_id)
    payload_bytes = json.dumps(payload_dict).encode()
    signature = sign_payload(hook.secret, payload_bytes)

    headers = {
        "Content-Type": "application/json",
        "X-LeadGen-Signature": signature,
        "X-LeadGen-Event": event_type,
        "User-Agent": "LeadGenAI-Webhook/1.0",
    }

    last_error = None
    for attempt in range(max_attempts):
        if attempt > 0:
            time.sleep(5 ** attempt)   # 5s, 25s
        try:
            resp = httpx.post(hook.url, content=payload_bytes, headers=headers, timeout=10)
            if resp.status_code < 300:
                logger.info(json.dumps({
                    "event": "webhook_delivered", "hook_id": hook.id,
                    "status": resp.status_code, "attempt": attempt + 1,
                    "timestamp": datetime.utcnow().isoformat(),
                }))
                return
            last_error = f"HTTP {resp.status_code}"
        except Exception as e:
            last_error = str(e)

    raise RuntimeError(f"Webhook delivery failed after {max_attempts} attempts: {last_error}")


# ── Celery-based async dispatch ───────────────────────────────────────────────
def dispatch_event_async(client_id: str, event_type: str, data: dict):
    """Non-blocking dispatch via Celery. Use this in hot paths."""
    try:
        from ..tasks.webhook_tasks import deliver_webhook
        deliver_webhook.delay(client_id, event_type, data)
    except Exception as e:
        logger.error(json.dumps({
            "event": "async_dispatch_error", "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }))

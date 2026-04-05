from datetime import datetime, date
import httpx
from sqlalchemy.orm import Session

from ..config import GUPSHUP_API_KEY, GUPSHUP_APP_NAME, GUPSHUP_SOURCE_NUMBER
from ..database import SessionLocal
from ..models import MessageLogDB, LeadDB, ClientDB

GUPSHUP_API_URL = "https://api.gupshup.io/sm/api/v1/msg"
GUPSHUP_QUALITY_URL = "https://api.gupshup.io/sm/api/v1/app/account/quality"


def _phone_e164(phone: str) -> str:
    """Ensure phone is in E.164 format (+91XXXXXXXXXX)."""
    phone = phone.strip().replace(" ", "").replace("-", "")
    if not phone.startswith("+"):
        phone = "+91" + phone.lstrip("0")
    return phone


def is_lead_warm(lead_id: str, db: Session) -> bool:
    """Returns True only if lead has shown engagement (opened email, replied, etc.)."""
    lead = db.query(LeadDB).filter(LeadDB.id == lead_id).first()
    if not lead:
        return False
    if lead.wa_consent:
        return True
    if lead.status in ("replied", "interested", "warm"):
        return True
    log = db.query(MessageLogDB).filter(
        MessageLogDB.lead_id == lead_id,
        MessageLogDB.opened_at != None
    ).first()
    return log is not None


def check_daily_wa_limit(client_id: str, db: Session) -> bool:
    """Returns True if client is within their daily WA send limit."""
    client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
    if not client:
        return False
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = db.query(MessageLogDB).filter(
        MessageLogDB.client_id == client_id,
        MessageLogDB.channel == "whatsapp",
        MessageLogDB.sent_at >= today_start
    ).count()
    daily_limit = (client.monthly_wa_cap or 1000) // 30
    return today_count < daily_limit


def check_quality_safe(client_id: str) -> dict:
    """Check Gupshup quality rating. Returns {safe: bool, rating: str}."""
    if not GUPSHUP_API_KEY or not GUPSHUP_APP_NAME:
        return {"safe": True, "rating": "UNKNOWN"}
    try:
        resp = httpx.get(
            GUPSHUP_QUALITY_URL,
            headers={"apikey": GUPSHUP_API_KEY},
            params={"appName": GUPSHUP_APP_NAME},
            timeout=10
        )
        data = resp.json()
        rating = data.get("qualityRating", "GREEN").upper()
        return {"safe": rating != "RED", "rating": rating}
    except Exception:
        return {"safe": True, "rating": "UNKNOWN"}


def send_template_message(to_phone: str, template_name: str, template_params: list, client_id: str) -> dict:
    """Send a Meta-approved WhatsApp template message via Gupshup."""
    db = SessionLocal()
    try:
        # Safety checks
        lead = db.query(LeadDB).filter(LeadDB.whatsapp == to_phone).first()
        if lead:
            if not lead.wa_consent:
                return {"success": False, "error": "No WA consent for this lead"}
            if lead.do_not_contact:
                return {"success": False, "error": "Lead marked do_not_contact"}
            if not is_lead_warm(lead.id, db):
                return {"success": False, "error": "Lead is cold — warm up via email first"}

        if not check_daily_wa_limit(client_id, db):
            return {"success": False, "error": "Daily WhatsApp limit reached"}

        quality = check_quality_safe(client_id)
        if not quality["safe"]:
            return {"success": False, "error": f"WA quality rating is RED — sends paused"}

        phone = _phone_e164(to_phone)

        # Build template payload
        params_str = "|".join(template_params)
        payload = {
            "channel": "whatsapp",
            "source": GUPSHUP_SOURCE_NUMBER,
            "destination": phone,
            "src.name": GUPSHUP_APP_NAME,
            "message": f'{{"type":"template","template":{{"id":"{template_name}","params":["{params_str}"]}}}}'
        }

        if not GUPSHUP_API_KEY:
            # Simulate if no API key
            log = MessageLogDB(
                client_id=client_id,
                lead_id=lead.id if lead else "",
                campaign_id="", channel="whatsapp",
                message=f"[TEMPLATE:{template_name}] {params_str}",
                status="simulated"
            )
            db.add(log)
            db.commit()
            return {"success": True, "message_id": "simulated", "error": None}

        resp = httpx.post(
            GUPSHUP_API_URL,
            headers={"apikey": GUPSHUP_API_KEY, "Content-Type": "application/x-www-form-urlencoded"},
            data=payload,
            timeout=15
        )
        result = resp.json()
        message_id = result.get("messageId", "")
        success = resp.status_code == 202 or result.get("status") == "submitted"

        log = MessageLogDB(
            client_id=client_id,
            lead_id=lead.id if lead else "",
            campaign_id="", channel="whatsapp",
            message=f"[TEMPLATE:{template_name}] {params_str}",
            status="sent" if success else "failed",
            sendgrid_message_id=message_id  # reusing field for WA message ID
        )
        db.add(log)
        db.commit()

        if success:
            try:
                from .cost_tracker import log_gupshup
                log_gupshup(client_id, count=1)
            except Exception:
                pass

        return {"success": success, "message_id": message_id, "error": None if success else result.get("message")}

    except Exception as e:
        return {"success": False, "message_id": None, "error": str(e)}
    finally:
        db.close()


def send_session_message(to_phone: str, message_text: str, client_id: str) -> dict:
    """Send a free-form session message (only within 24h reply window)."""
    db = SessionLocal()
    try:
        lead = db.query(LeadDB).filter(LeadDB.whatsapp == to_phone).first()
        if lead:
            if lead.do_not_contact:
                return {"success": False, "error": "Lead marked do_not_contact"}
            if lead.status not in ("replied", "interested", "warm"):
                return {"success": False, "error": "No active session — lead has not replied recently"}

        if not check_daily_wa_limit(client_id, db):
            return {"success": False, "error": "Daily WhatsApp limit reached"}

        phone = _phone_e164(to_phone)

        if not GUPSHUP_API_KEY:
            return {"success": True, "message_id": "simulated", "error": None}

        payload = {
            "channel": "whatsapp",
            "source": GUPSHUP_SOURCE_NUMBER,
            "destination": phone,
            "src.name": GUPSHUP_APP_NAME,
            "message": f'{{"type":"text","text":"{message_text}"}}'
        }

        resp = httpx.post(
            GUPSHUP_API_URL,
            headers={"apikey": GUPSHUP_API_KEY, "Content-Type": "application/x-www-form-urlencoded"},
            data=payload,
            timeout=15
        )
        result = resp.json()
        success = resp.status_code == 202 or result.get("status") == "submitted"
        message_id = result.get("messageId", "")

        log = MessageLogDB(
            client_id=client_id,
            lead_id=lead.id if lead else "",
            campaign_id="", channel="whatsapp",
            message=message_text, status="sent" if success else "failed",
            sendgrid_message_id=message_id
        )
        db.add(log)
        db.commit()

        return {"success": success, "message_id": message_id, "error": None if success else result.get("message")}

    except Exception as e:
        return {"success": False, "message_id": None, "error": str(e)}
    finally:
        db.close()


def get_quality_rating(client_id: str) -> dict:
    """Get current WhatsApp quality rating from Gupshup."""
    result = check_quality_safe(client_id)
    status = "ok"
    if result["rating"] == "YELLOW":
        status = "warning"
    elif result["rating"] == "RED":
        status = "danger — sends paused"
    return {"rating": result["rating"], "status": status}

import re
from datetime import datetime, timedelta

import httpx

from ..config import ZEROBOUNCE_API_KEY, GUPSHUP_API_KEY


# ── Phone formatting ──────────────────────────────────────────────────────────
def format_phone_e164(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        return f"+91{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    if not phone.startswith("+"):
        return f"+{digits}"
    return phone


# ── Email verification via ZeroBounce ────────────────────────────────────────
def verify_email(email: str) -> dict:
    if not email or "@" not in email:
        return {"is_valid": False, "status": "invalid", "sub_status": "no_email", "did_you_mean": ""}

    if not ZEROBOUNCE_API_KEY:
        # No API key — basic format check only
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        is_valid = bool(re.match(pattern, email))
        return {"is_valid": is_valid, "status": "valid" if is_valid else "invalid",
                "sub_status": "", "did_you_mean": ""}

    try:
        resp = httpx.get(
            "https://api.zerobounce.net/v2/validate",
            params={"api_key": ZEROBOUNCE_API_KEY, "email": email},
            timeout=10
        )
        data = resp.json()
        status = data.get("status", "unknown")
        did_you_mean = data.get("did_you_mean", "")

        if did_you_mean:
            print(f"ZEROBOUNCE: Did you mean {did_you_mean} instead of {email}?")

        try:
            from .cost_tracker import log_zerobounce
            log_zerobounce(None, count=1)  # no client_id here; logged at service level
        except Exception:
            pass
        return {
            "is_valid": status in ["valid", "catch-all"],
            "status": status,
            "sub_status": data.get("sub_status", ""),
            "did_you_mean": did_you_mean
        }
    except Exception as e:
        print(f"ZEROBOUNCE ERROR: {e}")
        return {"is_valid": True, "status": "unknown", "sub_status": "", "did_you_mean": ""}


# ── WhatsApp verification via Gupshup ────────────────────────────────────────
def verify_whatsapp_number(phone: str) -> dict:
    if not phone:
        return {"is_valid": False, "is_whatsapp": False}

    formatted = format_phone_e164(phone)

    if not GUPSHUP_API_KEY:
        # No API key — just validate format
        is_valid = bool(re.match(r'^\+\d{10,15}$', formatted))
        return {"is_valid": is_valid, "is_whatsapp": False, "formatted": formatted}

    try:
        resp = httpx.get(
            "https://api.gupshup.io/wa/api/v1/contacts/check",
            params={"phone": formatted},
            headers={"apikey": GUPSHUP_API_KEY},
            timeout=10
        )
        data = resp.json()
        is_wa = data.get("status") == "valid" or data.get("is_whatsapp", False)
        return {"is_valid": True, "is_whatsapp": is_wa, "formatted": formatted}
    except Exception as e:
        print(f"GUPSHUP ERROR: {e}")
        return {"is_valid": True, "is_whatsapp": False, "formatted": formatted}


# ── Combined lead verification ────────────────────────────────────────────────
def verify_lead_contacts(lead_id: str) -> dict:
    from ..database import SessionLocal
    from ..models import LeadDB

    db = SessionLocal()
    try:
        lead = db.query(LeadDB).filter(LeadDB.id == lead_id).first()
        if not lead:
            return {"error": "Lead not found"}

        # Skip if verified this month
        if lead.verification_date:
            days_since = (datetime.utcnow() - lead.verification_date).days
            if days_since < 30:
                return {
                    "email_verified": lead.email_verified,
                    "wa_verified": lead.wa_verified,
                    "cached": True
                }

        email_result = {"is_valid": None}
        wa_result = {"is_whatsapp": None}

        # Verify email
        if lead.email:
            email_result = verify_email(lead.email)
            lead.email_verified = email_result["is_valid"]

        # Verify WhatsApp
        if lead.whatsapp:
            wa_result = verify_whatsapp_number(lead.whatsapp)
            lead.wa_verified = wa_result.get("is_whatsapp", False)
            if wa_result.get("formatted"):
                lead.whatsapp = wa_result["formatted"]

        # Compute contact channels
        channels = []
        if lead.email_verified:
            channels.append("email")
        if lead.wa_verified:
            channels.append("whatsapp")
        lead.contact_channels = channels

        # Mark uncontactable if both invalid
        if lead.email_verified is False and lead.wa_verified is False:
            lead.status = "uncontactable"
            lead.do_not_contact = True

        lead.verification_date = datetime.utcnow()
        db.commit()

        return {
            "email_verified": lead.email_verified,
            "wa_verified": lead.wa_verified,
            "contact_channels": channels,
            "email_status": email_result.get("status"),
            "cached": False
        }
    finally:
        db.close()

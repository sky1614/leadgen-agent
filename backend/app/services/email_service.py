import hashlib
import hmac
import os
from datetime import datetime, date

from ..config import SENDGRID_API_KEY, WEBHOOK_BASE_URL


# ── Daily send limit (warm-up aware) ─────────────────────────────────────────
def get_daily_send_limit(client_id: str) -> int:
    from ..database import SessionLocal
    from ..models import ClientDB
    db = SessionLocal()
    try:
        client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
        if not client or not client.created_at:
            return 10
        days = (datetime.utcnow() - client.created_at).days
        if days <= 7:
            return 10
        elif days <= 14:
            return 25
        elif days <= 21:
            return 50
        else:
            return client.monthly_email_cap // 30 if client.monthly_email_cap else 9999
    finally:
        db.close()


def get_emails_sent_today(client_id: str) -> int:
    from ..database import SessionLocal
    from ..models import MessageLogDB
    db = SessionLocal()
    try:
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        return db.query(MessageLogDB).filter(
            MessageLogDB.client_id == client_id,
            MessageLogDB.channel == "email",
            MessageLogDB.sent_at >= today_start
        ).count()
    finally:
        db.close()


def can_send_email(client_id: str) -> bool:
    return get_emails_sent_today(client_id) < get_daily_send_limit(client_id)


# ── Main send function ────────────────────────────────────────────────────────
def send_email(
    to_email: str,
    subject: str,
    body_html: str,
    body_text: str,
    from_email: str,
    from_name: str,
    client_id: str = None,
    lead_id: str = None,
    campaign_id: str = None
) -> dict:
    if not SENDGRID_API_KEY:
        return {"success": False, "error": "SendGrid API key not configured", "simulated": True}

    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail, Email, To, Content, ReplyTo

        unsubscribe_url = f"{WEBHOOK_BASE_URL}/unsubscribe/{lead_id}" if lead_id else f"{WEBHOOK_BASE_URL}/unsubscribe"

        # Add unsubscribe link to body
        body_html_with_unsub = body_html + f'<br><br><small><a href="{unsubscribe_url}">Unsubscribe</a></small>'
        body_text_with_unsub = body_text + f"\n\nUnsubscribe: {unsubscribe_url}"

        message = Mail(
            from_email=Email(from_email, from_name),
            to_emails=To(to_email),
            subject=subject,
        )
        message.content = [
            Content("text/plain", body_text_with_unsub),
            Content("text/html", body_html_with_unsub),
        ]
        message.reply_to = ReplyTo(from_email, from_name)

        # Custom tracking args for webhook identification
        message.custom_args = {
            "client_id": client_id or "",
            "lead_id": lead_id or "",
            "campaign_id": campaign_id or ""
        }

        # Unsubscribe headers
        message.headers = {
            "List-Unsubscribe": f"<{unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"
        }

        sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
        response = sg.send(message)

        message_id = response.headers.get("X-Message-Id", "")
        try:
            from .cost_tracker import log_sendgrid
            log_sendgrid(client_id or "", count=1, task_type="email")
        except Exception:
            pass
        return {"success": True, "message_id": message_id, "status_code": response.status_code}


    except Exception as e:
        print(f"SENDGRID ERROR: {e}")
        return {"success": False, "error": str(e)}


# ── Domain authentication check ───────────────────────────────────────────────
def check_domain_setup(domain: str) -> dict:
    try:
        import dns.resolver

        result = {"spf": False, "dkim": False, "dmarc": False, "domain": domain}

        # Check SPF
        try:
            answers = dns.resolver.resolve(domain, "TXT")
            for r in answers:
                if "v=spf1" in str(r):
                    result["spf"] = True
                    break
        except Exception:
            pass

        # Check DMARC
        try:
            answers = dns.resolver.resolve(f"_dmarc.{domain}", "TXT")
            for r in answers:
                if "v=DMARC1" in str(r):
                    result["dmarc"] = True
                    break
        except Exception:
            pass

        # Check DKIM (common selectors)
        for selector in ["google", "sendgrid", "default", "mail", "s1", "s2"]:
            try:
                dns.resolver.resolve(f"{selector}._domainkey.{domain}", "TXT")
                result["dkim"] = True
                break
            except Exception:
                continue

        return result
    except Exception as e:
        return {"spf": False, "dkim": False, "dmarc": False, "error": str(e)}


# ── Webhook signature verification ───────────────────────────────────────────
def verify_sendgrid_webhook(payload: bytes, signature: str, timestamp: str) -> bool:
    try:
        from sendgrid.helpers.eventwebhook import EventWebhook, EventWebhookHeader
        public_key = os.getenv("SENDGRID_WEBHOOK_PUBLIC_KEY", "")
        if not public_key:
            return True  # skip verification if key not configured
        ew = EventWebhook()
        ec_public_key = ew.convert_public_key_to_ecdsa(public_key)
        return ew.verify_signature(payload, ec_public_key, signature, timestamp)
    except Exception:
        return True  # fail open in dev

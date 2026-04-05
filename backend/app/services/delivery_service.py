import logging
import random
import time
from datetime import datetime, date, timedelta

from ..database import SessionLocal
from ..models import LeadDB, MessageLogDB, CampaignDB, ClientDB, ConversationDB

logger = logging.getLogger("delivery_service")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_blackout(client: ClientDB) -> dict:
    """Returns blackout info using cultural_service calendar."""
    try:
        from .cultural_service import is_blackout_date
        return is_blackout_date(date.today(), client.id)
    except Exception:
        today = date.today().isoformat()
        hit = today in (client.festival_blackout_dates or [])
        return {"is_blackout": hit, "festival_name": None, "type": "full_blackout" if hit else None}

def _sent_today(lead_id: str, db) -> bool:
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return db.query(MessageLogDB).filter(
        MessageLogDB.lead_id == lead_id,
        MessageLogDB.sent_at >= today_start,
        MessageLogDB.status == "sent"
    ).count() > 0


def _lead_has_opened_email(lead_id: str, db) -> bool:
    return db.query(MessageLogDB).filter(
        MessageLogDB.lead_id == lead_id,
        MessageLogDB.channel == "email",
        MessageLogDB.opened_at != None
    ).first() is not None


# ── Channel routing ───────────────────────────────────────────────────────────

def determine_channel(lead_id: str, client_id: str) -> dict:
    db = SessionLocal()
    try:
        lead = db.query(LeadDB).filter(LeadDB.id == lead_id).first()
        if not lead:
            return {"primary_channel": "skip", "backup_channel": None, "reason": "lead not found"}

        has_email = bool(lead.email and lead.email_verified)
        has_wa = bool(lead.whatsapp and lead.wa_verified and lead.wa_consent)
        is_warm = lead.status in ("replied", "interested", "warm") or _lead_has_opened_email(lead_id, db)

        if not has_email and not has_wa:
            return {"primary_channel": "skip", "backup_channel": None, "reason": "no verified contact method"}

        if lead.status in ("replied", "interested"):
            return {"primary_channel": "skip", "backup_channel": None, "reason": "lead replied — manual handling required"}

        if is_warm:
            if has_wa:
                return {"primary_channel": "whatsapp", "backup_channel": "email" if has_email else None, "reason": "warm lead with WA consent"}
            elif has_email:
                return {"primary_channel": "email", "backup_channel": None, "reason": "warm lead, no WA consent"}

        # Cold lead
        if has_email:
            return {"primary_channel": "email", "backup_channel": "whatsapp_after_day7" if has_wa else None, "reason": "cold lead — email first"}
        else:
            return {"primary_channel": "skip", "backup_channel": None, "reason": "cold lead with no verified email — cannot cold-outreach on WA"}

    except Exception as e:
        logger.error({"event": "determine_channel_error", "lead_id": lead_id, "error": str(e), "ts": datetime.utcnow().isoformat()})
        return {"primary_channel": "skip", "backup_channel": None, "reason": f"error: {e}"}
    finally:
        db.close()


# ── Execute send ──────────────────────────────────────────────────────────────

def execute_send(message_id: str, lead_id: str, client_id: str) -> dict:
    db = SessionLocal()
    try:
        lead = db.query(LeadDB).filter(LeadDB.id == lead_id).first()
        if not lead:
            return {"sent": False, "channel_used": None, "error": "lead not found"}

        if client:
            blackout = _is_blackout(client)
            if blackout["is_blackout"] and blackout["type"] == "full_blackout":
                return {"sent": False, "channel_used": None,
                        "error": f"Festival blackout ({blackout['festival_name']}) — no outreach today"}
            elif blackout["is_blackout"] and blackout["type"] == "soft_blackout":
                # Soft blackout: skip sales outreach silently
                logger.info({"event": "soft_blackout_skip", "festival": blackout["festival_name"], "lead_id": lead_id})
                return {"sent": False, "channel_used": "skip",
                        "error": f"Soft blackout ({blackout['festival_name']}) — sales outreach paused"}


        client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
        if client and _is_blackout(client):
            return {"sent": False, "channel_used": None, "error": "festival blackout — send skipped"}

        if _sent_today(lead_id, db):
            return {"sent": False, "channel_used": None, "error": "already sent to lead today"}

        routing = determine_channel(lead_id, client_id)
        channel = routing["primary_channel"]

        if channel == "skip":
            log = db.query(MessageLogDB).filter(MessageLogDB.id == message_id).first()
            if log:
                log.status = f"skipped:{routing['reason']}"
                db.commit()
            return {"sent": False, "channel_used": "skip", "error": routing["reason"]}

        log = db.query(MessageLogDB).filter(MessageLogDB.id == message_id).first()
        if not log:
            return {"sent": False, "channel_used": None, "error": "message log entry not found"}

        result = {"sent": False, "channel_used": channel, "error": None}

        if channel == "email":
            from .email_service import send_email, can_send_email
            if not can_send_email(client_id):
                return {"sent": False, "channel_used": "email", "error": "daily email limit reached"}

            subject = "Following up"
            body = log.message
            if log.message.startswith("Subject:"):
                lines = log.message.split("\n", 2)
                subject = lines[0].replace("Subject:", "").strip()
                body = lines[2].strip() if len(lines) > 2 else log.message

            campaign = db.query(CampaignDB).filter(CampaignDB.id == log.campaign_id).first()
            from_email = f"hello@{client.email_domain}" if client and client.email_domain else "hello@yourdomain.com"
            sg_result = send_email(
                to_email=lead.email, subject=subject,
                body_html=body.replace("\n", "<br>"), body_text=body,
                from_email=from_email, from_name="Sales Team",
                client_id=client_id, lead_id=lead_id,
                campaign_id=log.campaign_id
            )
            result["sent"] = sg_result.get("success", False)
            result["error"] = sg_result.get("error")
            log.sendgrid_message_id = sg_result.get("message_id")

        elif channel == "whatsapp":
            from .whatsapp_service import send_template_message
            wa_result = send_template_message(
                to_phone=lead.whatsapp,
                template_name="outreach_v1",
                template_params=[lead.name or "there", log.message[:100]],
                client_id=client_id
            )
            result["sent"] = wa_result.get("success", False)
            result["error"] = wa_result.get("error")

        if result["sent"]:
            log.status = "sent"
            log.sent_at = datetime.utcnow()
            lead.status = "contacted"
            lead.last_contacted = datetime.utcnow()
            db.commit()

            # Schedule Day 3 and Day 7 follow-ups
            from ..tasks.followup_tasks import schedule_followup, channel_switch_followup
            schedule_followup.apply_async(
                args=[message_id, lead_id, client_id, 3],
                eta=datetime.utcnow() + timedelta(days=3)
            )
            channel_switch_followup.apply_async(
                args=[message_id, lead_id, client_id],
                eta=datetime.utcnow() + timedelta(days=7)
            )

        return result

    except Exception as e:
        logger.error({"event": "execute_send_error", "lead_id": lead_id, "message_id": message_id, "error": str(e), "ts": datetime.utcnow().isoformat()})
        return {"sent": False, "channel_used": None, "error": str(e)}
    finally:
        db.close()


# ── Day 3 follow-up ───────────────────────────────────────────────────────────

def handle_day3_followup(original_message_id: str, lead_id: str, client_id: str) -> dict:
    db = SessionLocal()
    try:
        lead = db.query(LeadDB).filter(LeadDB.id == lead_id).first()
        if not lead:
            return {"skipped": True, "reason": "lead not found"}
        if lead.status in ("replied", "unsubscribed", "bounced", "do_not_contact"):
            return {"skipped": True, "reason": f"lead status is {lead.status}"}
        if lead.do_not_contact:
            return {"skipped": True, "reason": "do_not_contact"}

        original = db.query(MessageLogDB).filter(MessageLogDB.id == original_message_id).first()
        channel = original.channel if original else "email"

        campaign = db.query(CampaignDB).filter(
            CampaignDB.client_id == client_id,
            CampaignDB.status == "active"
        ).first()
        if not campaign:
            return {"skipped": True, "reason": "no active campaign"}

        from .groq_service import ai_message
        msg = ai_message(lead, campaign, channel, followup_number=1)

        log = MessageLogDB(
            user_id=lead.user_id, client_id=client_id,
            lead_id=lead_id, campaign_id=campaign.id,
            channel=channel, message=msg,
            follow_up_number=2, status="pending"
        )
        db.add(log)
        db.add(ConversationDB(client_id=client_id, lead_id=lead_id, role="assistant", content=msg))
        db.commit()

        return execute_send(log.id, lead_id, client_id)

    except Exception as e:
        logger.error({"event": "day3_followup_error", "lead_id": lead_id, "error": str(e), "ts": datetime.utcnow().isoformat()})
        return {"skipped": True, "reason": str(e)}
    finally:
        db.close()


# ── Day 7 channel switch ──────────────────────────────────────────────────────

def handle_day7_channel_switch(original_message_id: str, lead_id: str, client_id: str) -> dict:
    db = SessionLocal()
    try:
        lead = db.query(LeadDB).filter(LeadDB.id == lead_id).first()
        if not lead:
            return {"skipped": True, "reason": "lead not found"}
        if lead.status in ("replied", "unsubscribed", "bounced", "do_not_contact", "sequence_complete"):
            return {"skipped": True, "reason": f"lead status is {lead.status}"}

        original = db.query(MessageLogDB).filter(MessageLogDB.id == original_message_id).first()
        original_channel = original.channel if original else "email"

        campaign = db.query(CampaignDB).filter(
            CampaignDB.client_id == client_id,
            CampaignDB.status == "active"
        ).first()
        if not campaign:
            return {"skipped": True, "reason": "no active campaign"}

        from .groq_service import ai_message
        has_opened = _lead_has_opened_email(lead_id, db)
        has_wa = bool(lead.whatsapp and lead.wa_verified and lead.wa_consent)

        # Upgrade to warm if email was opened
        if has_opened and lead.status not in ("warm", "replied", "interested"):
            lead.status = "warm"

        # Decide channel for Day 7
        if lead.status == "warm" and has_wa:
            channel = "whatsapp"
        else:
            channel = "email"

        msg = ai_message(lead, campaign, channel, followup_number=2)

        log = MessageLogDB(
            user_id=lead.user_id, client_id=client_id,
            lead_id=lead_id, campaign_id=campaign.id,
            channel=channel, message=msg,
            follow_up_number=3, status="pending"
        )
        db.add(log)
        db.add(ConversationDB(client_id=client_id, lead_id=lead_id, role="assistant", content=msg))

        # After Day 7 — move to nurture pool
        lead.status = "sequence_complete"
        db.commit()

        result = execute_send(log.id, lead_id, client_id)
        result["sequence"] = "complete — lead moved to nurture pool"
        return result

    except Exception as e:
        logger.error({"event": "day7_channel_switch_error", "lead_id": lead_id, "error": str(e), "ts": datetime.utcnow().isoformat()})
        return {"skipped": True, "reason": str(e)}
    finally:
        db.close()


# ── Batch send ────────────────────────────────────────────────────────────────

def batch_send(campaign_id: str, client_id: str) -> dict:
    db = SessionLocal()
    stats = {"total": 0, "sent": 0, "skipped": 0, "errors": 0}
    try:
        pending = db.query(MessageLogDB).filter(
            MessageLogDB.campaign_id == campaign_id,
            MessageLogDB.client_id == client_id,
            MessageLogDB.status == "pending"
        ).all()
        stats["total"] = len(pending)

        client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
        if client and _is_blackout(client):
            return {**stats, "error": "festival blackout — batch skipped"}

        for log in pending:
            result = execute_send(log.id, log.lead_id, client_id)

            if result["sent"]:
                stats["sent"] += 1
            elif result.get("error") in ("daily email limit reached", "Daily WhatsApp limit reached"):
                logger.info({"event": "batch_limit_reached", "campaign_id": campaign_id, "sent_so_far": stats["sent"]})
                break
            elif result.get("channel_used") == "skip":
                stats["skipped"] += 1
            else:
                stats["errors"] += 1
                logger.warning({"event": "batch_send_error", "lead_id": log.lead_id, "error": result.get("error"), "ts": datetime.utcnow().isoformat()})

            # Anti-spam delay: 30–60 seconds between sends
            delay = random.uniform(30, 60)
            time.sleep(delay)

        return stats

    except Exception as e:
        logger.error({"event": "batch_send_fatal", "campaign_id": campaign_id, "error": str(e), "ts": datetime.utcnow().isoformat()})
        return {**stats, "error": str(e)}
    finally:
        db.close()

from datetime import datetime

from fastapi import APIRouter, Request, HTTPException
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import MessageLogDB, LeadDB
from ..services.email_service import verify_sendgrid_webhook
from ..services.payment_service import (
    verify_razorpay_webhook, activate_client, handle_payment_failure,
    cancel_subscription, log_payment
)

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/sendgrid")
async def sendgrid_webhook(request: Request):
    body = await request.body()

    # Verify signature
    sig = request.headers.get("X-Twilio-Email-Event-Webhook-Signature", "")
    ts = request.headers.get("X-Twilio-Email-Event-Webhook-Timestamp", "")
    if not verify_sendgrid_webhook(body, sig, ts):
        raise HTTPException(403, "Invalid webhook signature")

    events = await request.json()
    db = SessionLocal()
    try:
        for event in events:
            msg_id = event.get("sg_message_id", "").split(".")[0]
            lead_id = event.get("lead_id") or event.get("unique_args", {}).get("lead_id", "")
            event_type = event.get("event", "")
            timestamp = event.get("timestamp", 0)
            dt = datetime.utcfromtimestamp(timestamp) if timestamp else datetime.utcnow()

            # Find message log entry
            log = db.query(MessageLogDB).filter(
                MessageLogDB.sendgrid_message_id == msg_id
            ).first() if msg_id else None

            if event_type == "delivered" and log:
                log.delivered_at = dt

            elif event_type == "open" and log:
                log.opened_at = dt
                try:
                    from ..services.memory_service import store_episodic_outcome
                    store_episodic_outcome(log.client_id or "", log.lead_id or "", "opened", "email", log.message or "", db)
                except Exception:
                    pass

                try:
                    from ..services.rag_service import sync_new_outcome
                    import threading
                    threading.Thread(
                        target=sync_new_outcome,
                        args=(log.client_id or "", log.lead_id or "", "opened", db),
                        daemon=True
                    ).start()
                except Exception:
                    pass
                
                try:
                    if log.ab_test_id and log.ab_test_variant:
                        from ..services.ab_testing_service import record_outcome
                        record_outcome(log.ab_test_id, log.ab_test_variant, "open", db)
                except Exception:
                    pass

                try:
                    if log.ab_test_id and log.ab_test_variant:
                        from ..services.ab_testing_service import record_outcome
                        record_outcome(log.ab_test_id, log.ab_test_variant, "open", db)
                except Exception:
                    pass


            elif event_type == "click" and log:
                log.clicked_at = dt

            elif event_type == "bounce":
                if log:
                    log.bounced = True
                    log.bounce_type = event.get("type", "hard")
                    try:
                        from ..services.memory_service import store_episodic_outcome
                        store_episodic_outcome(log.client_id or "", log.lead_id or "", "bounced", "email", log.message or "", db)
                    except Exception:
                        pass
                    try:
                        from ..services.rag_service import sync_new_outcome
                        import threading
                        threading.Thread(
                            target=sync_new_outcome,
                            args=(log.client_id or "", log.lead_id or "", "bounced", db),
                            daemon=True
                        ).start()
                    except Exception:
                        pass

                    try:
                        if log.ab_test_id and log.ab_test_variant:
                            from ..services.ab_testing_service import record_outcome
                            record_outcome(log.ab_test_id, log.ab_test_variant, "bounce", db)
                    except Exception:
                        pass

                    try:
                        if log.ab_test_id and log.ab_test_variant:
                            from ..services.ab_testing_service import record_outcome
                            record_outcome(log.ab_test_id, log.ab_test_variant, "bounce", db)
                    except Exception:
                        pass



            elif event_type == "spamreport":
                if log:
                    log.spam_reported = True
                if lead_id:
                    lead = db.query(LeadDB).filter(LeadDB.id == lead_id).first()
                    if lead:
                        lead.do_not_contact = True
                        lead.status = "do_not_contact"

            elif event_type == "unsubscribe":
                if log:
                    log.unsubscribed = True
                if lead_id:
                    lead = db.query(LeadDB).filter(LeadDB.id == lead_id).first()
                    if lead:
                        lead.do_not_contact = True
                        lead.status = "unsubscribed"

        db.commit()
    finally:
        db.close()

    return {"success": True}


@router.post("/unsubscribe/{lead_id}")
def unsubscribe(lead_id: str):
    db = SessionLocal()
    try:
        lead = db.query(LeadDB).filter(LeadDB.id == lead_id).first()
        if lead:
            lead.do_not_contact = True
            lead.status = "unsubscribed"
            db.commit()
        return {"success": True, "message": "You have been unsubscribed."}
    finally:
        db.close()


@router.get("/unsubscribe/{lead_id}")
def unsubscribe_page(lead_id: str):
    db = SessionLocal()
    try:
        lead = db.query(LeadDB).filter(LeadDB.id == lead_id).first()
        if lead:
            lead.do_not_contact = True
            lead.status = "unsubscribed"
            db.commit()
        return {"success": True, "message": "You have been unsubscribed successfully."}
    finally:
        db.close()


@router.post("/webhooks/gupshup")
async def gupshup_webhook(request: Request):
    """Handles Gupshup WhatsApp delivery and reply callbacks."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    db = SessionLocal()
    try:
        event_type = payload.get("type", "")
        entry = payload.get("payload", {})
        wa_message_id = entry.get("id", "")
        phone = entry.get("source", "")

        # Find log by WA message ID (stored in sendgrid_message_id field)
        log = db.query(MessageLogDB).filter(
            MessageLogDB.sendgrid_message_id == wa_message_id,
            MessageLogDB.channel == "whatsapp"
        ).first() if wa_message_id else None

        if event_type == "message-event":
            msg_event = entry.get("type", "")
            if msg_event == "delivered" and log:
                log.delivered_at = datetime.utcnow()
            elif msg_event == "read" and log:
                log.opened_at = datetime.utcnow()

        elif event_type == "user-event":
            # User replied or opted out
            user_event = entry.get("type", "")
            message_text = entry.get("text", {}).get("body", "") if isinstance(entry.get("text"), dict) else ""

            lead = db.query(LeadDB).filter(LeadDB.whatsapp == phone).first()

            if user_event == "OPT_IN":
                if lead:
                    lead.wa_consent = True
                    lead.wa_consent_date = datetime.utcnow()
                    lead.wa_consent_source = "opt_in"

            elif user_event == "OPT_OUT":
                if lead:
                    lead.wa_consent = False
                    lead.do_not_contact = True
                    lead.status = "unsubscribed"

            elif user_event == "message":
                # User sent a message (reply)
                if lead:
                    lead.status = "replied"
                    try:
                        from ..services.memory_service import store_episodic_outcome
                        last_log = db.query(MessageLogDB).filter(
                            MessageLogDB.lead_id == lead.id,
                            MessageLogDB.channel == "whatsapp"
                        ).order_by(MessageLogDB.sent_at.desc()).first()
                        store_episodic_outcome(lead.client_id or "", lead.id, "replied", "whatsapp",
                                               last_log.message if last_log else "", db)
                    except Exception:
                        pass
                    try:
                        from ..services.rag_service import sync_new_outcome
                        import threading
                        threading.Thread(
                            target=sync_new_outcome,
                            args=(lead.client_id or "", lead.id, "replied", db),
                            daemon=True
                        ).start()
                    except Exception:
                        pass

                    try:
                        last_log = db.query(MessageLogDB).filter(
                            MessageLogDB.lead_id == lead.id,
                            MessageLogDB.channel == "whatsapp"
                        ).order_by(MessageLogDB.sent_at.desc()).first()
                        if last_log and last_log.ab_test_id and last_log.ab_test_variant:
                            from ..services.ab_testing_service import record_outcome
                            record_outcome(last_log.ab_test_id, last_log.ab_test_variant, "reply", db)
                    except Exception:
                        pass

                    try:
                        last_log = db.query(MessageLogDB).filter(
                            MessageLogDB.lead_id == lead.id,
                            MessageLogDB.channel == "whatsapp",
                            MessageLogDB.ab_test_id != None,
                        ).order_by(MessageLogDB.sent_at.desc()).first()
                        if last_log and last_log.ab_test_id:
                            from ..services.ab_testing_service import record_outcome
                            record_outcome(last_log.ab_test_id, last_log.ab_test_variant or "control", "reply", db)
                    except Exception:
                        pass



                    from ..models import ConversationDB
                    db.add(ConversationDB(
                        lead_id=lead.id,
                        client_id=lead.client_id,
                        role="user",
                        content=f"[WhatsApp] {message_text}"
                    ))

        db.commit()
    finally:
        db.close()

    return {"success": True}


@router.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request):
    """Handles Razorpay subscription and payment events."""
    import json as _json
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    if not verify_razorpay_webhook(body, signature):
        raise HTTPException(403, "Invalid Razorpay webhook signature")

    try:
        payload = _json.loads(body)
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")

    event = payload.get("event", "")
    entity = payload.get("payload", {})
    now = datetime.utcnow()

    db = SessionLocal()
    try:
        if event == "subscription.activated":
            sub_data = entity.get("subscription", {}).get("entity", {})
            rz_sub_id = sub_data.get("id", "")
            notes = sub_data.get("notes", {})
            client_id = notes.get("client_id", "")
            tier = notes.get("tier", "starter")
            start = datetime.utcfromtimestamp(sub_data.get("current_start", now.timestamp()))
            end   = datetime.utcfromtimestamp(sub_data.get("current_end", now.timestamp()))
            activate_client(client_id, tier, start, end, rz_sub_id)

        elif event == "subscription.charged":
            sub_data = entity.get("subscription", {}).get("entity", {})
            pmt_data = entity.get("payment", {}).get("entity", {})
            rz_sub_id = sub_data.get("id", "")
            notes = sub_data.get("notes", {})
            client_id = notes.get("client_id", "")
            tier = notes.get("tier", "starter")
            start = datetime.utcfromtimestamp(sub_data.get("current_start", now.timestamp()))
            end   = datetime.utcfromtimestamp(sub_data.get("current_end", now.timestamp()))
            activate_client(client_id, tier, start, end, rz_sub_id)
            log_payment(
                client_id=client_id,
                rz_payment_id=pmt_data.get("id", ""),
                rz_invoice_id=pmt_data.get("invoice_id", ""),
                amount_paise=pmt_data.get("amount", 0),
                status="captured",
                period_start=start,
                period_end=end,
            )

        elif event == "payment.failed":
            pmt_data = entity.get("payment", {}).get("entity", {})
            rz_sub_id = pmt_data.get("subscription_id", "")
            reason = pmt_data.get("error_description", "Payment failed")
            # Find client from subscription
            from ..models import SubscriptionDB
            sub = db.query(SubscriptionDB).filter(
                SubscriptionDB.razorpay_subscription_id == rz_sub_id
            ).first()
            client_id = sub.client_id if sub else ""
            if client_id:
                log_payment(
                    client_id=client_id,
                    rz_payment_id=pmt_data.get("id", ""),
                    rz_invoice_id=pmt_data.get("invoice_id", ""),
                    amount_paise=pmt_data.get("amount", 0),
                    status="failed",
                    failure_reason=reason,
                )
                handle_payment_failure(client_id, rz_sub_id, reason)

        elif event in ("subscription.cancelled", "subscription.completed"):
            sub_data = entity.get("subscription", {}).get("entity", {})
            rz_sub_id = sub_data.get("id", "")
            notes = sub_data.get("notes", {})
            client_id = notes.get("client_id", "")
            # On cancellation: let the current period end naturally
            cancel_subscription(client_id, rz_sub_id, at_period_end=True)

    except Exception as e:
        import json as _json2
        import logging
        logging.getLogger("webhooks").error(_json2.dumps({
            "event": "razorpay_webhook_handler_error",
            "rz_event": event,
            "error": str(e),
            "timestamp": now.isoformat(),
        }))
    finally:
        db.close()

    return {"success": True}

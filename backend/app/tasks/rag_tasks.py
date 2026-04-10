import logging
from ..tasks.celery_app import celery

logger = logging.getLogger("rag_tasks")


@celery.task(bind=True, max_retries=2)
def sync_client_rag(self, client_id: str):
    from datetime import datetime, timedelta
    from ..database import SessionLocal
    from ..models import MessageLogDB, LeadDB
    from ..services.rag_service import store_successful_message

    db = SessionLocal()
    indexed = 0
    skipped = 0
    cutoff = datetime.utcnow() - timedelta(days=7)
    try:
        logs = db.query(MessageLogDB).filter(
            MessageLogDB.client_id == client_id,
            MessageLogDB.status == "sent",
            MessageLogDB.sent_at >= cutoff,
        ).all()

        for log in logs:
            try:
                lead = db.query(LeadDB).filter(LeadDB.id == log.lead_id).first()
                if not lead or not log.message:
                    skipped += 1
                    continue

                if lead.status in ("replied", "meeting_booked"):
                    signal = 1.0
                elif lead.status == "contacted" and log.opened_at:
                    signal = 0.5
                else:
                    signal = 0.0

                if signal == 0.0:
                    skipped += 1
                    continue

                language = "en"
                try:
                    from ..models import ClientDB
                    client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
                    if client and isinstance(client.tone_config, dict):
                        language = client.tone_config.get("language", "en")
                except Exception:
                    pass

                store_successful_message(
                    client_id=client_id,
                    lead_id=log.lead_id,
                    message_text=log.message,
                    channel=log.channel or "email",
                    language=language,
                    industry=lead.industry or "",
                    reply_rate_signal=signal,
                    db=db,
                )
                indexed += 1
            except Exception as e:
                logger.error(f"sync_client_rag: error on log {log.id}: {e}")
                skipped += 1

    except Exception as exc:
        logger.error(f"sync_client_rag failed for {client_id}: {exc}")
        raise self.retry(exc=exc)
    finally:
        db.close()

    logger.info(f"sync_client_rag: client={client_id} indexed={indexed} skipped={skipped}")
    return {"client_id": client_id, "indexed": indexed, "skipped": skipped}


@celery.task
def sync_all_client_messages():
    from ..database import SessionLocal
    from ..models import ClientDB

    db = SessionLocal()
    count = 0
    try:
        clients = db.query(ClientDB).filter(ClientDB.is_active == True).all()
        for client in clients:
            sync_client_rag.delay(client.id)
            count += 1
    finally:
        db.close()

    logger.info(f"sync_all_client_messages: queued {count} clients")
    return {"clients_queued": count}

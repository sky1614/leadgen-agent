import logging
from datetime import datetime, timedelta

from .celery_app import celery
from ..database import SessionLocal
from ..models import ClientDB

logger = logging.getLogger("followup_tasks")


def _is_blackout(client: ClientDB) -> bool:
    from datetime import date
    today = date.today().isoformat()
    return today in (client.festival_blackout_dates or [])


@celery.task(bind=True, max_retries=3, default_retry_delay=300)
def schedule_followup(self, message_id: str, lead_id: str, client_id: str, followup_day: int):
    db = SessionLocal()
    try:
        client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
        if client and _is_blackout(client):
            raise self.retry(eta=datetime.utcnow() + timedelta(days=1))

        from ..services.delivery_service import handle_day3_followup
        result = handle_day3_followup(message_id, lead_id, client_id)
        logger.info({"event": "day3_followup_done", "lead_id": lead_id, "result": result})
        return result

    except Exception as exc:
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            logger.error({"event": "day3_followup_failed", "lead_id": lead_id, "error": str(exc)})
            return {"error": str(exc)}
    finally:
        db.close()


@celery.task(bind=True, max_retries=2)
def channel_switch_followup(self, message_id: str, lead_id: str, client_id: str):
    db = SessionLocal()
    try:
        from ..services.delivery_service import handle_day7_channel_switch
        result = handle_day7_channel_switch(message_id, lead_id, client_id)
        logger.info({"event": "day7_channel_switch_done", "lead_id": lead_id, "result": result})
        return result

    except Exception as exc:
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            logger.error({"event": "day7_channel_switch_failed", "lead_id": lead_id, "error": str(exc)})
            return {"error": str(exc)}
    finally:
        db.close()

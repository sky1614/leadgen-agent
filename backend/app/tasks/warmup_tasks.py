from datetime import datetime

from .celery_app import celery
from ..database import SessionLocal
from ..models import ClientDB


def get_daily_limit(client: ClientDB) -> int:
    if not client.created_at:
        return 10
    days_since_setup = (datetime.utcnow() - client.created_at).days
    if days_since_setup <= 7:
        return 10
    elif days_since_setup <= 14:
        return 25
    elif days_since_setup <= 21:
        return 50
    else:
        return client.monthly_email_cap // 30 or 9999


@celery.task(bind=True, max_retries=2)
def check_warmup_status(self, client_id: str):
    db = SessionLocal()
    try:
        client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
        if not client:
            return {"error": "client not found"}
        limit = get_daily_limit(client)
        return {
            "client_id": client_id,
            "daily_limit": limit,
            "days_since_setup": (datetime.utcnow() - client.created_at).days if client.created_at else 0
        }
    except Exception as exc:
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {"error": str(exc)}
    finally:
        db.close()


@celery.task
def check_all_warmups():
    db = SessionLocal()
    try:
        clients = db.query(ClientDB).filter(ClientDB.is_active == True).all()
        for client in clients:
            check_warmup_status.delay(client.id)
        return {"checked": len(clients)}
    finally:
        db.close()

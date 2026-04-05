from datetime import datetime

from .celery_app import celery
from ..database import SessionLocal
from ..models import ClientDB, MessageLogDB
from ..services.whatsapp_service import check_quality_safe


@celery.task(bind=True, max_retries=2)
def check_wa_health(self, client_id: str):
    """Runs every 6 hours. Checks WA quality and complaint rate."""
    db = SessionLocal()
    try:
        client = db.query(ClientDB).filter(ClientDB.id == client_id).first()
        if not client:
            return {"error": "client not found"}

        quality = check_quality_safe(client_id)
        rating = quality["rating"]
        alert = None

        if rating == "RED":
            alert = f"[URGENT] WA quality RED for client {client_id} — all WA sends paused"
            print(alert)

        elif rating == "YELLOW":
            alert = f"[WARNING] WA quality YELLOW for client {client_id} — volume reduced 50%"
            print(alert)

        # Check complaint rate: # spam reports / total WA sends in last 7 days
        seven_days_ago = datetime.utcnow().replace(hour=0, minute=0, second=0) 
        from datetime import timedelta
        seven_days_ago = datetime.utcnow() - timedelta(days=7)

        total_sent = db.query(MessageLogDB).filter(
            MessageLogDB.client_id == client_id,
            MessageLogDB.channel == "whatsapp",
            MessageLogDB.sent_at >= seven_days_ago
        ).count()

        spam_reports = db.query(MessageLogDB).filter(
            MessageLogDB.client_id == client_id,
            MessageLogDB.channel == "whatsapp",
            MessageLogDB.spam_reported == True,
            MessageLogDB.sent_at >= seven_days_ago
        ).count()

        complaint_rate = (spam_reports / total_sent * 100) if total_sent > 0 else 0

        if complaint_rate > 2:
            alert = f"[URGENT] WA complaint rate {complaint_rate:.1f}% for client {client_id} — pausing sends"
            print(alert)

        return {
            "client_id": client_id,
            "quality_rating": rating,
            "complaint_rate": f"{complaint_rate:.2f}%",
            "total_wa_sent_7d": total_sent,
            "alert": alert
        }

    except Exception as exc:
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {"error": str(exc)}
    finally:
        db.close()


@celery.task
def check_all_wa_health():
    db = SessionLocal()
    try:
        clients = db.query(ClientDB).filter(ClientDB.is_active == True).all()
        for client in clients:
            check_wa_health.delay(client.id)
        return {"checked": len(clients)}
    finally:
        db.close()

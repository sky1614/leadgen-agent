import logging
import json
from datetime import datetime, timedelta
from .celery_app import celery

logger = logging.getLogger("demo_tasks")


@celery.task
def cleanup_expired_demos():
    """
    Daily cleanup:
    - Expire demos past their 7-day active window (mark status=expired).
    - Hard-delete demo data (leads, messages, client) older than 30 days.
    - Keep DemoDB record itself (report_viewed, converted_to_paid = sales funnel data).
    """
    from ..database import SessionLocal
    from ..models import DemoDB, LeadDB, MessageLogDB, ClientDB, UserDB, CampaignDB

    db = SessionLocal()
    now = datetime.utcnow()
    expired_count = 0
    deleted_count = 0

    try:
        # ── 1. Mark demos past expiry as expired ──────────────────────────────
        active_demos = db.query(DemoDB).filter(
            DemoDB.status.in_(["created", "running", "complete"]),
            DemoDB.expires_at < now,
        ).all()

        for demo in active_demos:
            demo.status = "expired"
            expired_count += 1

        db.commit()

        # ── 2. Hard-delete demo data older than 30 days ───────────────────────
        cutoff = now - timedelta(days=30)
        old_demos = db.query(DemoDB).filter(
            DemoDB.created_at < cutoff,
            DemoDB.demo_client_id != None,
        ).all()

        for demo in old_demos:
            cid = demo.demo_client_id
            try:
                db.query(MessageLogDB).filter(MessageLogDB.client_id == cid).delete()
                db.query(LeadDB).filter(LeadDB.client_id == cid).delete()
                db.query(CampaignDB).filter(CampaignDB.client_id == cid).delete()
                db.query(UserDB).filter(UserDB.client_id == cid).delete()
                db.query(ClientDB).filter(ClientDB.id == cid).delete()
                demo.demo_client_id = None  # keep demo record, drop client data
                deleted_count += 1
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(json.dumps({
                    "event": "demo_cleanup_error",
                    "demo_id": demo.id,
                    "client_id": cid,
                    "error": str(e),
                    "timestamp": now.isoformat(),
                }))

        logger.info(json.dumps({
            "event": "demo_cleanup_complete",
            "expired": expired_count,
            "data_deleted": deleted_count,
            "timestamp": now.isoformat(),
        }))

        return {"expired": expired_count, "data_deleted": deleted_count}

    except Exception as e:
        logger.error(json.dumps({
            "event": "demo_cleanup_fatal",
            "error": str(e),
            "timestamp": now.isoformat(),
        }))
        return {"error": str(e)}
    finally:
        db.close()

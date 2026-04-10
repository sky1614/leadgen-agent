import logging
from datetime import datetime

from ..database import SessionLocal
from ..models import AgentJobDB, AgentJobItemDB, MessageLogDB

logger = logging.getLogger("delivery_agent")

DELIVERY_BATCH_SIZE = 20
AUTO_APPROVE_THRESHOLD = 9.0
AUTO_APPROVE_MIN_MESSAGES = 100


def run_delivery(job_id: str, client_id: str, user_id: str, db):
    from ..services.redis_service import consume_from_queue

    auto_approved = 0
    pending_approval = 0
    delivery_triggered = 0

    queue_key = f"delivery_queue:{job_id}"

    # STEP 2 — Check auto-approve eligibility for this client
    historical_count = db.query(MessageLogDB).filter(
        MessageLogDB.client_id == client_id
    ).count()
    client_auto_approve_eligible = historical_count >= AUTO_APPROVE_MIN_MESSAGES

    # STEP 1 — Consume all items from queue
    items_to_process = []
    while True:
        item = consume_from_queue(queue_key, timeout=30)
        if item is None:
            break
        items_to_process.append(item)

    for item in items_to_process:
        item_id = item.get("item_id")
        job_item = db.query(AgentJobItemDB).filter(AgentJobItemDB.id == item_id).first()
        if not job_item:
            continue

        # Get judge score if available (stored in quality_gate_score via message log)
        judge_score = _get_judge_score(job_id, job_item.lead_id, db)

        auto_approve = (
            client_auto_approve_eligible and
            judge_score is not None and
            judge_score >= AUTO_APPROVE_THRESHOLD
        )

        # STEP 3 — Create MessageLogDB records
        if job_item.email_message:
            log = MessageLogDB(
                user_id=user_id,
                client_id=client_id,
                lead_id=job_item.lead_id,
                campaign_id=_get_campaign_id(job_id, db),
                channel="email",
                message=job_item.email_message,
                status="pending" if auto_approve else "pending_approval",
                approval_status="auto_approved" if auto_approve else "pending_approval",
                quality_gate_score=judge_score,
            )
            db.add(log)
            db.flush()

            if auto_approve:
                _trigger_send(log.id, job_item.lead_id, client_id)
                delivery_triggered += 1

        if job_item.whatsapp_message:
            log = MessageLogDB(
                user_id=user_id,
                client_id=client_id,
                lead_id=job_item.lead_id,
                campaign_id=_get_campaign_id(job_id, db),
                channel="whatsapp",
                message=job_item.whatsapp_message,
                status="pending" if auto_approve else "pending_approval",
                approval_status="auto_approved" if auto_approve else "pending_approval",
                quality_gate_score=judge_score,
            )
            db.add(log)
            db.flush()

            if auto_approve:
                _trigger_send(log.id, job_item.lead_id, client_id)
                delivery_triggered += 1

        if auto_approve:
            job_item.status = "auto_approved"
            auto_approved += 1
        else:
            job_item.status = "pending_approval"
            pending_approval += 1

        db.commit()

    # STEP 5 — Update AgentJobDB
    job = db.query(AgentJobDB).filter(AgentJobDB.id == job_id).first()
    if job:
        job.delivery_status = "complete"
        job.auto_approved_count = auto_approved
        job.pending_approval_count = pending_approval
        if pending_approval > 0:
            job.status = "pending_approval"
        elif auto_approved > 0:
            job.status = "auto_approved"
        db.commit()

    logger.info({
        "event": "delivery_complete",
        "job_id": job_id,
        "auto_approved": auto_approved,
        "pending_approval": pending_approval,
        "delivery_triggered": delivery_triggered,
    })

    return {
        "auto_approved": auto_approved,
        "pending_approval": pending_approval,
        "delivery_triggered": delivery_triggered,
    }


def _get_judge_score(job_id: str, lead_id: str, db):
    try:
        from ..models import JudgeEvaluationDB
        judge = db.query(JudgeEvaluationDB).filter(
            JudgeEvaluationDB.job_id == job_id,
            JudgeEvaluationDB.lead_id == lead_id,
        ).order_by(JudgeEvaluationDB.created_at.desc()).first()
        if judge:
            return judge.weighted_score
    except Exception:
        pass
    return None


def _get_campaign_id(job_id: str, db):
    try:
        job = db.query(AgentJobDB).filter(AgentJobDB.id == job_id).first()
        return job.campaign_id if job else ""
    except Exception:
        return ""


def _trigger_send(message_id: str, lead_id: str, client_id: str):
    try:
        from ..tasks.multi_agent_tasks import trigger_send_task
        trigger_send_task.delay(message_id, lead_id, client_id)
    except Exception as _e:
        logger.warning(f"trigger_send failed for {message_id}: {_e}")


def get_delivery_status(job_id: str, db):
    job = db.query(AgentJobDB).filter(AgentJobDB.id == job_id).first()
    if not job or not job.delivery_status:
        return {"status": "not_started", "auto_approved_count": 0, "pending_approval_count": 0}
    return {
        "status": job.delivery_status,
        "auto_approved_count": job.auto_approved_count or 0,
        "pending_approval_count": job.pending_approval_count or 0,
    }

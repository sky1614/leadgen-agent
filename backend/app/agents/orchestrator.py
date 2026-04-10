import logging
from datetime import datetime, timedelta

from ..database import SessionLocal
from ..models import AgentJobDB
from .prospector_agent import run_prospector, get_prospector_status
from .scorer_agent import get_scorer_status
from .writer_agent import get_writer_status
from .delivery_agent import get_delivery_status

logger = logging.getLogger("orchestrator")

MAX_JOB_MINUTES = 30


def run_multi_agent_job(job_id: str, user_id: str, req, db):
    from ..tasks.multi_agent_tasks import (
        scorer_agent_task, writer_agent_task,
        delivery_agent_task, check_job_completion_task,
    )

    job = db.query(AgentJobDB).filter(AgentJobDB.id == job_id).first()
    client_id = job.client_id if job else None

    # PHASE 1 — Prospector (synchronous)
    try:
        result = run_prospector(
            job_id=job_id,
            client_id=client_id,
            user_id=user_id,
            industry=req.industry,
            city=getattr(req, "city", "Mumbai"),
            count=req.count,
            source_url=req.source_url or "",
            db=db,
        )
        if result["leads_found"] == 0:
            job = db.query(AgentJobDB).filter(AgentJobDB.id == job_id).first()
            if job:
                job.status = "error"
                job.prospector_status = "complete"
                db.commit()
            logger.warning({"event": "no_leads_found", "job_id": job_id})
            return
    except Exception as _pe:
        logger.error({"event": "prospector_error", "job_id": job_id, "error": str(_pe)})
        job = db.query(AgentJobDB).filter(AgentJobDB.id == job_id).first()
        if job:
            job.status = "error"
            db.commit()
        return

    # PHASE 2 & 3 — Scorer, Writer, Delivery (pipeline via Celery)
    scorer_agent_task.delay(job_id, client_id, user_id)
    writer_agent_task.delay(job_id, client_id, user_id, req.campaign_id)
    delivery_agent_task.delay(job_id, client_id, user_id)

    # PHASE 4 — Schedule completion check
    check_job_completion_task.apply_async(
        args=[job_id],
        countdown=300,
    )

    logger.info({"event": "multi_agent_job_launched", "job_id": job_id})


def check_job_completion(job_id: str, db):
    from ..services.redis_service import cleanup_job_queues

    job = db.query(AgentJobDB).filter(AgentJobDB.id == job_id).first()
    if not job:
        return

    # Timeout check
    if job.created_at:
        elapsed = datetime.utcnow() - job.created_at
        if elapsed > timedelta(minutes=MAX_JOB_MINUTES):
            if job.status not in ("pending_approval", "auto_approved", "approved", "error"):
                job.status = "timeout"
                db.commit()
            cleanup_job_queues(job_id)
            return

    # Check terminal statuses
    if job.status in ("pending_approval", "auto_approved", "approved", "error", "timeout"):
        cleanup_job_queues(job_id)
        _trigger_post_job_tasks(job_id, job.client_id, db)
        return

    prospector_done = (job.prospector_status == "complete")
    scorer_done = (job.scorer_status == "complete")
    writer_done = (job.writer_status == "complete")
    delivery_done = (job.delivery_status == "complete")

    if prospector_done and scorer_done and writer_done and delivery_done:
        # Set final status based on delivery result
        if (job.pending_approval_count or 0) > 0:
            job.status = "pending_approval"
        elif (job.auto_approved_count or 0) > 0:
            job.status = "auto_approved"
        else:
            job.status = "error"
        db.commit()
        cleanup_job_queues(job_id)
        _trigger_post_job_tasks(job_id, job.client_id, db)
        return

    # Reschedule check
    from ..tasks.multi_agent_tasks import check_job_completion_task
    check_job_completion_task.apply_async(args=[job_id], countdown=60)


def _trigger_post_job_tasks(job_id: str, client_id: str, db):
    try:
        from ..services.autonomous_loop import run_autonomous_evaluation
        import threading
        threading.Thread(
            target=run_autonomous_evaluation,
            args=(client_id, SessionLocal()),
            daemon=True
        ).start()
    except Exception:
        pass

    try:
        from ..services.reflexion_service import analyze_job_failures, generate_reflection, save_reflection
        import threading

        def _reflexion():
            _db = SessionLocal()
            try:
                failures = analyze_job_failures(job_id, client_id, _db)
                if failures:
                    job = _db.query(AgentJobDB).filter(AgentJobDB.id == job_id).first()
                    camp_context = {"industry": job.industry if job else ""}
                    reflection = generate_reflection(failures, camp_context, client_id)
                    if reflection:
                        save_reflection(client_id, job_id, reflection, _db)
            finally:
                _db.close()

        threading.Thread(target=_reflexion, daemon=True).start()
    except Exception:
        pass

import logging

from .celery_app import celery
from ..database import SessionLocal

logger = logging.getLogger("multi_agent_tasks")


@celery.task(bind=True, max_retries=2, name="app.tasks.multi_agent_tasks.scorer_agent_task")
def scorer_agent_task(self, job_id: str, client_id: str, user_id: str):
    db = SessionLocal()
    try:
        from ..agents.scorer_agent import run_scorer
        return run_scorer(job_id, client_id, user_id, db)
    except Exception as exc:
        logger.error({"event": "scorer_task_error", "job_id": job_id, "error": str(exc)})
        try:
            self.retry(exc=exc, countdown=30)
        except self.MaxRetriesExceededError:
            _mark_job_error(job_id)
    finally:
        db.close()


@celery.task(bind=True, max_retries=2, name="app.tasks.multi_agent_tasks.writer_agent_task")
def writer_agent_task(self, job_id: str, client_id: str, user_id: str, campaign_id: str):
    db = SessionLocal()
    try:
        from ..agents.writer_agent import run_writer
        return run_writer(job_id, client_id, user_id, campaign_id, db)
    except Exception as exc:
        logger.error({"event": "writer_task_error", "job_id": job_id, "error": str(exc)})
        try:
            self.retry(exc=exc, countdown=30)
        except self.MaxRetriesExceededError:
            _mark_job_error(job_id)
    finally:
        db.close()


@celery.task(bind=True, max_retries=2, name="app.tasks.multi_agent_tasks.delivery_agent_task")
def delivery_agent_task(self, job_id: str, client_id: str, user_id: str):
    db = SessionLocal()
    try:
        from ..agents.delivery_agent import run_delivery
        return run_delivery(job_id, client_id, user_id, db)
    except Exception as exc:
        logger.error({"event": "delivery_task_error", "job_id": job_id, "error": str(exc)})
        try:
            self.retry(exc=exc, countdown=30)
        except self.MaxRetriesExceededError:
            _mark_job_error(job_id)
    finally:
        db.close()


@celery.task(bind=True, max_retries=10, name="app.tasks.multi_agent_tasks.check_job_completion_task")
def check_job_completion_task(self, job_id: str):
    db = SessionLocal()
    try:
        from ..agents.orchestrator import check_job_completion
        check_job_completion(job_id, db)
    except Exception as exc:
        logger.error({"event": "completion_check_error", "job_id": job_id, "error": str(exc)})
        try:
            self.retry(exc=exc, countdown=60)
        except self.MaxRetriesExceededError:
            _mark_job_error(job_id)
    finally:
        db.close()


@celery.task(bind=True, max_retries=2, name="app.tasks.multi_agent_tasks.trigger_send_task")
def trigger_send_task(self, message_id: str, lead_id: str, client_id: str):
    try:
        from ..services.delivery_service import execute_send
        return execute_send(message_id, lead_id, client_id)
    except Exception as exc:
        logger.error({"event": "trigger_send_error", "message_id": message_id, "error": str(exc)})
        try:
            self.retry(exc=exc, countdown=60)
        except self.MaxRetriesExceededError:
            pass


def _mark_job_error(job_id: str):
    db = SessionLocal()
    try:
        from ..models import AgentJobDB
        job = db.query(AgentJobDB).filter(AgentJobDB.id == job_id).first()
        if job and job.status == "running":
            job.status = "error"
            db.commit()
    except Exception:
        pass
    finally:
        db.close()

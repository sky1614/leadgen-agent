import logging
from .celery_app import celery

logger = logging.getLogger("autonomous_tasks")


@celery.task(bind=True, max_retries=2, name="app.tasks.autonomous_tasks.evaluate_and_replan_client")
def evaluate_and_replan_client(self, client_id: str):
    from ..database import SessionLocal
    from ..services.autonomous_loop import run_autonomous_evaluation
    db = SessionLocal()
    try:
        results = run_autonomous_evaluation(client_id, db)
        replanned = sum(1 for r in results if r.get("replan_result", {}) and r["replan_result"].get("replanned"))
        logger.info(f"LOOP TASK: client={client_id} campaigns_evaluated={len(results)} replanned={replanned}")
        return {"client_id": client_id, "evaluated": len(results), "replanned": replanned}
    except Exception as exc:
        logger.error(f"evaluate_and_replan_client error client={client_id}: {exc}")
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {"error": str(exc), "client_id": client_id}
    finally:
        db.close()


@celery.task(name="app.tasks.autonomous_tasks.run_autonomous_loop_all_clients")
def run_autonomous_loop_all_clients():
    from ..database import SessionLocal
    from ..models import ClientDB
    db = SessionLocal()
    try:
        clients = db.query(ClientDB).filter(ClientDB.is_active == True).all()
        for client in clients:
            evaluate_and_replan_client.delay(client.id)
        logger.info(f"LOOP: dispatched autonomous evaluation for {len(clients)} clients")
        return {"dispatched": len(clients)}
    except Exception as e:
        logger.error(f"run_autonomous_loop_all_clients error: {e}")
        return {"error": str(e)}
    finally:
        db.close()

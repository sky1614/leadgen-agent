import logging
from .celery_app import celery

logger = logging.getLogger("opro_tasks")


@celery.task(name="app.tasks.opro_tasks.run_opro_for_all_clients")
def run_opro_for_all_clients():
    try:
        from ..database import SessionLocal
        from ..models import ClientDB
        from ..services.opro_service import run_opro_cycle

        db = SessionLocal()
        try:
            clients = db.query(ClientDB).filter(ClientDB.is_active == True).all()
            results = []
            for client in clients:
                try:
                    result = run_opro_cycle(client.id, db)
                    results.append({"client_id": client.id, **result})
                    logger.info(f"OPRO: client={client.id} optimized={result['optimized_count']}")
                except Exception as e:
                    logger.error(f"OPRO: failed for client={client.id}: {e}")
            return results
        finally:
            db.close()
    except Exception as e:
        logger.error(f"run_opro_for_all_clients error: {e}")
        return []

from .celery_app import celery
from ..database import SessionLocal
from ..models import ClientDB


@celery.task
def check_all_client_health():
    """Daily health check for all active clients at 8 AM IST."""
    from ..services.health_monitor import calculate_client_health
    db = SessionLocal()
    try:
        clients = db.query(ClientDB).filter(ClientDB.is_active == True).all()
        results = []
        for client in clients:
            try:
                health = calculate_client_health(client.id)
                results.append({
                    "client_id": client.id,
                    "status": health.get("status"),
                    "score": health.get("overall_score"),
                    "alerts": len(health.get("alerts", [])),
                })
                if health.get("alerts"):
                    print(f"HEALTH ALERTS for {client.id} ({client.name}): {health['alerts']}")
            except Exception as e:
                print(f"HEALTH CHECK ERROR for {client.id}: {e}")
        return {"checked": len(results), "results": results}
    finally:
        db.close()

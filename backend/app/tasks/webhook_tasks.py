import json
import logging
from .celery_app import celery

logger = logging.getLogger("webhook_tasks")


@celery.task(bind=True, max_retries=3, default_retry_delay=30)
def deliver_webhook(self, client_id: str, event_type: str, data: dict):
    """Celery task for async webhook delivery with retry."""
    try:
        from ..services.webhook_dispatcher import dispatch_event
        dispatch_event(client_id, event_type, data)
    except Exception as exc:
        logger.error(json.dumps({
            "event": "webhook_task_error",
            "client_id": client_id,
            "event_type": event_type,
            "error": str(exc),
        }))
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            pass

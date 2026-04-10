import json
import logging

logger = logging.getLogger("redis_service")

_redis_client = None


def get_redis_client():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis
        from ..config import REDIS_URL
        _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        _redis_client.ping()
        return _redis_client
    except Exception as _e:
        logger.warning(f"Redis connection failed: {_e}")
        return None


def publish_to_queue(queue_key: str, data: dict) -> bool:
    client = get_redis_client()
    if not client:
        return False
    try:
        client.lpush(queue_key, json.dumps(data))
        return True
    except Exception as _e:
        logger.error(f"publish_to_queue failed for {queue_key}: {_e}")
        return False


def consume_from_queue(queue_key: str, timeout: int = 30):
    client = get_redis_client()
    if not client:
        return None
    try:
        result = client.brpop(queue_key, timeout=timeout)
        if result is None:
            return None
        _, value = result
        return json.loads(value)
    except Exception as _e:
        logger.error(f"consume_from_queue failed for {queue_key}: {_e}")
        return None


def get_queue_size(queue_key: str) -> int:
    client = get_redis_client()
    if not client:
        return 0
    try:
        return client.llen(queue_key)
    except Exception:
        return 0


def cleanup_job_queues(job_id: str):
    client = get_redis_client()
    if not client:
        return
    keys = [
        f"scorer_queue:{job_id}",
        f"writer_queue:{job_id}",
        f"delivery_queue:{job_id}",
        f"writer_skip:{job_id}",
    ]
    try:
        client.delete(*keys)
    except Exception as _e:
        logger.warning(f"cleanup_job_queues failed for {job_id}: {_e}")

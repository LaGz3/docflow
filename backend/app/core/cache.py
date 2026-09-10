import json
import logging
from functools import lru_cache
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings

logger = logging.getLogger(__name__)


@lru_cache
def get_redis_client() -> Redis | None:
    if settings.REDIS_URL is None:
        return None
    return Redis.from_url(
        str(settings.REDIS_URL),
        decode_responses=True,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )


def get_json(key: str) -> Any | None:
    client = get_redis_client()
    if client is None:
        return None
    try:
        value = client.get(key)
    except RedisError:
        logger.warning("Redis read failed", exc_info=True)
        return None
    return json.loads(value) if value is not None else None


def set_json(key: str, value: Any, ttl_seconds: int | None = None) -> None:
    client = get_redis_client()
    if client is None:
        return
    try:
        client.setex(
            key,
            ttl_seconds or settings.CACHE_TTL_SECONDS,
            json.dumps(value, default=str),
        )
    except RedisError:
        logger.warning("Redis write failed", exc_info=True)


def delete(key: str) -> None:
    client = get_redis_client()
    if client is None:
        return
    try:
        client.delete(key)
    except RedisError:
        logger.warning("Redis delete failed", exc_info=True)


def ping() -> bool:
    client = get_redis_client()
    if client is None:
        return False
    try:
        return bool(client.ping())
    except RedisError:
        return False

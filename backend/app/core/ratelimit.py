"""Fixed-window rate limiter. Uses Redis when reachable, otherwise per-process memory."""
import threading
import time

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import AppError


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


class _MemoryWindow:
    def __init__(self):
        self.lock = threading.Lock()
        self.buckets: dict[str, tuple[int, int]] = {}

    def hit(self, key: str, window: int) -> int:
        now = int(time.time()) // window
        with self.lock:
            win, count = self.buckets.get(key, (now, 0))
            if win != now:
                win, count = now, 0
            count += 1
            self.buckets[key] = (win, count)
            return count


_memory = _MemoryWindow()
_redis = None
_redis_checked = False


def _redis_client():
    global _redis, _redis_checked
    if _redis_checked:
        return _redis
    _redis_checked = True
    s = get_settings()
    if s.environment == "test" or s.celery_task_always_eager:
        return None
    try:
        import redis

        client = redis.Redis.from_url(s.redis_url, socket_connect_timeout=0.5)
        client.ping()
        _redis = client
    except Exception:
        _redis = None
    return _redis


def check_rate(key: str, limit: int, window_seconds: int = 60) -> None:
    client = _redis_client()
    if client is not None:
        bucket = f"rl:{key}:{int(time.time()) // window_seconds}"
        count = client.incr(bucket)
        if count == 1:
            client.expire(bucket, window_seconds)
    else:
        count = _memory.hit(key, window_seconds)
    if count > limit:
        raise RateLimited("Too many requests. Please wait a minute and try again.")


def auth_rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    check_rate(f"auth:{ip}:{request.url.path}", get_settings().rate_limit_auth_per_minute)


def reset_rate_limits() -> None:
    _memory.buckets.clear()

"""Fixed-window rate limiting. Redis when reachable (shared across workers), in-process fallback otherwise."""
import logging
import time

from fastapi import HTTPException, Request

from .config import get_settings

log = logging.getLogger("medcart.ratelimit")
_mem: dict[str, tuple[int, float]] = {}
_redis = None
_redis_failed = False


def _get_redis():
    global _redis, _redis_failed
    if _redis or _redis_failed:
        return _redis
    try:
        import redis
        r = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=0.3, socket_timeout=0.3)
        r.ping()
        _redis = r
    except Exception:  # noqa: BLE001
        _redis_failed = True
        log.warning("Redis unavailable: using per-process rate limiting")
    return _redis


def reset() -> None:
    _mem.clear()
    r = _get_redis()
    if r:
        for k in r.scan_iter("rl:*"):
            r.delete(k)


def hit(key: str, limit: int, window: int) -> bool:
    """Returns True if the call is allowed."""
    r = _get_redis()
    if r:
        try:
            k = f"rl:{key}:{int(time.time() // window)}"
            n = r.incr(k)
            if n == 1:
                r.expire(k, window)
            return n <= limit
        except Exception:  # noqa: BLE001
            pass
    now = time.time()
    n, start = _mem.get(key, (0, now))
    if now - start >= window:
        n, start = 0, now
    _mem[key] = (n + 1, start)
    return n + 1 <= limit


def client_ip(request: Request) -> str:
    if get_settings().trust_proxy_headers:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def limit(name: str, per: int, window: int):
    """FastAPI dependency: `Depends(limit("login", 10, 60))`."""
    def dep(request: Request):
        if get_settings().rate_limit_enabled and not hit(f"{name}:{client_ip(request)}", per, window):
            raise HTTPException(429, "Too many requests. Please slow down.", headers={"Retry-After": str(window)})
    return dep

"""Small production-ops helpers: structured logging and rate limiting.

These are intentionally dependency-light. For multi-instance deployments,
replace the in-memory limiter with Redis/Valkey while keeping the same API.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import defaultdict, deque

logger = logging.getLogger("revenuerescue")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

_BUCKETS: dict[str, deque[float]] = defaultdict(deque)
_LOCK = threading.Lock()


def request_id() -> str:
    return "req_" + uuid.uuid4().hex[:16]


def log_event(event: str, **fields) -> None:
    logger.info(json.dumps({
        "ts": time.time(),
        "event": event,
        **fields,
    }, separators=(",", ":"), default=str))


def allow_request(key: str, *, limit: int = 30, window_seconds: int = 60) -> bool:
    now = time.time()
    cutoff = now - window_seconds
    with _LOCK:
        bucket = _BUCKETS[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True

"""Per-source in-memory cache to coalesce model panels sharing one account."""

import threading
import time

_guard = threading.Lock()
_locks = {}
_values = {}


def cached(key: tuple, ttl: float, fetch):
    with _guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        now = time.monotonic()
        entry = _values.get(key)
        if entry and entry[0] > now:
            return entry[1]
        value = fetch()
        _values[key] = (time.monotonic() + ttl, value)
        return value


def cached_with_time(key: tuple, ttl: float, fetch):
    return cached(key, ttl, lambda: (fetch(), time.time()))

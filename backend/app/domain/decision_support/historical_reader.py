from datetime import datetime
import logging
import os
import time
import threading

# Try to import the historical aggregator; if it's not available, fall back
# to returning None so the reliability pipeline can handle missing data.
try:
    from app.jobs.live_historical.historical_aggregator import HISTORICAL_STORE, time_bucket  # type: ignore
except Exception:
    HISTORICAL_STORE = None
    time_bucket = None  # type: ignore


# Simple in-memory TTL cache for historical lookups to avoid repeated reads
# within a short window. Keyed by (mode, from_id, to_id, bucket).
_HIST_CACHE = {}
_HIST_CACHE_LOCK = threading.Lock()
logger = logging.getLogger(__name__)

def _cache_key(mode: str, from_id: str, to_id: str, bucket: str):
    return f"{mode}:{from_id}:{to_id}:{bucket}"


def _get_ttl_seconds() -> int:
    try:
        return int(os.environ.get("HISTORICAL_CACHE_TTL_SECONDS", "300"))
    except Exception:
        return 300


def get_historical_stats(mode: str, from_id: str, to_id: str, depart_time: datetime):
    """Return historical stats or None if unavailable.

    Expected return shape: {"on_time_pct", "avg_delay", "missed_pct"}
    """
    if HISTORICAL_STORE is None or time_bucket is None:
        logger.debug("historical stats unavailable; returning safe default")
        return {"available": False, "on_time_pct": 70.0, "avg_delay": 0.0, "missed_pct": 0.0}

    try:
        bucket = time_bucket(depart_time)
        key = _cache_key(mode, from_id, to_id, bucket)

        now = time.time()
        ttl = _get_ttl_seconds()

        # Check cache
        with _HIST_CACHE_LOCK:
            entry = _HIST_CACHE.get(key)
            if entry is not None:
                expiry, value = entry
                if now < expiry:
                    return value
                else:
                    # expired
                    del _HIST_CACHE[key]

        # Not cached or expired — fetch from store
        stats = HISTORICAL_STORE.get_stats(mode, from_id, to_id, bucket)
        if not stats:
            value = {"available": False, "on_time_pct": 70.0, "avg_delay": 0.0, "missed_pct": 0.0}
        else:
            count = stats.get("count", 0)
            if count == 0:
                value = {"available": False, "on_time_pct": 70.0, "avg_delay": 0.0, "missed_pct": 0.0}
            else:
                on_time_pct = (stats.get("on_time_count", 0) / count) * 100
                avg_delay = stats.get("total_delay", 0) / count
                missed_pct = (stats.get("missed_connection_count", 0) / count) * 100

                value = {
                    "available": True,
                    "on_time_pct": on_time_pct,
                    "avg_delay": avg_delay,
                    "missed_pct": missed_pct,
                }

        # Store in cache (including None results) with TTL
        expiry = now + ttl
        with _HIST_CACHE_LOCK:
            _HIST_CACHE[key] = (expiry, value)

        return value
    except Exception as e:
        logger.exception("Error reading historical stats: %s", e)
        return {"available": False, "on_time_pct": 70.0, "avg_delay": 0.0, "missed_pct": 0.0}

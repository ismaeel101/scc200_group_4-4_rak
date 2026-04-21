"""Live data reader with graceful fallbacks.

This module reads live status for bus/rail from Redis. If Redis or the
expected keys are not available, the `get_*_live` functions return `None`.
"""
import logging
import os
import json

from app.domain.decision_support.reliability_dto import LegLiveStatus

try:
    import redis  # type: ignore
    _REDIS_AVAILABLE = True
except Exception:
    redis = None
    _REDIS_AVAILABLE = False


def _redis():
    if not _REDIS_AVAILABLE:
        return None
    try:
        host = os.environ.get("REDIS_HOST", "redis")
        port = int(os.environ.get("REDIS_PORT", 6379))
        return redis.Redis(host=host, port=port, decode_responses=True)
    except Exception:
        logging.exception("Unable to create Redis client")
        return None


def _load_json(raw):
    try:
        if isinstance(raw, str):
            return json.loads(raw)
        if isinstance(raw, (bytes, bytearray)):
            return json.loads(raw.decode("utf-8"))
        return raw
    except Exception:
        logging.exception("Failed to parse live JSON payload")
        return None


def get_bus_live(service_id: str):
    """Return `LegLiveStatus` or None when live data is unavailable."""
    conn = _redis()
    if conn is None:
        logging.debug("Redis unavailable; returning None for bus live status")
        return None

    key = f"live:bus:{service_id}"
    try:
        raw = conn.get(key)
    except Exception:
        logging.exception("Redis get failed for key %s", key)
        return None

    if raw is None:
        return None

    data = _load_json(raw)
    if not data:
        return None

    return LegLiveStatus(
        available=True,
        delay_minutes=data.get("delay", 0),
        cancelled=data.get("cancelled", False),
        source=data.get("source", "live"),
    )


def get_rail_live(service_id: str):
    """Return `LegLiveStatus` or None when live data is unavailable."""
    conn = _redis()
    if conn is None:
        logging.debug("Redis unavailable; returning None for rail live status")
        return None

    key = f"live:rail:{service_id}"
    try:
        raw = conn.get(key)
    except Exception:
        logging.exception("Redis get failed for key %s", key)
        return None

    if raw is None:
        return None

    data = _load_json(raw)
    if not data:
        return None

    return LegLiveStatus(
        available=True,
        delay_minutes=data.get("delay", 0),
        cancelled=data.get("cancelled", False),
        source=data.get("source", "live"),
    )

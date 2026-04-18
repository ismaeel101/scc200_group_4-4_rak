def get_bus_live(stop_id):
    return None


def get_rail_live(stop_id):
    return None
import redis, json
from app.domain.decision_support.reliability_dto import LegLiveStatus

def _redis():
    return redis.Redis(host="redis", port=6379, decode_responses=True)

def get_bus_live(service_id: str):
    key = f"live:bus:{service_id}"
    raw = _redis().get(key)
    if raw is None:
        return None
    data = json.loads(raw)
    return LegLiveStatus(
        available=True,
        delay_minutes=data.get("delay", 0),
        cancelled=data.get("cancelled", False),
        source="live"
    )

def get_rail_live(service_id: str):
    key = f"live:rail:{service_id}"
    raw = _redis().get(key)
    if raw is None:
        return None
    data = json.loads(raw)
    return LegLiveStatus(
        available=True,
        delay_minutes=data.get("delay", 0),
        cancelled=data.get("cancelled", False),
        source="live"
    )

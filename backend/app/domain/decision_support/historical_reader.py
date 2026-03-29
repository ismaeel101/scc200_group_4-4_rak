from datetime import datetime
from app.jobs.live_historical.historical_aggregator import HISTORICAL_STORE, time_bucket

def get_historical_stats(mode: str, from_id: str, to_id: str, depart_time: datetime):
    bucket = time_bucket(depart_time)
    stats = HISTORICAL_STORE.get_stats(mode, from_id, to_id, bucket)
    if not stats:
        return None

    count = stats["count"]
    if count == 0:
        return None

    on_time_pct = (stats["on_time_count"] / count) * 100
    avg_delay = stats["total_delay"] / count
    missed_pct = (stats["missed_connection_count"] / count) * 100

    return {
        "on_time_pct": on_time_pct,
        "avg_delay": avg_delay,
        "missed_pct": missed_pct,
    }

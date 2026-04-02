from datetime import datetime

class CacheService:
    def get_freshness(self):
        now = datetime.utcnow()
        return {
            "timetable_updated_at": now,
            "live_updated_at": now,
            "weather_updated_at": now,
        }

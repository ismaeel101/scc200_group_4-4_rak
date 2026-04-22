from datetime import datetime
import time


def test_historical_cache_hit_and_expiry(monkeypatch):
    import app.domain.decision_support.historical_reader as hr

    # simple fake store that counts calls
    calls = {"n": 0}

    class FakeStore:
        def get_stats(self, mode, from_id, to_id, bucket):
            calls["n"] += 1
            return {"count": 2, "on_time_count": 2, "total_delay": 4, "missed_connection_count": 0}

    monkeypatch.setenv("HISTORICAL_CACHE_TTL_SECONDS", "1")
    monkeypatch.setattr(hr, "HISTORICAL_STORE", FakeStore())
    monkeypatch.setattr(hr, "time_bucket", lambda dt: "b1")

    # ensure cache is empty
    with hr._HIST_CACHE_LOCK:
        hr._HIST_CACHE.clear()

    # first call should hit the store
    v1 = hr.get_historical_stats("bus", "A", "B", datetime.now())
    assert v1 is not None
    assert calls["n"] == 1

    # second call within TTL should not call the store again
    v2 = hr.get_historical_stats("bus", "A", "B", datetime.now())
    assert calls["n"] == 1

    # wait for TTL to expire
    time.sleep(1.2)

    # next call should call the store again
    v3 = hr.get_historical_stats("bus", "A", "B", datetime.now())
    assert calls["n"] == 2

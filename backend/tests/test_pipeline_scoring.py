from datetime import datetime


class FakeLive:
    def __init__(self, delay_minutes=0, cancelled=False, source="live"):
        self.delay_minutes = delay_minutes
        self.cancelled = cancelled
        self.source = source


class FakeWeather:
    def __init__(self, condition="normal"):
        self.condition = condition


def test_history_delay_and_missed_penalties(monkeypatch):
    import app.domain.decision_support.reliability_pipeline as rp

    # Historical: on time 85, avg delay 5, missed 4%
    monkeypatch.setattr(rp, "get_historical_stats", lambda **kw: {
        "on_time_pct": 85,
        "avg_delay": 5,
        "missed_pct": 4,
    })
    monkeypatch.setattr(rp, "get_bus_live", lambda service_id: None)
    monkeypatch.setattr(rp, "get_rail_live", lambda service_id: None)
    monkeypatch.setattr(rp, "get_weather_stub", lambda: FakeWeather("normal"))

    j = {"depart_time": datetime.utcnow(), "legs": [{"mode": "bus", "service_id": "s1", "from": "A", "to": "B"}]}
    updated, flags = rp.compute_reliability(j)

    # base = 85 - 5 (avg_delay) - 2 (missed_pct/2) = 78
    assert updated["reliability_score"] == 78
    assert updated["reliability_band"] == "Medium"
    assert any("Average delay" in t for t in updated["reliability_explanation"]) 
    assert any("Missed connections" in t for t in updated["reliability_explanation"]) 


def test_weather_penalty_applied(monkeypatch):
    import app.domain.decision_support.reliability_pipeline as rp

    monkeypatch.setattr(rp, "get_historical_stats", lambda **kw: {"on_time_pct": 90, "avg_delay": 0, "missed_pct": 0})
    monkeypatch.setattr(rp, "get_bus_live", lambda service_id: None)
    monkeypatch.setattr(rp, "get_rail_live", lambda service_id: None)
    monkeypatch.setattr(rp, "get_weather_stub", lambda: FakeWeather("snow"))

    j = {"depart_time": datetime.utcnow(), "legs": [{"mode": "bus", "service_id": "s1", "from": "A", "to": "B"}]}
    updated, flags = rp.compute_reliability(j)

    # base 90, weather -10 => 80
    assert updated["reliability_score"] == 80
    assert updated["reliability_band"] == "High"
    assert any("Adverse weather" in t for t in updated["reliability_explanation"]) 


def test_multi_leg_live_cumulative_penalties(monkeypatch):
    import app.domain.decision_support.reliability_pipeline as rp

    # strong historical
    monkeypatch.setattr(rp, "get_historical_stats", lambda **kw: {"on_time_pct": 95, "avg_delay": 0, "missed_pct": 0})

    # leg1 delayed 10, leg2 cancelled
    def fake_bus_live(sid):
        if sid == "s1":
            return FakeLive(delay_minutes=10, cancelled=False)
        if sid == "s2":
            return FakeLive(delay_minutes=0, cancelled=True)

    monkeypatch.setattr(rp, "get_bus_live", fake_bus_live)
    monkeypatch.setattr(rp, "get_rail_live", lambda service_id: None)
    monkeypatch.setattr(rp, "get_weather_stub", lambda: FakeWeather("normal"))

    j = {"depart_time": datetime.utcnow(), "legs": [
        {"mode": "bus", "service_id": "s1", "from": "A", "to": "B"},
        {"mode": "bus", "service_id": "s2", "from": "B", "to": "C"},
    ]}

    updated, flags = rp.compute_reliability(j)

    # base 95 -10 (delay) =85 -40 (cancelled) =45
    assert updated["reliability_score"] == 45
    assert updated["reliability_band"] == "Low"
    assert any("Current live delay" in t for t in updated["reliability_explanation"]) 
    assert any("disrupted or cancelled" in t for t in updated["reliability_explanation"]) 


def test_avg_delay_clipped(monkeypatch):
    import app.domain.decision_support.reliability_pipeline as rp

    # avg_delay 30 should be clipped to 20 in penalty
    monkeypatch.setattr(rp, "get_historical_stats", lambda **kw: {"on_time_pct": 100, "avg_delay": 30, "missed_pct": 0})
    monkeypatch.setattr(rp, "get_bus_live", lambda service_id: None)
    monkeypatch.setattr(rp, "get_rail_live", lambda service_id: None)
    monkeypatch.setattr(rp, "get_weather_stub", lambda: FakeWeather("normal"))

    j = {"depart_time": datetime.utcnow(), "legs": [{"mode": "bus", "service_id": "s1", "from": "A", "to": "B"}]}
    updated, flags = rp.compute_reliability(j)

    # 100 - min(30,20) = 80
    assert updated["reliability_score"] == 80
    assert updated["reliability_band"] == "High"

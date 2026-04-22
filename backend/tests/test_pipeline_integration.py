from datetime import datetime


class FakeLive:
    def __init__(self, delay_minutes=0, cancelled=False, source="live"):
        self.delay_minutes = delay_minutes
        self.cancelled = cancelled
        self.source = source


class FakeWeather:
    def __init__(self, condition="normal"):
        self.condition = condition


def test_compute_reliability_with_historical(monkeypatch):
    import app.domain.decision_support.reliability_pipeline as rp

    # historical stats present
    monkeypatch.setattr(rp, "get_historical_stats", lambda **kw: {
        "on_time_pct": 90,
        "avg_delay": 0,
        "missed_pct": 0,
    })

    # live missing
    monkeypatch.setattr(rp, "get_bus_live", lambda service_id: None)
    monkeypatch.setattr(rp, "get_rail_live", lambda service_id: None)
    monkeypatch.setattr(rp, "get_weather_stub", lambda: FakeWeather("normal"))

    journey = {"depart_time": datetime.utcnow(), "legs": [{"mode": "bus", "service_id": "1", "from": "A", "to": "B"}]}

    updated, flags = rp.compute_reliability(journey)
    assert updated["reliability_score"] == 90
    assert updated["reliability_band"] == "High"
    # live missing reported
    assert "LIVE_MISSING" in flags


def test_compute_reliability_live_delay(monkeypatch):
    import app.domain.decision_support.reliability_pipeline as rp

    # historical missing
    monkeypatch.setattr(rp, "get_historical_stats", lambda **kw: None)

    # live shows a 15 minute delay
    monkeypatch.setattr(rp, "get_bus_live", lambda service_id: FakeLive(delay_minutes=15, cancelled=False))
    monkeypatch.setattr(rp, "get_rail_live", lambda service_id: None)
    monkeypatch.setattr(rp, "get_weather_stub", lambda: FakeWeather("normal"))

    journey = {"depart_time": datetime.utcnow(), "legs": [{"mode": "bus", "service_id": "1", "from": "A", "to": "B"}]}

    updated, flags = rp.compute_reliability(journey)
    # base 70 - 15 delay = 55
    assert updated["reliability_score"] == 55
    assert updated["reliability_band"] == "Medium"
    assert "HISTORICAL_MISSING" in flags
    assert any("Current live delay" in t for t in updated["reliability_explanation"])


def test_compute_reliability_live_cancelled(monkeypatch):
    import app.domain.decision_support.reliability_pipeline as rp

    monkeypatch.setattr(rp, "get_historical_stats", lambda **kw: None)
    monkeypatch.setattr(rp, "get_bus_live", lambda service_id: FakeLive(delay_minutes=0, cancelled=True))
    monkeypatch.setattr(rp, "get_rail_live", lambda service_id: None)
    monkeypatch.setattr(rp, "get_weather_stub", lambda: FakeWeather("normal"))

    journey = {"depart_time": datetime.utcnow(), "legs": [{"mode": "bus", "service_id": "1", "from": "A", "to": "B"}]}

    updated, flags = rp.compute_reliability(journey)
    # base 70 - 40 cancelled = 30
    assert updated["reliability_score"] == 30
    assert updated["reliability_band"] == "Low"
    assert any("disrupted or cancelled" in t for t in updated["reliability_explanation"]) 


def test_decision_support_annotate_delegates(monkeypatch):
    import app.domain.decision_support.decision_support as ds

    # Monkeypatch compute_reliability to ensure annotate calls it
    def fake_compute(j):
        j["reliability_score"] = 42
        return j, ["CUSTOM_FLAG"]

    monkeypatch.setattr("app.domain.decision_support.reliability_pipeline.compute_reliability", fake_compute)

    # Create a DecisionSupport enabled and run
    d = ds.DecisionSupport(enabled=True)
    journey = {"depart_time": datetime.utcnow(), "legs": []}
    annotated, flags = d.annotate([journey])
    assert annotated[0]["reliability_score"] == 42
    assert "CUSTOM_FLAG" in flags

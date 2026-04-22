import datetime

from app.domain.decision_support.reliability_pipeline import compute_reliability
from app.domain.decision_support.decision_support import DecisionSupport
from app.domain.decision_support.reliability_dto import LegLiveStatus


def make_leg(mode="bus", service_id="S1", from_id="A", to_id="B"):
    return {
        "mode": mode,
        "service_id": service_id,
        "from": from_id,
        "to": to_id,
        "depart": datetime.datetime.utcnow(),
    }


def test_compute_reliability_with_historical(monkeypatch):
    # historical stats present; no live data
    def fake_hist(mode, from_id, to_id, depart_time):
        return {"on_time_pct": 90, "avg_delay": 2.0, "missed_pct": 1.0}

    # patch both the reader module and the pipeline-local reference
    monkeypatch.setattr("app.domain.decision_support.historical_reader.get_historical_stats", fake_hist)
    monkeypatch.setattr(
        "app.domain.decision_support.reliability_pipeline.get_historical_stats",
        fake_hist,
    )
    monkeypatch.setattr("app.cache.live_reader.get_bus_live", lambda service_id: None)
    monkeypatch.setattr(
        "app.domain.decision_support.reliability_pipeline.get_bus_live",
        lambda service_id: None,
    )

    journey = {"legs": [make_leg()], "depart_time": datetime.datetime.utcnow()}
    j, flags = compute_reliability(journey)

    assert "reliability_score" in j
    assert j["reliability_score"] == 88
    assert j["reliability_band"] == "High"
    assert any("Historically on time" in t for t in j["reliability_explanation"]) or any("HIST_NONE" in t for t in j.get("reliability_explanation", []))
    assert "LIVE_MISSING" in flags


def test_compute_reliability_live_delay(monkeypatch):
    # no historical data, live shows delay
    monkeypatch.setattr("app.domain.decision_support.historical_reader.get_historical_stats", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.domain.decision_support.reliability_pipeline.get_historical_stats",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.cache.live_reader.get_bus_live",
        lambda service_id: LegLiveStatus(available=True, delay_minutes=15, cancelled=False, source="live"),
    )
    monkeypatch.setattr(
        "app.domain.decision_support.reliability_pipeline.get_bus_live",
        lambda service_id: LegLiveStatus(available=True, delay_minutes=15, cancelled=False, source="live"),
    )

    journey = {"legs": [make_leg()], "depart_time": datetime.datetime.utcnow()}
    j, flags = compute_reliability(journey)

    assert j["reliability_score"] == 55  # base 70 - 15 live delay
    assert j["reliability_band"] == "Medium"
    assert "HISTORICAL_MISSING" in flags


def test_compute_reliability_live_cancelled(monkeypatch):
    # no historical data, live shows cancelled
    monkeypatch.setattr("app.domain.decision_support.historical_reader.get_historical_stats", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.domain.decision_support.reliability_pipeline.get_historical_stats",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.cache.live_reader.get_bus_live",
        lambda service_id: LegLiveStatus(available=True, delay_minutes=0, cancelled=True, source="live"),
    )
    monkeypatch.setattr(
        "app.domain.decision_support.reliability_pipeline.get_bus_live",
        lambda service_id: LegLiveStatus(available=True, delay_minutes=0, cancelled=True, source="live"),
    )

    journey = {"legs": [make_leg()], "depart_time": datetime.datetime.utcnow()}
    j, flags = compute_reliability(journey)

    assert j["reliability_score"] == 30  # base 70 - 40 cancelled penalty
    assert j["reliability_band"] == "Low"
    assert any("disrupted" in t.lower() or "cancelled" in t.lower() for t in j["reliability_explanation"]) 
    assert "HISTORICAL_MISSING" in flags


def test_decision_support_annotate_aggregates_flags(monkeypatch):
    # ensure DecisionSupport.annotate calls compute_reliability and aggregates flags
    monkeypatch.setattr("app.domain.decision_support.historical_reader.get_historical_stats", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.domain.decision_support.reliability_pipeline.get_historical_stats",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.cache.live_reader.get_bus_live",
        lambda service_id: LegLiveStatus(available=True, delay_minutes=0, cancelled=True, source="live"),
    )
    monkeypatch.setattr(
        "app.domain.decision_support.reliability_pipeline.get_bus_live",
        lambda service_id: LegLiveStatus(available=True, delay_minutes=0, cancelled=True, source="live"),
    )

    ds = DecisionSupport(enabled=True)
    journeys = [{"legs": [make_leg()], "depart_time": datetime.datetime.utcnow()}]
    annotated, flags = ds.annotate(journeys)

    assert isinstance(annotated, list)
    assert len(annotated) == 1
    assert "reliability_score" in annotated[0]
    assert "HISTORICAL_MISSING" in flags
    assert any("disrupted" in f.lower() or "cancelled" in f.lower() for f in annotated[0]["reliability_explanation"]) or any("LIVE_CANCELLED" in f for f in annotated[0]["reliability_explanation"])
import os
import sys
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

# Ensure backend package is importable
here = os.path.dirname(__file__)
backend_root = os.path.abspath(os.path.join(here, ".."))
sys.path.insert(0, backend_root)

from app import api as api_module


class FakePlannerBase:
    def __init__(self, n=1):
        self.n = n

    def plan(self, origin_id, destination_id, time_type, time_iso, modes, max_options):
        out = []
        for i in range(self.n):
            out.append(
                {
                    "total_duration_min": 60 + i,
                    "depart_time": datetime.fromisoformat("2026-04-04T09:00:00"),
                    "arrive_time": datetime.fromisoformat("2026-04-04T10:00:00"),
                    "changes": 0,
                    "legs": [],
                }
            )
        return out


class FakeDecisionSupport:
    def __init__(self, score):
        self.score = score

    def annotate(self, journeys):
        annotated = []
        for j in journeys:
            band = "High" if self.score >= 80 else ("Medium" if self.score >= 50 else "Low")
            annotated.append(
                {
                    "total_duration_min": j.get("total_duration_min", 60),
                    "depart_time": j.get("depart_time", datetime.utcnow()),
                    "arrive_time": j.get("arrive_time", datetime.utcnow()),
                    "changes": j.get("changes", 0),
                    "reliability_score": self.score,
                    "reliability_band": band,
                    "reliability_explanations": [],
                    "has_connection_risk": False,
                    "legs": [],
                }
            )
        return annotated, []


@pytest.fixture(autouse=True)
def disable_real_planner_and_support(monkeypatch):
    # Prevent db access by replacing JourneyPlanner class used in handler
    api_module.JourneyPlanner = lambda: FakePlannerBase()
    # Default DecisionSupport will be overridden per-test via dependency_overrides
    api_module.calculate_reliability = lambda legs: type("R", (), {"score": 85, "band": "High", "explanations": []})()
    yield


@pytest.fixture
def client():
    app = api_module.app
    # ensure dependency_overrides cleaned between tests
    app.dependency_overrides = {}
    return TestClient(app)


def post_payload(client):
    payload = {
        "origin_id": "Lancaster",
        "destination_id": "Preston",
        "time_type": "depart_at",
        "time_iso": "2026-04-04T09:00:00",
        "modes": "mixed",
    }
    return client.post("/journeys", json=payload)


def test_adverse_weather_reduces_score(client, monkeypatch):
    # return baseline score 85
    app = api_module.app
    app.dependency_overrides[api_module.get_journey_planner] = lambda: FakePlannerBase(n=1)
    app.dependency_overrides[api_module.get_decision_support] = lambda: FakeDecisionSupport(85)

    calls = {"n": 0}

    def fake_fetch(lat, lon):
        calls["n"] += 1
        return api_module.WeatherInfo(available=True, is_adverse=True, description="bad", temperature_c=0.0, windspeed_kmh=60.0)

    monkeypatch.setattr(api_module, "fetch_weather", fake_fetch)

    r = post_payload(client)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["journeys"]) == 1
    j = data["journeys"][0]
    assert j["reliability_score"] == 75
    assert j["reliability_band"] == "Medium"
    assert "Adverse weather conditions may increase delays" in j["reliability_explanations"]
    assert calls["n"] == 1


def test_non_adverse_weather_no_change(client, monkeypatch):
    app = api_module.app
    app.dependency_overrides[api_module.get_journey_planner] = lambda: FakePlannerBase(n=1)
    app.dependency_overrides[api_module.get_decision_support] = lambda: FakeDecisionSupport(85)

    def fake_fetch(lat, lon):
        return api_module.WeatherInfo(available=True, is_adverse=False, description="ok", temperature_c=10.0, windspeed_kmh=5.0)

    monkeypatch.setattr(api_module, "fetch_weather", fake_fetch)

    r = post_payload(client)
    assert r.status_code == 200, r.text
    j = r.json()["journeys"][0]
    assert j["reliability_score"] == 85
    assert j["reliability_band"] == "High"
    assert not any("Adverse weather conditions may increase delays" in e for e in j["reliability_explanations"])


def test_adverse_weather_clamps_to_zero(client, monkeypatch):
    app = api_module.app
    app.dependency_overrides[api_module.get_journey_planner] = lambda: FakePlannerBase(n=1)
    # Simulate DecisionSupport failure so the API falls back to calculate_reliability
    def failing_annotate(journeys):
        raise api_module.DecisionSupportError("simulated failure")

    app.dependency_overrides[api_module.get_decision_support] = lambda: __import__('types').SimpleNamespace(annotate=failing_annotate)

    # Ensure calculate_reliability returns a small baseline (5) so penalty clamps
    monkeypatch.setattr(api_module, "calculate_reliability", lambda legs: type("R", (), {"score": 5, "band": "Low", "explanations": []})())

    def fake_fetch(lat, lon):
        return api_module.WeatherInfo(available=True, is_adverse=True, description="bad", temperature_c=0.0, windspeed_kmh=60.0)

    monkeypatch.setattr(api_module, "fetch_weather", fake_fetch)

    r = post_payload(client)
    assert r.status_code == 200, r.text
    j = r.json()["journeys"][0]
    assert j["reliability_score"] == 0
    assert j["reliability_band"] == "Low"


def test_weather_fetch_failure_does_not_affect_score(client, monkeypatch):
    app = api_module.app
    app.dependency_overrides[api_module.get_journey_planner] = lambda: FakePlannerBase(n=1)
    app.dependency_overrides[api_module.get_decision_support] = lambda: FakeDecisionSupport(85)

    def fake_fetch(lat, lon):
        raise Exception("upstream error")

    monkeypatch.setattr(api_module, "fetch_weather", fake_fetch)

    r = post_payload(client)
    assert r.status_code == 200, r.text
    j = r.json()["journeys"][0]
    assert j["reliability_score"] == 85
    assert j["reliability_band"] == "High"


def test_weather_fetch_called_once_not_per_journey(client, monkeypatch):
    app = api_module.app
    app.dependency_overrides[api_module.get_journey_planner] = lambda: FakePlannerBase(n=2)
    app.dependency_overrides[api_module.get_decision_support] = lambda: FakeDecisionSupport(85)

    calls = {"n": 0}

    def fake_fetch(lat, lon):
        calls["n"] += 1
        return api_module.WeatherInfo(available=True, is_adverse=True, description="bad", temperature_c=0.0, windspeed_kmh=60.0)

    monkeypatch.setattr(api_module, "fetch_weather", fake_fetch)

    r = post_payload(client)
    assert r.status_code == 200, r.text
    assert calls["n"] == 1

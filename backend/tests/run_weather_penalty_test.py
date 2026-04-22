from fastapi.testclient import TestClient
from datetime import datetime
import os
import sys

# Ensure backend package root is on sys.path so `app` imports resolve
here = os.path.dirname(__file__)
backend_root = os.path.abspath(os.path.join(here, ".."))
sys.path.insert(0, backend_root)

from app import api as api_module


class FakePlanner:
    def plan(self, origin_id, destination_id, time_type, time_iso, modes, max_options):
        return [
            {
                "total_duration_min": 60,
                "depart_time": datetime.fromisoformat("2026-04-04T09:00:00"),
                "arrive_time": datetime.fromisoformat("2026-04-04T10:00:00"),
                "changes": 0,
                "legs": [],
            }
        ]


class FakeDecisionSupport:
    def annotate(self, journeys):
        annotated = []
        for j in journeys:
            annotated.append(
                {
                    "total_duration_min": j.get("total_duration_min", 60),
                    "depart_time": j.get("depart_time", datetime.utcnow()),
                    "arrive_time": j.get("arrive_time", datetime.utcnow()),
                    "changes": j.get("changes", 0),
                    "reliability_score": 85,
                    "reliability_band": "High",
                    "reliability_explanations": [],
                    "has_connection_risk": False,
                    "legs": [],
                }
            )
        return annotated, []


def run_tests():
    client = TestClient(api_module.app)

    # Inject fakes
    api_module.app.dependency_overrides[api_module.get_journey_planner] = lambda: FakePlanner()
    api_module.app.dependency_overrides[api_module.get_decision_support] = lambda: FakeDecisionSupport()
    # The api module instantiates JourneyPlanner() directly in the handler,
    # so override the class name in the module to our fake to avoid DB access.
    api_module.JourneyPlanner = FakePlanner
    # Ensure calculate_reliability returns predictable value if called
    api_module.calculate_reliability = lambda legs: type(
        "R",
        (),
        {"score": 85, "band": "High", "explanations": ["No legs — default reliability"]},
    )()

    # Test 1: adverse weather -> penalty applied
    calls = {"n": 0}

    def fake_fetch_adverse(lat, lon):
        calls["n"] += 1
        return api_module.WeatherInfo(available=True, is_adverse=True, description="bad", temperature_c=0.0, windspeed_kmh=50.0)

    api_module.fetch_weather = fake_fetch_adverse

    payload = {
        "origin_id": "Lancaster",
        "destination_id": "Preston",
        "time_type": "depart_at",
        "time_iso": "2026-04-04T09:00:00",
        "modes": "mixed",
    }

    r = client.post("/journeys", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["journeys"]) == 1
    j = data["journeys"][0]
    print("DEBUG adverse response:", data)
    print("DEBUG fetch calls:", calls["n"])
    assert j["reliability_score"] == 75, f"expected 75 got {j['reliability_score']}"
    assert j["reliability_band"] == "Medium"
    assert "Adverse weather conditions may increase delays" in j["reliability_explanations"]
    assert calls["n"] == 1

    # Test 2: non-adverse weather -> no change
    calls["n"] = 0

    def fake_fetch_ok(lat, lon):
        calls["n"] += 1
        return api_module.WeatherInfo(available=True, is_adverse=False, description="ok", temperature_c=10.0, windspeed_kmh=5.0)

    api_module.fetch_weather = fake_fetch_ok
    r2 = client.post("/journeys", json=payload)
    assert r2.status_code == 200, r2.text
    data2 = r2.json()
    j2 = data2["journeys"][0]
    assert j2["reliability_score"] == 85, f"expected 85 got {j2['reliability_score']}"
    assert j2["reliability_band"] == "High"
    assert not any("Adverse weather conditions may increase delays" in e for e in j2["reliability_explanations"])
    assert calls["n"] == 1

    print("All weather-penalty tests passed")


if __name__ == "__main__":
    run_tests()

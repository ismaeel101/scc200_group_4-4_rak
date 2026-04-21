import datetime
import os
from fastapi.testclient import TestClient

from app.api import app
from app.domain.planner.planner import JourneyPlanner


def synthetic_plan(self, **kwargs):
    depart = datetime.datetime.utcnow()
    arrive = depart + datetime.timedelta(minutes=30)
    legs = [
        {
            "mode": "bus",
            "from": "STOP_A",
            "to": "STOP_B",
            "depart": depart.isoformat(),
            "arrive": arrive.isoformat(),
            "service_id": "SYN123",
        }
    ]
    return [
        {
            "total_duration_min": 30,
            "depart_time": depart.isoformat(),
            "arrive_time": arrive.isoformat(),
            "changes": 0,
            "legs": legs,
        }
    ]


def test_journeys_endpoint_returns_reliability(monkeypatch):
    # ensure decision support enabled for the test
    os.environ["ENABLE_DECISION_SUPPORT"] = "true"

    # monkeypatch the planner.plan used by the API
    monkeypatch.setattr(JourneyPlanner, "plan", synthetic_plan)

    client = TestClient(app)

    payload = {
        "origin_id": "STOP_A",
        "destination_id": "STOP_B",
        "time_type": "depart_at",
        "time_iso": datetime.datetime.utcnow().isoformat(),
        "modes": "bus",
        "max_options": 3,
    }

    r = client.post("/journeys", json=payload)

    assert r.status_code == 200
    body = r.json()
    assert "journeys" in body
    assert isinstance(body["journeys"], list)
    assert len(body["journeys"]) >= 1

    j = body["journeys"][0]
    assert "reliability_score" in j
    assert "reliability_band" in j
    assert "reliability_explanation" in j
    assert isinstance(body.get("data_quality_flags", []), list)
    # with our default fallbacks, historical/live data will be missing
    assert any(f in ("HISTORICAL_MISSING", "LIVE_MISSING") for f in body.get("data_quality_flags", []))

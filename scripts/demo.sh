#!/usr/bin/env bash
set -euo pipefail

echo "Demo script: tests -> runner -> in-process /journeys demo"
cd /workspace

echo "\n1) Running pytest backend/tests"
python3 -m pytest backend/tests -q

echo "\n2) Running lightweight reliability runner"
python3 backend/run_reliability_tests_runner.py

echo "\n3) Running in-process /journeys demo (monkeypatched planner + weather)"
python3 - <<'PY'
import sys
from datetime import datetime
sys.path.insert(0, '/workspace/backend')
from app import api as api_module
from fastapi.testclient import TestClient

class FakePlanner:
    def plan(self, *a, **k):
        return [{
            'total_duration_min': 45,
            'depart_time': '2026-04-05T09:00:00',
            'arrive_time': '2026-04-05T09:45:00',
            'changes': 0,
            'legs': []
        }]

class RealisticDecisionSupport:
    def annotate(self, journeys):
        out = []
        for j in journeys:
            score = 90
            try:
                w = api_module.fetch_weather(None, None)
                if getattr(w, 'is_adverse', False):
                    score -= 10
            except Exception:
                pass
            jj = dict(j)
            jj['reliability_score'] = score
            jj['reliability_band'] = 'High' if score >= 80 else 'Medium' if score >= 50 else 'Low'
            jj['reliability_explanations'] = ['Simulated decision support']
            out.append(jj)
        return out, []

api_module.JourneyPlanner = FakePlanner
api_module.app.dependency_overrides[api_module.get_decision_support] = lambda: RealisticDecisionSupport()
from app.domain.weather import WeatherInfo

client = TestClient(api_module.app)

print('--- Non-adverse demo ---')
api_module.fetch_weather = lambda lat, lon: WeatherInfo(available=True, is_adverse=False, description='Clear', temperature_c=10.0, windspeed_kmh=5.0)
resp1 = client.post('/journeys', json={
    'origin_id': 'Lancaster', 'destination_id': 'Preston', 'time_type': 'depart_at', 'time_iso': '2026-04-05T09:00:00', 'modes': 'mixed'
})
print('Status:', resp1.status_code)
import json
print(json.dumps(resp1.json(), indent=2))

print('\n--- Adverse demo ---')
api_module.fetch_weather = lambda lat, lon: WeatherInfo(available=True, is_adverse=True, description='Storm', temperature_c=8.0, windspeed_kmh=80.0)
resp2 = client.post('/journeys', json={
    'origin_id': 'Lancaster', 'destination_id': 'Preston', 'time_type': 'depart_at', 'time_iso': '2026-04-05T09:00:00', 'modes': 'mixed'
})
print('Status:', resp2.status_code)
print(json.dumps(resp2.json(), indent=2))

try:
    s1 = resp1.json()['journeys'][0]['reliability_score']
    s2 = resp2.json()['journeys'][0]['reliability_score']
    print('\nScore diff (non-adverse - adverse):', s1 - s2)
except Exception as e:
    print('Error extracting scores:', e)
PY

echo "\nDemo finished. To run the live API, start uvicorn:"
echo "uvicorn backend.app.api:app --host 127.0.0.1 --port 8000"

echo "To build frontend: cd frontend && npm install && npm run build"

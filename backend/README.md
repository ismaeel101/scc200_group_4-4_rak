# OptiRoute — Development notes

This repository contains a small FastAPI backend and a Vite React frontend. The backend includes a journey reliability calculator and lightweight test utilities to run checks in the dev container.

**Quick highlights**
- Reliability: `backend/app/domain/reliability.py` computes per-leg and journey scores (0–100) and assigns bands (High/Medium/Low).
- API DTOs: the API exposes `reliability_score`, `reliability_band`, `reliability_explanations` and per-leg `live_status` fields.
- Tests: a lightweight runner `backend/run_reliability_tests_runner.py` is available when `pytest` is not present.

**Minimal setup**
1. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
python3 -m pip install --upgrade pip
pip install -r requirements.txt
```

**Common commands**
- Run loaders (from repo root):

```bash
cd backend
python3 load_stops.py
python3 load_bus.py
python3 load_bus_timetable.py
python3 load_rail.py
```

- Start the API locally:

```bash
uvicorn backend.app.api:app --reload --host 0.0.0.0 --port 8000
```

- Run tests:

With `pytest`:

```bash
python3 -m pytest backend/tests -q
```

Without `pytest` (restricted envs):

```bash
python3 backend/run_reliability_tests_runner.py
```

**Notes on accuracy & troubleshooting**
- Loader scripts expect small sample files under `backend/data/` — verify those files if a loader fails.
- If the API reports missing DB files, ensure any required SQLite files are present in `backend/` or use test doubles where appropriate.
- The repo's test suite uses `app.dependency_overrides` and fakes, so many API tests run without a real DB.

**Weather integration (summary)**
- A planned improvement is a `fetch_weather(lat, lon)` helper that calls Open-Meteo and returns a small `WeatherInfo`. If `is_adverse` is true a -10 penalty should be applied to journey scores and an explanatory message appended to `reliability_explanations`. Keep weather sourcing separate from scoring logic.

Updated ->
frontend/src/pages/ResultsPage.tsx
frontend/src/pages/SearchPage.tsx
frontend/src/components/RouteCard.tsx
Added ->
frontend/src/components/WeatherWidget.tsx

## Testing & Merge Notes

- A full local verification run was performed on 2026-04-05 and recorded in `MERGE_TESTS` at the repo root. Key outcomes:
	- Backend unit tests and the reliability runner passed locally after restoring missing `backend/app/data` files for test collection.
	- The `/api/weather` endpoint returns the expected fields: `available`, `is_adverse`, `description`, `temperature_c`, `windspeed_kmh`.
	- The `frontend` builds successfully with Vite (`npm run build`) and the `WeatherWidget` and `RouteCard` components consume the backend fields as expected.

- Note about `/journeys` integration: the `plan_journey` handler currently instantiates `JourneyPlanner()` directly inside the route handler. This causes real planner code to open the DB even when `app.dependency_overrides` is used in tests, which led to a runtime "no such table: stops" error in environments without the expected SQLite stops table. Two safe options:
	1. Provide the expected `stops` SQLite data in `backend/` for full integration testing.
	2. Refactor the handler to use the injected `journey_planner` dependency (recommended) so tests and CI can stub the planner cleanly.

- For local verification, a runtime monkeypatch was used to replace `app.api.JourneyPlanner` and `get_decision_support` so the `/journeys` POST could be exercised without the DB. This is a temporary testing workaround and should not be relied on for CI or production readiness.

See `MERGE_TESTS` for a step-by-step log and final recommendation.

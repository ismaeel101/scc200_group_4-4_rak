# OptiRoute — Development notes (concise)

This repository contains a small FastAPI backend and a Vite React frontend. The backend includes a journey reliability calculator and lightweight test utilities so you can run common checks in a dev container.

**Quick highlights**
- Reliability: `backend/app/domain/reliability.py` computes per-leg and journey scores (0–100) and assigns bands (High/Medium/Low).
- API DTOs: the API exposes `reliability_score`, `reliability_band`, `reliability_explanations` and per-leg `live_status` fields.
- Tests: a lightweight runner `backend/run_reliability_tests_runner.py` is available when `pytest` is not present.

**Minimal setup (recommended)**
1. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

**Common commands**
- Run loaders (from repo root):

```bash
cd backend
python load_stops.py
python load_bus.py
python load_bus_timetable.py
python load_rail.py
```

- Start the API locally:

```bash
uvicorn backend.app.api:app --reload --host 0.0.0.0 --port 8000
```

- Run tests:

With `pytest`:

```bash
python -m pytest backend/tests -q
```

Without `pytest` (restricted envs):

```bash
python backend/run_reliability_tests_runner.py
```

**Notes on accuracy & troubleshooting**
- Loader scripts expect small sample files under `backend/data/` — verify those files if a loader fails.
- If the API reports missing DB files, ensure any required SQLite files are present in `backend/` or use test doubles where appropriate.
- The repo's test suite uses `app.dependency_overrides` and fakes, so many API tests run without a real DB.

**Weather integration (summary)**
- A planned improvement is a `fetch_weather(lat, lon)` helper that calls Open-Meteo and returns a small `WeatherInfo`. If `is_adverse` is true a -10 penalty should be applied to journey scores and an explanatory message appended to `reliability_explanations`. Keep weather sourcing separate from scoring logic.

**Next steps**
- Integrate `calculate_reliability()` into the DecisionSupport pipeline if desired.
- Consider a short CONTRIBUTING.md or design note for the weather code and API DTO changes (the README keeps those details minimal).

---
Small, focused README — let me know if you want the removed technical lists restored or moved into a separate developer notes file.
---
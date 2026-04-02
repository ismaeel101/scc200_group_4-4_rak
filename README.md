# OptiRoute — Current Development Notes

This README summarises the recent backend changes, the current API contract (DTOs), reliability scoring behaviour, test data, and quick commands to run loaders and tests in the dev container.

## Quick summary of recent changes
- Added a journey reliability calculator: `backend/app/domain/reliability.py` which returns a `ReliabilityResult` (score 0–100, band: High/Medium/Low, explanations, and an internal `has_tight_connection` flag).
- API DTOs and mapping functions in `backend/app/api.py` were clarified and now document the exact field names expected by the frontend and other services (`reliability_score`, `reliability_band`, `reliability_explanations`, and `legs.live_status`).
- Lightweight test runner `backend/run_reliability_tests_runner.py` added so tests can be executed without `pytest` in restricted environments.
- Small sample test data present under `backend/data/` to allow local execution of loader scripts.

## API / DTOs (contract highlights)
- Journey-level: `reliability_score` (int 0–100), `reliability_band` ("High"/"Medium"/"Low"), `reliability_explanations` (string list).
- Leg-level `live_status` object fields: `available` (bool), `delay_minutes` (int), `disrupted_flag` (bool), `source` (string).
- Leg-level: `leg_risk_band` ("High"/"Medium"/"Low") and `risk_explanation` (string list) are included when provided by DecisionSupport.
- Note: the internal `ReliabilityResult` includes `has_tight_connection` (bool) for domain use. The public `Journey` DTO now exposes `has_connection_risk` (mapped from `has_tight_connection`) and the API injects a tight-connection summary into `reliability_explanations` for clients that consume textual explanations.

## Reliability scoring behaviour (summary)
- Per-leg baseline is `historical_on_time_pct` (default 75).
- Penalties applied per-leg:
	- Tight connection (<5 min): −20
	- Short connection (<10 min): −10
	- Live delay >10 min: −30
	- Cancellation: −50
- Each leg is clamped to 0–100; journey score is the average of leg scores and mapped to a band: High (>=80), Medium (50–79), Low (<50).
- Explanations generated include historical notes, current delay statements, cancellation notices and a summary if very tight connections were found.

## Behavioural and infrastructure notes
- FastAPI application: `backend/app/api.py` exposes endpoints and Pydantic DTOs. Use `uvicorn backend.app.api:app` to run locally.
- CORS is enabled for typical local Vite origins (`http://127.0.0.1:5173`, etc.).
- Rate limiting: lightweight IP-based limiter configured for ~30 requests per minute (per-IP) — endpoints declare `Depends(rate_limiter)` where used.
- Request size limit: middleware enforces a 50KB max request payload.
- The scheduler start/stop calls were removed from startup events (scheduler functions are not available in this branch).

## Test data (minimal)
- `backend/data/naptan.xml` — small sample stop file used by `load_stops.py`.
- `backend/data/timetables/test_service.xml` — small TransXChange example used by timetable loaders.
- `backend/data/rail_schedule.json` (and gzipped variant) — small rail schedule example.

Additional files added/modified in this branch:
- `backend/tests/test_reliability.py` — updated to check `has_connection_risk` mapping.
- `backend/run_api_mapping_checks.py` — small local script to validate the API mapping injects tight-connection explanations.

These are intentionally small so loader scripts can be exercised in the dev container without large datasets.

## How to run (development container)

1. Create / activate a virtualenv (recommended if system installs are restricted):

```bash
python3 -m venv ~/optiroute-venv
source ~/optiroute-venv/bin/activate
```

2. Install dependencies (if you can):

```bash
python -m ensurepip --upgrade
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

3. Run loaders from the repo root (`/workspace/backend`):

```bash
cd backend
python load_stops.py
python load_bus.py
python load_bus_timetable.py
python load_rail.py
```

4. Run the FastAPI app locally via `uvicorn` (bind to all interfaces for container use):

```bash
uvicorn backend.app.api:app --reload --host 0.0.0.0 --port 8000
```

5. Run reliability tests:

- With `pytest`:

```bash
python -m pytest backend/tests/test_reliability.py -q
```

- Without `pytest` (restricted environments):

```bash
python backend/run_reliability_tests_runner.py
```

## Known constraints & troubleshooting
- Some dev container environments enforce PEP 668 / externally-managed environments; if `pip install` is blocked, use a virtualenv as shown above.
- `load_stops.py` and certain loader scripts expect test files in `backend/data/` — check those paths before running.
- If the API reports database files missing, verify the SQLite files exist at the resolved locations printed by the API (the code attempts several legacy names like `optiroute.db`, `stops.db`, `bus.db`).

## Next suggested steps
- Integrate `calculate_reliability()` into the DecisionSupport pipeline so live and historical data are combined into the returned journey DTOs.
- Consider exposing the `has_tight_connection` flag in the API if the frontend needs to present a specific UI treatment for tight transfers.
- Add integration tests that exercise the API endpoints with injected fakes via `app.dependency_overrides` to validate full request/response behaviour.

---

If you'd like, I can also run the reliability tests locally (using the lightweight runner) and/or open a PR with this README update.
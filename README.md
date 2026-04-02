# OptiRoute — Current Development Notes

This README summarises recent local work, test data added, constraints observed in the dev container, and quick commands to run the data loaders and reliability tests.

## Summary of changes
- Implemented a journey reliability layer: `backend/app/domain/reliability.py` (score, band, explanations).
- Integrated defaults into the API: `backend/app/api.py` now ensures each journey includes `reliability_score`, `reliability_band`, and `reliability_explanations` when DecisionSupport data is missing.
- Added tests: `backend/tests/test_reliability.py` and a lightweight runner `backend/run_reliability_tests_runner.py` for environments without `pytest`.
- Created minimal test data under `backend/data/` (NaPTAN and a TransXChange sample) so loader scripts can be executed locally.

## Test data created (minimal)
- `backend/data/naptan.xml` — two sample stops in NW bounding box
- `backend/data/timetables/test_service.xml` — one small TransXChange service
- `backend/data/rail_schedule.json.gz` — small gzipped ndjson rail schedule (generated from `backend/data/rail_schedule.json`)

These allow the loader scripts to run in the container for basic smoke tests.

## Files added/modified
- `backend/app/domain/reliability.py`
- `backend/app/api.py` (injection of reliability defaults)
- `backend/tests/test_reliability.py`
- `backend/run_reliability_tests_runner.py`
- Test data under `backend/data/`

## How to run (development container)

1. Create / activate virtualenv (if not already created):

```bash
python3 -m venv ~/optiroute-venv
source ~/optiroute-venv/bin/activate
```

2. (Optional) bootstrap pip and install requirements:

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

4. Run reliability tests:

- If `pytest` is available:

```bash
python -m pytest backend/tests/test_reliability.py -q
```

- If `pytest` is not available, use the lightweight runner:

```bash
python backend/run_reliability_tests_runner.py
```

## Known constraints & notes
- The dev container enforces an externally-managed Python environment in some setups (PEP 668). If `pip install` fails system-wide, create and use a virtualenv as shown above. A minimal test-runner is provided to avoid requiring `pytest` where pip cannot be used.
- `load_stops.py` defaults to `backend/data/naptan.xml` — ensure the test file exists at that path before running.
- The reliability implementation uses conservative defaults (historical_on_time_pct=75, no delays, no cancellations) until full historical/live data integration is available.

## Next suggested steps
- Wire `calculate_reliability()` into the DecisionSupport implementation (app/domain/decision_support) to use real live/historical sources.
- Add more extensive unit and integration tests covering DecisionSupport and API endpoints.
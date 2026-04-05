MERGE VERIFICATION NOTES — feature/Molly-reliability-weather
Date: 2026-04-05

Summary
-------
This file summarizes a local merge verification run for branch `feature/Molly-reliability-weather`.
A detailed step-by-step log is available at `MERGE_TESTS` in the repo root.

Key outcomes
------------
- Unit tests: All backend unit tests executed locally (after restoring `backend/app/data` files) — passed.
- Reliability runner: `backend/run_reliability_tests_runner.py` completed successfully.
- `/api/weather`: returns expected JSON fields: `available`, `is_adverse`, `description`, `temperature_c`, `windspeed_kmh`.
- Frontend: `npm run build` produced `dist/` assets; `WeatherWidget` and `RouteCard` consume the backend fields as expected.
- `/journeys`: The endpoint can be exercised locally by monkeypatching `app.api.JourneyPlanner` at runtime to avoid DB access. In the real handler the code instantiates `JourneyPlanner()` inside the route handler which opens the DB even when `app.dependency_overrides` is used. In environments without the expected `stops` table this produced a "no such table: stops" error.

Recommendations
---------------
1) Preferred (safe for CI): Refactor `backend/app/api.py` so the `plan_journey` handler uses the injected `journey_planner` dependency (remove the internal `JourneyPlanner()` instantiation). This allows tests and CI to stub/override the planner without touching DB files.

2) Alternative (data-first): Provide the expected `stops` SQLite data in `backend/` (or mount it in CI) so the real planner can run during integration tests.

3) Short-term testing: Continue using runtime monkeypatching for quick local checks (as was done during verification). This is a temporary convenience only.

Notes for reviewers
------------------
- See `MERGE_TESTS` for the detailed step-by-step log and final verdict.
- I updated `README.md` to include a short "Testing & Merge Notes" section pointing to `MERGE_TESTS` and describing the monkeypatch workaround.

Next actions I can take
-----------------------
- Apply the recommended refactor to `backend/app/api.py` and run the full test suite + integration checks.
- Inspect `optiroute.db` and prepare a `stops` table export suitable for CI and local integration.
- Continue local runtime monkeypatch testing to validate further scenarios.

# OptiRoute — Developer Notes

This file contains the detailed technical material on DTO mappings, reliability scoring rules, weather codes and test details for developer reference.

## API DTOs & Mapping
- Journey-level fields (public API):
  - `reliability_score`: int (0–100)
  - `reliability_band`: "High" | "Medium" | "Low"
  - `reliability_explanations`: list[str]
  - `has_connection_risk`: bool (mapped from internal `has_tight_connection`)
- Leg-level fields:
  - `live_status`: { `available`: bool, `delay_minutes`: int, `disrupted_flag`: bool, `source`: str }
  - Optional: `leg_risk_band`: "High"|"Medium"|"Low" and `risk_explanation`: list[str]

Notes: internal domain model `ReliabilityResult.has_tight_connection` -> public `Journey.has_connection_risk`. The API also injects a short textual summary about tight transfers into `reliability_explanations` for UIs that prefer text.

## Reliability scoring (detailed)
- Per-leg baseline: `historical_on_time_pct` (default 75 if missing).
- Per-leg penalties (apply then clamp each leg 0–100):
  - Tight connection (<5 minutes): −20
  - Short connection (<10 minutes): −10
  - Live delay >10 minutes: −30
  - Cancellation: −50
- Journey score: average of per-leg scores (after clamping). After per-journey adjustments (e.g., weather), clamp to 0–100 and recompute band.
- Bands:
  - High: score >= 80
  - Medium: 50 <= score <= 79
  - Low: score < 50

Explanations: include history notes, delay/cancellation notices, and a tight-connection summary when applicable.

## Weather integration (implementation notes)
- Helper signature: `fetch_weather(lat: float, lon: float) -> WeatherInfo` where `WeatherInfo` includes:
  - `available`: bool
  - `is_adverse`: bool
  - `description`: str
  - `temperature_c`: float
  - `windspeed_kmh`: float
- Upstream API: Open-Meteo current weather
  - URL template: `https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true`
  - Default coords: `lat=54.0466`, `lon=-2.8007` (Lancaster) when none provided.
- Adverse criteria:
  - `windspeed_kmh > 50` OR
  - `weather_code` in [61,62,63,64,65,71,72,73,74,75,80,81,82,85,86,95,96,99]
- On fetch failure: return safe fallback
  - `WeatherInfo(available=False, is_adverse=False, description="Weather data unavailable", temperature_c=0, windspeed_kmh=0)`
- Applying penalty: if `is_adverse` then subtract 10 from journey score (clamp to 0) and append "Adverse weather conditions may increase delays" to `reliability_explanations` (avoid duplicates); recompute `reliability_band`.

## Tests & expectations
- Test files in `backend/tests/` of interest:
  - `test_reliability.py` — checks scoring and `has_connection_risk` mapping
  - `test_weather_penalty.py` — verifies weather penalty behaviour for `/journeys` (adverse vs non-adverse, clamping, resilience on fetch failure, single fetch invocation when multiple journeys returned)
- Lightweight runner: `backend/run_reliability_tests_runner.py` runs core tests without requiring `pytest` (useful in restricted containers).

Typical test commands:
```bash
# with pytest
python -m pytest backend/tests -q

# without pytest
python backend/run_reliability_tests_runner.py
```

Notes: tests use `app.dependency_overrides` and fakes (planner/decision support) so they usually run without a real SQLite DB.

## Run & troubleshooting notes
- Start API:
```bash
uvicorn backend.app.api:app --reload --host 0.0.0.0 --port 8000
```
- If `uvicorn` or other tools fail, ensure the active virtualenv has dependencies from `requirements.txt` installed.
- Loader scripts expect sample files under `backend/data/` — verify presence if a loader errors.
- If the API logs missing database files, provide the expected SQLite files in `backend/` or run tests that override DB dependencies.

## PR Notes (for pull request)
Features implemented:
- **FR-H1**: Weather module + `GET /api/weather` endpoint
- **FR-H2**: Graceful fallback when weather unavailable
- **FR-D1**: Reliability scoring with weather penalty (-10 when adverse)

Files changed/added:
- `backend/app/domain/weather.py` (new/updated)
- `backend/app/api.py` (weather endpoint, weather penalty application)
- `backend/app/domain/reliability.py` (scoring logic)
- `backend/tests/test_weather_penalty.py` (tests covering weather penalty)

Verification:
- Copilot used: `weather.py`, `api.py`, `test_weather_penalty.py`
- Verified by: 5 pytest tests passing (see `backend/tests`) and manual `curl` checks against `/api/weather` and `/journeys`.

Suggested PR description (short):
"Add weather integration and scoring: `fetch_weather` + `/api/weather` endpoint, graceful fallback, and a -10 adverse-weather penalty applied to journey reliability. Includes tests (`test_weather_penalty.py`) validating penalty, resilience on fetch failure, and clamping behaviour."
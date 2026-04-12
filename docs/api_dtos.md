# API DTO Reference

This document is the canonical reference for the JSON shapes exposed and consumed by the OptiRoute FastAPI backend. Field names are taken from the Pydantic models in `backend/app/api.py` and the domain dataclasses.

Each DTO section lists field name, JSON type, and a short description. Example payloads follow where useful.

## JourneyRequest
Description: request body for `/journeys` (planning) endpoint.

Fields:
- `origin_id` (string): AtcoCode (bus) or CRS (rail) wrapped in PlaceId.
- `destination_id` (string): AtcoCode (bus) or CRS (rail) wrapped in PlaceId.
- `time_type` (string; enum: `depart_at` | `arrive_by`): whether `time_iso` is a departure or arrival constraint.
- `time_iso` (ISO datetime): time in ISO 8601 format (string allowed; `Z` suffix is normalised).
- `modes` (string; enum: `bus` | `rail` | `mixed`): transport mode preference.
- `max_options` (int): max number of journey options (default 5, 1–10).

Example:
```json
{
  "origin_id": "place:ATCO:490004",
  "destination_id": "place:CRS:MAN",
  "time_type": "depart_at",
  "time_iso": "2026-04-03T09:00:00+00:00",
  "modes": "bus",
  "max_options": 5
}
```

## LiveStatus
Description: per-leg live feed annotation.

Fields:
- `available` (bool): whether live data is present.
- `delay_minutes` (int): current delay in minutes (may be 0).
- `disrupted_flag` (bool): true for cancelled/disrupted services.
- `source` (string): textual source identifier for the live feed (e.g. 'rtpi').

Example:
```json
{
  "available": true,
  "delay_minutes": 5,
  "disrupted_flag": false,
  "source": "mock-feed"
}
```

## Leg
Description: single leg of a journey. Serialized JSON uses `from` and `to` keys.

Fields:
- `mode` (string; enum: `walk` | `bus` | `rail`)
- `from` (string): origin stop id (serialized from internal `from_loc`).
- `to` (string): destination stop id (serialized from internal `to_loc`).
- `depart` (ISO datetime)
- `arrive` (ISO datetime)
- `operator` (string | null)
- `service_id` (string | null)
- `live_status` (object | null): `LiveStatus` as above
- `leg_risk_band` (string | null; enum: `High` | `Medium` | `Low`)
- `risk_explanation` (array[string] | null)

Example:
```json
{
  "mode": "bus",
  "from": "490004",
  "to": "490005",
  "depart": "2026-04-03T09:10:00+00:00",
  "arrive": "2026-04-03T09:25:00+00:00",
  "operator": "Stagecoach",
  "service_id": "S1",
  "live_status": { "available": true, "delay_minutes": 0, "disrupted_flag": false, "source": "rtpi" },
  "leg_risk_band": "Medium",
  "risk_explanation": ["Short transfer"]
}
```

## Journey
Description: journey-level DTO returned in `/journeys` responses.

Fields:
- `total_duration_min` (int): total journey duration in minutes.
- `depart_time` (ISO datetime)
- `arrive_time` (ISO datetime)
- `changes` (int): number of interchanges
- `reliability_score` (int 0–100)
- `reliability_band` (string; `High` | `Medium` | `Low`)
- `reliability_explanations` (array[string]): human-readable reasons and notes.
- `has_connection_risk` (bool): public mapping from internal `has_tight_connection`.
- `legs` (array[Leg])

Example:
```json
{
  "total_duration_min": 120,
  "depart_time": "2026-04-03T09:00:00+00:00",
  "arrive_time": "2026-04-03T11:00:00+00:00",
  "changes": 1,
  "reliability_score": 70,
  "reliability_band": "Medium",
  "reliability_explanations": ["Route historically on time 75% of days"],
  "has_connection_risk": false,
  "legs": [ /* Leg objects */ ]
}
```

## JourneyResponse
Description: top-level response model for `/journeys`.

Fields:
- `journeys` (array[Journey])
- `data_quality_flags` (array[string]): diagnostic flags; allowed values include `TIMETABLE_ONLY`, `LIVE_MISSING`, `WEATHER_MISSING`, `HISTORICAL_MISSING`.

Example:
```json
{
  "journeys": [ /* Journey objects */ ],
  "data_quality_flags": []
}
```

## StopResponse
Description: stop/station object returned by search endpoints.

Fields:
- `id` (string)
- `name` (string)
- `type` (string; `bus` | `rail`)
- `lat` (float)
- `lon` (float)

Example:
```json
{ "id": "490004", "name": "Town Centre", "type": "bus", "lat": 54.05, "lon": -2.80 }
```

## StatusResponse
Description: system freshness status returned by `/status`.

Fields:
- `timetable_updated_at` (ISO datetime)
- `live_updated_at` (ISO datetime)
- `weather_updated_at` (ISO datetime)

## WeatherInfo
Description: domain dataclass returned by `fetch_weather` and used by `/api/weather`.

Fields:
- `available` (bool): whether weather data was successfully retrieved.
- `is_adverse` (bool): whether conditions meet the project's adverse criteria.
- `description` (string): short textual description (mapped from `weather_code`).
- `temperature_c` (float)
- `windspeed_kmh` (float)

Notes: The API endpoint returns this dataclass as a plain JSON object and falls back to a safe payload on any error.

## ReliabilityResult (domain)
Description: internal domain result returned by `calculate_reliability`.

Fields:
- `score` (int 0–100)
- `band` (string: `High` | `Medium` | `Low`)
- `explanations` (array[string])
- `has_tight_connection` (bool)

Mapping notes:
- The public `Journey.has_connection_risk` is mapped from `ReliabilityResult.has_tight_connection`.
- The API mapping functions append a short tight-connection summary to `reliability_explanations` when `has_tight_connection` is true to ensure UI clients receive the text explanation.

## Change guidance
- When adding or renaming fields in code, update these DTO docs and the `_parse_*` mapping functions in `backend/app/api.py`.
- Tests rely on these exact JSON field names; renames are breaking changes for clients unless accompanied by API compatibility shims.

---
File generated from `backend/app/api.py` and domain dataclasses.
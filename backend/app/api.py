from fastapi import FastAPI, HTTPException, Query, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import List, Optional, Literal
from datetime import datetime
import time
import sqlite3
from pathlib import Path

from app.data.stops import StopService
from app.domain.planner.planner import JourneyPlanner
from app.domain.decision_support.decision_support import DecisionSupport
from app.cache.cache_service import CacheService
from app.domain.reliability import calculate_reliability
from app.domain.weather import fetch_weather, WeatherInfo

from app.data.exceptions import DataUnavailableError, StaticDataMissingError
from app.domain.planner.exceptions import PlannerError, NoRouteFoundError
from app.domain.decision_support.exceptions import DecisionSupportError
from app.cache.exceptions import CacheUnavailableError

app = FastAPI(
    title="OptiRoute Regional Transport API",
    description="Backend API layer providing thin orchestration for journey planning.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:5174", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _find_db_path(*names: str) -> Optional[Path]:
    """Look for DBs in both likely locations:
    - repo root
    - backend folder
    """
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2],  # repo root if file is backend/app/api.py
        here.parents[1],  # backend folder
    ]

    for base in candidates:
        for name in names:
            path = base / name
            if path.exists():
                return path
    return None


@app.on_event("startup")
async def validate_bus_stops_on_startup():
    """Validate that bus timetable stop IDs can be resolved at boot time."""
    try:
        from app.data.validation import validate_bus_stop_resolution

        bus_db = _find_db_path("bus.db", "database1.db")
        stops_db = _find_db_path("stops.db", "optiroute.db")

        if bus_db and stops_db:
            report = validate_bus_stop_resolution(bus_db, stops_db)
            print(
                f"[startup] Bus stop validation: "
                f"{report.resolved}/{report.total_bus_stop_ids} resolved "
                f"({report.resolution_pct:.1f}%), "
                f"{len(report.unresolved_ids)} unresolved"
            )
            if not report.is_healthy:
                print(
                    "[startup] WARNING: Bus stop resolution is below 95%. "
                    "Run `python sync_bus_stops.py` to fix."
                )
        else:
            print("[startup] bus.db or stops.db not found — bus routing disabled")
    except Exception as e:
        print(f"[startup] Bus stop validation skipped: {e}")


rate_limit_records: dict[str, list[float]] = {}


def rate_limiter(request: Request):
    client_ip = request.headers.get(
        "X-Forwarded-For",
        request.client.host if request.client else "127.0.0.1"
    )
    client_ip = client_ip.split(",")[0].strip()
    current_time = time.time()

    if client_ip in rate_limit_records:
        req_times = [t for t in rate_limit_records[client_ip] if current_time - t < 60]
        if len(req_times) >= 30:
            raise HTTPException(status_code=429, detail="Too Many Requests")
        req_times.append(current_time)
        rate_limit_records[client_ip] = req_times
    else:
        rate_limit_records[client_ip] = [current_time]


MAX_REQ_SIZE = 1024 * 50  # 50KB


@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_REQ_SIZE:
        return JSONResponse(status_code=413, content={"detail": "Payload Too Large"})
    return await call_next(request)


class JourneyRequest(BaseModel):
    origin_id: str = Field(..., description="AtcoCode (bus) or CRS/Tiploc (rail)")
    destination_id: str = Field(..., description="AtcoCode (bus) or CRS/Tiploc (rail)")
    time_type: Literal["depart_at", "arrive_by"]
    time_iso: datetime
    modes: Literal["bus", "rail", "mixed"]
    max_options: int = Field(5, ge=1, le=10)

    @field_validator("time_iso", mode="before")
    def parse_time(cls, value):
        if isinstance(value, str):
            value = value.replace("Z", "+00:00")
        return value


class LiveStatus(BaseModel):
    available: bool
    delay_minutes: int
    disrupted_flag: bool
    source: str


class Leg(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    mode: Literal["walk", "bus", "rail"]
    from_loc: str = Field(..., alias="from")
    to_loc: str = Field(..., alias="to")
    depart: datetime
    arrive: datetime
    from_lat: Optional[float] = None
    from_lon: Optional[float] = None
    to_lat: Optional[float] = None
    to_lon: Optional[float] = None
    operator: Optional[str] = None
    service_id: Optional[str] = None
    live_status: Optional[LiveStatus] = None
    leg_risk_band: Optional[Literal["High", "Medium", "Low"]] = None
    risk_explanation: Optional[List[str]] = None


class Journey(BaseModel):
    total_duration_min: int
    depart_time: datetime
    arrive_time: datetime
    changes: int
    reliability_score: int = Field(..., ge=0, le=100)
    reliability_band: Literal["High", "Medium", "Low"]
    reliability_explanation: List[str]
    depart_time:        datetime
    arrive_time:        datetime
    changes:            int
    reliability_score:       int = Field(..., ge=0, le=100)
    reliability_band:        Literal["High", "Medium", "Low"]
    reliability:            Literal["High", "Medium", "Low"]
    reliability_explanations: List[str]
    has_connection_risk:     bool = False
    legs: List[Leg]


class JourneyResponse(BaseModel):
    journeys: List[Journey]
    data_quality_flags: List[
        Literal["TIMETABLE_ONLY", "LIVE_MISSING", "WEATHER_MISSING", "HISTORICAL_MISSING"]
    ]


class StopResponse(BaseModel):
    id: str
    name: str
    type: Literal["bus", "rail"]
    lat: float
    lon: float


class StatusResponse(BaseModel):
    timetable_updated_at: datetime
    live_updated_at: datetime
    weather_updated_at: datetime


def _parse_live_status(raw) -> Optional[dict]:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    return {
        "available": raw.available,
        "delay_minutes": raw.delay_minutes,
        "disrupted_flag": raw.disrupted_flag,
        "source": raw.source,
    }


def _parse_leg(raw) -> dict:
    if isinstance(raw, dict):
        return {
            "from": raw.get("from") or raw.get("from_loc") or getattr(raw, "from_id", None),
            "to": raw.get("to") or raw.get("to_loc") or getattr(raw, "to_id", None),
            "mode": raw.get("mode"),
            "depart": raw.get("depart") or raw.get("depart_time"),
            "arrive": raw.get("arrive") or raw.get("arrive_time"),
            "from_lat": raw.get("from_lat"),
            "from_lon": raw.get("from_lon"),
            "to_lat": raw.get("to_lat"),
            "to_lon": raw.get("to_lon"),
            "operator": raw.get("operator"),
            "service_id": raw.get("line", raw.get("service_id")),
            "live_status": _parse_live_status(raw.get("live_status")),
            "leg_risk_band": raw.get("leg_risk_band"),
            "risk_explanation": raw.get("risk_explanation"),
        }

    return {
        "from": getattr(raw, "from_id", None) or getattr(raw, "from_loc", None),
        "to": getattr(raw, "to_id", None) or getattr(raw, "to_loc", None),
        "mode": getattr(raw, "mode", None),
        "depart": getattr(raw, "depart_time", getattr(raw, "depart", None)),
        "arrive": getattr(raw, "arrive_time", getattr(raw, "arrive", None)),
        "from_lat": getattr(raw, "from_lat", None),
        "from_lon": getattr(raw, "from_lon", None),
        "to_lat": getattr(raw, "to_lat", None),
        "to_lon": getattr(raw, "to_lon", None),
        "operator": getattr(raw, "operator", None),
        "service_id": getattr(raw, "service_id", None),
        "live_status": _parse_live_status(getattr(raw, "live_status", None)),
        "leg_risk_band": getattr(raw, "leg_risk_band", None),
        "risk_explanation": getattr(raw, "risk_explanation", None),
    }


def _parse_journey(raw) -> dict:
    if isinstance(raw, dict):
        parsed = dict(raw)
        parsed["legs"] = [_parse_leg(leg) for leg in raw.get("legs", [])]
        return parsed

    return {
        "total_duration_min": raw.total_duration_min,
        "depart_time": raw.depart_time,
        "arrive_time": raw.arrive_time,
        "changes": raw.changes,
        "reliability_score": getattr(raw, "reliability_score", 0),
        "reliability_band": getattr(raw, "reliability_band", "Low"),
        "reliability_explanation": getattr(raw, "reliability_explanation", []),
        "legs": [_parse_leg(leg) for leg in raw.legs],
    """
    Person E (Rak)    — base journey fields from JourneyPlanner.
    Person F (Daniel) — adds reliability_score, reliability_band,
                        reliability_explanation via DecisionSupport.
    """
    # canonical summary text used by the reliability calculator
    tight_summary = "One or more legs have very tight connections (<5 minutes) — increased risk of missed transfers"

    if isinstance(raw, dict):
        # ensure older dict inputs get a consistent boolean field
        out = dict(raw)
        out.setdefault("has_connection_risk", out.get("has_tight_connection", False))
        # Ensure explanations list exists
        expls = list(out.get("reliability_explanations") or [])
        if (out.get("has_connection_risk") or out.get("has_tight_connection")) and not any(tight_summary in e for e in expls):
            expls.append(tight_summary)
        out["reliability_explanations"] = expls
        out.setdefault("reliability", out.get("reliability_band", "Low"))
        return out

    expls = list(getattr(raw, "reliability_explanations", []) or [])
    has_risk = getattr(raw, "has_connection_risk", getattr(raw, "has_tight_connection", False))
    if has_risk and not any(tight_summary in e for e in expls):
        expls.append(tight_summary)

    return {
        "total_duration_min":      raw.total_duration_min,
        "depart_time":             raw.depart_time,
        "arrive_time":             raw.arrive_time,
        "changes":                 raw.changes,
        "reliability_score":       getattr(raw, "reliability_score",       0),
        "reliability_band":        getattr(raw, "reliability_band",        "Low"),
        "reliability":            getattr(raw, "reliability_band",        "Low"),
        "reliability_explanations": expls,
        "has_connection_risk":     has_risk,
        "legs":                    [_parse_leg(leg) for leg in raw.legs],
    }


def get_stop_service() -> StopService:
    return StopService()


def get_journey_planner() -> JourneyPlanner:
    return JourneyPlanner()


def get_decision_support() -> DecisionSupport:
    return DecisionSupport()


def get_cache_service() -> CacheService:
    return CacheService()


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok"}


@app.get("/api/bus-stop-validation", tags=["System"])
async def bus_stop_validation():
    """Return a report on bus stop ID resolution health."""
    try:
        from app.data.validation import validate_bus_stop_resolution

        bus_db = _find_db_path("bus.db", "database1.db")
        stops_db = _find_db_path("stops.db", "optiroute.db")

        if not bus_db or not stops_db:
            raise HTTPException(status_code=503, detail="Required database files not found")

        report = validate_bus_stop_resolution(bus_db, stops_db)
        return {
            "total_bus_stop_ids": report.total_bus_stop_ids,
            "resolved": report.resolved,
            "resolved_with_coords": report.resolved_with_coords,
            "unresolved_count": len(report.unresolved_ids),
            "resolution_pct": round(report.resolution_pct, 2),
            "healthy": report.is_healthy,
            "unresolved_sample": sorted(report.unresolved_ids)[:20],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/status", response_model=StatusResponse, tags=["System"], dependencies=[Depends(rate_limiter)])
async def system_status(cache_service: CacheService = Depends(get_cache_service)):
    try:
        freshness = cache_service.get_freshness()
        return StatusResponse(**freshness)
    except CacheUnavailableError:
        raise HTTPException(status_code=503, detail="Cache unavailable")


@app.get("/api/stops", tags=["Search"], dependencies=[Depends(rate_limiter)])
async def api_get_stops(
    min_lat: float = Query(..., description="Minimum latitude (south)"),
    max_lat: float = Query(..., description="Maximum latitude (north)"),
    min_lon: float = Query(..., description="Minimum longitude (west)"),
    max_lon: float = Query(..., description="Maximum longitude (east)"),
    limit: int = Query(500, ge=1, le=500),
):
    """Return stops within the provided bounding box using sqlite3."""
    db_path = _find_db_path("stops.db", "optiroute.db")
    if not db_path:
        raise HTTPException(status_code=503, detail="Database file not found")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    bus_db = _find_db_path("bus.db", "database1.db")
    if bus_db:
        try:
            conn.execute(f"ATTACH DATABASE '{bus_db}' AS bus")
        except Exception:
            pass

    try:
        results = []
        seen_ids: set[str] = set()

        cur = conn.execute(
            """
            SELECT atco_code AS id, common_name AS name, latitude AS lat, longitude AS lon,
                   CASE WHEN stop_type IN ('RLY', 'RSE', 'TMU', 'MET') THEN 'rail' ELSE 'bus' END as type
            FROM stops
            WHERE latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ?
            LIMIT ?
            """,
            (min_lat, max_lat, min_lon, max_lon, limit),
        )
        for r in cur.fetchall():
            d = dict(r)
            results.append(d)
            seen_ids.add(d["id"])

        try:
            cur2 = conn.execute(
                """
                SELECT atco_code AS id, common_name AS name, latitude AS lat, longitude AS lon, 'bus' as type
                FROM bus.bus_stops
                WHERE latitude IS NOT NULL
                  AND longitude IS NOT NULL
                  AND latitude BETWEEN ? AND ?
                  AND longitude BETWEEN ? AND ?
                LIMIT ?
                """,
                (min_lat, max_lat, min_lon, max_lon, limit),
            )
            for r in cur2.fetchall():
                d = dict(r)
                if d["id"] not in seen_ids:
                    results.append(d)
                    seen_ids.add(d["id"])
        except Exception:
            pass

        return results
    except sqlite3.DatabaseError as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/routable-stops", tags=["Search"], dependencies=[Depends(rate_limiter)])
async def api_routable_stops():
    """Return distinct stop IDs from bus and rail timetables."""
    bus_db_path = _find_db_path("bus.db", "database1.db")
    rail_db_path = _find_db_path("rail.db")

    routable_ids = set()

    if bus_db_path:
        try:
            conn = sqlite3.connect(str(bus_db_path))
            cur = conn.execute("SELECT DISTINCT stop_id FROM stop_times")
            routable_ids.update(r[0] for r in cur.fetchall() if r and r[0])
            conn.close()
        except sqlite3.DatabaseError:
            pass

    if rail_db_path:
        try:
            conn = sqlite3.connect(str(rail_db_path))
            cur = conn.execute("SELECT DISTINCT tiploc FROM schedules")
            rail_ids = [r[0] for r in cur.fetchall() if r and r[0]]
            routable_ids.update(rail_ids)
            routable_ids.update(f"RAIL:{r}" for r in rail_ids)
            routable_ids.update(f"9100{r}" for r in rail_ids)
            conn.close()
        except sqlite3.DatabaseError:
            pass

    if not routable_ids:
        raise HTTPException(status_code=503, detail="No routable databases found")

    return {"ids": list(routable_ids)}


@app.get("/stops", response_model=List[StopResponse], tags=["Search"], dependencies=[Depends(rate_limiter)])
@app.get(
    "/api/weather",
    tags=["System"],
    dependencies=[Depends(rate_limiter)],
)
async def api_get_weather(
    lat: float = Query(54.0466, description="Latitude"),
    lon: float = Query(-2.8007, description="Longitude"),
):
    """Return current weather for the provided coordinates.

    Uses `fetch_weather` from the domain layer. This endpoint must never
    raise a 500 — any failure returns a safe fallback payload.
    """
    from dataclasses import asdict

    try:
        info = fetch_weather(lat, lon)
        # Ensure a plain JSON-serialisable dict is returned
        return asdict(info)
    except Exception as e:
        print(f"Weather endpoint error: {e}")
        fallback = WeatherInfo(
            available=False,
            is_adverse=False,
            description="Weather data unavailable",
            temperature_c=0.0,
            windspeed_kmh=0.0,
        )
        return asdict(fallback)


@app.get(
    "/stops",
    response_model=List[StopResponse],
    tags=["Search"],
    dependencies=[Depends(rate_limiter)],
)
async def get_stops(
    query: str = Query(..., min_length=2),
    limit: int = Query(10, ge=1, le=50),
    stop_service: StopService = Depends(get_stop_service),
):
    """Autocomplete search endpoint for all transport modes."""
    db_path = _find_db_path("stops.db", "optiroute.db")
    if not db_path:
        raise HTTPException(status_code=503, detail="Database file not found")

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        bus_db = _find_db_path("bus.db", "database1.db")
        if bus_db:
            try:
                conn.execute(f"ATTACH DATABASE '{bus_db}' AS bus")
            except Exception:
                pass

        results: list[dict] = []
        seen_ids: set[str] = set()

        cur = conn.execute(
            """
            SELECT atco_code AS id, common_name AS name, latitude AS lat, longitude AS lon,
                   CASE WHEN stop_type IN ('RLY', 'RSE', 'TMU', 'MET') THEN 'rail' ELSE 'bus' END as type
            FROM stops
            WHERE common_name LIKE ?
            LIMIT ?
            """,
            (f"%{query}%", limit),
        )
        for r in cur.fetchall():
            d = dict(r)
            results.append(d)
            seen_ids.add(d["id"])

        try:
            cur2 = conn.execute(
                """
                SELECT atco_code AS id, common_name AS name, latitude AS lat, longitude AS lon, 'bus' as type
                FROM bus.bus_stops
                WHERE common_name LIKE ?
                LIMIT ?
                """,
                (f"%{query}%", limit),
            )
            for r in cur2.fetchall():
                d = dict(r)
                if d["id"] not in seen_ids:
                    results.append(d)
                    seen_ids.add(d["id"])
        except Exception:
            pass

        if not results:
            raise HTTPException(status_code=404, detail="No stops found")
        return results[:limit]
    except HTTPException:
        raise
    except sqlite3.DatabaseError as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.post("/journeys", response_model=JourneyResponse, tags=["Routing"], dependencies=[Depends(rate_limiter)])
async def plan_journey(
    request: JourneyRequest,
    sort_by: Literal["time", "reliability"] = Query("time", description="Sort by fastest time or highest reliability"),
    journey_planner: JourneyPlanner = Depends(get_journey_planner),
    decision_support: DecisionSupport = Depends(get_decision_support),
):
    if request.origin_id == request.destination_id:
        raise HTTPException(status_code=400, detail="Origin and destination cannot be identical")

    try:
        raw_journeys = journey_planner.plan(
            origin_id=request.origin_id,
            destination_id=request.destination_id,
            time_type=request.time_type,
            time_iso=request.time_iso,
            modes=request.modes,
            max_options=request.max_options,
        )
    except NoRouteFoundError:
        return JSONResponse(
            status_code=200,
            content={
                "journeys": [],
                "data_quality_flags": [],
                "message": f"No nearby routes found connecting {request.origin_id} and {request.destination_id}",
            },
        )
    except PlannerError:
        raise HTTPException(status_code=503, detail="Journey planning service unavailable")
    except Exception:
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    journeys = [_parse_journey(j) for j in raw_journeys]

    try:
        annotated_journeys, flags = decision_support.annotate(journeys)
        annotated_journeys = [_parse_journey(j) for j in annotated_journeys]
    except DecisionSupportError:
        annotated_journeys = journeys
        flags = ["TIMETABLE_ONLY", "LIVE_MISSING", "HISTORICAL_MISSING"]

    # Ensure every journey includes reliability fields. If DecisionSupport
    # did not provide them, compute a default using historical defaults and
    # available live_status fields.
    for j in annotated_journeys:
        # Prepare legs for reliability calculation: map any live_status.delay_minutes
        # -> live_delay_minutes and live_status.disrupted_flag -> is_cancelled
        legs_for_calc = []
        for leg in j.get("legs", []):
            l = dict(leg) if isinstance(leg, dict) else dict(leg.__dict__)
            ls = l.get("live_status") or {}
            if isinstance(ls, dict):
                if "delay_minutes" in ls:
                    l["live_delay_minutes"] = ls.get("delay_minutes", 0)
                if "disrupted_flag" in ls:
                    l["is_cancelled"] = bool(ls.get("disrupted_flag"))
            legs_for_calc.append(l)

        # If reliability fields missing or zero-ish, compute defaults
        missing_score = not j.get("reliability_score") and j.get("reliability_score") != 0
        missing_band = not j.get("reliability_band")
        missing_expl = not j.get("reliability_explanations")
        if missing_score or missing_band or missing_expl:
            res = calculate_reliability(legs_for_calc)
            j["reliability_score"] = int(res.score)
            j["reliability_band"] = res.band
            j["reliability"] = j["reliability_band"]
            j["reliability_explanations"] = res.explanations

    # Step 4: Sort with tie-breakers per README routing objective:
    #   Primary:   earliest arrival (time) or reliability_score (reliability)
    #   Secondary: fewer changes  (README: "tie-breaker: fewer changes")
    #   Tertiary:  reliability / duration as final tie-breaker
    if sort_by == "time":
        annotated_journeys.sort(
            key=lambda j: (j["total_duration_min"], j["changes"], -j["reliability_score"])
        )
    else:
        annotated_journeys.sort(
            key=lambda j: (-j["reliability_score"], j["changes"], j["total_duration_min"])
        )

    return JourneyResponse(journeys=annotated_journeys, data_quality_flags=flags)
    # Apply weather penalty once (single fetch) — non-fatal and non-blocking.
    # If fetch fails, do not modify journeys.
    weather_fetch_succeeded = False
    try:
        weather = fetch_weather(lat=54.0466, lon=-2.8007)
        weather_fetch_succeeded = True
    except Exception as e:
        print(f"Weather fetch failed (non-fatal): {e}")
        # create a safe fallback with is_adverse False but mark fetch as failed
        weather = WeatherInfo(
            available=False,
            is_adverse=False,
            description="Weather data unavailable",
            temperature_c=0.0,
            windspeed_kmh=0.0,
        )

    # Only apply penalty when fetch succeeded and weather reports adverse conditions
    if weather_fetch_succeeded and getattr(weather, "is_adverse", False):
        penalty_expl = "Adverse weather conditions may increase delays"
        for j in annotated_journeys:
            # Ensure explanations list exists
            expls = list(j.get("reliability_explanations") or [])

            # Subtract penalty and clamp
            orig_score = int(j.get("reliability_score", 0))
            new_score = max(0, orig_score - 10)
            j["reliability_score"] = new_score

            # Recompute band
            if new_score >= 80:
                j["reliability_band"] = "High"
            elif new_score >= 50:
                j["reliability_band"] = "Medium"
            else:
                j["reliability_band"] = "Low"
            j["reliability"] = j["reliability_band"]

            # Append explanation if not already present
            if penalty_expl not in expls:
                expls.append(penalty_expl)
            j["reliability_explanations"] = expls

    return JourneyResponse(journeys=annotated_journeys, data_quality_flags=flags)


# ==========================================
# ASSUMPTIONS
#
# Source of truth: repo README fixed group assumptions.
# Any change to these must be communicated to the relevant person
# AND reflected in the _parse_* functions and DTOs above.
#
# ── Person D (Kamol) ── app/data/
#
#   File:    app/data/stops.py
#   Class:   StopService
#   Method:  search_stops(query: str, limit: int) -> list
#   Returns: list of dicts OR ORM objects with attributes:
#              id   : str   — AtcoCode for bus stops (NaPTAN canonical ID)
#              name : str   — human-readable stop/station name
#              type : str   — exactly "bus" or "rail", no other values
#              lat  : float
#              lon  : float
#
#   File:    app/data/exceptions.py
#   Must define and raise:
#     StaticDataMissingError  — NaPTAN/NPTG not loaded (DB empty)
#     DataUnavailableError    — DB temporarily unreachable
#   Any other exception propagates uncaught and crashes loudly — intentional.
#
# ── Person E (Rak) ── app/domain/planner/
#
#   File:    app/domain/planner/planner.py
#   Class:   JourneyPlanner
#   Method:  plan(
#                origin_id: str,
#                destination_id: str,
#                time_type: str,       # "depart_at" or "arrive_by"
#                time_iso: datetime,
#                modes: str,           # "bus", "rail", or "mixed"
#                max_options: int
#            ) -> list
#   Returns: list of dicts OR domain objects with attributes:
#              total_duration_min : int
#              depart_time        : datetime
#              arrive_time        : datetime
#              changes            : int
#              legs               : iterable of leg dicts or leg objects
#
#   Each leg object must have these attributes (README leg-level format):
#              from_loc          : str      — MUST be from_loc not from
#                                            ('from' is a reserved keyword)
#              to_loc            : str
#              mode              : str      — exactly "walk", "bus", or "rail"
#              depart            : datetime
#              arrive            : datetime
#              operator          : Optional[str]
#              service_id        : Optional[str]
#              live_status       : Optional — see LiveStatus fields below
#              leg_risk_band     : Optional[str] — README: leg_risk_band
#              risk_explanation  : Optional[list[str]]
#
#   README routing objective implemented here:
#     Primary:   earliest arrival / shortest duration
#     Tie-break: fewer changes, then more slack (slack output is advisory,
#                planner outputs it, DecisionSupport annotates risk from it)
#
#   README walking transfer rule (Rak must implement in planner):
#     Max distance: WALK_MAX_METERS (e.g. 800m)
#     Walking time: distance_m / 1.4 m/s
#     Distance:     straight-line Haversine (no external routing API)
#     Scope:        transfers between StopGroups only, not whole journeys
#
#   File:    app/domain/planner/exceptions.py
#   Must define and raise:
#     NoRouteFoundError — valid stops, no timetabled route connects them.
#                         API returns empty journey list, not 503.
#     PlannerError      — any other planning failure.
#   Any other exception propagates uncaught — intentional.
#
#   CRITICAL NAMING AGREEMENT WITH RAK:
#     Leg field must be named from_loc (not from, origin, departure_stop).
#     If named differently, _parse_leg raises AttributeError.
#
# ── Person F (Daniel) ── app/domain/decision_support/ and app/cache/
#
#   File:    app/domain/decision_support/decision_support.py
#   Class:   DecisionSupport
#   Method:  annotate(journeys: list[dict]) -> tuple[list, list[str]]
#   Receives: Already-parsed list of journey dicts (plain dicts, not ORM).
#   Returns:  tuple of (annotated_journeys, flags) where:
#
#     annotated_journeys: list of dicts or objects, each journey having:
#       reliability_score       : int (0–100)
#       reliability_band        : str — exactly "High", "Medium", or "Low"
#       reliability_explanation : list[str]
#     Each leg within journey also annotated with (README leg-level format):
#       live_status   : dict/object with fields:
#                         available      : bool
#                         delay_minutes  : int   — README: delay_minutes
#                         disrupted_flag : bool  — README: disrupted_flag
#                         source         : str
#       leg_risk_band : str — README: leg_risk_band ("High"/"Medium"/"Low")
#
#     flags: list[str], subset of:
#       "TIMETABLE_ONLY", "LIVE_MISSING", "WEATHER_MISSING", "HISTORICAL_MISSING"
#
#   README reliability bands (must match exactly — used in sorting):
#     High   >= 80
#     Medium  50–79
#     Low    <  50
#
#   README assumption 5 — non-blocking failure:
#     Daniel must raise DecisionSupportError (not generic Exception) for
#     recoverable failures. If raised, API returns journeys without
#     reliability data rather than failing the whole request.
#
#   File:    app/domain/decision_support/exceptions.py
#   Must define: DecisionSupportError
#
#   File:    app/cache/cache_service.py
#   Class:   CacheService
#   Method:  get_freshness() -> dict
#   Returns: dict with exactly these keys (datetime values):
#              timetable_updated_at : datetime
#              live_updated_at      : datetime
#              weather_updated_at   : datetime
#
#   File:    app/cache/exceptions.py
#   Must define: CacheUnavailableError
#
# ── Person B (Ismaeel) ── frontend/
#
#   No code dependency, but a strict JSON contract dependency.
#   The JSON field names Ismaeel's TypeScript interfaces must match:
#
#   StopResponse:    id, name, type, lat, lon
#   JourneyResponse: journeys[], data_quality_flags[]
#   Journey:         total_duration_min, depart_time, arrive_time, changes,
#                    reliability_score, reliability_band,
#                    reliability_explanation[], legs[]
#   Leg:             "from", "to", mode, depart, arrive, operator,
#                    service_id, live_status, leg_risk_band,
#                    risk_explanation[]
#                    NOTE: JSON uses "from"/"to" (via Pydantic alias),
#                    not "from_loc"/"to_loc" — Ismaeel's TS type should
#                    use "from" and "to".
#   LiveStatus:      available, delay_minutes, disrupted_flag, source
#                    NOTE: delay_minutes (not delay_min),
#                          disrupted_flag (not cancelled) — per README.
#
# ── Network / Infrastructure (Person A / Molly) ──
#
#   Rate limiter reads X-Forwarded-For for the real client IP because
#   university ISS VPN and web proxy sit in front of the app.
#   If deployed without a proxy (direct Docker on lab machine),
#   X-Forwarded-For is absent and fallback to request.client.host applies.
#   If multiple proxy hops exist, X-Forwarded-For is comma-separated;
#   code takes first entry (original client).
#   For multi-worker deployments, rate limit state must move to Redis.
#
# ==========================================

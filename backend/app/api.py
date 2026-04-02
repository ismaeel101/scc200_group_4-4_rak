from fastapi import FastAPI, HTTPException, Query, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import List, Optional, Literal
from datetime import datetime
import time

# ==========================================
# DOMAIN & DATA IMPORTS
#
# ASSUMPTIONS (see full list at bottom of file):
#   app.data.stops              — Person D (Kamol)
#   app.domain.planner.planner  — Person E (Rak)
#   app.domain.decision_support — Person F (Daniel)
#   app.cache.cache_service     — Person F (Daniel)
# ==========================================
from app.data.stops import StopService
from app.domain.planner.planner import JourneyPlanner
from app.domain.decision_support.decision_support import DecisionSupport
from app.cache.cache_service import CacheService
from app.domain.reliability import calculate_reliability

# ==========================================
# DOMAIN EXCEPTION IMPORTS
#
# Catching specific exceptions rather than bare Exception ensures that
# genuine bugs (TypeErrors, AttributeErrors, etc.) surface loudly during
# development instead of being silently swallowed as 503 responses.
#
# Each person must define and raise these from the paths below.
# Person D (Kamol)  -> app/data/exceptions.py
# Person E (Rak)    -> app/domain/planner/exceptions.py
# Person F (Daniel) -> app/domain/decision_support/exceptions.py
#                      app/cache/exceptions.py
# ==========================================
from app.data.exceptions import DataUnavailableError, StaticDataMissingError
from app.domain.planner.exceptions import PlannerError, NoRouteFoundError
from app.domain.decision_support.exceptions import DecisionSupportError
from app.cache.exceptions import CacheUnavailableError

# Scheduler (Person D / Kamol — Week 3: timetable refresh job)



# ==========================================
# APP SETUP
# ==========================================
app = FastAPI(
    title="OptiRoute Regional Transport API",
    description="Backend API layer providing thin orchestration for journey planning.",
    version="1.0.0"
)

# Allow CORS from local dev frontend (vite) and other origins during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173","http://localhost:5173","http://127.0.0.1:5174","http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================
# STARTUP / SHUTDOWN EVENTS
# (scheduler start/stop removed — scheduler functions not available)
# ==========================================


# Rate limiter (moved before endpoints that use it)
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

 
@app.get(
    "/api/stops",
    tags=["Search"],
    dependencies=[Depends(rate_limiter)],
)
async def api_get_stops(
    min_lat: float = Query(..., description="Minimum latitude (south)"),
    max_lat: float = Query(..., description="Maximum latitude (north)"),
    min_lon: float = Query(..., description="Minimum longitude (west)"),
    max_lon: float = Query(..., description="Maximum longitude (east)"),
    limit: int = Query(500, ge=1, le=500),
):
    """Return stops within the provided bounding box using sqlite3.

    This lightweight endpoint is used by the frontend map to fetch visible
    stops. It directly queries the local `backend/database1.db` SQLite file.
    """
    import sqlite3
    from pathlib import Path

    # Resolve DB path relative to this file: workspace/backend/stops.db
    base = Path(__file__).resolve().parents[1]
    db_path = base / "stops.db"
    # Log resolved path for debugging
    print(f"Resolved DB path: {db_path}")
    if not db_path.exists():
        # Try legacy optiroute.db location
        alt = base / "optiroute.db"
        if alt.exists():
            db_path = alt
        else:
            raise HTTPException(status_code=503, detail="Database file not found")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT atco_code AS id, common_name AS name, latitude AS lat, longitude AS lon FROM stops "
            "WHERE latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ? LIMIT ?",
            (min_lat, max_lat, min_lon, max_lon, limit),
        )
        rows = cur.fetchall()
        results = [dict(r) for r in rows]
        return results
    except sqlite3.DatabaseError as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get(
    "/api/routable-stops",
    tags=["Search"],
    dependencies=[Depends(rate_limiter)],
)
async def api_routable_stops():
    """Return distinct stop IDs from the timetable (stop_times).

    This reads from the local `bus.db` SQLite file and returns a JSON
    object with an `ids` array.
    """
    import sqlite3
    from pathlib import Path

    base = Path(__file__).resolve().parents[1]
    db_path = base / "bus.db"
    if not db_path.exists():
        # try alternate names
        alt = base / "database1.db"
        if alt.exists():
            db_path = alt
        else:
            raise HTTPException(status_code=503, detail="Bus database not found")

    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute("SELECT DISTINCT stop_id FROM stop_times")
        rows = cur.fetchall()
        ids = [r[0] for r in rows if r and r[0]]
        return {"ids": ids}
    except sqlite3.DatabaseError as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            conn.close()
        except Exception:
            pass



# ==========================================
# MIDDLEWARE
# ==========================================

MAX_REQ_SIZE = 1024 * 50  # 50KB

@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_REQ_SIZE:
        return JSONResponse(status_code=413, content={"detail": "Payload Too Large"})
    return await call_next(request)


 


# ==========================================
# DATA TRANSFER OBJECTS (DTOs)
#
# Field names here are the source of truth for the JSON API contract.
# They are derived directly from the repo README fixed group assumptions.
# Do NOT rename fields without updating:
#   - Person B (Ismaeel) TypeScript interfaces
#   - Person E (Rak) domain leg model attribute names
#   - Person F (Daniel) decision support output attribute names
#   - The _parse_* mapping functions below
# ==========================================

class JourneyRequest(BaseModel):
    origin_id: str = Field(..., description="AtcoCode (bus) or CRS (rail) wrapped in PlaceId")
    destination_id: str = Field(..., description="AtcoCode (bus) or CRS (rail) wrapped in PlaceId")
    time_type: Literal["depart_at", "arrive_by"]
    time_iso: datetime
    modes: Literal["bus", "rail", "mixed"]
    max_options: int = Field(5, ge=1, le=10)

    @field_validator("time_iso", mode="before")
    def parse_time(cls, value):
        # Normalise ambiguous timezone suffix sent by some frontend clients
        if isinstance(value, str):
            value = value.replace("Z", "+00:00")
        return value


class LiveStatus(BaseModel):
    """
    README leg-level reliability output format:
        live_status, delay_minutes, disrupted_flag (Boolean), leg_risk_band
    Field names here match the README exactly.
    """
    available:      bool
    delay_minutes:  int    # README: delay_minutes (not delay_min)
    disrupted_flag: bool   # README: disrupted_flag Boolean (not cancelled)
    source:         str


class Leg(BaseModel):
    # Pydantic V2 — replaces deprecated inner Config class
    model_config = ConfigDict(populate_by_name=True)

    mode: Literal["walk", "bus", "rail"]
    from_loc: str = Field(..., alias="from")   # serialises as "from" in JSON
    to_loc:   str = Field(..., alias="to")     # serialises as "to" in JSON
    depart:   datetime
    arrive:   datetime
    operator:         Optional[str] = None
    service_id:       Optional[str] = None
    live_status:      Optional[LiveStatus] = None                    # README: live_status
    leg_risk_band:    Optional[Literal["High", "Medium", "Low"]] = None  # README: leg_risk_band
    risk_explanation: Optional[List[str]] = None


class Journey(BaseModel):
    """
    README journey-level reliability output format:
        reliability_band (High/Medium/Low) + reliability_score (0-100) + explanation[]
    """
    total_duration_min: int
    depart_time:        datetime
    arrive_time:        datetime
    changes:            int
    reliability_score:       int = Field(..., ge=0, le=100)
    reliability_band:        Literal["High", "Medium", "Low"]
    reliability_explanations: List[str]
    legs: List[Leg]


class JourneyResponse(BaseModel):
    journeys: List[Journey]
    data_quality_flags: List[
        Literal["TIMETABLE_ONLY", "LIVE_MISSING", "WEATHER_MISSING", "HISTORICAL_MISSING"]
    ]


class StopResponse(BaseModel):
    id:   str
    name: str
    type: Literal["bus", "rail"]
    lat:  float
    lon:  float


class StatusResponse(BaseModel):
    timetable_updated_at: datetime
    live_updated_at:      datetime
    weather_updated_at:   datetime


# ==========================================
# MAPPING FUNCTIONS
#
# Domain services (Persons D, E, F) may return SQLAlchemy ORM objects,
# custom domain model instances, or plain dicts. These functions normalise
# any of those into plain dicts that sorting logic and Pydantic response
# models can safely consume, preventing TypeError crashes on dict-key
# access against ORM objects.
#
# Attribute names used here (e.g. raw.delay_minutes, raw.leg_risk_band)
# are the contract with Rak and Daniel. If they name their fields
# differently the mapping will raise AttributeError — see Assumptions.
# ==========================================

def _parse_stop(raw) -> dict:
    """
    Person D (Kamol) — StopService return type.
    May be a SQLAlchemy Stop ORM row or a plain dict.
    """
    if isinstance(raw, dict):
        return raw
    return {
        "id":   raw.id,
        "name": raw.name,
        "type": raw.type,
        "lat":  raw.lat,
        "lon":  raw.lon,
    }


def _parse_live_status(raw) -> Optional[dict]:
    """
    Person F (Daniel) — live data annotated onto legs by DecisionSupport.
    Field names match README: delay_minutes, disrupted_flag.
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    return {
        "available":      raw.available,
        "delay_minutes":  raw.delay_minutes,   # README: delay_minutes
        "disrupted_flag": raw.disrupted_flag,  # README: disrupted_flag
        "source":         raw.source,
    }


def _parse_leg(raw) -> dict:
    """
    Person E (Rak) — base leg fields from JourneyPlanner.
    Person F (Daniel) — adds live_status and leg_risk_band via DecisionSupport.

    CRITICAL: from field must be raw.from_loc (not raw.from) because
    'from' is a reserved Python keyword. Agreed with Rak — see Assumptions.

    Field names live_status and leg_risk_band match README exactly.
    """
    if isinstance(raw, dict):
        return raw
    return {
        "from":             raw.from_loc,
        "to":               raw.to_loc,
        "mode":             raw.mode,
        "depart":           raw.depart,
        "arrive":           raw.arrive,
        "operator":         getattr(raw, "operator",         None),
        "service_id":       getattr(raw, "service_id",       None),
        "live_status":      _parse_live_status(getattr(raw, "live_status",      None)),  # README
        "leg_risk_band":    getattr(raw, "leg_risk_band",    None),                      # README
        "risk_explanation": getattr(raw, "risk_explanation", None),
    }


def _parse_journey(raw) -> dict:
    """
    Person E (Rak)    — base journey fields from JourneyPlanner.
    Person F (Daniel) — adds reliability_score, reliability_band,
                        reliability_explanation via DecisionSupport.
    """
    if isinstance(raw, dict):
        return raw
    return {
        "total_duration_min":      raw.total_duration_min,
        "depart_time":             raw.depart_time,
        "arrive_time":             raw.arrive_time,
        "changes":                 raw.changes,
        "reliability_score":       getattr(raw, "reliability_score",       0),
        "reliability_band":        getattr(raw, "reliability_band",        "Low"),
        "reliability_explanations": getattr(raw, "reliability_explanations", []),
        "legs":                    [_parse_leg(leg) for leg in raw.legs],
    }


# ==========================================
# DEPENDENCY PROVIDERS
#
# Instantiated once per request via FastAPI's DI system.
# Override in tests via app.dependency_overrides to inject fakes
# without touching endpoint logic.
# ==========================================

def get_stop_service() -> StopService:
    return StopService()

def get_journey_planner() -> JourneyPlanner:
    return JourneyPlanner()

def get_decision_support() -> DecisionSupport:
    return DecisionSupport()

def get_cache_service() -> CacheService:
    return CacheService()


# ==========================================
# ENDPOINTS
# Orchestration only — no planning logic, no data access.
# ==========================================

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok"}


@app.get(
    "/status",
    response_model=StatusResponse,
    tags=["System"],
    dependencies=[Depends(rate_limiter)],
)
async def system_status(
    cache_service: CacheService = Depends(get_cache_service),
):
    """
    Returns last-updated timestamps for each data layer.
    Used by the frontend data-freshness banner.
    Depends on: CacheService (Person F / Daniel)
    """
    try:
        freshness = cache_service.get_freshness()
        return StatusResponse(**freshness)
    except CacheUnavailableError:
        raise HTTPException(status_code=503, detail="Cache unavailable")


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
    """
    Stop/station autocomplete search.
    Queries NaPTAN/NPTG data via StopService (Person D / Kamol).
    404 when no stops match — frontend shows a 'no results' message.
    Depends on: StopService (Person D / Kamol)
    """
    # Replace StopService dummy/autocomplete with direct SQLite lookup
    import sqlite3
    from pathlib import Path

    base = Path(__file__).resolve().parents[1]
    db_path = base / "stops.db"
    if not db_path.exists():
        alt = base / "optiroute.db"
        if alt.exists():
            db_path = alt
        else:
            raise HTTPException(status_code=503, detail="Database file not found")

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT atco_code AS id, common_name AS name, latitude AS lat, longitude AS lon FROM stops WHERE common_name LIKE ? LIMIT ?",
            (f"%{query}%", limit),
        )
        rows = cur.fetchall()
        stops = [dict(r) for r in rows]
        if not stops:
            raise HTTPException(status_code=404, detail="No stops found")
        return stops
    except sqlite3.DatabaseError as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.post(
    "/journeys",
    response_model=JourneyResponse,
    tags=["Routing"],
    dependencies=[Depends(rate_limiter)],
)
async def plan_journey(
    request: JourneyRequest,
    sort_by: Literal["time", "reliability"] = Query(
        "time", description="Sort by fastest time or highest reliability"
    ),
    journey_planner: JourneyPlanner = Depends(get_journey_planner),
    decision_support: DecisionSupport = Depends(get_decision_support),
):
    """
    Core journey planning endpoint.
    Validates input, calls JourneyPlanner for route generation,
    passes results to DecisionSupport for reliability annotation,
    then sorts and returns.

    README scope assumption 5: live feed failure is non-blocking.
    If DecisionSupport fails, journeys are returned without reliability
    data and data_quality_flags signals the degraded state to the frontend.

    Depends on:
        JourneyPlanner  (Person E / Rak)    — route generation
        DecisionSupport (Person F / Daniel) — reliability annotation
    """
    if request.origin_id == request.destination_id:
        raise HTTPException(
            status_code=400,
            detail="Origin and destination cannot be identical",
        )

    # Step 1: Generate raw journey options from timetable data
    try:
        # Instantiate planner directly to ensure the real planner implementation is used
        planner = JourneyPlanner()
        raw_journeys = planner.plan(
            origin_id=request.origin_id,
            destination_id=request.destination_id,
            time_type=request.time_type,
            time_iso=request.time_iso,
            modes=request.modes,
            max_options=request.max_options,
        )
    except NoRouteFoundError:
        # Valid stops, but no nearby stops found — treat as no route
        print(f"NoRouteFound: no nearby stops for {request.origin_id} -> {request.destination_id}")
        # Return empty journeys with a clear message in the body (frontend will display)
        return JSONResponse(status_code=200, content={
            "journeys": [],
            "data_quality_flags": [],
            "message": f"No nearby stops found for {request.origin_id} or {request.destination_id}"
        })
    except PlannerError as pe:
        print(f"PlannerError: {pe}")
        raise HTTPException(status_code=503, detail="Journey planning service unavailable")
    except Exception as e:
        # Unexpected error — log and return 500
        print(f"Error while planning journey: {e}")
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    # Step 2: Normalise to dicts regardless of what Person E returned
    journeys = [_parse_journey(j) for j in raw_journeys]
    # Log planner summary
    print(f"Planner called: {request.origin_id} -> {request.destination_id} returned {len(journeys)} journeys")

    # Step 3: Annotate with reliability scores, live data, and quality flags.
    # README assumption 5: live feed failure is non-blocking.
    # DecisionSupportError is treated as non-fatal — journeys return without
    # reliability data, frontend shows a degraded-mode warning via flags.
    try:
        annotated_journeys, flags = decision_support.annotate(journeys)
        # Normalise inside try — journeys already parsed dicts on failure path
        annotated_journeys = [_parse_journey(j) for j in annotated_journeys]
    except DecisionSupportError:
        annotated_journeys = journeys  # already normalised dicts from Step 2
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
            j["reliability_explanations"] = res.explanations

    # Step 4: Sort with tie-breakers per README routing objective:
    #   Primary:   earliest arrival (time) or reliability_score (reliability)
    #   Secondary: fewer changes  (README: "tie-breaker: fewer changes")
    #   Tertiary:  reliability / duration as final tie-breaker
    if sort_by == "time":
        annotated_journeys.sort(
            key=lambda j: (
                j["total_duration_min"],
                j["changes"],
                -j["reliability_score"],    # higher reliability wins tie
            )
        )
    else:
        annotated_journeys.sort(
            key=lambda j: (
                -j["reliability_score"],
                j["changes"],               # fewer changes wins tie
                j["total_duration_min"],    # shorter duration wins final tie
            )
        )

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
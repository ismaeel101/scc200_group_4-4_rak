from fastapi import FastAPI, HTTPException, Query, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import List, Optional, Literal
from datetime import datetime
import time
import sqlite3
import os

from app.data.stops import StopService
from app.domain.planner.planner import JourneyPlanner
from app.domain.decision_support.decision_support import DecisionSupport
from app.cache.cache_service import CacheService

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
    allow_origins=["http://127.0.0.1:5173","http://localhost:5173","http://127.0.0.1:5174","http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

rate_limit_records: dict[str, list[float]] = {}

def rate_limiter(request: Request):
    client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "127.0.0.1")
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

MAX_REQ_SIZE = 1024 * 50

@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_REQ_SIZE:
        return JSONResponse(status_code=413, content={"detail": "Payload Too Large"})
    return await call_next(request)


# ==========================================
# DATA TRANSFER OBJECTS (DTOs)
# ==========================================

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
    available:      bool
    delay_minutes:  int
    disrupted_flag: bool
    source:         str

class Leg(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    mode: Literal["walk", "bus", "rail"]
    from_loc: str = Field(..., alias="from")
    to_loc:   str = Field(..., alias="to")
    depart:   datetime
    arrive:   datetime
    from_lat: Optional[float] = None
    from_lon: Optional[float] = None
    to_lat:   Optional[float] = None
    to_lon:   Optional[float] = None
    operator: Optional[str] = None
    service_id: Optional[str] = None
    live_status: Optional[LiveStatus] = None
    leg_risk_band: Optional[Literal["High", "Medium", "Low"]] = None
    risk_explanation: Optional[List[str]] = None

class Journey(BaseModel):
    total_duration_min: int
    depart_time:        datetime
    arrive_time:        datetime
    changes:            int
    reliability_score:       int = Field(..., ge=0, le=100)
    reliability_band:        Literal["High", "Medium", "Low"]
    reliability_explanation: List[str]
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
# ==========================================

def _parse_live_status(raw) -> Optional[dict]:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    return {
        "available":      raw.available,
        "delay_minutes":  raw.delay_minutes,
        "disrupted_flag": raw.disrupted_flag,
        "source":         raw.source,
    }

def _parse_leg(raw) -> dict:
    if isinstance(raw, dict):
        return {
            "from":             raw.get("from") or getattr(raw, "from_id", None),
            "to":               raw.get("to") or getattr(raw, "to_id", None),
            "mode":             raw.get("mode"),
            "depart":           raw.get("depart"),
            "arrive":           raw.get("arrive"),
            "from_lat":         raw.get("from_lat"),
            "from_lon":         raw.get("from_lon"),
            "to_lat":           raw.get("to_lat"),
            "to_lon":           raw.get("to_lon"),
            "operator":         raw.get("operator", getattr(raw, "operator", None)),
            "service_id":       raw.get("line", raw.get("service_id", getattr(raw, "service_id", None))),
            "live_status":      _parse_live_status(raw.get("live_status", getattr(raw, "live_status", None))),
            "leg_risk_band":    raw.get("leg_risk_band", getattr(raw, "leg_risk_band", None)),
            "risk_explanation": raw.get("risk_explanation", getattr(raw, "risk_explanation", None)),
        }
    
    return {
        "from":             getattr(raw, "from_id", None) or getattr(raw, "from_loc", None),
        "to":               getattr(raw, "to_id", None) or getattr(raw, "to_loc", None),
        "mode":             getattr(raw, "mode", None),
        "depart":           getattr(raw, "depart_time", getattr(raw, "depart", None)),
        "arrive":           getattr(raw, "arrive_time", getattr(raw, "arrive", None)),
        "operator":         getattr(raw, "operator", None),
        "service_id":       getattr(raw, "service_id", None),
        "live_status":      _parse_live_status(getattr(raw, "live_status", None)),
        "leg_risk_band":    getattr(raw, "leg_risk_band", None),
        "risk_explanation": getattr(raw, "risk_explanation", None),
    }

def _parse_journey(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    return {
        "total_duration_min":      raw.total_duration_min,
        "depart_time":             raw.depart_time,
        "arrive_time":             raw.arrive_time,
        "changes":                 raw.changes,
        "reliability_score":       getattr(raw, "reliability_score", 0),
        "reliability_band":        getattr(raw, "reliability_band", "Low"),
        "reliability_explanation": getattr(raw, "reliability_explanation", []),
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


# ==========================================
# ENDPOINTS
# ==========================================

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok"}

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
    db_path = "/workspace/backend/stops.db"
    if not os.path.exists(db_path):
        raise HTTPException(status_code=503, detail="Database file not found")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """
            SELECT atco_code AS id, common_name AS name, latitude AS lat, longitude AS lon,
            CASE WHEN stop_type IN ('RLY', 'RSE', 'TMU', 'MET') THEN 'rail' ELSE 'bus' END as type
            FROM stops 
            WHERE latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ? LIMIT ?
            """,
            (min_lat, max_lat, min_lon, max_lon, limit),
        )
        return [dict(r) for r in cur.fetchall()]
    except sqlite3.DatabaseError as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.get("/api/routable-stops", tags=["Search"], dependencies=[Depends(rate_limiter)])
async def api_routable_stops():
    bus_db_path = "/workspace/backend/bus.db"
    rail_db_path = "/workspace/backend/rail.db"

    routable_ids = set()

    # 1. Extract Bus Stops
    if os.path.exists(bus_db_path):
        try:
            conn = sqlite3.connect(bus_db_path)
            cur = conn.execute("SELECT DISTINCT stop_id FROM stop_times")
            routable_ids.update(r[0] for r in cur.fetchall() if r and r[0])
            conn.close()
        except sqlite3.DatabaseError as e:
            print(f"Bus DB read error: {e}")

    # 2. Extract Rail Stations
    if os.path.exists(rail_db_path):
        try:
            conn = sqlite3.connect(rail_db_path)
            # tiploc is the primary id for rail stations in the schedules
            cur = conn.execute("SELECT DISTINCT tiploc FROM schedules")
            rail_ids = [r[0] for r in cur.fetchall() if r and r[0]]
            routable_ids.update(rail_ids)
            
            # Planner.py occasionally wraps rail IDs in 'RAIL:' prefix
            routable_ids.update(f"RAIL:{r}" for r in rail_ids)
            conn.close()
        except sqlite3.DatabaseError as e:
            print(f"Rail DB read error: {e}")

    if not routable_ids:
         raise HTTPException(status_code=503, detail="No routable databases found")

    return {"ids": list(routable_ids)}

@app.get("/stops", response_model=List[StopResponse], tags=["Search"], dependencies=[Depends(rate_limiter)])
async def get_stops(
    query: str = Query(..., min_length=2),
    limit: int = Query(10, ge=1, le=50),
    stop_service: StopService = Depends(get_stop_service),
):
    db_path = "/workspace/backend/stops.db"
    if not os.path.exists(db_path):
        raise HTTPException(status_code=503, detail="Database file not found")

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT atco_code AS id, common_name AS name, latitude AS lat, longitude AS lon, 
            CASE WHEN stop_type IN ('RLY', 'RSE', 'TMU', 'MET') THEN 'rail' ELSE 'bus' END as type 
            FROM stops WHERE common_name LIKE ? LIMIT ?
            """,
            (f"%{query}%", limit),
        )
        stops = [dict(r) for r in cur.fetchall()]
        if not stops:
            raise HTTPException(status_code=404, detail="No stops found")
        return stops
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
        return JSONResponse(status_code=200, content={
            "journeys": [],
            "data_quality_flags": [],
            "message": f"No nearby routes found connecting {request.origin_id} and {request.destination_id}"
        })
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

    if sort_by == "time":
        annotated_journeys.sort(key=lambda j: (j["total_duration_min"], j["changes"], -j["reliability_score"]))
    else:
        annotated_journeys.sort(key=lambda j: (-j["reliability_score"], j["changes"], j["total_duration_min"]))

    return JourneyResponse(journeys=annotated_journeys, data_quality_flags=flags)
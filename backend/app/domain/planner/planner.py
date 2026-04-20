from __future__ import annotations

from pathlib import Path
import sqlite3
import math
import time
import heapq

from datetime import datetime, timedelta
from typing import Optional

from .exceptions import NoRouteFoundError
from .models import Journey, Leg, Mode
from .providers import StopInfo

# walking constants
WALK_MAX_METERS = 800
WALKING_SPEED_MPS = 1.4
WALK_TRANSFER_MAX_M = 1200  # max walk between stops at a transfer (metres) — covers ~15 min walk

# human-behaviour transfer constants
MIN_TRANSFER_WAIT_BUS_SECS  = 120   # 2 min minimum wait after arriving by bus
MIN_TRANSFER_WAIT_RAIL_SECS = 300   # 5 min minimum wait after arriving by train
CHANGE_TIME_SAVING_THRESHOLD_SECS = 600   # a change must save >=10 min vs direct to justify it
MAX_WALK_TRANSFER_SECS = int(WALK_TRANSFER_MAX_M / WALKING_SPEED_MPS)  # ~857 s ≈ 14 min walk


class JourneyPlanner:
    """
    Timetable-backed JourneyPlanner implementing multi-leg search with
    walking catchments, direct trips and a bounded earliest-arrival search.

    Also contains a provider-based compatibility path so older provider-based
    unit tests can still instantiate:

        Planner(provider).plan(request)

    while the real app can still use the DB-backed path:

        JourneyPlanner().plan(origin_id=..., destination_id=..., ...)
    """

    def __init__(self, provider=None):
        self.provider = provider
        _project_root = Path(__file__).resolve().parents[3]
        self.DB = _project_root / "stops.db"
        self.BUS_DB = _project_root / "bus.db"
        self.RAIL_DB = _project_root / "rail.db"

    def _parse_iso(self, s):
        if isinstance(s, datetime):
            return s
        try:
            return datetime.fromisoformat(s)
        except Exception:
            try:
                return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
            except Exception:
                return None

    def _parse_time_to_dt(self, time_str, base_dt):
        if not time_str or str(time_str).strip().lower() == "none":
            return None
        try:
            if "T" in time_str:
                return datetime.fromisoformat(time_str)
        except Exception:
            pass

        # Handle CIF rail format: HHMM or HHMMH (H = half-minute)
        raw = str(time_str).strip()
        half = raw.endswith("H")
        if half:
            raw = raw[:-1]

        if len(raw) == 4 and raw.isdigit() and ":" not in raw:
            raw = raw[:2] + ":" + raw[2:]

        try:
            fmt = "%H:%M:%S" if raw.count(":") == 2 else "%H:%M"
            t = datetime.strptime(raw, fmt).time()
            dt = datetime.combine(base_dt.date(), t)
            if half:
                dt = dt + timedelta(seconds=30)
            if dt < base_dt - timedelta(hours=12):
                dt = dt + timedelta(days=1)
            return dt
        except Exception:
            try:
                return datetime.fromisoformat(time_str)
            except Exception:
                return None

    def _window_contains(self, dt, window_start, window_end):
        if dt is None:
            return False
        if window_start is not None and dt < window_start:
            return False
        if window_end is not None and dt > window_end:
            return False
        return True

    def _haversine_m(self, lat1, lon1, lat2, lon2):
        R = 6371000.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def _get_stop_name(self, conn, stop_id):
        try:
            cur = conn.execute("SELECT common_name AS name FROM stops WHERE atco_code=?", (stop_id,))
            r = cur.fetchone()
            if r and r[0]:
                return r[0]
        except Exception:
            pass

        try:
            cur = conn.execute("SELECT common_name AS name FROM bus.bus_stops WHERE atco_code=?", (stop_id,))
            r = cur.fetchone()
            if r and r[0]:
                return r[0]
        except Exception:
            pass

        try:
            cur = conn.execute("SELECT common_name FROM bus.stop_points WHERE atco_code=?", (stop_id,))
            r = cur.fetchone()
            if r and r[0]:
                return r[0]
        except Exception:
            pass

        return stop_id

    def _get_line_name(self, conn, trip_id, _cache={}):
        if trip_id in _cache:
            return _cache[trip_id]
        try:
            r = conn.execute(
                "SELECT s.line_name FROM bus.trips t JOIN bus.services s ON t.service_id=s.id WHERE t.id=? LIMIT 1",
                (trip_id,)
            ).fetchone()
            if r and r[0]:
                _cache[trip_id] = r[0]
                return r[0]
        except Exception:
            pass
        _cache[trip_id] = None
        return None

    def _resolve_stop(self, conn, stop_id):
        try:
            r = conn.execute(
                "SELECT atco_code AS id, common_name AS name, latitude AS lat, longitude AS lon "
                "FROM stops WHERE atco_code=? LIMIT 1",
                (stop_id,),
            ).fetchone()
            if r:
                return {"id": r["id"], "name": r["name"], "lat": r["lat"], "lon": r["lon"]}
        except Exception:
            pass

        try:
            r = conn.execute(
                "SELECT atco_code AS id, common_name AS name, latitude AS lat, longitude AS lon "
                "FROM bus.bus_stops WHERE atco_code=? LIMIT 1",
                (stop_id,),
            ).fetchone()
            if r:
                return {"id": r["id"], "name": r["name"], "lat": r["lat"], "lon": r["lon"]}
        except Exception:
            pass

        return None

    def _compute_reliability(self, legs, duration_min, conn, is_adverse_weather=False):
        score = 100
        explanation = []
        changes = max(0, len([l for l in legs if l.get("mode") != "walk"]) - 1) if legs else 0
        score -= 10 * changes
        if changes > 0:
            explanation.append(f"{changes} transfer(s) -10")
        if duration_min > 60:
            score -= 5
            explanation.append("Long journey >60min -5")

        delayed = False
        for leg in legs:
            if leg.get("mode") == "rail":
                try:
                    from_name = leg.get("from")
                    cur = conn.execute(
                        "SELECT is_delayed FROM rail_departures WHERE station=? LIMIT 1",
                        (from_name,),
                    )
                    r = cur.fetchone()
                    if r and r[0]:
                        delayed = True
                except Exception:
                    pass

        if delayed:
            score -= 10
            explanation.append("Rail delay reported -10")

        # Weather penalty
        if is_adverse_weather:
            score -= 10
            explanation.append("Adverse weather conditions -10")

        score = max(0, min(100, score))
        if score >= 80:
            band = "High"
        elif score >= 50:
            band = "Medium"
        else:
            band = "Low"

        return score, band, explanation

    def _catchment_stops(self, conn, lat, lon, meters=800):
        lat_delta = meters / 111320.0
        lon_delta = meters / (111320.0 * math.cos(math.radians(lat)) if math.cos(math.radians(lat)) != 0 else 1)
        min_lat = lat - lat_delta
        max_lat = lat + lat_delta
        min_lon = lon - lon_delta
        max_lon = lon + lon_delta

        seen_ids: set[str] = set()
        out = []

        cur = conn.execute(
            """
            SELECT atco_code AS id, common_name AS name, latitude AS lat, longitude AS lon
            FROM stops
            WHERE latitude IS NOT NULL
              AND longitude IS NOT NULL
              AND latitude != 0
              AND longitude != 0
              AND latitude BETWEEN ? AND ?
              AND longitude BETWEEN ? AND ?
            """,
            (min_lat, max_lat, min_lon, max_lon),
        )
        for r in cur.fetchall():
            try:
                dist = self._haversine_m(lat, lon, float(r[2]), float(r[3]))
            except Exception:
                continue
            if dist <= meters:
                out.append(
                    {
                        "id": r[0],
                        "name": r[1],
                        "lat": float(r[2]),
                        "lon": float(r[3]),
                        "distance_m": dist,
                    }
                )
                seen_ids.add(r[0])

        try:
            cur2 = conn.execute(
                """
                SELECT atco_code AS id, common_name AS name, latitude AS lat, longitude AS lon
                FROM bus.bus_stops
                WHERE latitude IS NOT NULL
                  AND longitude IS NOT NULL
                  AND latitude != 0
                  AND longitude != 0
                  AND latitude BETWEEN ? AND ?
                  AND longitude BETWEEN ? AND ?
                """,
                (min_lat, max_lat, min_lon, max_lon),
            )
            for r in cur2.fetchall():
                if r[0] in seen_ids:
                    continue
                try:
                    dist = self._haversine_m(lat, lon, float(r[2]), float(r[3]))
                except Exception:
                    continue
                if dist <= meters:
                    out.append(
                        {
                            "id": r[0],
                            "name": r[1],
                            "lat": float(r[2]),
                            "lon": float(r[3]),
                            "distance_m": dist,
                        }
                    )
                    seen_ids.add(r[0])
        except Exception:
            pass

        out.sort(key=lambda x: (x["distance_m"], x["id"]))
        return out

    def _walk_leg_dict(self, from_name, to_name, depart_dt, arrive_dt, from_lat=None, from_lon=None, to_lat=None, to_lon=None):
        return {
            "mode": "walk",
            "from": from_name,
            "to": to_name,
            "depart": depart_dt.isoformat(),
            "arrive": arrive_dt.isoformat(),
            "from_lat": from_lat,
            "from_lon": from_lon,
            "to_lat": to_lat,
            "to_lon": to_lon,
        }

    def _vehicle_leg_dict(self, mode, from_name, to_name, depart_dt, arrive_dt, line=None, from_lat=None, from_lon=None, to_lat=None, to_lon=None, service_id=None, from_seq=None, to_seq=None):
        return {
            "mode": mode,
            "line": line or "",
            "from": from_name,
            "to": to_name,
            "depart": depart_dt.isoformat(),
            "arrive": arrive_dt.isoformat(),
            "from_lat": from_lat,
            "from_lon": from_lon,
            "to_lat": to_lat,
            "to_lon": to_lon,
            "service_id": service_id,
            "from_seq": from_seq,
            "to_seq": to_seq,
        }

    def _get_rail_candidates_from_stop(
        self,
        conn,
        stop_id,
        current_time,
        requested_dt,
        enforce_window=False,
        window_start=None,
        window_end=None,
        downstream_limit=10,
    ):
        """
        Return candidate rail legs starting from stop_id.

        Planner rail stop ids may look like:
          - "RAIL:LNS"
          - "RAIL:PRE"
          - "9100PRST"

        rail.schedules.tiploc stores the TIPLOC code.
        """
        candidates = []

        tiploc = stop_id
        if isinstance(stop_id, str) and stop_id.startswith("RAIL:"):
            code = stop_id.split(":", 1)[1]
            try:
                row = conn.execute(
                    "SELECT tiploc FROM rail.stations WHERE tiploc=? OR crs=? LIMIT 1",
                    (code, code),
                ).fetchone()
                if row:
                    tiploc = row[0]
                else:
                    tiploc = code
            except Exception:
                tiploc = code
        elif isinstance(stop_id, str) and stop_id.startswith("9100"):
            tiploc = stop_id[4:]

        if tiploc == stop_id:
            try:
                row = conn.execute(
                    "SELECT crs_code FROM stops WHERE atco_code=? LIMIT 1",
                    (stop_id,),
                ).fetchone()
                if row and row[0]:
                    r2 = conn.execute(
                        "SELECT tiploc FROM rail.stations WHERE crs=? LIMIT 1",
                        (row[0],),
                    ).fetchone()
                    if r2:
                        tiploc = r2[0]
                    else:
                        tiploc = row[0]
            except Exception:
                pass

        dep_lower = f"{current_time.hour:02d}{current_time.minute:02d}"

        try:
            cur = conn.execute(
                """
                SELECT train_uid, seq, departure
                FROM rail.schedules
                WHERE tiploc = ?
                  AND departure IS NOT NULL
                  AND departure != ''
                  AND REPLACE(departure, 'H', '') >= ?
                ORDER BY departure, train_uid, seq
                LIMIT 100
                """,
                (tiploc, dep_lower),
            )
            rows = cur.fetchall()
        except Exception:
            return candidates

        if not rows:
            try:
                cur = conn.execute(
                    """
                    SELECT train_uid, seq, departure
                    FROM rail.schedules
                    WHERE tiploc = ?
                      AND departure IS NOT NULL
                      AND departure != ''
                    ORDER BY departure, train_uid, seq
                    LIMIT 50
                    """,
                    (tiploc,),
                )
                rows = cur.fetchall()
            except Exception:
                return candidates

        for row in rows:
            depart_dt = self._parse_time_to_dt(row["departure"], requested_dt)
            if not depart_dt:
                continue
            if depart_dt < current_time:
                continue
            if enforce_window and not self._window_contains(depart_dt, window_start, window_end):
                continue

            try:
                downstream = conn.execute(
                    """
                    SELECT tiploc, seq, arrival, departure
                    FROM rail.schedules
                    WHERE train_uid = ?
                      AND seq > ?
                    ORDER BY seq
                    LIMIT ?
                    """,
                    (row["train_uid"], row["seq"], downstream_limit),
                ).fetchall()
            except Exception:
                continue

            for ds in downstream:
                ds_tiploc = ds["tiploc"]
                if ds_tiploc == tiploc:
                    continue

                arrive_raw = ds["arrival"] if ds["arrival"] else ds["departure"]
                arrive_dt = self._parse_time_to_dt(arrive_raw, depart_dt)
                if not arrive_dt or arrive_dt <= depart_dt:
                    continue

                ds_row = conn.execute(
                    """
                    SELECT atco_code AS id, common_name AS name, latitude AS lat, longitude AS lon
                    FROM stops
                    WHERE atco_code IN (?, ?)
                       OR crs_code=?
                    ORDER BY CASE WHEN atco_code=? THEN 0
                                  WHEN atco_code=? THEN 1
                                  ELSE 2 END
                    LIMIT 1
                    """,
                    (f"RAIL:{ds_tiploc}", f"9100{ds_tiploc}", ds_tiploc,
                     f"RAIL:{ds_tiploc}", f"9100{ds_tiploc}"),
                ).fetchone()

                if ds_row:
                    ds_id = ds_row["id"]
                    ds_name = ds_row["name"]
                    try:
                        ds_lat = float(ds_row["lat"]) if ds_row["lat"] is not None else None
                        ds_lon = float(ds_row["lon"]) if ds_row["lon"] is not None else None
                    except Exception:
                        ds_lat = None
                        ds_lon = None
                else:
                    ds_id = f"RAIL:{ds_tiploc}"
                    ds_name = ds_tiploc
                    ds_lat = None
                    ds_lon = None

                candidates.append(
                    {
                        "to_stop_id": ds_id,
                        "to_stop_name": ds_name,
                        "depart_dt": depart_dt,
                        "arrive_dt": arrive_dt,
                        "trip_id": row["train_uid"],
                        "from_seq": row["seq"],
                        "to_seq": ds["seq"],
                        "to_lat": ds_lat,
                        "to_lon": ds_lon,
                    }
                )

        # Sort by arrival time first — always prefer the train that gets there fastest,
        # even if it departs slightly later (e.g. fast express vs slow stopper)
        candidates.sort(
            key=lambda x: (
                x["arrive_dt"],
                x["depart_dt"],
                str(x["trip_id"]),
                str(x["to_stop_id"]),
            )
        )

        # Deduplicate: keep only the fastest-arriving train per destination stop
        seen_dst = {}
        deduped = []
        for c in candidates:
            dst = c["to_stop_id"]
            if dst not in seen_dst:
                seen_dst[dst] = c
                deduped.append(c)
            else:
                # Replace if this arrives earlier
                if c["arrive_dt"] < seen_dst[dst]["arrive_dt"]:
                    seen_dst[dst] = c
                    deduped = [x for x in deduped if x["to_stop_id"] != dst]
                    deduped.append(c)

        deduped.sort(key=lambda x: (x["arrive_dt"], x["depart_dt"]))
        return deduped

    def _journey_sort_key(self, j):
        arrive = self._parse_iso(j.get("arrive_time")) or datetime.max
        changes = j.get("changes", 0)
        # Each change adds a 10-min penalty to the effective arrival time.
        # This means a 1-change journey must arrive >10 min earlier than a
        # direct to be ranked above it — matching human decision-making.
        penalty = timedelta(minutes=10 * changes)
        effective_arrive = arrive + penalty
        return (
            effective_arrive,
            arrive,
            changes,
            tuple(
                (
                    leg.get("mode", ""),
                    leg.get("from", ""),
                    leg.get("to", ""),
                    leg.get("depart", ""),
                    leg.get("arrive", ""),
                    leg.get("line", ""),
                )
                for leg in j.get("legs", [])
            ),
        )

    def _round_time_bucket(self, value, minutes=5):
        dt = self._parse_iso(value) if not isinstance(value, datetime) else value
        if dt is None:
            return None
        bucket_minute = (dt.minute // minutes) * minutes
        return dt.replace(minute=bucket_minute, second=0, microsecond=0).isoformat()

    def _journey_alternative_signature(self, journey):
        legs = journey.get("legs", [])
        vehicle_legs = [leg for leg in legs if leg.get("mode") != "walk"]

        if not vehicle_legs:
            return tuple()

        first_vehicle = vehicle_legs[0]
        last_vehicle = vehicle_legs[-1]

        transfer_points = []
        for i in range(len(vehicle_legs) - 1):
            transfer_points.append(vehicle_legs[i].get("to"))

        return (
            tuple((leg.get("mode"), leg.get("line") or "") for leg in vehicle_legs),
            first_vehicle.get("from"),
            last_vehicle.get("to"),
            tuple(transfer_points),
            self._round_time_bucket(first_vehicle.get("depart"), minutes=5),
            self._round_time_bucket(last_vehicle.get("arrive"), minutes=5),
        )

    def _select_distinct_journeys(self, journeys, max_options):
        journeys = sorted(journeys, key=self._journey_sort_key)

        best_per_signature = {}
        for journey in journeys:
            sig = self._journey_alternative_signature(journey)
            if sig not in best_per_signature:
                best_per_signature[sig] = journey

        selected = list(best_per_signature.values())
        selected.sort(key=self._journey_sort_key)
        return selected[:max_options]

    # ---------------------------
    # Provider-based compatibility
    # ---------------------------

    def _walk_leg_object(self, from_id, to_id, depart_time, arrive_time):
        return Leg(
            mode=Mode.WALK,
            from_id=from_id,
            to_id=to_id,
            depart_time=depart_time,
            arrive_time=arrive_time,
            operator=None,
            service_id=None,
        )

    def _vehicle_leg_object(self, row):
        mode = Mode.RAIL if getattr(row.from_id, "kind", "") == "RAIL" else Mode.BUS
        return Leg(
            mode=mode,
            from_id=row.from_id,
            to_id=row.to_id,
            depart_time=row.depart_time,
            arrive_time=row.arrive_time,
            operator=row.operator,
            service_id=row.service_id,
        )

    def _journey_from_legs(self, legs):
        vehicle_legs = [l for l in legs if l.mode != Mode.WALK]
        return Journey(
            legs=tuple(legs),
            depart_time=legs[0].depart_time,
            arrive_time=legs[-1].arrive_time,
            changes=max(0, len(vehicle_legs) - 1),
        )

    def _provider_distance_ok(self, a: Optional[StopInfo], b: Optional[StopInfo], max_distance_m: float) -> bool:
        if a is None or b is None:
            return False
        if a.stop_group_id and b.stop_group_id and a.stop_group_id == b.stop_group_id:
            return True
        dist = self._haversine_m(a.lat, a.lon, b.lat, b.lon)
        return dist <= max_distance_m

    def _provider_walk_minutes(self, a: StopInfo, b: StopInfo) -> int:
        dist = self._haversine_m(a.lat, a.lon, b.lat, b.lon)
        return max(1, int(math.ceil(dist / WALKING_SPEED_MPS / 60.0)))

    def _plan_with_provider(self, request):
        provider = self.provider
        if provider is None:
            return []

        origin = request.origin
        destination = request.destination
        depart_at = request.time
        max_options = request.max_options

        journeys = []

        direct_rows = provider.get_direct_rows(origin, destination, depart_at, max_results=max_options)
        for row in direct_rows:
            journeys.append(self._journey_from_legs([self._vehicle_leg_object(row)]))

        if journeys:
            journeys.sort(key=lambda j: (j.arrive_time, j.depart_time, j.changes))
            return journeys[:max_options]

        first_rows = provider.get_rows_from(origin, depart_at)
        for first in first_rows:
            second_rows = provider.get_direct_rows(first.to_id, destination, first.arrive_time, max_results=max_options)
            for second in second_rows:
                if second.depart_time >= first.arrive_time:
                    legs = [self._vehicle_leg_object(first), self._vehicle_leg_object(second)]
                    journeys.append(self._journey_from_legs(legs))

        for first in first_rows:
            walkable = provider.get_walkable_stops(first.to_id, max_distance_m=WALK_TRANSFER_MAX_M)
            first_stop_info = provider.get_stop_info(first.to_id)
            for walked_stop in walkable:
                if first_stop_info is None:
                    continue

                walk_minutes = self._provider_walk_minutes(first_stop_info, walked_stop)
                walk_depart = first.arrive_time
                walk_arrive = first.arrive_time + timedelta(minutes=walk_minutes)

                second_rows = provider.get_direct_rows(walked_stop.place_id, destination, walk_arrive, max_results=max_options)
                for second in second_rows:
                    if second.depart_time >= walk_arrive:
                        legs = [
                            self._vehicle_leg_object(first),
                            self._walk_leg_object(first.to_id, walked_stop.place_id, walk_depart, walk_arrive),
                            self._vehicle_leg_object(second),
                        ]
                        journeys.append(self._journey_from_legs(legs))

        unique = []
        seen = set()
        for j in journeys:
            key = tuple(
                (
                    leg.mode.value if hasattr(leg.mode, "value") else str(leg.mode),
                    getattr(leg.from_id, "value", str(leg.from_id)),
                    getattr(leg.to_id, "value", str(leg.to_id)),
                    leg.depart_time.isoformat(),
                    leg.arrive_time.isoformat(),
                    leg.service_id or "",
                )
                for leg in j.legs
            )
            if key not in seen:
                seen.add(key)
                unique.append(j)

        unique.sort(key=lambda j: (j.arrive_time, j.depart_time, j.changes))
        return unique[:max_options]

    # ---------------------------
    # Main public method
    # ---------------------------

    def plan(self, origin_id=None, destination_id=None, time_type=None, time_iso=None, modes=None, max_options=None, is_adverse_weather=False):
        if (
            self.provider is not None
            and origin_id is not None
            and destination_id is None
            and hasattr(origin_id, "origin")
            and hasattr(origin_id, "destination")
        ):
            return self._plan_with_provider(origin_id)

        requested_dt = self._parse_iso(time_iso)
        if requested_dt is not None and requested_dt.tzinfo is not None:
            import datetime
            requested_dt = requested_dt.replace(tzinfo=None)
        if requested_dt is None:
            requested_dt = datetime.now()

        if max_options is None:
            max_options = 5

        use_bus = modes in ("bus", "mixed")
        use_rail = modes in ("rail", "mixed")

        conn = sqlite3.connect(str(self.DB))
        conn.row_factory = sqlite3.Row

        try:
            conn.execute(f"ATTACH DATABASE '{self.BUS_DB}' AS bus")
        except Exception:
            pass
        try:
            conn.execute(f"ATTACH DATABASE '{self.RAIL_DB}' AS rail")
        except Exception:
            pass

        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_stops_atco ON stops(atco_code)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_stops_crs ON stops(crs_code)")
            conn.commit()
        except Exception:
            pass

        # Indexes are pre-built - skip creation to avoid locking

        start_time = time.time()

        def check_timeout():
            if time.time() - start_time > 30:
                try:
                    conn.close()
                except Exception:
                    pass
                raise NoRouteFoundError("Search timeout")

        # Per-call caches — keyed dicts passed to helper calls to avoid
        # repeated SQLite queries for the same stop IDs across 5000 heap states
        _resolve_cache: dict = {}
        _catchment_cache: dict = {}

        def _resolve(stop_id):
            if stop_id not in _resolve_cache:
                _resolve_cache[stop_id] = self._resolve_stop(conn, stop_id)
            return _resolve_cache[stop_id]

        def _catchment(lat, lon, meters=800):
            key = (round(lat, 4), round(lon, 4), meters)
            if key not in _catchment_cache:
                _catchment_cache[key] = self._catchment_stops(conn, lat, lon, meters)
            return _catchment_cache[key]

        orow = _resolve(origin_id)
        if not orow:
            conn.close()
            raise NoRouteFoundError(
                f"Origin stop {origin_id} not found in stops or bus_stops. "
                "The stop ID from the timetable cannot be resolved to metadata. "
                "Ensure merge_stops.py has been run after loading timetables."
            )
        origin_lat = float(orow["lat"]) if orow["lat"] is not None else None
        origin_lon = float(orow["lon"]) if orow["lon"] is not None else None
        origin_name = orow["name"]

        drow = _resolve(destination_id)
        if not drow:
            conn.close()
            raise NoRouteFoundError(
                f"Destination stop {destination_id} not found in stops or bus_stops. "
                "The stop ID from the timetable cannot be resolved to metadata. "
                "Ensure merge_stops.py has been run after loading timetables."
            )
        dest_lat = float(drow["lat"]) if drow["lat"] is not None else None
        dest_lon = float(drow["lon"]) if drow["lon"] is not None else None
        dest_name = drow["name"]

        radii = [500, 1000]
        window_hours_attempts = [3, 6, 12, None]

        def _placeholder_dt():
            today = datetime.now()
            return datetime(today.year, today.month, today.day, 9, 0, 0)

        def _safe_parse(dt_str):
            if not dt_str:
                return _placeholder_dt()
            parsed = self._parse_time_to_dt(dt_str, requested_dt)
            return parsed or _placeholder_dt()

        if origin_lat is not None and origin_lon is not None:
            origin_catch = _catchment(origin_lat, origin_lon, meters=radii[0])
        else:
            origin_catch = [{"id": origin_id, "name": origin_name, "lat": origin_lat, "lon": origin_lon, "distance_m": 0.0}]
        if dest_lat is not None and dest_lon is not None:
            dest_catch = _catchment(dest_lat, dest_lon, meters=radii[0])
        else:
            dest_catch = [{"id": destination_id, "name": dest_name, "lat": dest_lat, "lon": dest_lon, "distance_m": 0.0}]

        journeys = []


        # --- Targeted bus->rail search (fast, no heap) ---
        if use_bus and use_rail and origin_lat and origin_lon and dest_lat and dest_lon:
            try:
                # Look back 10 min to catch buses already in service
                lookback_dt = requested_dt - timedelta(minutes=10)
                dep_str = f"{lookback_dt.hour:02d}:{lookback_dt.minute:02d}:00"
                origin_catch = _catchment(origin_lat, origin_lon, 500)
                origin_stop_ids = [s["id"] for s in origin_catch]
                dest_stop_ids = set(s["id"] for s in _catchment(dest_lat, dest_lon, 800))
                dest_stop_ids.add(destination_id)

                if origin_stop_ids:
                    q = ",".join("?" * len(origin_stop_ids))

                    # Query origin stop first to prioritise trips that serve it directly
                    # Then supplement with catchment stops for nearby alternatives
                    bus_trips_origin = conn.execute("""
                        SELECT DISTINCT st.trip_id, st.stop_id, st.sequence, st.departure_time,
                               s.line_name
                        FROM bus.stop_times st
                        JOIN bus.trips t ON st.trip_id = t.id
                        JOIN bus.services s ON t.service_id = s.id
                        WHERE st.stop_id = ?
                        AND st.departure_time >= ?
                        ORDER BY st.departure_time LIMIT 40
                    """, (origin_stop_ids[0], dep_str)).fetchall()

                    bus_trips_catch = conn.execute(f"""
                        SELECT DISTINCT st.trip_id, st.stop_id, st.sequence, st.departure_time,
                               s.line_name
                        FROM bus.stop_times st
                        JOIN bus.trips t ON st.trip_id = t.id
                        JOIN bus.services s ON t.service_id = s.id
                        WHERE st.stop_id IN ({q})
                        AND st.departure_time >= ?
                        ORDER BY st.departure_time LIMIT 80
                    """, tuple(origin_stop_ids) + (dep_str,)).fetchall()

                    # Merge: origin trips first, then catchment
                    bus_trips = bus_trips_origin + [r for r in bus_trips_catch
                                                    if r["trip_id"] not in {x["trip_id"] for x in bus_trips_origin}]

                    # Build trip_ids: prioritise trips serving exact origin stop first,
                    # then add other catchment trips sorted by departure time
                    origin_exact_trip_ids = []
                    seen = set()
                    for r in sorted(bus_trips_origin, key=lambda r: (r["departure_time"], r["trip_id"])):
                        if r["trip_id"] not in seen:
                            seen.add(r["trip_id"])
                            origin_exact_trip_ids.append(r["trip_id"])

                    other_trip_ids = []
                    for r in sorted(bus_trips_catch, key=lambda r: (r["departure_time"], r["trip_id"])):
                        if r["trip_id"] not in seen:
                            seen.add(r["trip_id"])
                            other_trip_ids.append(r["trip_id"])

                    trip_ids = (origin_exact_trip_ids + other_trip_ids)[:30]

                    # Build all downstream stop IDs for these trips
                    ph = ",".join("?" * len(trip_ids))
                    all_stop_ids = [r["stop_id"] for r in conn.execute(
                        f"SELECT DISTINCT stop_id FROM bus.stop_times WHERE trip_id IN ({ph})",
                        trip_ids
                    ).fetchall()]

                    # Build rail_interchange map once
                    rail_interchange = {}
                    for sid in all_stop_ids:
                        sr = _resolve(sid)
                        if not sr or sr.get("lat") is None or sr.get("lon") is None:
                            continue
                        nearby = _catchment(float(sr["lat"]), float(sr["lon"]), WALK_TRANSFER_MAX_M)
                        rail_near = [n for n in nearby
                                    if n["id"].startswith("RAIL:") or n["id"].startswith("9100")]
                        if rail_near:
                            rail_interchange[sid] = rail_near

                    trip_origins = {}
                    for r in bus_trips:
                        trip_origins.setdefault(r["trip_id"], []).append(r)

                    journey_dedup = {}  # line_name -> (arrive_dt, journey)

                    for trip_id in trip_ids:
                        o_rows = trip_origins.get(trip_id, [])
                        if not o_rows:
                            continue

                        line_name = self._get_line_name(conn, trip_id) or o_rows[0]["line_name"]

                        # Direction check: does any downstream rail-interchange stop
                        # exist at all? If yes, the bus is going the right way.
                        # (The 800m walk cap in best_ds loop already filters nonsense)
                        # No expensive per-stop catchment here — just use rail_interchange.

                        # Pick boarding stop: prefer exact origin stop, then closest
                        exact_origin = [r for r in o_rows if r["stop_id"] == origin_stop_ids[0]]
                        if exact_origin:
                            best_o = min(exact_origin, key=lambda r: r["sequence"])
                        else:
                            def _walk(r):
                                sr = _resolve(r["stop_id"])
                                if not sr or not sr.get("lat"): return 9999
                                return self._haversine_m(origin_lat, origin_lon,
                                    float(sr["lat"]), float(sr["lon"]))
                            best_o = min(o_rows, key=lambda r: (_walk(r), r["sequence"]))
                        board_stop_id = best_o["stop_id"]
                        board_seq = best_o["sequence"]

                        # Get downstream stops
                        downstream = conn.execute("""
                            SELECT stop_id, sequence, departure_time
                            FROM bus.stop_times
                            WHERE trip_id=? AND sequence > ?
                            ORDER BY sequence
                        """, (trip_id, board_seq)).fetchall()

                        # Find furthest downstream stop with rail nearby
                        # Cap to 45 min of bus travel to avoid picking up wrong-city stations
                        best_ds = None
                        best_ds_rail = None
                        for ds in downstream:
                            if ds["stop_id"] not in rail_interchange:
                                continue
                            cand_rail = min(rail_interchange[ds["stop_id"]], key=lambda x: x["distance_m"])
                            if cand_rail["distance_m"] > 800:
                                continue
                            # Bus must not travel more than 45 min from boarding stop
                            ds_dt = _safe_parse(ds["departure_time"])
                            board_dt_tmp = _safe_parse(best_o["departure_time"])
                            if ds_dt and board_dt_tmp:
                                if (ds_dt - board_dt_tmp).total_seconds() > 2700:  # 45 min
                                    continue
                            best_ds = ds
                            best_ds_rail = rail_interchange[ds["stop_id"]]

                        if not best_ds or not best_ds_rail:
                            continue

                        board_r = _resolve(board_stop_id)
                        ds_r = _resolve(best_ds["stop_id"])
                        if not board_r or not ds_r:
                            continue

                        depart_dt = _safe_parse(best_o["departure_time"])
                        bus_arr = _safe_parse(best_ds["departure_time"])
                        if not depart_dt or not bus_arr or bus_arr <= depart_dt:
                            continue
                        # Human gate: bus must travel at least 1 minute before alighting
                        if (bus_arr - depart_dt).total_seconds() < 60:
                            continue

                        # Use closest rail stop
                        rail_stop = min(best_ds_rail, key=lambda x: x["distance_m"])
                        walk_m = rail_stop["distance_m"]
                        walk_secs = walk_m / WALKING_SPEED_MPS
                        rail_arr = (bus_arr + timedelta(seconds=walk_secs)).replace(microsecond=0)
                        board_rail_dt = rail_arr + timedelta(seconds=MIN_TRANSFER_WAIT_RAIL_SECS)

                        rail_cands = self._get_rail_candidates_from_stop(
                            conn=conn, stop_id=rail_stop["id"],
                            current_time=board_rail_dt, requested_dt=requested_dt,
                            downstream_limit=20,
                        )
                        best_rc = None
                        for rc in rail_cands:
                            if rc["to_stop_id"] not in dest_stop_ids:
                                continue
                            # Train must depart after requested_dt (user's desired departure)
                            if rc["depart_dt"] < requested_dt:
                                continue
                            if best_rc is None or rc["arrive_dt"] < best_rc["arrive_dt"]:
                                best_rc = rc

                        if not best_rc:
                            continue

                        # Build legs
                        legs = []
                        o_name = board_r["name"]
                        ds_name = ds_r["name"]

                        walk_to_stop = self._haversine_m(
                            origin_lat, origin_lon,
                            float(board_r.get("lat") or 0), float(board_r.get("lon") or 0)
                        )
                        if walk_to_stop > 50:
                            ws = walk_to_stop / WALKING_SPEED_MPS
                            walk_depart = (depart_dt - timedelta(seconds=ws)).replace(microsecond=0)
                            legs.append(self._walk_leg_dict(
                                origin_name, o_name,
                                walk_depart, depart_dt,
                                from_lat=origin_lat, from_lon=origin_lon,
                                to_lat=float(board_r["lat"]), to_lon=float(board_r["lon"])
                            ))

                        legs.append(self._vehicle_leg_dict(
                            "bus", o_name, ds_name, depart_dt, bus_arr,
                            line=line_name,
                            from_lat=float(board_r.get("lat") or 0),
                            from_lon=float(board_r.get("lon") or 0),
                            to_lat=float(ds_r["lat"]), to_lon=float(ds_r["lon"]),
                            service_id=trip_id,
                        ))

                        if walk_m > 30:
                            legs.append(self._walk_leg_dict(
                                ds_name, rail_stop["name"],
                                bus_arr, rail_arr,
                                from_lat=float(ds_r["lat"]), from_lon=float(ds_r["lon"]),
                                to_lat=rail_stop["lat"], to_lon=rail_stop["lon"]
                            ))

                        legs.append(self._vehicle_leg_dict(
                            "rail", rail_stop["name"], best_rc["to_stop_name"],
                            best_rc["depart_dt"], best_rc["arrive_dt"],
                            line=best_rc.get("trip_id"),
                            from_lat=rail_stop["lat"], from_lon=rail_stop["lon"],
                            to_lat=best_rc.get("to_lat"), to_lon=best_rc.get("to_lon"),
                            service_id=best_rc.get("trip_id"),
                            from_seq=best_rc.get("from_seq"), to_seq=best_rc.get("to_seq"),
                        ))

                        start_dt = self._parse_iso(legs[0]["depart"])
                        end_dt = self._parse_iso(legs[-1]["arrive"])
                        if not start_dt or not end_dt or end_dt <= start_dt:
                            continue
                        total_dur = int((end_dt - start_dt).total_seconds() / 60)
                        total_walk_s = sum(
                            max(0, (self._parse_iso(l["arrive"]) - self._parse_iso(l["depart"])).total_seconds())
                            for l in legs if l.get("mode") == "walk"
                        )
                        if total_walk_s > 900:
                            continue

                        existing = journey_dedup.get(line_name)
                        if existing is None or end_dt < existing[0]:
                            score, band, expl = self._compute_reliability(legs, total_dur, conn)
                            journey_dedup[line_name] = (end_dt, {
                                "depart_time": start_dt.isoformat(),
                                "arrive_time": end_dt.isoformat(),
                                "total_duration_min": total_dur,
                                "changes": 1,
                                "total_walk_minutes": int(total_walk_s / 60),
                                "reliability_score": score,
                                "reliability_band": band,
                                "reliability_explanation": expl,
                                "legs": legs,
                            })

                    all_found = sorted(
                        [v[1] for v in journey_dedup.values()],
                        key=lambda j: self._parse_iso(j["arrive_time"]) or datetime.max
                    )
                    if all_found:
                        best_arr = self._parse_iso(all_found[0]["arrive_time"])
                        all_found = [j for j in all_found
                                    if not best_arr or
                                    (self._parse_iso(j["arrive_time"]) or datetime.max)
                                    <= best_arr + timedelta(minutes=15)]
                    journeys.extend(all_found[:max_options])
            except Exception:
                pass

        for wh in window_hours_attempts:
            enforce_window = wh is not None
            if enforce_window:
                if time_type == "depart_at":
                    window_start = requested_dt
                    window_end = requested_dt + timedelta(hours=wh)
                else:
                    window_start = requested_dt - timedelta(hours=wh)
                    window_end = requested_dt
            else:
                window_start = None
                window_end = None

            def _has_usable(stop_id):
                try:
                    if enforce_window:
                        if use_bus:
                            cur_local = conn.execute(
                                """
                                SELECT 1 FROM bus.stop_times
                                WHERE stop_id=?
                                AND departure_time >= ?
                                LIMIT 1
                                """,
                                (stop_id, f"{window_start.hour:02d}:{window_start.minute:02d}:00"),
                            )
                            if cur_local.fetchone() is not None:
                                return True

                        if use_rail:
                            tiploc = None
                            if isinstance(stop_id, str) and stop_id.startswith("RAIL:"):
                                code = stop_id.split(":", 1)[1]
                                r = conn.execute(
                                    "SELECT tiploc FROM rail.stations WHERE tiploc=? OR crs=? LIMIT 1",
                                    (code, code),
                                ).fetchone()
                                tiploc = r[0] if r else code
                            elif isinstance(stop_id, str) and stop_id.startswith("9100"):
                                tiploc = stop_id[4:]
                            if tiploc:
                                dep_lower = f"{window_start.hour:02d}{window_start.minute:02d}" if window_start else "0000"
                                r = conn.execute(
                                    """
                                    SELECT 1 FROM rail.schedules
                                    WHERE tiploc=? AND departure IS NOT NULL
                                      AND REPLACE(departure,'H','') >= ?
                                    LIMIT 1
                                    """,
                                    (tiploc, dep_lower),
                                ).fetchone()
                                if r:
                                    return True
                        return False
                    else:
                        if use_bus:
                            cur_local = conn.execute("SELECT 1 FROM bus.stop_times WHERE stop_id=? LIMIT 1", (stop_id,))
                            if cur_local.fetchone() is not None:
                                return True
                        if use_rail:
                            tiploc = None
                            if isinstance(stop_id, str) and stop_id.startswith("RAIL:"):
                                code = stop_id.split(":", 1)[1]
                                r = conn.execute(
                                    "SELECT tiploc FROM rail.stations WHERE tiploc=? OR crs=? LIMIT 1",
                                    (code, code),
                                ).fetchone()
                                tiploc = r[0] if r else code
                            elif isinstance(stop_id, str) and stop_id.startswith("9100"):
                                tiploc = stop_id[4:]
                            if tiploc:
                                r = conn.execute(
                                    "SELECT 1 FROM rail.schedules WHERE tiploc=? AND departure IS NOT NULL LIMIT 1",
                                    (tiploc,),
                                ).fetchone()
                                if r:
                                    return True
                        return False
                except Exception:
                    return False

            origin_exact_usable = _has_usable(origin_id)
            dest_exact_usable = _has_usable(destination_id)
            exact_journeys = []
            try:
                if origin_exact_usable and dest_exact_usable and use_bus:
                    cur_exact = conn.execute(
                        """
                        SELECT trip_id, sequence, departure_time
                        FROM bus.stop_times
                        WHERE stop_id=?
                        ORDER BY departure_time, trip_id, sequence
                        LIMIT 2000
                        """,
                        (origin_id,),
                    )
                    for origin_row in cur_exact.fetchall():
                        check_timeout()
                        trip = origin_row["trip_id"]
                        o_seq = origin_row["sequence"]
                        depart_dt = self._parse_time_to_dt(origin_row["departure_time"], requested_dt)
                        if not depart_dt:
                            continue
                        if enforce_window and not self._window_contains(depart_dt, window_start, window_end):
                            continue

                        cur_dest = conn.execute(
                            """
                            SELECT sequence, departure_time
                            FROM bus.stop_times
                            WHERE trip_id=? AND stop_id=?
                            ORDER BY sequence
                            LIMIT 1
                            """,
                            (trip, destination_id),
                        )
                        dr = cur_dest.fetchone()
                        if not dr:
                            continue
                        if dr["sequence"] <= o_seq:
                            continue

                        dest_seq = dr["sequence"]
                        arrive_dt = self._parse_time_to_dt(dr["departure_time"], depart_dt) or (
                            depart_dt + timedelta(minutes=2 * (dest_seq - o_seq))
                        )
                        if arrive_dt < depart_dt:
                            continue

                        vehicle = self._vehicle_leg_dict(
                            "bus",
                            origin_name,
                            dest_name,
                            depart_dt,
                            arrive_dt,
                            line=self._get_line_name(conn, trip),
                            from_lat=origin_lat,
                            from_lon=origin_lon,
                            to_lat=dest_lat,
                            to_lon=dest_lon,
                            service_id=trip,
                            from_seq=o_seq,
                            to_seq=dest_seq,
                        )
                        total_duration = int((arrive_dt - depart_dt).total_seconds() / 60)
                        if total_duration <= 0 and (dest_seq - o_seq) > 0:
                            arrive_dt = depart_dt + timedelta(minutes=1)
                            vehicle = self._vehicle_leg_dict(
                                "bus",
                                origin_name,
                                dest_name,
                                depart_dt,
                                arrive_dt,
                                line=None,
                                from_lat=origin_lat,
                                from_lon=origin_lon,
                                to_lat=dest_lat,
                                to_lon=dest_lon,
                                service_id=trip,
                                from_seq=o_seq,
                                to_seq=dest_seq,
                            )
                            total_duration = 1

                        score, band, explanation = self._compute_reliability([vehicle], total_duration, conn, is_adverse_weather=is_adverse_weather)
                        exact_journeys.append(
                            {
                                "depart_time": depart_dt.isoformat(),
                                "arrive_time": arrive_dt.isoformat(),
                                "total_duration_min": total_duration,
                                "changes": 0,
                                "total_walk_minutes": 0,
                                "reliability_score": score,
                                "reliability_band": band,
                                "reliability_explanation": explanation,
                                "legs": [vehicle],
                            }
                        )
                    
            except NoRouteFoundError:
                pass
            except Exception:
                pass

            if origin_exact_usable and dest_exact_usable and use_rail:
                try:
                    rail_candidates = self._get_rail_candidates_from_stop(
                        conn=conn,
                        stop_id=origin_id,
                        current_time=requested_dt,
                        requested_dt=requested_dt,
                        enforce_window=enforce_window,
                        window_start=window_start,
                        window_end=window_end,
                        downstream_limit=15,
                    )
                    rail_direct = []
                    dest_catch_local = _catchment(dest_lat, dest_lon, meters=500)
                    dest_ids_local = set(s["id"] for s in dest_catch_local)
                    for rc in rail_candidates:
                        if rc["to_stop_id"] in dest_ids_local or rc["to_stop_id"] == destination_id:
                            depart_dt = rc["depart_dt"]
                            arrive_dt = rc["arrive_dt"]
                            total_duration = int((arrive_dt - depart_dt).total_seconds() / 60)
                            if total_duration <= 0:
                                continue
                            vehicle = self._vehicle_leg_dict(
                                "rail",
                                origin_name,
                                rc["to_stop_name"],
                                depart_dt,
                                arrive_dt,
                                line=rc.get("trip_id"),
                                from_lat=origin_lat,
                                from_lon=origin_lon,
                                to_lat=rc.get("to_lat"),
                                to_lon=rc.get("to_lon"),
                                service_id=rc.get("trip_id"),
                                from_seq=rc.get("from_seq"),
                                to_seq=rc.get("to_seq"),
                            )
                            score, band, explanation = self._compute_reliability([vehicle], total_duration, conn, is_adverse_weather=is_adverse_weather)
                            rail_direct.append(
                                {
                                    "depart_time": depart_dt.isoformat(),
                                    "arrive_time": arrive_dt.isoformat(),
                                    "total_duration_min": total_duration,
                                    "changes": 0,
                                    "reliability_score": score,
                                    "reliability_band": band,
                                    "reliability_explanation": explanation,
                                    "legs": [vehicle],
                                }
                            )
                    if rail_direct:
                        journeys.extend(rail_direct)
                except NoRouteFoundError:
                    pass
                except Exception:
                    pass

            # Always add direct journeys first
            journeys.extend(exact_journeys)


            # Only run heap-based multi-leg if we still need more options
            # Skip heap for mixed mode — targeted bus->rail search handles it faster
            if len(journeys) < max_options and not (use_bus and use_rail):
                for radius in radii:
                    origin_catch = _catchment(origin_lat, origin_lon, meters=radius)
                    dest_catch = _catchment(dest_lat, dest_lon, meters=radius)

                    if not origin_catch or not dest_catch:
                        continue

                    origin_ids = [s["id"] for s in origin_catch]
                    dest_ids = set(s["id"] for s in dest_catch)

                    if use_bus and origin_ids and dest_ids:
                        q_marks = ",".join("?" for _ in origin_ids)
                        cur_bus = conn.execute(
                            f"""
                            SELECT trip_id, stop_id, sequence, departure_time
                            FROM bus.stop_times
                            WHERE stop_id IN ({q_marks})
                            ORDER BY departure_time, trip_id, sequence
                            """,
                            tuple(origin_ids),
                        )
                        rows = cur_bus.fetchall()
                        trip_to_origins = {}
                        for r in rows:
                            trip_to_origins.setdefault(r["trip_id"], []).append(r)

                        for trip_id, origins in sorted(trip_to_origins.items(), key=lambda kv: str(kv[0])):
                            check_timeout()
                            q_marks2 = ",".join("?" for _ in list(dest_ids))
                            cur_dest = conn.execute(
                                f"""
                                SELECT stop_id, sequence, departure_time
                                FROM bus.stop_times
                                WHERE trip_id=? AND stop_id IN ({q_marks2})
                                ORDER BY sequence
                                """,
                                (trip_id, *list(dest_ids)),
                            )
                            dest_rows = cur_dest.fetchall()
                            if not dest_rows:
                                continue

                            origins = sorted(origins, key=lambda r: (r["departure_time"], r["sequence"], r["stop_id"]))
                            for o in origins:
                                o_seq = o["sequence"]
                                o_stop = o["stop_id"]
                                for dr in dest_rows:
                                    if dr["sequence"] <= o_seq:
                                        continue

                                    d_stop = dr["stop_id"]
                                    depart_dt = _safe_parse(o["departure_time"])
                                    arrive_dt = _safe_parse(dr["departure_time"])

                                    orig_stop_row = _resolve(o_stop)
                                    dest_stop_row = _resolve(d_stop)

                                    walk1_m = 0
                                    walk2_m = 0
                                    o_lat = None
                                    o_lon = None
                                    d_lat = None
                                    d_lon = None

                                    if orig_stop_row:
                                        try:
                                            o_lat = float(orig_stop_row["lat"]) if orig_stop_row["lat"] is not None else None
                                            o_lon = float(orig_stop_row["lon"]) if orig_stop_row["lon"] is not None else None
                                            if origin_lat is not None and origin_lon is not None and o_lat is not None and o_lon is not None:
                                                walk1_m = self._haversine_m(origin_lat, origin_lon, o_lat, o_lon)
                                        except Exception:
                                            walk1_m = 0

                                    if dest_stop_row:
                                        try:
                                            d_lat = float(dest_stop_row["lat"]) if dest_stop_row["lat"] is not None else None
                                            d_lon = float(dest_stop_row["lon"]) if dest_stop_row["lon"] is not None else None
                                            if dest_lat is not None and dest_lon is not None and d_lat is not None and d_lon is not None:
                                                walk2_m = self._haversine_m(dest_lat, dest_lon, d_lat, d_lon)
                                        except Exception:
                                            walk2_m = 0

                                    legs = []
                                    if walk1_m > 50:
                                        walk_secs = walk1_m / WALKING_SPEED_MPS
                                        walk_arrive = depart_dt
                                        walk_depart = walk_arrive - timedelta(seconds=walk_secs)
                                        if not (origin_exact_usable and origin_id == o_stop):
                                            legs.append(
                                                self._walk_leg_dict(
                                                    origin_name,
                                                    orig_stop_row["name"] if orig_stop_row else o_stop,
                                                    walk_depart,
                                                    walk_arrive,
                                                    from_lat=origin_lat,
                                                    from_lon=origin_lon,
                                                    to_lat=o_lat,
                                                    to_lon=o_lon,
                                                )
                                            )

                                    try:
                                        from_name = orig_stop_row["name"] if orig_stop_row else None
                                        to_name = dest_stop_row["name"] if dest_stop_row else None
                                    except Exception:
                                        from_name = None
                                        to_name = None

                                    veh_dur_secs = (arrive_dt - depart_dt).total_seconds() if (arrive_dt and depart_dt) else 0
                                    if from_name and to_name and from_name == to_name:
                                        continue
                                    if veh_dur_secs <= 0:
                                        continue

                                    legs.append(
                                        self._vehicle_leg_dict(
                                            "bus",
                                            from_name,
                                            to_name,
                                            depart_dt,
                                            arrive_dt,
                                            line=self._get_line_name(conn, trip_id),
                                            from_lat=o_lat,
                                            from_lon=o_lon,
                                            to_lat=d_lat,
                                            to_lon=d_lon,
                                            service_id=trip_id,
                                            from_seq=o_seq,
                                            to_seq=dr["sequence"],
                                        )
                                    )

                                    if walk2_m > 50:
                                        walk_secs2 = walk2_m / WALKING_SPEED_MPS
                                        walk_depart2 = arrive_dt
                                        walk_arrive2 = arrive_dt + timedelta(seconds=walk_secs2)
                                        if not (dest_exact_usable and destination_id == d_stop):
                                            legs.append(
                                                self._walk_leg_dict(
                                                    dest_stop_row["name"] if dest_stop_row else d_stop,
                                                    dest_name,
                                                    walk_depart2,
                                                    walk_arrive2,
                                                    from_lat=d_lat,
                                                    from_lon=d_lon,
                                                    to_lat=dest_lat,
                                                    to_lon=dest_lon,
                                                )
                                            )

                                    try:
                                        start_dt = datetime.fromisoformat(legs[0]["depart"])
                                        end_dt = datetime.fromisoformat(legs[-1]["arrive"])
                                    except Exception:
                                        continue

                                    total_duration = int((end_dt - start_dt).total_seconds() / 60)
                                    if total_duration < 0:
                                        continue

                                    score, band, explanation = self._compute_reliability(legs, total_duration, conn, is_adverse_weather=is_adverse_weather)

                                    journeys.append(
                                        {
                                            "depart_time": start_dt.isoformat(),
                                            "arrive_time": end_dt.isoformat(),
                                            "total_duration_min": total_duration,
                                            "changes": 0,
                                            "reliability_score": score,
                                            "reliability_band": band,
                                            "reliability_explanation": explanation,
                                            "legs": legs,
                                        }
                                    )
                                    if len(journeys) >= max_options:
                                        break
                                if len(journeys) >= max_options:
                                    break
                            if len(journeys) >= max_options:
                                break

                    if len(journeys) >= max_options:
                        break

                origin_ids = [s["id"] for s in origin_catch]
                dest_ids = set(s["id"] for s in dest_catch)

                if (use_bus or use_rail) and origin_ids and dest_ids:
                    origin_candidates = []

                    if use_bus:
                        for sid in origin_ids:
                            cur_seed = conn.execute(
                                """
                                SELECT trip_id, stop_id, sequence, departure_time
                                FROM bus.stop_times
                                WHERE stop_id=?
                                ORDER BY departure_time, trip_id, sequence
                                LIMIT 200
                                """,
                                (sid,),
                            )
                            for r in cur_seed.fetchall():
                                depart_dt = self._parse_time_to_dt(r["departure_time"], requested_dt)
                                if not depart_dt:
                                    continue
                                if enforce_window and not self._window_contains(depart_dt, window_start, window_end):
                                    continue
                                origin_candidates.append((depart_dt, r, "bus"))

                    if use_rail:
                        for sid in origin_ids:
                            rail_candidates = self._get_rail_candidates_from_stop(
                                conn=conn,
                                stop_id=sid,
                                current_time=requested_dt,
                                requested_dt=requested_dt,
                                enforce_window=enforce_window,
                                window_start=window_start,
                                window_end=window_end,
                                downstream_limit=15,
                            )
                            for rc in rail_candidates:
                                origin_candidates.append(
                                    (
                                        rc["depart_dt"],
                                        {
                                            "stop_id": sid,
                                            "departure_time": rc["depart_dt"].isoformat(),
                                        },
                                        "rail",
                                    )
                                )

                    origin_candidates.sort(key=lambda x: (x[0], str(x[1]["stop_id"]), x[2]))
                    seed_cap = 20 if journeys else 50
                    origin_candidates = origin_candidates[:seed_cap]

                    MAX_STATES = 5000
                    MAX_VEHICLE_LEGS = 3      # hard cap: never suggest more than 3 changes
                    DOWNSTREAM_LIMIT = 10

                    journeys_found = []
                    explored_states = 0
                    heap = []
                    counter = 0
                    best = {}

                    for depart_dt, r, seed_mode in origin_candidates:
                        start_stop = r["stop_id"]
                        legs = []

                        if not origin_exact_usable and start_stop != origin_id:
                            sr = _resolve(start_stop)
                            if sr:
                                nm = sr["name"]
                                try:
                                    s_lat = float(sr["lat"]) if sr["lat"] is not None else None
                                    s_lon = float(sr["lon"]) if sr["lon"] is not None else None
                                except Exception:
                                    s_lat = None
                                    s_lon = None

                                if origin_lat is not None and origin_lon is not None and s_lat is not None and s_lon is not None:
                                    walk_m = self._haversine_m(origin_lat, origin_lon, s_lat, s_lon)
                                    if walk_m > 50 and walk_m <= WALK_MAX_METERS:
                                        walk_secs = walk_m / WALKING_SPEED_MPS
                                        walk_arrive = depart_dt
                                        walk_depart = walk_arrive - timedelta(seconds=walk_secs)
                                        legs.append(
                                            self._walk_leg_dict(
                                                origin_name,
                                                nm,
                                                walk_depart,
                                                walk_arrive,
                                                from_lat=origin_lat,
                                                from_lon=origin_lon,
                                                to_lat=s_lat,
                                                to_lon=s_lon,
                                            )
                                        )

                        heapq.heappush(
                            heap,
                            (depart_dt.timestamp(), counter, start_stop, depart_dt, legs, 0, None),
                        )
                        best[(start_stop, 0, None)] = depart_dt
                        counter += 1

                    while heap and len(journeys_found) < max_options and explored_states < MAX_STATES:
                        _, _, cur_stop, cur_time, cur_legs, vehicle_legs, last_vehicle_mode = heapq.heappop(heap)
                        explored_states += 1
                        check_timeout()

                        bkey = (cur_stop, vehicle_legs, last_vehicle_mode)
                        bval = best.get(bkey)
                        if bval and cur_time > bval + timedelta(seconds=1):
                            continue

                        if cur_stop in dest_ids and cur_legs:
                            try:
                                start_dt = datetime.fromisoformat(cur_legs[0]["depart"])
                                end_dt = datetime.fromisoformat(cur_legs[-1]["arrive"])
                            except Exception:
                                continue

                            total_duration = int((end_dt - start_dt).total_seconds() / 60)
                            if total_duration < 0:
                                continue

                            n_vehicle = len([l for l in cur_legs if l.get("mode") != "walk"])
                            n_changes = max(0, n_vehicle - 1)

                            # Human-behaviour gate: count total walk time across all walk legs
                            total_walk_secs = sum(
                                max(0, (
                                    self._parse_iso(l["arrive"]) - self._parse_iso(l["depart"])
                                ).total_seconds())
                                for l in cur_legs if l.get("mode") == "walk"
                            )
                            # Reject if total walking exceeds 15 minutes — nobody wants a 20-min walk as part of a transit journey
                            if total_walk_secs > 900:
                                continue

                            # Reject if a change is present but saves less than 10 min per change vs best known direct
                            if n_changes > 0 and journeys:
                                best_direct = min(
                                    (j for j in journeys if j.get("changes", 0) == 0),
                                    key=lambda j: self._parse_iso(j.get("arrive_time")) or datetime.max,
                                    default=None,
                                )
                                if best_direct:
                                    best_direct_arrive = self._parse_iso(best_direct.get("arrive_time"))
                                    saving_secs = (best_direct_arrive - end_dt).total_seconds() if best_direct_arrive else 0
                                    required_saving = CHANGE_TIME_SAVING_THRESHOLD_SECS * n_changes
                                    if saving_secs < required_saving:
                                        continue

                            score, band, explanation = self._compute_reliability(cur_legs, total_duration, conn, is_adverse_weather=is_adverse_weather)
                            journeys_found.append(
                                {
                                    "depart_time": cur_legs[0]["depart"],
                                    "arrive_time": cur_legs[-1]["arrive"],
                                    "total_duration_min": total_duration,
                                    "changes": n_changes,
                                    "total_walk_minutes": int(total_walk_secs / 60),
                                    "reliability_score": score,
                                    "reliability_band": band,
                                    "reliability_explanation": explanation,
                                    "legs": cur_legs,
                                }
                            )
                            continue

                        cur_stop_resolved = _resolve(cur_stop)
                        if not cur_stop_resolved:
                            continue

                        cur_name = cur_stop_resolved["name"]
                        try:
                            cur_lat = float(cur_stop_resolved["lat"]) if cur_stop_resolved["lat"] is not None else None
                        except Exception:
                            cur_lat = None
                        try:
                            cur_lon = float(cur_stop_resolved["lon"]) if cur_stop_resolved["lon"] is not None else None
                        except Exception:
                            cur_lon = None

                        if vehicle_legs < MAX_VEHICLE_LEGS and len(cur_legs) < (MAX_VEHICLE_LEGS * 2):
                            is_rail_stop = (
                                isinstance(cur_stop, str)
                                and (cur_stop.startswith("RAIL:") or cur_stop.startswith("9100"))
                            )
                            nearby = []
                            if (not is_rail_stop or vehicle_legs == 0) and cur_lat is not None and cur_lon is not None:
                                nearby = _catchment(cur_lat, cur_lon, meters=WALK_TRANSFER_MAX_M)
                            nearby.sort(key=lambda x: (x["distance_m"], x["id"]))
                            expanded = 0
                            for nb in nearby:
                                if expanded >= 5:
                                    break
                                nb_id = nb["id"]
                                if nb_id == cur_stop:
                                    continue
                                walk_m = nb["distance_m"]
                                if walk_m <= 0 or walk_m > WALK_TRANSFER_MAX_M:
                                    continue

                                walk_secs = walk_m / WALKING_SPEED_MPS
                                arrive_walk = cur_time + timedelta(seconds=walk_secs)
                                walk_leg = self._walk_leg_dict(
                                    cur_name,
                                    nb["name"],
                                    cur_time,
                                    arrive_walk,
                                    from_lat=cur_lat,
                                    from_lon=cur_lon,
                                    to_lat=nb["lat"],
                                    to_lon=nb["lon"],
                                )
                                legs_new = cur_legs + [walk_leg]
                                walk_last_mode = last_vehicle_mode
                                bkey = (nb_id, vehicle_legs, walk_last_mode)
                                prev = best.get(bkey)
                                if prev and arrive_walk >= prev:
                                    continue
                                best[bkey] = arrive_walk
                                heapq.heappush(
                                    heap,
                                    (arrive_walk.timestamp(), counter, nb_id, arrive_walk, legs_new, vehicle_legs, walk_last_mode),
                                )
                                counter += 1
                                expanded += 1

                        if use_bus:
                            cur_out = conn.execute(
                                """
                                SELECT trip_id, sequence, departure_time
                                FROM bus.stop_times
                                WHERE stop_id=?
                                ORDER BY departure_time, trip_id, sequence
                                LIMIT 100
                                """,
                                (cur_stop,),
                            )
                            # Minimum wait before boarding: 0 for first leg, 2 min for a transfer
                            min_board_wait = timedelta(seconds=MIN_TRANSFER_WAIT_BUS_SECS if vehicle_legs > 0 else 0)
                            # Only process the first 20 valid departures — enough to find next buses
                            # without flooding the heap with every service of the day
                            bus_rows_processed = 0
                            for row in cur_out.fetchall():
                                if bus_rows_processed >= 20:
                                    break
                                depart_dt = self._parse_time_to_dt(row["departure_time"], requested_dt)
                                if not depart_dt:
                                    continue
                                if depart_dt < cur_time + min_board_wait:
                                    continue
                                if enforce_window and not self._window_contains(depart_dt, window_start, window_end):
                                    continue
                                bus_rows_processed += 1

                                cur_ds = conn.execute(
                                    """
                                    SELECT stop_id, sequence, departure_time
                                    FROM bus.stop_times
                                    WHERE trip_id=? AND sequence>?
                                    ORDER BY sequence
                                    LIMIT ?
                                    """,
                                    (row["trip_id"], row["sequence"], DOWNSTREAM_LIMIT),
                                )
                                for ds in cur_ds.fetchall():
                                    ds_id = ds["stop_id"]
                                    if ds_id == cur_stop:
                                        continue

                                    arrive_dt = self._parse_time_to_dt(ds["departure_time"], depart_dt) or (
                                        depart_dt + timedelta(minutes=2 * (ds["sequence"] - row["sequence"]))
                                    )
                                    if arrive_dt < depart_dt:
                                        continue
                                    if (arrive_dt - depart_dt).total_seconds() < 60:
                                        continue

                                    ds_resolved = _resolve(ds_id)
                                    ds_name = ds_resolved["name"] if ds_resolved else ds_id

                                    try:
                                        ds_lat = float(ds_resolved["lat"]) if ds_resolved and ds_resolved["lat"] is not None else None
                                        ds_lon = float(ds_resolved["lon"]) if ds_resolved and ds_resolved["lon"] is not None else None
                                    except Exception:
                                        ds_lat = None
                                        ds_lon = None

                                    allow_expand = True
                                    # Only prune if this is NOT the first leg and we've already
                                    # used a rail leg — a bus to a rail station may go away from
                                    # the destination before the train brings you back south
                                    if vehicle_legs > 0 and last_vehicle_mode == "bus":
                                        if (
                                            dest_lat is not None and dest_lon is not None
                                            and cur_lat is not None and cur_lon is not None
                                            and ds_lat is not None and ds_lon is not None
                                        ):
                                            cur_dist = self._haversine_m(cur_lat, cur_lon, dest_lat, dest_lon)
                                            ds_dist = self._haversine_m(ds_lat, ds_lon, dest_lat, dest_lon)
                                            if ds_dist > cur_dist + 5000:
                                                allow_expand = False

                                    if not allow_expand:
                                        continue
                                    if ds_name == cur_name:
                                        continue

                                    leg = self._vehicle_leg_dict(
                                        "bus",
                                        cur_name,
                                        ds_name,
                                        depart_dt,
                                        arrive_dt,
                                        line=self._get_line_name(conn, row["trip_id"]),
                                        from_lat=cur_lat,
                                        from_lon=cur_lon,
                                        to_lat=ds_lat,
                                        to_lon=ds_lon,
                                        service_id=row["trip_id"],
                                        from_seq=row["sequence"],
                                        to_seq=ds["sequence"],
                                    )
                                    legs_new = cur_legs + [leg]
                                    new_vehicle_legs = vehicle_legs + 1
                                    if new_vehicle_legs > MAX_VEHICLE_LEGS:
                                        break

                                    bkey = (ds_id, new_vehicle_legs, "bus")
                                    prev = best.get(bkey)
                                    if prev and arrive_dt >= prev:
                                        continue

                                    best[bkey] = arrive_dt
                                    heapq.heappush(
                                        heap,
                                        (arrive_dt.timestamp(), counter, ds_id, arrive_dt, legs_new, new_vehicle_legs, "bus"),
                                    )
                                    counter += 1

                        if use_rail:
                            # For a transfer (not the first leg), require 5 min buffer before boarding a train
                            rail_min_wait = timedelta(seconds=MIN_TRANSFER_WAIT_RAIL_SECS if vehicle_legs > 0 else 0)
                            rail_candidates = self._get_rail_candidates_from_stop(
                                conn=conn,
                                stop_id=cur_stop,
                                current_time=cur_time + rail_min_wait,
                                requested_dt=requested_dt,
                                enforce_window=enforce_window,
                                window_start=window_start,
                                window_end=window_end,
                                downstream_limit=DOWNSTREAM_LIMIT,
                            )
                            # Deduplicate: keep only the earliest departure per destination stop
                            # to avoid 100+ candidates for the same journey flooding the heap
                            seen_rail_dst = {}
                            for rc in rail_candidates:
                                key = rc["to_stop_id"]
                                if key not in seen_rail_dst:
                                    seen_rail_dst[key] = rc
                            rail_candidates = sorted(seen_rail_dst.values(), key=lambda x: x["depart_dt"])[:15]

                            for rc in rail_candidates:
                                ds_id = rc["to_stop_id"]
                                ds_name = rc["to_stop_name"]
                                depart_dt = rc["depart_dt"]
                                arrive_dt = rc["arrive_dt"]
                                ds_lat = rc["to_lat"]
                                ds_lon = rc["to_lon"]

                                allow_expand = True
                                if (
                                    dest_lat is not None and dest_lon is not None
                                    and cur_lat is not None and cur_lon is not None
                                    and ds_lat is not None and ds_lon is not None
                                ):
                                    cur_dist = self._haversine_m(cur_lat, cur_lon, dest_lat, dest_lon)
                                    ds_dist = self._haversine_m(ds_lat, ds_lon, dest_lat, dest_lon)
                                    if ds_dist > cur_dist + 2000:
                                        allow_expand = False

                                if not allow_expand:
                                    continue
                                if ds_name == cur_name:
                                    continue

                                leg = self._vehicle_leg_dict(
                                    "rail",
                                    cur_name,
                                    ds_name,
                                    depart_dt,
                                    arrive_dt,
                                    line=rc.get("trip_id"),
                                    from_lat=cur_lat,
                                    from_lon=cur_lon,
                                    to_lat=ds_lat,
                                    to_lon=ds_lon,
                                    service_id=rc.get("trip_id"),
                                    from_seq=rc.get("from_seq"),
                                    to_seq=rc.get("to_seq"),
                                )
                                legs_new = cur_legs + [leg]
                                new_vehicle_legs = vehicle_legs + 1
                                if new_vehicle_legs > MAX_VEHICLE_LEGS:
                                    break

                                bkey = (ds_id, new_vehicle_legs, "rail")
                                prev = best.get(bkey)
                                if prev and arrive_dt >= prev:
                                    continue

                                best[bkey] = arrive_dt
                                heapq.heappush(
                                    heap,
                                    (arrive_dt.timestamp(), counter, ds_id, arrive_dt, legs_new, new_vehicle_legs, "rail"),
                                )
                                counter += 1

                    journeys.extend(journeys_found)

                if len(journeys) >= max_options:
                    break

        # --- Targeted bus->rail search (outside window loop, runs once) ---
        conn.close()

        if not journeys:
            try:
                print(f"DEBUG: no route found")
            except Exception:
                pass
            raise NoRouteFoundError(f"No routes found between {origin_id} and {destination_id}")

        unique = []
        seen = set()

        def _norm_time_min(t):
            try:
                dt = self._parse_iso(t) if not isinstance(t, datetime) else t
                if not dt:
                    return None
                dt = dt.replace(second=0, microsecond=0)
                return dt.isoformat()
            except Exception:
                return None

        for j in journeys:
            key = tuple(
                (
                    l.get("mode"),
                    l.get("from"),
                    l.get("to"),
                    _norm_time_min(l.get("depart")),
                    _norm_time_min(l.get("arrive")),
                )
                for l in j.get("legs", [])
            )
            if key not in seen:
                seen.add(key)
                unique.append(j)

        good = []
        for j in unique:
            try:
                start_dt = self._parse_iso(j.get("depart_time"))
                end_dt = self._parse_iso(j.get("arrive_time"))
                if start_dt is None or end_dt is None:
                    continue
                if end_dt < start_dt:
                    continue

                total = int(j.get("total_duration_min", 0))
                leg_sum = 0
                valid_legs = True
                prev_arr = start_dt

                for leg in j.get("legs", []):
                    ldep = self._parse_iso(leg.get("depart"))
                    larr = self._parse_iso(leg.get("arrive"))
                    if ldep is None or larr is None or larr < ldep:
                        valid_legs = False
                        break
                    if ldep < prev_arr:
                        valid_legs = False
                        break

                    try:
                        dur_secs = int((larr - ldep).total_seconds())
                    except Exception:
                        dur_secs = 0

                    if leg.get("mode") in ("bus", "rail"):
                        if dur_secs < 60:
                            valid_legs = False
                            break
                        if leg.get("from") == leg.get("to"):
                            valid_legs = False
                            break

                    prev_arr = larr
                    leg_sum += int((larr - ldep).total_seconds() / 60)

                if not valid_legs:
                    continue
                if total <= 0 and leg_sum > 0:
                    continue
                if abs(total - leg_sum) > 2:
                    j["total_duration_min"] = leg_sum
                good.append(j)
            except Exception:
                continue

        if time_type == "depart_at":
            def _first_vehicle_depart(jj):
                for leg in jj.get("legs", []):
                    if leg.get("mode") in ("bus", "rail"):
                        return self._parse_iso(leg.get("depart"))
                return self._parse_iso(jj.get("depart_time"))

            later = [
                jj for jj in good
                if _first_vehicle_depart(jj) and _first_vehicle_depart(jj) >= requested_dt
            ]
            if later:
                later.sort(key=self._journey_sort_key)
                return self._select_distinct_journeys(later, max_options)

            raise NoRouteFoundError(
                f"No upcoming departures found from {origin_id} after {requested_dt.isoformat()}"
            )

        good.sort(key=self._journey_sort_key)
        return self._select_distinct_journeys(good, max_options)


Planner = JourneyPlanner
"""Unified stop lookup service (Person D — Kamol).

Provides a single interface to resolve stop metadata regardless of whether
the stop originated from:

* the NaPTAN XML export (``stops.db``)
* the TransXChange timetable XML (``bus.db`` → ``bus_stops`` table)
* the rail schedule JSON (``rail.db`` → ``stations`` table)

The resolution order is:
  1. ``stops.atco_code``   — canonical NaPTAN data (richest metadata)
  2. ``bus.bus_stops.atco_code`` — TransXChange stop metadata (name + optional coords)
  3. ``rail.stations.crs`` — CRS station code

This ensures that every ``stop_times.stop_id`` in ``bus.db`` can be mapped
to at least a name, and ideally lat/lon, without needing substring hacks
or fake joins.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from app.data.exceptions import DataUnavailableError, StaticDataMissingError


class StopService:
    """Thin wrapper around the stops SQLite databases."""

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir is None:
            # Default: workspace/backend/
            base_dir = str(Path(__file__).resolve().parents[2])
        self._base = Path(base_dir)
        self._stops_db = self._base / "stops.db"
        self._bus_db = self._base / "bus.db"
        self._rail_db = self._base / "rail.db"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        """Open stops.db with bus.db and rail.db attached."""
        if not self._stops_db.exists():
            raise DataUnavailableError(f"stops.db not found at {self._stops_db}")

        conn = sqlite3.connect(str(self._stops_db))
        conn.row_factory = sqlite3.Row

        if self._bus_db.exists():
            try:
                conn.execute(f"ATTACH DATABASE '{self._bus_db}' AS bus")
            except Exception:
                pass

        if self._rail_db.exists():
            try:
                conn.execute(f"ATTACH DATABASE '{self._rail_db}' AS rail")
            except Exception:
                pass

        return conn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search_stops(self, query: str, limit: int = 10) -> list[dict]:
        """Autocomplete search across all stop sources.

        Returns list of dicts with keys: id, name, type, lat, lon.
        """
        conn = self._get_conn()
        try:
            results: list[dict] = []
            pattern = f"%{query}%"

            # 1. NaPTAN stops
            cur = conn.execute(
                """
                SELECT atco_code AS id, common_name AS name,
                       latitude AS lat, longitude AS lon
                FROM stops
                WHERE common_name LIKE ?
                LIMIT ?
                """,
                (pattern, limit),
            )
            for r in cur.fetchall():
                results.append({
                    "id": r["id"], "name": r["name"], "type": "bus",
                    "lat": r["lat"], "lon": r["lon"],
                })

            # 2. Bus stops from TransXChange (only those not already found)
            seen_ids = {r["id"] for r in results}
            try:
                cur2 = conn.execute(
                    """
                    SELECT atco_code AS id, common_name AS name,
                           latitude AS lat, longitude AS lon
                    FROM bus.bus_stops
                    WHERE common_name LIKE ?
                    LIMIT ?
                    """,
                    (pattern, limit),
                )
                for r in cur2.fetchall():
                    if r["id"] not in seen_ids:
                        results.append({
                            "id": r["id"], "name": r["name"], "type": "bus",
                            "lat": r["lat"], "lon": r["lon"],
                        })
                        seen_ids.add(r["id"])
            except Exception:
                pass  # bus.db may not be attached

            # 3. Rail stations
            try:
                cur3 = conn.execute(
                    """
                    SELECT crs AS id, name, NULL AS lat, NULL AS lon
                    FROM rail.stations
                    WHERE name LIKE ?
                    LIMIT ?
                    """,
                    (pattern, limit),
                )
                for r in cur3.fetchall():
                    rid = f"RAIL:{r['id']}" if r["id"] else None
                    if rid and rid not in seen_ids:
                        results.append({
                            "id": rid, "name": r["name"], "type": "rail",
                            "lat": r["lat"], "lon": r["lon"],
                        })
                        seen_ids.add(rid)
            except Exception:
                pass  # rail.db may not be attached

            if not results:
                raise StaticDataMissingError(f"No stops matching '{query}'")

            return results[:limit]
        finally:
            conn.close()

    def get_stop(self, stop_id: str) -> Optional[dict]:
        """Resolve a single stop ID to its metadata.

        Tries stops.db first, then bus.bus_stops, then rail.stations.
        Returns dict with keys: id, name, type, lat, lon — or None.
        """
        conn = self._get_conn()
        try:
            # 1. NaPTAN stops table
            r = conn.execute(
                "SELECT atco_code AS id, common_name AS name, latitude AS lat, longitude AS lon FROM stops WHERE atco_code=?",
                (stop_id,),
            ).fetchone()
            if r:
                return {"id": r["id"], "name": r["name"], "type": "bus", "lat": r["lat"], "lon": r["lon"]}

            # 2. bus.bus_stops (TransXChange-sourced)
            try:
                r = conn.execute(
                    "SELECT atco_code AS id, common_name AS name, latitude AS lat, longitude AS lon FROM bus.bus_stops WHERE atco_code=?",
                    (stop_id,),
                ).fetchone()
                if r:
                    return {"id": r["id"], "name": r["name"], "type": "bus", "lat": r["lat"], "lon": r["lon"]}
            except Exception:
                pass

            # 3. Rail station (stop_id may be "RAIL:LAN" or just "LAN")
            crs = stop_id
            if stop_id.startswith("RAIL:"):
                crs = stop_id.split(":", 1)[1]
            try:
                r = conn.execute(
                    "SELECT crs AS id, name FROM rail.stations WHERE crs=?",
                    (crs,),
                ).fetchone()
                if r:
                    return {"id": f"RAIL:{r['id']}", "name": r["name"], "type": "rail", "lat": None, "lon": None}
            except Exception:
                pass

            return None
        finally:
            conn.close()

    def validate_bus_stop_coverage(self) -> tuple[int, int, list[str]]:
        """Check how many bus.stop_times.stop_id values exist in stops.

        Returns (resolved, unresolved, sample_missing_ids).
        """
        conn = self._get_conn()
        try:
            total = conn.execute(
                "SELECT COUNT(DISTINCT stop_id) FROM bus.stop_times"
            ).fetchone()[0]

            # Check against BOTH stops table and bus.bus_stops
            resolved = conn.execute(
                """
                SELECT COUNT(DISTINCT st.stop_id)
                FROM bus.stop_times st
                WHERE EXISTS (SELECT 1 FROM stops s WHERE s.atco_code = st.stop_id)
                   OR EXISTS (SELECT 1 FROM bus.bus_stops bs WHERE bs.atco_code = st.stop_id)
                """
            ).fetchone()[0]

            unresolved = total - resolved

            missing_sample: list[str] = []
            if unresolved > 0:
                rows = conn.execute(
                    """
                    SELECT DISTINCT st.stop_id
                    FROM bus.stop_times st
                    WHERE NOT EXISTS (SELECT 1 FROM stops s WHERE s.atco_code = st.stop_id)
                      AND NOT EXISTS (SELECT 1 FROM bus.bus_stops bs WHERE bs.atco_code = st.stop_id)
                    LIMIT 10
                    """,
                ).fetchall()
                missing_sample = [r[0] for r in rows]

            return (resolved, unresolved, missing_sample)
        except Exception:
            return (0, 0, [])
        finally:
            conn.close()

#!/usr/bin/env python3
"""Tests for bus stop ID resolution and data consistency.

These tests create lightweight in-memory (or temp-file) SQLite databases
that mirror the schemas used by the real loaders and the planner, then
verify that:

1. Bus stop IDs used in timetable rows can be resolved to metadata.
2. Frontend-selected bus stops can be validated through the StopService.
3. The planner no longer fails due to unresolved bus stop references.
4. The merge_stops script correctly populates stops.db from bus.bus_stops.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

# Ensure the backend package is on the path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ---------------------------------------------------------------------------
# Helpers: create test databases with realistic schemas
# ---------------------------------------------------------------------------

def _create_stops_db(path: str, rows: list[tuple]) -> None:
    """Create a stops.db with the NaPTAN schema."""
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stops (
            atco_code TEXT PRIMARY KEY,
            naptan_code TEXT,
            common_name TEXT,
            street TEXT,
            indicator TEXT,
            suburb TEXT,
            town TEXT,
            latitude REAL,
            longitude REAL,
            easting INTEGER,
            northing INTEGER,
            administrative_area_ref TEXT,
            stop_type TEXT,
            bus_stop_type TEXT
        )
        """
    )
    conn.executemany(
        """
        INSERT OR REPLACE INTO stops
            (atco_code, common_name, latitude, longitude, stop_type)
        VALUES (?, ?, ?, ?, 'BCT')
        """,
        rows,
    )
    conn.commit()
    conn.close()


def _create_bus_db(
    path: str,
    bus_stops: list[tuple],
    stop_times: list[tuple],
    services: list[tuple] | None = None,
    trips: list[tuple] | None = None,
) -> None:
    """Create a bus.db with bus_stops, stop_times, services, trips tables."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bus_stops (
            atco_code TEXT PRIMARY KEY,
            common_name TEXT,
            latitude REAL,
            longitude REAL
        );
        CREATE TABLE IF NOT EXISTS services (
            id TEXT PRIMARY KEY,
            line_name TEXT,
            operator TEXT
        );
        CREATE TABLE IF NOT EXISTS trips (
            id TEXT PRIMARY KEY,
            service_id TEXT,
            departure_time TEXT
        );
        CREATE TABLE IF NOT EXISTS stop_times (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id TEXT,
            stop_id TEXT,
            arrival_time TEXT,
            departure_time TEXT,
            sequence INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_stop_times_stop ON stop_times(stop_id);
        CREATE INDEX IF NOT EXISTS idx_stop_times_trip ON stop_times(trip_id);
        """
    )
    conn.executemany(
        "INSERT OR REPLACE INTO bus_stops (atco_code, common_name, latitude, longitude) VALUES (?, ?, ?, ?)",
        bus_stops,
    )
    if services:
        conn.executemany(
            "INSERT OR REPLACE INTO services (id, line_name, operator) VALUES (?, ?, ?)",
            services,
        )
    if trips:
        conn.executemany(
            "INSERT OR REPLACE INTO trips (id, service_id, departure_time) VALUES (?, ?, ?)",
            trips,
        )
    conn.executemany(
        "INSERT INTO stop_times (trip_id, stop_id, arrival_time, departure_time, sequence) VALUES (?, ?, ?, ?, ?)",
        stop_times,
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Test 1: Bus stop IDs in timetable rows can be resolved to metadata
# ---------------------------------------------------------------------------

class TestBusStopResolution(unittest.TestCase):
    """Verify that every stop_id in bus.stop_times can be resolved."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.stops_db = os.path.join(self.tmpdir, "stops.db")
        self.bus_db = os.path.join(self.tmpdir, "bus.db")

        # NaPTAN-style stops (numeric ATCO codes — different dataset)
        _create_stops_db(self.stops_db, [
            ("020033095", "Market Street", 54.05, -2.80),
            ("020035124", "Bus Station Bay 1", 54.04, -2.79),
        ])

        # TransXChange-style stops and timetable rows
        _create_bus_db(
            self.bus_db,
            bus_stops=[
                ("1290BOB20410", "Bowness Pier", 54.3651, -2.9228),
                ("1980SN120553", "Kendal Bus Station", 54.3268, -2.7462),
                ("1290BOB20411", "Windermere Station", 54.3801, -2.9053),
            ],
            stop_times=[
                ("trip1", "1290BOB20410", "09:00:00", "09:00:00", 1),
                ("trip1", "1980SN120553", "09:25:00", "09:25:00", 2),
                ("trip1", "1290BOB20411", "09:40:00", "09:40:00", 3),
            ],
            services=[("SVC1", "555", "Stagecoach")],
            trips=[("trip1", "SVC1", "09:00:00")],
        )

    def test_all_timetable_stop_ids_resolve_via_bus_stops(self):
        """Every stop_id in stop_times must exist in bus_stops."""
        conn = sqlite3.connect(self.bus_db)
        timetable_ids = [
            r[0] for r in conn.execute("SELECT DISTINCT stop_id FROM stop_times").fetchall()
        ]
        bus_stop_ids = {
            r[0] for r in conn.execute("SELECT atco_code FROM bus_stops").fetchall()
        }
        conn.close()

        for sid in timetable_ids:
            self.assertIn(
                sid, bus_stop_ids,
                f"Timetable stop_id '{sid}' not found in bus_stops table",
            )

    def test_stop_ids_are_not_numeric_naptan(self):
        """TransXChange ATCO codes should not look like old numeric-only IDs."""
        conn = sqlite3.connect(self.bus_db)
        ids = [r[0] for r in conn.execute("SELECT DISTINCT stop_id FROM stop_times").fetchall()]
        conn.close()
        for sid in ids:
            self.assertFalse(
                sid.isdigit(),
                f"stop_id '{sid}' is purely numeric — expected alphanumeric TransXChange ATCO code",
            )

    def test_stops_db_naptan_ids_are_separate(self):
        """NaPTAN stops.db IDs should not overlap with bus.db timetable IDs."""
        stops_conn = sqlite3.connect(self.stops_db)
        naptan_ids = {r[0] for r in stops_conn.execute("SELECT atco_code FROM stops").fetchall()}
        stops_conn.close()

        bus_conn = sqlite3.connect(self.bus_db)
        timetable_ids = {r[0] for r in bus_conn.execute("SELECT DISTINCT stop_id FROM stop_times").fetchall()}
        bus_conn.close()

        overlap = naptan_ids & timetable_ids
        # This test documents the ORIGINAL bug: zero overlap
        self.assertEqual(
            len(overlap), 0,
            "Before merge, NaPTAN and timetable IDs should not overlap (different datasets)",
        )


# ---------------------------------------------------------------------------
# Test 2: merge_stops resolves the mismatch
# ---------------------------------------------------------------------------

class TestMergeStops(unittest.TestCase):
    """Verify that merge_stops.py merges bus_stops into stops.db."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.stops_db = os.path.join(self.tmpdir, "stops.db")
        self.bus_db = os.path.join(self.tmpdir, "bus.db")

        _create_stops_db(self.stops_db, [
            ("020033095", "Market Street", 54.05, -2.80),
        ])

        _create_bus_db(
            self.bus_db,
            bus_stops=[
                ("1290BOB20410", "Bowness Pier", 54.3651, -2.9228),
                ("1980SN120553", "Kendal Bus Station", 54.3268, -2.7462),
            ],
            stop_times=[
                ("trip1", "1290BOB20410", "09:00:00", "09:00:00", 1),
                ("trip1", "1980SN120553", "09:25:00", "09:25:00", 2),
            ],
        )

    def test_merge_adds_bus_stops_to_stops_db(self):
        from merge_stops import merge

        merge(self.bus_db, self.stops_db, verbose=False)

        conn = sqlite3.connect(self.stops_db)
        ids = {r[0] for r in conn.execute("SELECT atco_code FROM stops").fetchall()}
        conn.close()

        self.assertIn("1290BOB20410", ids, "merge should add TransXChange stop")
        self.assertIn("1980SN120553", ids, "merge should add TransXChange stop")
        self.assertIn("020033095", ids, "merge should preserve original NaPTAN stop")

    def test_merge_preserves_existing_naptan_data(self):
        from merge_stops import merge

        merge(self.bus_db, self.stops_db, verbose=False)

        conn = sqlite3.connect(self.stops_db)
        row = conn.execute("SELECT common_name FROM stops WHERE atco_code='020033095'").fetchone()
        conn.close()
        self.assertEqual(row[0], "Market Street", "Original NaPTAN data should be preserved")

    def test_validate_after_merge(self):
        from merge_stops import merge, validate

        merge(self.bus_db, self.stops_db, verbose=False)
        resolved, unresolved = validate(self.bus_db, self.stops_db, verbose=False)

        self.assertGreater(resolved, 0, "Some stops must be resolved after merge")
        self.assertEqual(unresolved, 0, "All timetable stops must be resolved after merge")


# ---------------------------------------------------------------------------
# Test 3: StopService resolves bus stop IDs
# ---------------------------------------------------------------------------

class TestStopService(unittest.TestCase):
    """Verify that StopService can resolve TransXChange bus stop IDs."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.stops_db = os.path.join(self.tmpdir, "stops.db")
        self.bus_db = os.path.join(self.tmpdir, "bus.db")

        _create_stops_db(self.stops_db, [
            ("020033095", "Market Street", 54.05, -2.80),
        ])

        _create_bus_db(
            self.bus_db,
            bus_stops=[
                ("1290BOB20410", "Bowness Pier", 54.3651, -2.9228),
            ],
            stop_times=[
                ("trip1", "1290BOB20410", "09:00:00", "09:00:00", 1),
            ],
        )

    def test_get_stop_from_naptan(self):
        from app.data.stops import StopService

        svc = StopService(base_dir=self.tmpdir)
        result = svc.get_stop("020033095")
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "Market Street")

    def test_get_stop_from_bus_stops_fallback(self):
        from app.data.stops import StopService

        svc = StopService(base_dir=self.tmpdir)
        result = svc.get_stop("1290BOB20410")
        self.assertIsNotNone(result, "StopService should fall back to bus.bus_stops")
        self.assertEqual(result["name"], "Bowness Pier")
        self.assertEqual(result["type"], "bus")

    def test_get_stop_unknown_id(self):
        from app.data.stops import StopService

        svc = StopService(base_dir=self.tmpdir)
        result = svc.get_stop("NONEXISTENT_ID")
        self.assertIsNone(result)

    def test_search_includes_bus_stops(self):
        from app.data.stops import StopService

        svc = StopService(base_dir=self.tmpdir)
        results = svc.search_stops("Bowness")
        names = [r["name"] for r in results]
        self.assertIn("Bowness Pier", names, "Search should find bus_stops entries")

    def test_validate_bus_stop_coverage(self):
        from app.data.stops import StopService

        svc = StopService(base_dir=self.tmpdir)
        resolved, unresolved, sample = svc.validate_bus_stop_coverage()
        self.assertEqual(resolved, 1)
        self.assertEqual(unresolved, 0)


# ---------------------------------------------------------------------------
# Test 4: Planner resolves bus stops via _resolve_stop
# ---------------------------------------------------------------------------

class TestPlannerStopResolution(unittest.TestCase):
    """Verify that the planner's _resolve_stop falls back to bus.bus_stops."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.stops_db = os.path.join(self.tmpdir, "stops.db")
        self.bus_db = os.path.join(self.tmpdir, "bus.db")

        _create_stops_db(self.stops_db, [
            ("020033095", "Market Street", 54.05, -2.80),
        ])

        _create_bus_db(
            self.bus_db,
            bus_stops=[
                ("1290BOB20410", "Bowness Pier", 54.3651, -2.9228),
                ("1980SN120553", "Kendal Bus Station", 54.3268, -2.7462),
            ],
            stop_times=[
                ("trip1", "1290BOB20410", "09:00:00", "09:00:00", 1),
                ("trip1", "1980SN120553", "09:25:00", "09:25:00", 2),
            ],
            services=[("SVC1", "555", "Stagecoach")],
            trips=[("trip1", "SVC1", "09:00:00")],
        )

    def _get_conn(self):
        conn = sqlite3.connect(self.stops_db)
        conn.row_factory = sqlite3.Row
        conn.execute(f"ATTACH DATABASE '{self.bus_db}' AS bus")
        return conn

    def test_resolve_naptan_stop(self):
        from app.domain.planner.planner import JourneyPlanner

        planner = JourneyPlanner()
        conn = self._get_conn()
        result = planner._resolve_stop(conn, "020033095")
        conn.close()

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "Market Street")

    def test_resolve_transxchange_stop_via_fallback(self):
        from app.domain.planner.planner import JourneyPlanner

        planner = JourneyPlanner()
        conn = self._get_conn()
        result = planner._resolve_stop(conn, "1290BOB20410")
        conn.close()

        self.assertIsNotNone(result, "Planner should resolve TransXChange stop via bus.bus_stops")
        self.assertEqual(result["name"], "Bowness Pier")

    def test_resolve_unknown_stop_returns_none(self):
        from app.domain.planner.planner import JourneyPlanner

        planner = JourneyPlanner()
        conn = self._get_conn()
        result = planner._resolve_stop(conn, "DOES_NOT_EXIST")
        conn.close()

        self.assertIsNone(result)

    def test_get_stop_name_falls_back(self):
        from app.domain.planner.planner import JourneyPlanner

        planner = JourneyPlanner()
        conn = self._get_conn()
        name = planner._get_stop_name(conn, "1980SN120553")
        conn.close()

        self.assertEqual(name, "Kendal Bus Station")

    def test_catchment_finds_bus_stops(self):
        from app.domain.planner.planner import JourneyPlanner

        planner = JourneyPlanner()
        conn = self._get_conn()
        # Search near Bowness Pier
        nearby = planner._catchment_stops(conn, 54.3651, -2.9228, meters=500)
        conn.close()

        ids = [s["id"] for s in nearby]
        self.assertIn("1290BOB20410", ids, "Catchment should find bus_stops entries")

    def test_plan_raises_clear_error_for_missing_stop(self):
        """The planner should give a clear error when a stop ID cannot be resolved."""
        from app.domain.planner.planner import JourneyPlanner
        from app.domain.planner.exceptions import NoRouteFoundError

        planner = JourneyPlanner()
        planner.DB = Path(self.stops_db)

        with self.assertRaises(NoRouteFoundError) as ctx:
            planner.plan(
                origin_id="NONEXISTENT_STOP",
                destination_id="1290BOB20410",
                time_type="depart_at",
                time_iso=datetime.now(),
                modes="bus",
                max_options=3,
            )
        self.assertIn("not found", str(ctx.exception).lower())
        self.assertIn("merge_stops", str(ctx.exception).lower())


# ---------------------------------------------------------------------------
# Test 5: Frontend isRoutableStop accepts TransXChange ATCO codes
# ---------------------------------------------------------------------------

class TestIsRoutableStop(unittest.TestCase):
    """Verify the frontend utility accepts alphanumeric ATCO codes."""

    def test_transxchange_atco_code(self):
        # We can't run TypeScript directly, so we replicate the logic
        def is_routable(sid):
            if not sid:
                return False
            s = str(sid).strip()
            return len(s) >= 3

        self.assertTrue(is_routable("1290BOB20410"))
        self.assertTrue(is_routable("1980SN120553"))
        self.assertTrue(is_routable("RAIL:LAN"))
        self.assertFalse(is_routable(""))
        self.assertFalse(is_routable(None))
        self.assertFalse(is_routable("AB"))  # too short


# ---------------------------------------------------------------------------
# Test 6: load_bus_timetable creates bus_stops table
# ---------------------------------------------------------------------------

class TestTimetableLoaderSchema(unittest.TestCase):
    """Verify the loader creates the bus_stops table."""

    def test_ensure_tables_creates_bus_stops(self):
        conn = sqlite3.connect(":memory:")
        # Import the ensure_tables function
        from load_bus_timetable import ensure_tables

        ensure_tables(conn)

        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        self.assertIn("bus_stops", tables, "ensure_tables must create bus_stops table")
        conn.close()

    def test_bus_stops_table_has_correct_columns(self):
        conn = sqlite3.connect(":memory:")
        from load_bus_timetable import ensure_tables

        ensure_tables(conn)

        cols = [
            r[1]
            for r in conn.execute("PRAGMA table_info(bus_stops)").fetchall()
        ]
        self.assertIn("atco_code", cols)
        self.assertIn("common_name", cols)
        self.assertIn("latitude", cols)
        self.assertIn("longitude", cols)
        conn.close()


if __name__ == "__main__":
    unittest.main()

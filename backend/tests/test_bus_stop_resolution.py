"""
Tests for bus stop data integrity and resolution.

These tests verify that:
1. All bus timetable stop_ids in bus.db can be resolved to metadata in stops.db
2. The /stops and /api/stops endpoints return valid stop data
3. Frontend-selected bus stops can be validated
4. The planner does not fail due to unresolved bus stop references
5. The sync_bus_stops module functions work correctly

Run with:
    cd /workspace/backend && python -m pytest tests/ -v
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure backend is on the import path
BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

# Database paths (auto-detected)
BUS_DB = None
STOPS_DB = None

for candidate_dir in [ROOT_DIR, BACKEND_DIR, Path("/workspace/backend")]:
    if (candidate_dir / "bus.db").exists():
        BUS_DB = str(candidate_dir / "bus.db")
    if (candidate_dir / "stops.db").exists():
        STOPS_DB = str(candidate_dir / "stops.db")
    if BUS_DB and STOPS_DB:
        break

# Skip all tests if DBs don't exist
pytestmark = pytest.mark.skipif(
    not BUS_DB or not STOPS_DB,
    reason="bus.db or stops.db not found — cannot run integration tests",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def bus_conn():
    conn = sqlite3.connect(BUS_DB)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def stops_conn():
    conn = sqlite3.connect(STOPS_DB)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def all_bus_stop_ids(bus_conn):
    cur = bus_conn.execute(
        "SELECT DISTINCT stop_id FROM stop_times "
        "WHERE stop_id IS NOT NULL AND stop_id != ''"
    )
    return {row[0] for row in cur.fetchall()}


@pytest.fixture(scope="module")
def all_stops_atco_codes(stops_conn):
    cur = stops_conn.execute("SELECT atco_code FROM stops")
    return {row[0] for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# 1. Bus timetable stop IDs resolve to metadata
# ---------------------------------------------------------------------------

class TestBusStopResolution:
    """Verify that bus.db stop_times.stop_id values exist in stops.db."""

    def test_all_bus_stop_ids_exist_in_stops_db(
        self, all_bus_stop_ids, all_stops_atco_codes
    ):
        """Every bus stop ID from stop_times must have a matching atco_code in stops."""
        missing = all_bus_stop_ids - all_stops_atco_codes
        pct_resolved = (
            (len(all_bus_stop_ids) - len(missing)) / len(all_bus_stop_ids) * 100
            if all_bus_stop_ids
            else 0
        )
        assert pct_resolved >= 95.0, (
            f"Only {pct_resolved:.1f}% of bus stop IDs resolved. "
            f"{len(missing)} unresolved out of {len(all_bus_stop_ids)}. "
            f"Sample: {sorted(missing)[:10]}"
        )

    def test_zero_unresolved_after_sync(
        self, all_bus_stop_ids, all_stops_atco_codes
    ):
        """After running sync_bus_stops.py, there should be zero unresolved IDs."""
        missing = all_bus_stop_ids - all_stops_atco_codes
        assert len(missing) == 0, (
            f"{len(missing)} bus stop IDs are unresolved: {sorted(missing)[:20]}"
        )

    def test_resolved_stops_have_coordinates(self, all_bus_stop_ids, stops_conn):
        """Resolved bus stops should have valid lat/lon coordinates."""
        sample_ids = sorted(all_bus_stop_ids)[:100]
        no_coords = []
        for sid in sample_ids:
            row = stops_conn.execute(
                "SELECT latitude, longitude FROM stops WHERE atco_code = ?",
                (sid,),
            ).fetchone()
            if row is None:
                continue  # tested separately
            if row["latitude"] is None or row["longitude"] is None:
                no_coords.append(sid)

        assert len(no_coords) == 0, (
            f"{len(no_coords)} stops have no coordinates: {no_coords[:10]}"
        )

    def test_resolved_stops_have_name(self, all_bus_stop_ids, stops_conn):
        """Resolved bus stops should have a common_name."""
        sample_ids = sorted(all_bus_stop_ids)[:100]
        no_name = []
        for sid in sample_ids:
            row = stops_conn.execute(
                "SELECT common_name FROM stops WHERE atco_code = ?",
                (sid,),
            ).fetchone()
            if row is None:
                continue
            if not row["common_name"] or row["common_name"].strip() == "":
                no_name.append(sid)

        assert len(no_name) == 0, (
            f"{len(no_name)} stops have no name: {no_name[:10]}"
        )

    def test_join_key_consistency(self):
        """Confirm the join key between bus.db and stops.db is correct."""
        conn = sqlite3.connect(BUS_DB)
        conn.execute("ATTACH DATABASE ? AS sdb", (STOPS_DB,))
        count = conn.execute(
            "SELECT COUNT(DISTINCT st.stop_id) "
            "FROM stop_times st "
            "JOIN sdb.stops s ON st.stop_id = s.atco_code"
        ).fetchone()[0]
        total = conn.execute(
            "SELECT COUNT(DISTINCT stop_id) FROM stop_times "
            "WHERE stop_id IS NOT NULL"
        ).fetchone()[0]
        conn.close()

        assert count == total, (
            f"Join key mismatch: {count}/{total} stop_ids match atco_code"
        )


# ---------------------------------------------------------------------------
# 2. Frontend stop validation
# ---------------------------------------------------------------------------

class TestFrontendStopValidation:
    """Verify stops returned by API endpoints are valid for the planner."""

    def test_api_stops_return_valid_ids(self, stops_conn):
        """The /api/stops endpoint returns stops with valid atco_codes."""
        # Simulate what the API does: query stops by name
        cur = stops_conn.execute(
            "SELECT atco_code, common_name, latitude, longitude "
            "FROM stops WHERE common_name LIKE '%Station%' LIMIT 10"
        )
        rows = cur.fetchall()
        for row in rows:
            assert row["atco_code"] is not None
            assert len(row["atco_code"]) >= 8
            assert row["common_name"] is not None

    def test_routable_stops_are_in_stops_db(self, all_bus_stop_ids, all_stops_atco_codes):
        """All IDs returned by /api/routable-stops exist in stops.db."""
        # /api/routable-stops returns bus.db stop_ids — they must all be in stops.db
        for sid in sorted(all_bus_stop_ids)[:200]:
            assert sid in all_stops_atco_codes, (
                f"Routable stop {sid} not found in stops.db"
            )

    def test_naptan_atco_code_format(self, all_bus_stop_ids):
        """Bus stop IDs should be valid NaPTAN ATCO codes (alphanumeric, 8-12 chars)."""
        import re
        pattern = re.compile(r"^[A-Za-z0-9]{8,12}$")
        invalid = [
            sid for sid in sorted(all_bus_stop_ids)[:500]
            if not pattern.match(sid)
        ]
        assert len(invalid) == 0, (
            f"{len(invalid)} stop IDs don't match NaPTAN format: {invalid[:10]}"
        )


# ---------------------------------------------------------------------------
# 3. Planner does not fail due to unresolved stops
# ---------------------------------------------------------------------------

class TestPlannerStopResolution:
    """Verify the planner can resolve bus stops referenced in timetables."""

    def test_planner_can_resolve_catchment_stops(self, all_bus_stop_ids, stops_conn):
        """The planner's catchment query should find nearby stops with coords."""
        # Pick a random stop with known coords
        sample_id = sorted(all_bus_stop_ids)[0]
        row = stops_conn.execute(
            "SELECT latitude, longitude FROM stops WHERE atco_code = ?",
            (sample_id,),
        ).fetchone()
        if row is None or row["latitude"] is None:
            pytest.skip("Sample stop has no coordinates")

        lat, lon = row["latitude"], row["longitude"]
        # Simulate catchment query (same as planner._catchment_stops)
        lat_delta = 800 / 111320.0
        import math
        lon_delta = 800 / (111320.0 * math.cos(math.radians(lat)))

        cur = stops_conn.execute(
            "SELECT atco_code, common_name, latitude, longitude "
            "FROM stops "
            "WHERE latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ? "
            "LIMIT 50",
            (lat - lat_delta, lat + lat_delta, lon - lon_delta, lon + lon_delta),
        )
        nearby = cur.fetchall()
        assert len(nearby) > 0, (
            f"No catchment stops found near ({lat}, {lon})"
        )

    def test_planner_stop_name_lookup(self, all_bus_stop_ids, stops_conn):
        """_get_stop_name should return a meaningful name for bus stops."""
        for sid in sorted(all_bus_stop_ids)[:50]:
            row = stops_conn.execute(
                "SELECT common_name FROM stops WHERE atco_code = ?",
                (sid,),
            ).fetchone()
            assert row is not None, f"Stop {sid} not in stops.db"
            assert row["common_name"] is not None, f"Stop {sid} has no name"
            assert row["common_name"] != sid, (
                f"Stop {sid} name is just the ID — metadata missing"
            )


# ---------------------------------------------------------------------------
# 4. Validation module
# ---------------------------------------------------------------------------

class TestValidationModule:
    """Test the app.data.validation module."""

    def test_validate_bus_stop_resolution(self):
        from app.data.validation import validate_bus_stop_resolution
        report = validate_bus_stop_resolution(BUS_DB, STOPS_DB)
        assert report.total_bus_stop_ids > 0
        assert report.resolved > 0
        assert report.resolution_pct >= 95.0
        assert report.is_healthy

    def test_check_stop_exists(self, all_bus_stop_ids):
        from app.data.validation import check_stop_exists
        sample_id = sorted(all_bus_stop_ids)[0]
        assert check_stop_exists(sample_id, STOPS_DB) is True
        assert check_stop_exists("NONEXISTENT_STOP_999", STOPS_DB) is False

    def test_get_stop_metadata(self, all_bus_stop_ids):
        from app.data.validation import get_stop_metadata
        sample_id = sorted(all_bus_stop_ids)[0]
        meta = get_stop_metadata(sample_id, STOPS_DB)
        assert meta is not None
        assert meta["id"] == sample_id
        assert meta["name"] is not None
        assert meta["lat"] is not None
        assert meta["lon"] is not None

    def test_validation_fails_on_missing_db(self):
        from app.data.validation import validate_bus_stop_resolution
        from app.data.exceptions import StaticDataMissingError
        with pytest.raises(StaticDataMissingError):
            validate_bus_stop_resolution("/nonexistent/bus.db", STOPS_DB)


# ---------------------------------------------------------------------------
# 5. sync_bus_stops module functions
# ---------------------------------------------------------------------------

class TestSyncBusStops:
    """Test sync_bus_stops utility functions (no network calls)."""

    def test_find_missing_stop_ids(self):
        sys.path.insert(0, str(BACKEND_DIR))
        from sync_bus_stops import find_missing_stop_ids
        missing = find_missing_stop_ids(BUS_DB, STOPS_DB)
        assert isinstance(missing, set)
        # After sync, should be empty
        assert len(missing) == 0, (
            f"Expected 0 missing stop IDs after sync, got {len(missing)}"
        )

    def test_get_all_bus_stop_ids(self):
        from sync_bus_stops import get_all_bus_stop_ids
        ids = get_all_bus_stop_ids(BUS_DB)
        assert isinstance(ids, set)
        assert len(ids) > 0

    def test_validate_resolution(self):
        from sync_bus_stops import validate_resolution
        total, resolved, no_coords = validate_resolution(BUS_DB, STOPS_DB)
        assert total > 0
        assert resolved == total
        assert no_coords == 0

    def test_insert_resolved_stops_idempotent(self):
        """Re-inserting the same stops should not cause errors."""
        from sync_bus_stops import insert_resolved_stops
        # Insert a fake stop, then insert again
        fake_stops = {
            "TEST_ATCO_999": {
                "atco_code": "TEST_ATCO_999",
                "naptan_code": None,
                "common_name": "Test Stop",
                "latitude": 53.5,
                "longitude": -2.5,
            }
        }
        n1 = insert_resolved_stops(STOPS_DB, fake_stops)
        n2 = insert_resolved_stops(STOPS_DB, fake_stops)  # should not fail
        # Clean up
        conn = sqlite3.connect(STOPS_DB)
        conn.execute("DELETE FROM stops WHERE atco_code = 'TEST_ATCO_999'")
        conn.commit()
        conn.close()

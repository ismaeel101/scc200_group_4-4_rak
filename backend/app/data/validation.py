"""
Bus stop data integrity validation.

Provides functions to verify that all bus timetable stop_ids can be
resolved to metadata (name, coordinates) in stops.db.  Used at startup
and by the test suite.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import NamedTuple, Set, Tuple

from app.data.exceptions import StaticDataMissingError


class StopResolutionReport(NamedTuple):
    """Summary of bus stop ID resolution against stops.db."""
    total_bus_stop_ids: int
    resolved: int
    resolved_with_coords: int
    unresolved_ids: Set[str]

    @property
    def resolution_pct(self) -> float:
        if self.total_bus_stop_ids == 0:
            return 100.0
        return self.resolved / self.total_bus_stop_ids * 100.0

    @property
    def is_healthy(self) -> bool:
        """True when ≥ 95 % of bus stop IDs can be resolved."""
        return self.resolution_pct >= 95.0


def validate_bus_stop_resolution(
    bus_db: str | Path,
    stops_db: str | Path,
) -> StopResolutionReport:
    """Check that bus.db stop_times stop_ids resolve in stops.db.

    Raises
    ------
    StaticDataMissingError
        If either database file is missing or the stops table is empty.
    """
    bus_db = Path(bus_db)
    stops_db = Path(stops_db)

    if not bus_db.exists():
        raise StaticDataMissingError(f"bus.db not found at {bus_db}")
    if not stops_db.exists():
        raise StaticDataMissingError(f"stops.db not found at {stops_db}")

    conn = sqlite3.connect(str(bus_db))
    try:
        conn.execute("ATTACH DATABASE ? AS sdb", (str(stops_db),))

        # Total distinct bus stop IDs
        total = conn.execute(
            "SELECT COUNT(DISTINCT stop_id) FROM stop_times "
            "WHERE stop_id IS NOT NULL AND stop_id != ''"
        ).fetchone()[0]

        if total == 0:
            raise StaticDataMissingError("bus.db stop_times table is empty")

        # Resolved (have a matching row in stops.db)
        resolved = conn.execute(
            "SELECT COUNT(DISTINCT st.stop_id) "
            "FROM stop_times st "
            "JOIN sdb.stops s ON st.stop_id = s.atco_code"
        ).fetchone()[0]

        # Resolved with valid coordinates
        with_coords = conn.execute(
            "SELECT COUNT(DISTINCT st.stop_id) "
            "FROM stop_times st "
            "JOIN sdb.stops s ON st.stop_id = s.atco_code "
            "WHERE s.latitude IS NOT NULL AND s.longitude IS NOT NULL "
            "AND s.latitude != 0 AND s.longitude != 0"
        ).fetchone()[0]

        # Unresolved IDs (for diagnostics)
        unresolved_cur = conn.execute(
            "SELECT DISTINCT st.stop_id "
            "FROM stop_times st "
            "LEFT JOIN sdb.stops s ON st.stop_id = s.atco_code "
            "WHERE s.atco_code IS NULL "
            "AND st.stop_id IS NOT NULL AND st.stop_id != ''"
        )
        unresolved_ids = {row[0] for row in unresolved_cur.fetchall()}

    finally:
        conn.close()

    return StopResolutionReport(
        total_bus_stop_ids=total,
        resolved=resolved,
        resolved_with_coords=with_coords,
        unresolved_ids=unresolved_ids,
    )


def check_stop_exists(
    stop_id: str,
    stops_db: str | Path,
) -> bool:
    """Return True if *stop_id* exists in stops.db."""
    stops_db = Path(stops_db)
    if not stops_db.exists():
        return False
    conn = sqlite3.connect(str(stops_db))
    try:
        row = conn.execute(
            "SELECT 1 FROM stops WHERE atco_code = ? LIMIT 1",
            (stop_id,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_stop_metadata(
    stop_id: str,
    stops_db: str | Path,
) -> dict | None:
    """Return stop metadata dict or None if not found."""
    stops_db = Path(stops_db)
    if not stops_db.exists():
        return None
    conn = sqlite3.connect(str(stops_db))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT atco_code AS id, common_name AS name, "
            "latitude AS lat, longitude AS lon "
            "FROM stops WHERE atco_code = ? LIMIT 1",
            (stop_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

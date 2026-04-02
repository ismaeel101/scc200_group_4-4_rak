#!/usr/bin/env python3
"""Merge bus stop metadata from bus.db into stops.db.

The TransXChange timetable XML files reference stops by their NaPTAN ATCO
codes (e.g. ``1290BOB20410``).  These same codes appear in the ``bus_stops``
table that the timetable loader creates inside ``bus.db``.

The NaPTAN XML export loaded into ``stops.db`` may cover a different (or
narrower) set of stops.  This script copies every ``bus_stops`` row from
``bus.db`` into the ``stops`` table of ``stops.db`` so that a single,
consistent lookup table exists for the planner and API.

Usage:
  python merge_stops.py [--bus-db backend/bus.db] [--stops-db backend/stops.db]
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from typing import Optional


def merge(bus_db_path: str, stops_db_path: str, *, verbose: bool = True) -> int:
    """Insert bus_stops rows from *bus_db_path* into *stops_db_path*.

    Returns the number of rows inserted.
    """
    if not os.path.exists(bus_db_path):
        print(f"bus.db not found: {bus_db_path}", file=sys.stderr)
        return 0
    if not os.path.exists(stops_db_path):
        print(f"stops.db not found: {stops_db_path}", file=sys.stderr)
        return 0

    bus_conn = sqlite3.connect(bus_db_path)
    bus_conn.row_factory = sqlite3.Row

    # Check that bus_stops table exists
    tables = [
        r[0]
        for r in bus_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    if "bus_stops" not in tables:
        print("bus_stops table not found in bus.db — run the timetable loader first", file=sys.stderr)
        bus_conn.close()
        return 0

    rows = bus_conn.execute(
        "SELECT atco_code, common_name, latitude, longitude FROM bus_stops"
    ).fetchall()
    bus_conn.close()

    if not rows:
        if verbose:
            print("bus_stops table is empty — nothing to merge")
        return 0

    stops_conn = sqlite3.connect(stops_db_path)

    # Ensure the stops table exists (matches load_stops.py schema)
    stops_conn.execute(
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

    inserted = 0
    for r in rows:
        # INSERT OR IGNORE preserves richer NaPTAN data when already present.
        # We only fill in stops that are *missing* from the NaPTAN export.
        try:
            stops_conn.execute(
                """
                INSERT OR IGNORE INTO stops
                    (atco_code, common_name, latitude, longitude, stop_type)
                VALUES (?, ?, ?, ?, 'BCT')
                """,
                (r["atco_code"], r["common_name"], r["latitude"], r["longitude"]),
            )
            if stops_conn.total_changes:
                inserted += 1
        except Exception as exc:
            if verbose:
                print(f"  skip {r['atco_code']}: {exc}")

    stops_conn.commit()

    # Report final counts
    total = stops_conn.execute("SELECT COUNT(*) FROM stops").fetchone()[0]
    stops_conn.close()

    if verbose:
        print(f"Merged {inserted} bus stops into stops.db  (total stops now: {total})")

    return inserted


def validate(bus_db_path: str, stops_db_path: str, *, verbose: bool = True) -> tuple[int, int]:
    """Check how many bus.stop_times.stop_id values can be resolved in stops.db.

    Returns (resolved_count, unresolved_count).
    """
    if not os.path.exists(bus_db_path) or not os.path.exists(stops_db_path):
        print("Database files missing — cannot validate", file=sys.stderr)
        return (0, 0)

    conn = sqlite3.connect(stops_db_path)
    try:
        conn.execute(f"ATTACH DATABASE '{bus_db_path}' AS bus")
    except Exception as exc:
        print(f"Cannot attach bus.db: {exc}", file=sys.stderr)
        conn.close()
        return (0, 0)

    resolved = conn.execute(
        """
        SELECT COUNT(DISTINCT st.stop_id)
        FROM bus.stop_times st
        INNER JOIN stops s ON s.atco_code = st.stop_id
        """
    ).fetchone()[0]

    total = conn.execute(
        "SELECT COUNT(DISTINCT stop_id) FROM bus.stop_times"
    ).fetchone()[0]

    unresolved = total - resolved
    conn.close()

    if verbose:
        print(f"Validation: {resolved}/{total} timetable stop IDs resolved ({unresolved} missing)")
        if unresolved > 0:
            # Show a few examples
            conn2 = sqlite3.connect(stops_db_path)
            conn2.execute(f"ATTACH DATABASE '{bus_db_path}' AS bus")
            missing = conn2.execute(
                """
                SELECT DISTINCT st.stop_id
                FROM bus.stop_times st
                LEFT JOIN stops s ON s.atco_code = st.stop_id
                WHERE s.atco_code IS NULL
                LIMIT 10
                """
            ).fetchall()
            conn2.close()
            print("  Sample unresolved IDs:", [r[0] for r in missing])

    return (resolved, unresolved)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Merge bus stop metadata from bus.db into stops.db")
    p.add_argument("--bus-db", default="/workspace/backend/bus.db", help="Path to bus.db")
    p.add_argument("--stops-db", default="/workspace/backend/stops.db", help="Path to stops.db")
    p.add_argument("--validate-only", action="store_true", help="Only validate, don't merge")
    args = p.parse_args(argv)

    if args.validate_only:
        resolved, unresolved = validate(args.bus_db, args.stops_db)
        return 0 if unresolved == 0 else 1

    merge(args.bus_db, args.stops_db)
    resolved, unresolved = validate(args.bus_db, args.stops_db)
    return 0 if unresolved == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
setup_rail_stops.py – Prepare stops.db for rail integration.

1. Adds a `crs_code` column to stops.db (if missing).
2. Populates crs_code for 9100{TIPLOC} entries using rail.db.
3. Inserts RAIL:{tiploc} alias rows into stops.db so the planner can
   resolve rail schedule stops via  WHERE atco_code = 'RAIL:{tiploc}'.
4. Inserts CRS-keyed alias rows (RAIL:{CRS}) for quick CRS lookup.

Idempotent – safe to run multiple times.
"""

import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
# DBs live in the project root (one level above backend/)
PROJECT_ROOT = BASE.parent
STOPS_DB = PROJECT_ROOT / "stops.db"
RAIL_DB = PROJECT_ROOT / "rail.db"


def run(stops_db: Path = STOPS_DB, rail_db: Path = RAIL_DB) -> dict:
    if not stops_db.exists():
        print(f"ERROR: {stops_db} not found"); sys.exit(1)
    if not rail_db.exists():
        print(f"ERROR: {rail_db} not found"); sys.exit(1)

    conn = sqlite3.connect(str(stops_db))
    conn.execute(f"ATTACH DATABASE '{rail_db}' AS rail")

    # ── 1. Add crs_code column ──────────────────────────────────────────
    cols = [r[1] for r in conn.execute("PRAGMA table_info(stops)").fetchall()]
    if "crs_code" not in cols:
        conn.execute("ALTER TABLE stops ADD COLUMN crs_code TEXT")
        conn.commit()
        print("Added crs_code column to stops")
    else:
        print("crs_code column already exists")

    # ── 2. Populate crs_code on 9100* rows ──────────────────────────────
    # NaPTAN pattern: atco_code = '9100{TIPLOC}'
    updated = conn.execute("""
        UPDATE stops
        SET crs_code = (
            SELECT r.crs FROM rail.stations r
            WHERE r.tiploc = SUBSTR(stops.atco_code, 5)
              AND r.crs IS NOT NULL AND r.crs != ''
        )
        WHERE atco_code LIKE '9100%'
          AND (crs_code IS NULL OR crs_code = '')
    """).rowcount
    conn.commit()
    print(f"Populated crs_code for {updated} NaPTAN rail station rows")

    # ── 3. Insert RAIL:{tiploc} alias rows ──────────────────────────────
    # Take lat/lon from the parent 9100* row
    aliases = conn.execute("""
        SELECT
            'RAIL:' || SUBSTR(s.atco_code, 5) AS alias_id,
            s.naptan_code,
            s.common_name,
            s.street,
            s.indicator,
            s.suburb,
            s.town,
            s.latitude,
            s.longitude,
            s.easting,
            s.northing,
            s.administrative_area_ref,
            'RLY' AS stop_type,
            NULL AS bus_stop_type,
            s.crs_code
        FROM stops s
        WHERE s.atco_code LIKE '9100%'
          AND s.latitude IS NOT NULL
          AND s.longitude IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM stops x WHERE x.atco_code = 'RAIL:' || SUBSTR(s.atco_code, 5)
          )
    """).fetchall()

    inserted_tiploc = 0
    for row in aliases:
        try:
            conn.execute("""
                INSERT INTO stops (atco_code, naptan_code, common_name, street,
                                   indicator, suburb, town, latitude, longitude,
                                   easting, northing, administrative_area_ref,
                                   stop_type, bus_stop_type, crs_code)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, row)
            inserted_tiploc += 1
        except sqlite3.IntegrityError:
            pass  # already exists
    conn.commit()
    print(f"Inserted {inserted_tiploc} RAIL:{{tiploc}} alias rows")

    # ── 4. Insert RAIL:{CRS} alias rows (if CRS differs from tiploc) ───
    crs_aliases = conn.execute("""
        SELECT
            'RAIL:' || r.crs AS alias_id,
            s.naptan_code,
            s.common_name,
            s.street,
            s.indicator,
            s.suburb,
            s.town,
            s.latitude,
            s.longitude,
            s.easting,
            s.northing,
            s.administrative_area_ref,
            'RLY' AS stop_type,
            NULL AS bus_stop_type,
            r.crs
        FROM stops s
        JOIN rail.stations r ON r.tiploc = SUBSTR(s.atco_code, 5)
        WHERE s.atco_code LIKE '9100%'
          AND r.crs IS NOT NULL AND r.crs != ''
          AND r.crs != r.tiploc
          AND s.latitude IS NOT NULL AND s.longitude IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM stops x WHERE x.atco_code = 'RAIL:' || r.crs
          )
    """).fetchall()

    inserted_crs = 0
    for row in crs_aliases:
        try:
            conn.execute("""
                INSERT INTO stops (atco_code, naptan_code, common_name, street,
                                   indicator, suburb, town, latitude, longitude,
                                   easting, northing, administrative_area_ref,
                                   stop_type, bus_stop_type, crs_code)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, row)
            inserted_crs += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    print(f"Inserted {inserted_crs} RAIL:{{CRS}} alias rows")

    # ── 5. Create index on crs_code ─────────────────────────────────────
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_stops_crs ON stops(crs_code)")
        conn.commit()
        print("Created index idx_stops_crs")
    except Exception as e:
        print(f"Index creation note: {e}")

    # ── Summary ─────────────────────────────────────────────────────────
    total_rail = conn.execute(
        "SELECT COUNT(*) FROM stops WHERE atco_code LIKE 'RAIL:%'"
    ).fetchone()[0]
    total_crs = conn.execute(
        "SELECT COUNT(*) FROM stops WHERE crs_code IS NOT NULL AND crs_code != ''"
    ).fetchone()[0]

    conn.close()

    summary = {
        "crs_populated": updated,
        "rail_tiploc_inserted": inserted_tiploc,
        "rail_crs_inserted": inserted_crs,
        "total_rail_entries": total_rail,
        "total_crs_entries": total_crs,
    }
    print(f"\nSummary: {summary}")
    return summary


if __name__ == "__main__":
    run()

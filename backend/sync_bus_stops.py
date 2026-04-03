#!/usr/bin/env python3
"""Synchronise stops.db so that every stop_id referenced in bus.db can be
resolved to metadata (name, latitude, longitude).

The script works in three phases:

1. **Gap detection** — find stop_ids in ``bus.db → stop_times`` that have no
   matching row in ``stops.db → stops``.
2. **NaPTAN download** — fetch the official NaPTAN CSV from the DfT API and
   extract metadata for the missing ATCO codes.  Falls back to a local
   NaPTAN XML file if the download fails.
3. **Insertion** — insert resolved stops into ``stops.db`` so that the join
   ``stop_times.stop_id = stops.atco_code`` succeeds for *all* timetable rows.

Usage
-----
    python sync_bus_stops.py                         # auto-detect paths
    python sync_bus_stops.py --bus-db bus.db --stops-db stops.db
    python sync_bus_stops.py --naptan-csv /path/to/Stops.csv   # skip download
    python sync_bus_stops.py --naptan-xml naptan.xml            # use XML fallback

The script is **idempotent** — re-running it will not duplicate rows (INSERT
OR IGNORE).
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# NaPTAN CSV download URL (DfT open-data portal)
NAPTAN_CSV_URL = "https://naptan.api.dft.gov.uk/v1/access-nodes?dataFormat=csv"


# ---------------------------------------------------------------------------
# Phase 1 — gap detection
# ---------------------------------------------------------------------------

def find_missing_stop_ids(bus_db: str, stops_db: str) -> Set[str]:
    """Return the set of stop_ids in bus.db that have no match in stops.db."""
    conn = sqlite3.connect(bus_db)
    try:
        conn.execute(f"ATTACH DATABASE ? AS sdb", (stops_db,))
        cur = conn.execute(
            """
            SELECT DISTINCT st.stop_id
            FROM stop_times st
            LEFT JOIN sdb.stops s ON st.stop_id = s.atco_code
            WHERE s.atco_code IS NULL
              AND st.stop_id IS NOT NULL
              AND st.stop_id != ''
            """
        )
        missing = {row[0] for row in cur.fetchall()}
    finally:
        conn.close()
    return missing


def get_all_bus_stop_ids(bus_db: str) -> Set[str]:
    """Return every distinct stop_id from bus.db stop_times."""
    conn = sqlite3.connect(bus_db)
    try:
        cur = conn.execute("SELECT DISTINCT stop_id FROM stop_times WHERE stop_id IS NOT NULL AND stop_id != ''")
        return {row[0] for row in cur.fetchall()}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Phase 2 — NaPTAN data acquisition
# ---------------------------------------------------------------------------

def _download_naptan_csv(dest_path: str) -> bool:
    """Download the NaPTAN CSV from DfT and save to *dest_path*.

    Returns True on success.
    """
    try:
        import urllib.request
        print(f"  Downloading NaPTAN CSV from {NAPTAN_CSV_URL} …")
        urllib.request.urlretrieve(NAPTAN_CSV_URL, dest_path)
        print(f"  Saved to {dest_path}  ({os.path.getsize(dest_path)} bytes)")
        return True
    except Exception as exc:
        print(f"  Download failed: {exc}")
        return False


def _parse_naptan_csv(csv_path: str, wanted: Set[str]) -> Dict[str, dict]:
    """Parse a NaPTAN CSV file and return metadata for *wanted* ATCO codes.

    The DfT CSV typically has columns (order may vary):
        ATCOCode, NaptanCode, CommonName, Street, Indicator, …,
        Latitude, Longitude, …
    """
    found: Dict[str, dict] = {}
    encoding_attempts = ["utf-8-sig", "utf-8", "latin-1"]
    for enc in encoding_attempts:
        try:
            with open(csv_path, newline="", encoding=enc) as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    atco = (row.get("ATCOCode") or row.get("AtcoCode") or "").strip()
                    if atco and atco in wanted:
                        try:
                            lat = float(row.get("Latitude", ""))
                            lon = float(row.get("Longitude", ""))
                        except (ValueError, TypeError):
                            lat = None
                            lon = None
                        found[atco] = {
                            "atco_code": atco,
                            "naptan_code": (row.get("NaptanCode") or "").strip() or None,
                            "common_name": (row.get("CommonName") or "").strip() or None,
                            "street": (row.get("Street") or "").strip() or None,
                            "indicator": (row.get("Indicator") or "").strip() or None,
                            "suburb": (row.get("Suburb") or "").strip() or None,
                            "town": (row.get("Town") or "").strip() or None,
                            "latitude": lat,
                            "longitude": lon,
                            "stop_type": (row.get("StopType") or "").strip() or None,
                            "bus_stop_type": (row.get("BusStopType") or "").strip() or None,
                            "administrative_area_ref": (row.get("AdministrativeAreaCode") or "").strip() or None,
                        }
            break
        except UnicodeDecodeError:
            continue
    return found


def _parse_naptan_xml(xml_path: str, wanted: Set[str]) -> Dict[str, dict]:
    """Parse a NaPTAN XML file and return metadata for *wanted* ATCO codes."""
    import xml.etree.ElementTree as ET

    found: Dict[str, dict] = {}
    tree = ET.parse(xml_path)
    root = tree.getroot()

    ns_uri = ""
    if root.tag.startswith("{"):
        ns_uri = root.tag.split("}")[0].strip("{")

    def q(name: str) -> str:
        return f"{{{ns_uri}}}{name}" if ns_uri else name

    for sp in root.findall(f".//{q('StopPoint')}"):
        atco_el = sp.find(q("AtcoCode"))
        atco_code = atco_el.text.strip() if atco_el is not None and atco_el.text else None
        if not atco_code or atco_code not in wanted:
            continue

        naptan_el = sp.find(q("NaptanCode"))
        naptan_code = naptan_el.text.strip() if naptan_el is not None and naptan_el.text else None

        desc = sp.find(q("Descriptor"))
        common_name = street = indicator = None
        if desc is not None:
            cn = desc.find(q("CommonName"))
            common_name = cn.text.strip() if cn is not None and cn.text else None
            st = desc.find(q("Street"))
            street = st.text.strip() if st is not None and st.text else None
            ind = desc.find(q("Indicator"))
            indicator = ind.text.strip() if ind is not None and ind.text else None

        place = sp.find(q("Place"))
        suburb = town = latitude = longitude = None
        if place is not None:
            sub = place.find(q("Suburb"))
            suburb = sub.text.strip() if sub is not None and sub.text else None
            t = place.find(q("Town"))
            town = t.text.strip() if t is not None and t.text else None
            loc = place.find(q("Location"))
            if loc is not None:
                trans = loc.find(q("Translation"))
                if trans is not None:
                    try:
                        lon_el = trans.find(q("Longitude"))
                        latitude_el = trans.find(q("Latitude"))
                        longitude = float(lon_el.text) if lon_el is not None and lon_el.text else None
                        latitude = float(latitude_el.text) if latitude_el is not None and latitude_el.text else None
                    except (ValueError, TypeError):
                        pass

        found[atco_code] = {
            "atco_code": atco_code,
            "naptan_code": naptan_code,
            "common_name": common_name,
            "street": street,
            "indicator": indicator,
            "suburb": suburb,
            "town": town,
            "latitude": latitude,
            "longitude": longitude,
            "stop_type": None,
            "bus_stop_type": None,
            "administrative_area_ref": None,
        }

    return found


def resolve_stops(
    missing: Set[str],
    naptan_csv: Optional[str] = None,
    naptan_xml: Optional[str] = None,
) -> Tuple[Dict[str, dict], Set[str]]:
    """Try to resolve *missing* stop IDs via NaPTAN data.

    Returns (resolved_dict, still_missing_set).
    """
    resolved: Dict[str, dict] = {}
    still_missing = set(missing)

    # 1. Try user-provided CSV
    if naptan_csv and os.path.exists(naptan_csv):
        print(f"Phase 2a: parsing NaPTAN CSV {naptan_csv} …")
        found = _parse_naptan_csv(naptan_csv, still_missing)
        resolved.update(found)
        still_missing -= found.keys()
        print(f"  Resolved {len(found)} stops from CSV, {len(still_missing)} still missing")

    # 2. Try downloading CSV from DfT if needed
    if still_missing and not naptan_csv:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp_path = tmp.name
        ok = _download_naptan_csv(tmp_path)
        if ok and os.path.getsize(tmp_path) > 1000:
            print(f"Phase 2b: parsing downloaded NaPTAN CSV …")
            found = _parse_naptan_csv(tmp_path, still_missing)
            resolved.update(found)
            still_missing -= found.keys()
            print(f"  Resolved {len(found)} stops from downloaded CSV, {len(still_missing)} still missing")
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # 3. Try NaPTAN XML fallback
    if still_missing and naptan_xml and os.path.exists(naptan_xml):
        print(f"Phase 2c: parsing NaPTAN XML {naptan_xml} …")
        found = _parse_naptan_xml(naptan_xml, still_missing)
        resolved.update(found)
        still_missing -= found.keys()
        print(f"  Resolved {len(found)} stops from XML, {len(still_missing)} still missing")

    return resolved, still_missing


# ---------------------------------------------------------------------------
# Phase 3 — insertion
# ---------------------------------------------------------------------------

def insert_resolved_stops(stops_db: str, resolved: Dict[str, dict]) -> int:
    """Insert resolved stop metadata into stops.db.  Returns inserted count."""
    if not resolved:
        return 0

    conn = sqlite3.connect(stops_db)
    cur = conn.cursor()

    # Ensure the table exists (in case we're running against a fresh DB)
    cur.execute(
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

    rows = [
        (
            s["atco_code"],
            s.get("naptan_code"),
            s.get("common_name"),
            s.get("street"),
            s.get("indicator"),
            s.get("suburb"),
            s.get("town"),
            s.get("latitude"),
            s.get("longitude"),
            None,  # easting
            None,  # northing
            s.get("administrative_area_ref"),
            s.get("stop_type"),
            s.get("bus_stop_type"),
        )
        for s in resolved.values()
    ]

    cur.executemany(
        """
        INSERT OR IGNORE INTO stops (
            atco_code, naptan_code, common_name, street, indicator,
            suburb, town, latitude, longitude, easting, northing,
            administrative_area_ref, stop_type, bus_stop_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    inserted = cur.rowcount
    conn.close()
    return inserted


def insert_stub_stops(stops_db: str, still_missing: Set[str]) -> int:
    """Insert minimal stub rows for any remaining unresolved stop_ids.

    These stubs have common_name = atco_code and NULL lat/lon so the
    system can at least recognise that the stop exists, even if it cannot
    be placed on a map.  A warning is printed for each.
    """
    if not still_missing:
        return 0

    conn = sqlite3.connect(stops_db)
    cur = conn.cursor()

    rows = [
        (sid, None, sid, None, None, None, None, None, None, None, None, None, "BCT", None)
        for sid in still_missing
    ]

    cur.executemany(
        """
        INSERT OR IGNORE INTO stops (
            atco_code, naptan_code, common_name, street, indicator,
            suburb, town, latitude, longitude, easting, northing,
            administrative_area_ref, stop_type, bus_stop_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    inserted = cur.rowcount
    conn.close()
    return inserted


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_resolution(bus_db: str, stops_db: str) -> Tuple[int, int, int]:
    """Return (total_bus_stop_ids, resolved, unresolved_no_coords).

    Raises SystemExit if more than 5 % are completely unresolvable.
    """
    conn = sqlite3.connect(bus_db)
    conn.execute("ATTACH DATABASE ? AS sdb", (stops_db,))

    total = conn.execute("SELECT COUNT(DISTINCT stop_id) FROM stop_times WHERE stop_id IS NOT NULL").fetchone()[0]
    resolved = conn.execute(
        """
        SELECT COUNT(DISTINCT st.stop_id)
        FROM stop_times st
        JOIN sdb.stops s ON st.stop_id = s.atco_code
        """
    ).fetchone()[0]
    with_coords = conn.execute(
        """
        SELECT COUNT(DISTINCT st.stop_id)
        FROM stop_times st
        JOIN sdb.stops s ON st.stop_id = s.atco_code
        WHERE s.latitude IS NOT NULL AND s.longitude IS NOT NULL
        """
    ).fetchone()[0]
    conn.close()

    unresolved = total - resolved
    no_coords = resolved - with_coords

    return total, resolved, no_coords


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Synchronise stops.db with bus.db stop references."
    )
    parser.add_argument(
        "--bus-db",
        default=None,
        help="Path to bus.db (default: auto-detect in workspace)",
    )
    parser.add_argument(
        "--stops-db",
        default=None,
        help="Path to stops.db (default: auto-detect in workspace)",
    )
    parser.add_argument(
        "--naptan-csv",
        default=None,
        help="Path to a pre-downloaded NaPTAN CSV (Stops.csv)",
    )
    parser.add_argument(
        "--naptan-xml",
        default=None,
        help="Path to a NaPTAN XML file (fallback)",
    )
    parser.add_argument(
        "--allow-stubs",
        action="store_true",
        help="Insert stub rows (name=ATCO code, no lat/lon) for stops that "
             "cannot be resolved from NaPTAN.  Without this flag, unresolved "
             "stops are reported but not inserted.",
    )
    args = parser.parse_args(argv)

    # Auto-detect database paths
    search_dirs = [
        Path(__file__).resolve().parent,                     # backend/
        Path(__file__).resolve().parent.parent,              # project root
        Path("/workspace/backend"),
    ]
    bus_db = args.bus_db
    stops_db = args.stops_db

    if not bus_db:
        for d in search_dirs:
            candidate = d / "bus.db"
            if candidate.exists():
                bus_db = str(candidate)
                break
    if not stops_db:
        for d in search_dirs:
            candidate = d / "stops.db"
            if candidate.exists():
                stops_db = str(candidate)
                break

    if not bus_db or not os.path.exists(bus_db):
        print("ERROR: bus.db not found. Pass --bus-db.", file=sys.stderr)
        return 1
    if not stops_db or not os.path.exists(stops_db):
        print("ERROR: stops.db not found. Pass --stops-db.", file=sys.stderr)
        return 1

    print(f"bus.db  : {bus_db}")
    print(f"stops.db: {stops_db}")

    # Phase 1 — gap detection
    print("\nPhase 1: Detecting missing stop IDs …")
    missing = find_missing_stop_ids(bus_db, stops_db)
    total_bus = len(get_all_bus_stop_ids(bus_db))
    print(f"  bus.db distinct stop_ids : {total_bus}")
    print(f"  Missing from stops.db   : {len(missing)}")

    if not missing:
        print("\n✓ All bus stop IDs already exist in stops.db — nothing to do.")
        return 0

    # Phase 2 — resolve via NaPTAN
    print(f"\nPhase 2: Resolving {len(missing)} missing stops from NaPTAN …")
    resolved, still_missing = resolve_stops(
        missing,
        naptan_csv=args.naptan_csv,
        naptan_xml=args.naptan_xml,
    )
    print(f"\n  Resolved from NaPTAN : {len(resolved)}")
    print(f"  Still unresolved     : {len(still_missing)}")

    # Phase 3 — insert
    if resolved:
        print(f"\nPhase 3: Inserting {len(resolved)} resolved stops into stops.db …")
        n = insert_resolved_stops(stops_db, resolved)
        print(f"  Inserted: {n}")

    if still_missing:
        if args.allow_stubs:
            print(f"\nPhase 3b: Inserting {len(still_missing)} stub entries (no lat/lon) …")
            n = insert_stub_stops(stops_db, still_missing)
            print(f"  Inserted stubs: {n}")
        else:
            print(f"\n⚠ {len(still_missing)} stops could not be resolved from NaPTAN data.")
            print("  Run with --allow-stubs to insert placeholder entries.")
            if len(still_missing) <= 30:
                for sid in sorted(still_missing):
                    print(f"    {sid}")
            else:
                for sid in sorted(still_missing)[:20]:
                    print(f"    {sid}")
                print(f"    … and {len(still_missing) - 20} more")

    # Validation
    print("\n── Validation ──")
    total, res, no_coords = validate_resolution(bus_db, stops_db)
    unresolved = total - res
    pct = (res / total * 100) if total else 0
    print(f"  Total bus stop IDs       : {total}")
    print(f"  Resolved in stops.db     : {res}  ({pct:.1f}%)")
    print(f"  Resolved WITH coords     : {res - no_coords}")
    print(f"  Resolved WITHOUT coords  : {no_coords}")
    print(f"  Completely unresolved    : {unresolved}")

    if unresolved > 0 and (unresolved / total) > 0.05:
        print(
            f"\n⚠ WARNING: {unresolved}/{total} stop IDs ({unresolved/total*100:.1f}%) "
            f"cannot be resolved.  Bus routing will be degraded.",
            file=sys.stderr,
        )
        return 2

    print("\n✓ Sync complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

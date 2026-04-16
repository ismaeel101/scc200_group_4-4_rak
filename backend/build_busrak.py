#!/usr/bin/env python3
"""
build_busrak.py
Downloads Northwest bus timetables and builds busrak.db with tables
matching exactly what planner.py expects:
  - services(id, line_name, operator)
  - trips(id, service_id, departure_time)
  - stop_times(id, trip_id, stop_id, arrival_time, departure_time, sequence)
  - bus_stops(atco_code, common_name, latitude, longitude)
  - stop_points(atco_code, common_name)

Run from your backend directory:
  python3 build_busrak.py
"""
from __future__ import annotations

import os
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import requests
except ImportError:
    raise SystemExit("Install requests first: pip3 install requests")

# ── Config ────────────────────────────────────────────────────────────────────

DB_PATH = Path(__file__).resolve().parent / "busrak.db"
TMP_DIR = Path(__file__).resolve().parent / "data" / "busrak_timetables"

NW_DATASETS = [
    # ARCT - Archway Travel
    "https://transport.scc.lancs.ac.uk/timetable/dataset/16147/download/",
    "https://transport.scc.lancs.ac.uk/timetable/dataset/20830/download/",
    # BLAC - Blackpool Transport
    "https://transport.scc.lancs.ac.uk/timetable/dataset/22805/download/",
    # KLCO - Kirkby Lonsdale
    "https://transport.scc.lancs.ac.uk/timetable/dataset/14109/download/",
    "https://transport.scc.lancs.ac.uk/timetable/dataset/14598/download/",
    "https://transport.scc.lancs.ac.uk/timetable/dataset/20920/download/",
    "https://transport.scc.lancs.ac.uk/timetable/dataset/20951/download/",
    # NUTT / Coastliner
    "https://transport.scc.lancs.ac.uk/timetable/dataset/19206/download/",
    "https://transport.scc.lancs.ac.uk/timetable/dataset/22523/download/",
    # SCCU - Stagecoach Cumbria & North Lancashire
    "https://transport.scc.lancs.ac.uk/timetable/dataset/18047/download/",
    "https://transport.scc.lancs.ac.uk/timetable/dataset/18067/download/",
    "https://transport.scc.lancs.ac.uk/timetable/dataset/18508/download/",
]

TX_NS = "http://www.transxchange.org.uk/"
ns = {"tx": TX_NS}

COMMIT_EVERY = 5000

# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_runtime_iso(duration: str) -> int:
    if not duration or not duration.startswith("P"):
        return 0
    s = duration[1:]
    time_part = s.split("T", 1)[1] if "T" in s else s
    seconds = 0
    num = ""
    for ch in time_part:
        if ch.isdigit():
            num += ch
        elif ch == "H":
            seconds += int(num) * 3600
            num = ""
        elif ch == "M":
            seconds += int(num) * 60
            num = ""
        elif ch == "S":
            seconds += int(num)
            num = ""
    return seconds


def secs_to_hms(secs: int | None) -> str | None:
    if secs is None:
        return None
    secs = int(secs) % 86400
    return f"{secs // 3600:02d}:{(secs % 3600) // 60:02d}:{secs % 60:02d}"


def hms_to_secs(text: str | None) -> int | None:
    if not text:
        return None
    parts = text.strip().split(":")
    try:
        h, m, s = (int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
        return h * 3600 + m * 60 + s
    except Exception:
        return None

# ── Database ──────────────────────────────────────────────────────────────────

def create_db(path: Path) -> sqlite3.Connection:
    if path.exists():
        path.unlink()
    for suf in ("-shm", "-wal"):
        p = Path(str(path) + suf)
        if p.exists():
            p.unlink()

    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS services (
            id       TEXT PRIMARY KEY,
            line_name TEXT,
            operator  TEXT
        );
        CREATE TABLE IF NOT EXISTS trips (
            id             TEXT PRIMARY KEY,
            service_id     TEXT,
            departure_time TEXT
        );
        CREATE TABLE IF NOT EXISTS stop_times (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id        TEXT,
            stop_id        TEXT,
            arrival_time   TEXT,
            departure_time TEXT,
            sequence       INTEGER
        );
        CREATE TABLE IF NOT EXISTS bus_stops (
            atco_code   TEXT PRIMARY KEY,
            common_name TEXT,
            latitude    REAL,
            longitude   REAL
        );
        CREATE TABLE IF NOT EXISTS stop_points (
            atco_code   TEXT PRIMARY KEY,
            common_name TEXT
        );
    """)
    conn.commit()
    print(f"Created {path}")
    return conn


# ── Download ──────────────────────────────────────────────────────────────────

def download_datasets(urls: list[str], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for i, url in enumerate(urls, 1):
        name = f"dataset_{url.split('/dataset/')[1].split('/')[0]}.xml"
        dest = out_dir / name
        if dest.exists():
            print(f"  [{i}/{len(urls)}] Already exists: {name}")
        else:
            print(f"  [{i}/{len(urls)}] Downloading {url} ...")
            r = requests.get(url, timeout=120)
            r.raise_for_status()
            dest.write_bytes(r.content)
            print(f"    Saved {len(r.content)//1024}KB -> {name}")
        files.append(dest)
    return files


# ── Parse ─────────────────────────────────────────────────────────────────────

def process_file(path: Path, conn: sqlite3.Connection, counter: list[int]):
    print(f"  Parsing {path.name} ...")
    try:
        tree = ET.parse(str(path))
        root = tree.getroot()
    except Exception as e:
        print(f"    SKIP parse error: {e}")
        return

    cur = conn.cursor()

    # Stop points (metadata fallback)
    for sp in root.findall(".//tx:StopPoint", ns):
        atco = sp.find("tx:AtcoCode", ns)
        cname = sp.find("tx:CommonName", ns)
        if atco is not None and atco.text and cname is not None and cname.text:
            a = atco.text.strip()
            c = cname.text.strip()
            cur.execute("INSERT OR IGNORE INTO stop_points (atco_code, common_name) VALUES (?,?)", (a, c))
            cur.execute("INSERT OR IGNORE INTO bus_stops (atco_code, common_name) VALUES (?,?)", (a, c))

    # Services
    services_meta: dict[str, tuple[str, str]] = {}
    for svc in root.findall(".//tx:Service", ns):
        sc = svc.find("tx:ServiceCode", ns)
        ln = svc.find("tx:LineName", ns)
        op = svc.find("tx:OperatorRef", ns)
        if sc is not None and sc.text:
            code = sc.text.strip()
            name = ln.text.strip() if (ln is not None and ln.text) else ""
            operator = op.text.strip() if (op is not None and op.text) else ""
            services_meta[code] = (name, operator)
            cur.execute(
                "INSERT OR IGNORE INTO services (id, line_name, operator) VALUES (?,?,?)",
                (code, name, operator),
            )

    # Vehicle journeys
    for vj in root.findall(".//tx:VehicleJourney", ns):
        vjc = vj.find("tx:VehicleJourneyCode", ns)
        if vjc is None or not vjc.text:
            continue
        trip_id = vjc.text.strip()

        sref = vj.find("tx:ServiceRef", ns)
        service_id = sref.text.strip() if (sref is not None and sref.text) else None
        if not service_id:
            sc = vj.find(".//tx:ServiceCode", ns)
            service_id = sc.text.strip() if (sc is not None and sc.text) else None

        dt_el = vj.find("tx:DepartureTime", ns)
        dep_time_str = dt_el.text.strip() if (dt_el is not None and dt_el.text) else None

        cur.execute(
            "INSERT OR IGNORE INTO trips (id, service_id, departure_time) VALUES (?,?,?)",
            (trip_id, service_id, dep_time_str),
        )

        current_secs = hms_to_secs(dep_time_str)
        links = vj.findall(".//tx:VehicleJourneyTimingLink", ns)
        seq = 1

        if links:
            first = links[0]
            from_el = first.find("tx:From/tx:StopPointRef", ns)
            if from_el is not None and from_el.text:
                t = secs_to_hms(current_secs)
                cur.execute(
                    "INSERT INTO stop_times (trip_id, stop_id, arrival_time, departure_time, sequence) VALUES (?,?,?,?,?)",
                    (trip_id, from_el.text.strip(), t, t, seq),
                )
                seq += 1
                counter[0] += 1

        for link in links:
            rt_el = link.find("tx:RunTime", ns)
            run_secs = parse_runtime_iso(rt_el.text.strip()) if (rt_el is not None and rt_el.text) else 0
            if current_secs is not None:
                current_secs += run_secs

            to_el = link.find("tx:To/tx:StopPointRef", ns)
            if to_el is not None and to_el.text:
                t = secs_to_hms(current_secs)
                cur.execute(
                    "INSERT INTO stop_times (trip_id, stop_id, arrival_time, departure_time, sequence) VALUES (?,?,?,?,?)",
                    (trip_id, to_el.text.strip(), t, t, seq),
                )
                seq += 1
                counter[0] += 1

            if counter[0] % COMMIT_EVERY == 0:
                conn.commit()
                print(f"    {counter[0]} stop_times inserted...")

    conn.commit()


# ── Indexes ───────────────────────────────────────────────────────────────────

def build_indexes(conn: sqlite3.Connection):
    print("Building indexes...")
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_st_stop_id   ON stop_times(stop_id);
        CREATE INDEX IF NOT EXISTS idx_st_trip_id   ON stop_times(trip_id);
        CREATE INDEX IF NOT EXISTS idx_st_trip_seq  ON stop_times(trip_id, sequence);
        CREATE INDEX IF NOT EXISTS idx_trips_svc    ON trips(service_id);
        CREATE INDEX IF NOT EXISTS idx_bs_atco      ON bus_stops(atco_code);
    """)
    conn.commit()
    print("Indexes built.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Step 1: Downloading timetable XMLs")
    print("=" * 60)
    files = download_datasets(NW_DATASETS, TMP_DIR)

    print()
    print("=" * 60)
    print("Step 2: Creating busrak.db")
    print("=" * 60)
    conn = create_db(DB_PATH)

    print()
    print("=" * 60)
    print("Step 3: Parsing XMLs")
    print("=" * 60)
    counter = [0]
    for f in files:
        process_file(f, conn, counter)

    print()
    print("=" * 60)
    print("Step 4: Building indexes")
    print("=" * 60)
    build_indexes(conn)

    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    for table in ("services", "trips", "stop_times", "bus_stops", "stop_points"):
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {n}")

    conn.close()
    print(f"\nDone. Database saved to: {DB_PATH}")
    print("Copy busrak.db to your backend folder and rename it bus.db")
    print("Then run: python3 sync_bus_stops.py")


if __name__ == "__main__":
    main()

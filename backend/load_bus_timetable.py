#!/usr/bin/env python3
"""Load TransXChange timetables into SQLite using iterparse.

Creates /workspace/backend/database1.db with tables:
- services(id PRIMARY KEY, line_name, operator)
- trips(id PRIMARY KEY, service_id)
- stop_times(id AUTOINCREMENT, trip_id, stop_id, arrival_time, departure_time, sequence)

Parsing is namespace-aware (tx) and memory-efficient (iterparse).
"""
from __future__ import annotations

import os
import sqlite3
import xml.etree.ElementTree as ET
from typing import Dict, List, Tuple, Optional

TX_NS = "http://www.transxchange.org.uk/"
ns = {"tx": TX_NS}
TX = f"{{{TX_NS}}}"

DB_PATH = "/workspace/backend/bus.db"
XML_BASE = "/workspace/backend/data/timetables"

# commit/print thresholds
COMMIT_EVERY = 2000
PRINT_EVERY = 5000


def parse_runtime_iso(duration: str) -> int:
    # Parse ISO 8601 duration like PT1H2M30S into seconds (basic support)
    if not duration or not duration.startswith('P'):
        return 0
    # We only expect time component (PT..)
    s = duration
    seconds = 0
    # remove leading P
    if s.startswith('P'):
        s = s[1:]
    # split T
    time_part = ''
    if 'T' in s:
        time_part = s.split('T', 1)[1]
    else:
        time_part = s
    num = ''
    for ch in time_part:
        if ch.isdigit():
            num += ch
            continue
        if ch == 'H':
            seconds += int(num) * 3600
        elif ch == 'M':
            seconds += int(num) * 60
        elif ch == 'S':
            seconds += int(num)
        num = ''
    return seconds


def parse_time_hhmmss(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    text = text.strip()
    # Expect HH:MM:SS or HH:MM
    parts = text.split(':')
    try:
        if len(parts) == 3:
            h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
        elif len(parts) == 2:
            h, m, s = int(parts[0]), int(parts[1]), 0
        else:
            return None
        return h * 3600 + m * 60 + s
    except Exception:
        return None


def format_time_hhmmss(seconds: Optional[int]) -> Optional[str]:
    if seconds is None:
        return None
    seconds = int(seconds) % (24 * 3600)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def ensure_tables(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS services (
            id TEXT PRIMARY KEY,
            line_name TEXT,
            operator TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS trips (
            id TEXT PRIMARY KEY,
            service_id TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS stop_times (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id TEXT,
            stop_id TEXT,
            arrival_time TEXT,
            departure_time TEXT,
            sequence INTEGER
        )
        """
    )
    # Store stop metadata extracted from TransXChange StopPoint elements.
    # This provides a fallback name lookup when stops.db is incomplete.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS stop_points (
            atco_code TEXT PRIMARY KEY,
            common_name TEXT
        )
        """
    )
    conn.commit()
    print("Tables created successfully")


def process_file(path: str, conn: sqlite3.Connection, stop_times_counter: List[int]):
    # For each file we'll collect Service metadata found in <Service> elements
    services_meta: Dict[str, Tuple[str, str]] = {}
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception as e:
        print(f"Skipping {path}: parse error ({e})")
        return

    cur = conn.cursor()

    try:
        # Extract StopPoint metadata (AtcoCode -> CommonName) from this file.
        # TransXChange files embed stop definitions that serve as a fallback
        # when stops.db is incomplete.
        for sp in root.findall('.//tx:StopPoint', ns):
            atco_el = sp.find('tx:AtcoCode', ns)
            cname_el = sp.find('tx:CommonName', ns)
            if atco_el is not None and atco_el.text and cname_el is not None and cname_el.text:
                cur.execute(
                    "INSERT OR IGNORE INTO stop_points (atco_code, common_name) VALUES (?, ?)",
                    (atco_el.text.strip(), cname_el.text.strip()),
                )

        # collect services
        for svc in root.findall('.//tx:Service', ns):
            sc = svc.find('tx:ServiceCode', ns)
            ln = svc.find('tx:LineName', ns)
            op = svc.find('tx:OperatorRef', ns)
            if sc is not None and sc.text:
                code = sc.text.strip()
                name = ln.text.strip() if (ln is not None and ln.text) else ''
                operator = op.text.strip() if (op is not None and op.text) else ''
                services_meta[code] = (name, operator)
                cur.execute(
                    "INSERT OR IGNORE INTO services (id, line_name, operator) VALUES (?, ?, ?)",
                    (code, name, operator),
                )

        # process VehicleJourney elements
        for vj in root.findall('.//tx:VehicleJourney', ns):
            vjc = vj.find('tx:VehicleJourneyCode', ns)
            if vjc is None or not vjc.text:
                continue
            trip_id = vjc.text.strip()

            sref = vj.find('tx:ServiceRef', ns)
            service_id = None
            if sref is not None and sref.text:
                service_id = sref.text.strip()
            else:
                sc = vj.find('.//tx:ServiceCode', ns)
                if sc is not None and sc.text:
                    service_id = sc.text.strip()

            # insert service metadata if available
            if service_id and service_id in services_meta:
                line_name, operator = services_meta[service_id]
                cur.execute(
                    "INSERT OR IGNORE INTO services (id, line_name, operator) VALUES (?, ?, ?)",
                    (service_id, line_name, operator),
                )

            # insert trip
            cur.execute(
                "INSERT OR IGNORE INTO trips (id, service_id) VALUES (?, ?)",
                (trip_id, service_id),
            )

            # departure time
            dep_text = None
            dt = vj.find('tx:DepartureTime', ns)
            if dt is not None and dt.text:
                dep_text = dt.text.strip()
            current_secs = parse_time_hhmmss(dep_text)

            links = vj.findall('.//tx:VehicleJourneyTimingLink', ns)
            seq = 1
            if links:
                first = links[0]
                from_el = first.find('tx:From/tx:StopPointRef', ns)
                if from_el is not None and from_el.text:
                    first_stop = from_el.text.strip()
                    arrival = format_time_hhmmss(current_secs)
                    departure = format_time_hhmmss(current_secs)
                    cur.execute(
                        "INSERT INTO stop_times (trip_id, stop_id, arrival_time, departure_time, sequence) VALUES (?, ?, ?, ?, ?)",
                        (trip_id, first_stop, arrival, departure, seq),
                    )
                    seq += 1
                    stop_times_counter[0] += 1

            for link in links:
                rt_el = link.find('tx:RunTime', ns)
                run_seconds = parse_runtime_iso(rt_el.text.strip()) if (rt_el is not None and rt_el.text) else 0
                if current_secs is not None:
                    current_secs += run_seconds
                    arrival = format_time_hhmmss(current_secs)
                    departure = arrival
                else:
                    arrival = None
                    departure = None

                to_el = link.find('tx:To/tx:StopPointRef', ns)
                if to_el is not None and to_el.text:
                    stop_id = to_el.text.strip()
                    cur.execute(
                        "INSERT INTO stop_times (trip_id, stop_id, arrival_time, departure_time, sequence) VALUES (?, ?, ?, ?, ?)",
                        (trip_id, stop_id, arrival, departure, seq),
                    )
                    seq += 1
                    stop_times_counter[0] += 1

                if stop_times_counter[0] % COMMIT_EVERY == 0:
                    conn.commit()
                if stop_times_counter[0] % PRINT_EVERY == 0:
                    print(f"Inserted {stop_times_counter[0]} stop_times so far")

        conn.commit()
    except ET.ParseError as e:
        print(f"Skipping {path}: parse error ({e})")
    except Exception as e:
        print(f"Error processing {path}: {e}")


def main():
    if not os.path.isdir(XML_BASE):
        print(f"Timetables folder not found: {XML_BASE}")
        return

    # Delete existing DB file to start fresh, then create a new connection
    try:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
    except Exception:
        pass

    # Remove stale SQLite shared-memory or WAL files if present (best-effort)
    for suf in ("-shm", "-wal"):
        p = DB_PATH + suf
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass

    conn = sqlite3.connect(DB_PATH, timeout=30)
    print(f"Using DB: {DB_PATH}")
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
    except Exception:
        pass
    try:
        conn.execute("PRAGMA busy_timeout = 30000;")
    except Exception:
        pass
    # Create required tables up-front
    create_sql = '''
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
    CREATE TABLE IF NOT EXISTS stop_points (
        atco_code TEXT PRIMARY KEY,
        common_name TEXT
    );
    CREATE TABLE IF NOT EXISTS stop_points (
        atco_code TEXT PRIMARY KEY,
        common_name TEXT
    );
    '''
    # Set pragmas and attempt to create tables with retries to avoid transient locks
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
    except Exception:
        pass
    try:
        conn.execute("PRAGMA busy_timeout = 30000;")
    except Exception:
        pass

    import time as _time
    for _attempt in range(10):
        try:
            conn.executescript(create_sql)
            conn.commit()
            print('Database and tables created')
            break
        except sqlite3.OperationalError as e:
            if 'locked' in str(e).lower():
                print('Database locked while creating tables, retrying...')
                _time.sleep(1)
                continue
            print('Error creating tables:', e)
            raise

    stop_times_counter = [0]

    # Walk files
    for dirpath, _, filenames in os.walk(XML_BASE):
        for fn in filenames:
            if not fn.lower().endswith('.xml'):
                continue
            path = os.path.join(dirpath, fn)
            print(f"Processing {path}")
            process_file(path, conn, stop_times_counter)

    print(f"Done. Total stop_times: {stop_times_counter[0]}")

    # Print counts in each table
    try:
        cur = conn.cursor()
        services_cnt = cur.execute('SELECT COUNT(*) FROM services').fetchone()[0]
        trips_cnt = cur.execute('SELECT COUNT(*) FROM trips').fetchone()[0]
        stoptimes_cnt = cur.execute('SELECT COUNT(*) FROM stop_times').fetchone()[0]
        print(f"services: {services_cnt}")
        print(f"trips: {trips_cnt}")
        print(f"stop_times: {stoptimes_cnt}")
    except Exception as e:
        print('Error fetching summary counts:', e)

    conn.close()


if __name__ == '__main__':
    main()

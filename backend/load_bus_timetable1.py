#!/usr/bin/env python3
"""
Load TransXChange bus timetable XML files into bus.db
Tables: services, trips, stop_times
"""
import os
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import re

DB_PATH = "/tmp/backend/bus.db"
TIMETABLES_DIR = "/workspace/backend/data/timetables"
NS = {"tx": "http://www.transxchange.org.uk/"}


def parse_duration(duration):
    """Convert ISO 8601 duration (PT5M, PT1H30M) to seconds."""
    if not duration:
        return 0
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not m:
        return 0
    h = int(m.group(1) or 0)
    mins = int(m.group(2) or 0)
    secs = int(m.group(3) or 0)
    return h * 3600 + mins * 60 + secs


def add_seconds(time_str, seconds):
    """Add seconds to a HH:MM:SS time string."""
    try:
        t = datetime.strptime(time_str, "%H:%M:%S")
    except ValueError:
        try:
            t = datetime.strptime(time_str, "%H:%M")
        except ValueError:
            return time_str
    t2 = t + timedelta(seconds=seconds)
    return t2.strftime("%H:%M:%S")


def create_tables(conn):
    conn.executescript("""
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
        CREATE TABLE IF NOT EXISTS bus_stops (
            atco_code TEXT PRIMARY KEY,
            common_name TEXT,
            latitude REAL,
            longitude REAL
        );
        CREATE INDEX IF NOT EXISTS idx_stop_times_stop ON stop_times(stop_id);
        CREATE INDEX IF NOT EXISTS idx_stop_times_trip ON stop_times(trip_id);
        CREATE INDEX IF NOT EXISTS idx_bus_stops_name ON bus_stops(common_name);
    """)
    conn.commit()
    print("Tables created.")


def process_file(path, conn):
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception as e:
        print(f"  SKIP (parse error): {e}")
        return 0

    cur = conn.cursor()
    count = 0

    # ── Extract stop metadata from <StopPoint> elements ──
    # TransXChange files embed NaPTAN ATCO codes and common names for every
    # stop referenced by the timetable.  Storing them in bus_stops ensures
    # every stop_id in stop_times can be resolved to a name/location.
    for sp in root.findall(".//tx:StopPoint", NS):
        atco_el = sp.find("tx:AtcoCode", NS)
        cname_el = sp.find("tx:CommonName", NS)
        if atco_el is not None and atco_el.text and cname_el is not None and cname_el.text:
            atco = atco_el.text.strip()
            cname = cname_el.text.strip()
            lat = None
            lon = None
            loc_el = sp.find("tx:Place/tx:Location", NS)
            if loc_el is not None:
                lat_el = loc_el.find("tx:Latitude", NS)
                lon_el = loc_el.find("tx:Longitude", NS)
                try:
                    lat = float(lat_el.text) if lat_el is not None and lat_el.text else None
                except ValueError:
                    lat = None
                try:
                    lon = float(lon_el.text) if lon_el is not None and lon_el.text else None
                except ValueError:
                    lon = None
            cur.execute(
                "INSERT OR IGNORE INTO bus_stops (atco_code, common_name, latitude, longitude) VALUES (?,?,?,?)",
                (atco, cname, lat, lon),
            )

    # Extract services
    for svc in root.findall(".//tx:Service", NS):
        svc_id = None
        el = svc.find("tx:ServiceCode", NS)
        if el is not None and el.text:
            svc_id = el.text.strip()
        line_el = svc.find(".//tx:LineName", NS)
        line_name = line_el.text.strip() if line_el is not None and line_el.text else ""
        op_el = svc.find(".//tx:OperatorRef", NS)
        operator = op_el.text.strip() if op_el is not None and op_el.text else ""
        if svc_id:
            cur.execute(
                "INSERT OR IGNORE INTO services (id, line_name, operator) VALUES (?,?,?)",
                (svc_id, line_name, operator)
            )

    # Build a lookup of JourneyPatternTimingLink -> from/to/runtime
    pattern_links = {}
    for jps in root.findall(".//tx:JourneyPatternSection", NS):
        for jptl in jps.findall(".//tx:JourneyPatternTimingLink", NS):
            link_id = jptl.get("id")
            if not link_id:
                ref_el = jptl.find("tx:JourneyPatternTimingLinkRef", NS)
                link_id = ref_el.text.strip() if ref_el is not None and ref_el.text else None

            from_stop = None
            to_stop = None
            runtime = "PT0M"

            from_el = jptl.find("tx:From/tx:StopPointRef", NS)
            if from_el is not None and from_el.text:
                from_stop = from_el.text.strip()

            to_el = jptl.find("tx:To/tx:StopPointRef", NS)
            if to_el is not None and to_el.text:
                to_stop = to_el.text.strip()

            runtime_el = jptl.find("tx:RunTime", NS)
            if runtime_el is not None and runtime_el.text:
                runtime = runtime_el.text.strip()

            if link_id:
                pattern_links[link_id] = {"from_stop": from_stop, "to_stop": to_stop, "runtime": runtime}

    # Extract vehicle journeys and expand timing links using the pattern lookup
    for vj in root.findall(".//tx:VehicleJourney", NS):
        trip_id_el = vj.find("tx:VehicleJourneyCode", NS)
        trip_id = trip_id_el.text.strip() if trip_id_el is not None and trip_id_el.text else None

        svc_ref_el = vj.find("tx:ServiceRef", NS)
        service_id = svc_ref_el.text.strip() if svc_ref_el is not None and svc_ref_el.text else ""

        dep_el = vj.find("tx:DepartureTime", NS)
        departure_time = dep_el.text.strip() if dep_el is not None and dep_el.text else "00:00:00"

        if not trip_id:
            continue

        cur.execute(
            "INSERT OR IGNORE INTO trips (id, service_id, departure_time) VALUES (?,?,?)",
            (trip_id, service_id, departure_time)
        )

        # Build stop times from timing links using pattern_links
        current_time = departure_time
        seq = 0

        for link in vj.findall(".//tx:VehicleJourneyTimingLink", NS):
            # get the referenced JourneyPatternTimingLink id
            ref_el = link.find("tx:JourneyPatternTimingLinkRef", NS)
            key = ref_el.text.strip() if ref_el is not None and ref_el.text else None

            if key and key in pattern_links:
                pl = pattern_links[key]
                from_stop = pl.get("from_stop")
                to_stop = pl.get("to_stop")
                runtime = pl.get("runtime", "PT0M")
            else:
                # fallback: try to find StopPointRef directly
                from_stop = None
                to_stop = None
                ref = link.find(".//tx:From//tx:StopPointRef", NS)
                if ref is not None and ref.text:
                    from_stop = ref.text.strip()
                ref = link.find(".//tx:To//tx:StopPointRef", NS)
                if ref is not None and ref.text:
                    to_stop = ref.text.strip()
                runtime_el = link.find("tx:RunTime", NS)
                runtime = runtime_el.text.strip() if runtime_el is not None and runtime_el.text else "PT0M"

            if from_stop:
                seq += 1
                cur.execute(
                    "INSERT INTO stop_times (trip_id, stop_id, arrival_time, departure_time, sequence) VALUES (?,?,?,?,?)",
                    (trip_id, from_stop, current_time, current_time, seq)
                )
                count += 1

            seconds = parse_duration(runtime)
            current_time = add_seconds(current_time, seconds)

            if to_stop:
                seq += 1
                cur.execute(
                    "INSERT INTO stop_times (trip_id, stop_id, arrival_time, departure_time, sequence) VALUES (?,?,?,?,?)",
                    (trip_id, to_stop, current_time, current_time, seq)
                )
                count += 1

    return count


def main():
    print(f"Creating database at {DB_PATH}")
    os.makedirs("/tmp/backend", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA journal_mode=DELETE')
    create_tables(conn)

    xml_files = []
    for root, dirs, files in os.walk(TIMETABLES_DIR):
        for f in files:
            if f.endswith(".xml"):
                xml_files.append(os.path.join(root, f))

    print(f"Found {len(xml_files)} XML files")

    total = 0
    for i, path in enumerate(xml_files):
        if i % 100 == 0:
            print(f"Progress: {i}/{len(xml_files)} files, {total} stop_times so far...")
            conn.commit()
        n = process_file(path, conn)
        total += n

    conn.commit()

    cur = conn.cursor()
    services = cur.execute("SELECT COUNT(*) FROM services").fetchone()[0]
    trips = cur.execute("SELECT COUNT(*) FROM trips").fetchone()[0]
    stop_times = cur.execute("SELECT COUNT(*) FROM stop_times").fetchone()[0]
    conn.close()

    print(f"\nDone!")
    print(f"  Services:   {services}")
    print(f"  Trips:      {trips}")
    print(f"  Stop times: {stop_times}")

    import shutil
    shutil.copy(DB_PATH, "/workspace/backend/bus.db")


if __name__ == "__main__":
    main()
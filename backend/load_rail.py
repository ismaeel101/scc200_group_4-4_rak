#!/usr/bin/env python3
"""
Load rail timetable data from /workspace/backend/data/rail_schedule.json.gz
Build DB in /tmp/rail.db then copy to /workspace/backend/rail.db

Rules:
- Read gzip newline-delimited JSON (one object per line)
- Skip lines that fail JSON parsing
- Only process records where transaction_type == "Create"
- Commit every 10000 inserts
- Print progress every 50000 lines
"""
import os
import gzip
import json
import sqlite3
import shutil
import sys

DB_TMP = "/tmp/rail.db"
DB_FINAL = "/workspace/backend/rail.db"
INPUT_FILE = "/workspace/backend/data/rail_schedule.json.gz"

COMMIT_INTERVAL = 10000
PROGRESS_INTERVAL = 50000





def create_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS stations (
            tiploc TEXT PRIMARY KEY,
            crs TEXT,
            name TEXT,
            stanox TEXT
        );

        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            train_uid TEXT,
            runs_from TEXT,
            runs_to TEXT,
            days_run TEXT,
            tiploc TEXT,
            arrival TEXT,
            departure TEXT,
            seq INTEGER
        );

        CREATE INDEX IF NOT EXISTS idx_schedules_tiploc ON schedules(tiploc);
        CREATE INDEX IF NOT EXISTS idx_schedules_uid ON schedules(train_uid);
        CREATE INDEX IF NOT EXISTS idx_stations_crs ON stations(crs);
    """)
    conn.commit()


def main():
    if not os.path.exists(INPUT_FILE):
        print(f"Input file not found: {INPUT_FILE}")
        sys.exit(1)

    os.makedirs(os.path.dirname(DB_TMP), exist_ok=True)

    conn = sqlite3.connect(DB_TMP)
    cur = conn.cursor()
    create_tables(conn)

    stations_inserted = 0
    schedules_inserted = 0
    pending_inserts = 0
    line_count = 0

    with gzip.open(INPUT_FILE, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line_count += 1

            if line_count % PROGRESS_INTERVAL == 0:
                print(f"Processed {line_count} lines — stations: {stations_inserted}, schedules: {schedules_inserted}")
                conn.commit()

            line = line.strip()
            if not line:
                continue

            try:
                obj = json.loads(line)
            except Exception:
                # skip malformed JSON
                continue

            # handle JsonScheduleV1 records

            # TiplocV1 station record
            if "TiplocV1" in obj:
                rec = obj.get("TiplocV1") or {}
                if rec.get("transaction_type") != "Create":
                    continue

                tiploc = rec.get("tiploc_code")
                crs = rec.get("crs_code")
                name = rec.get("tps_description")
                stanox = rec.get("stanox")

                if tiploc:
                    try:
                        cur.execute(
                            "INSERT OR IGNORE INTO stations (tiploc, crs, name, stanox) VALUES (?,?,?,?)",
                            (tiploc, crs, name, stanox),
                        )
                        stations_inserted += 1
                        pending_inserts += 1
                    except Exception:
                        # ignore individual insert errors
                        pass

            # JsonScheduleV1 train schedule record
            elif "JsonScheduleV1" in obj:
                rec = obj.get("JsonScheduleV1") or {}
                if rec.get("transaction_type") != "Create":
                    continue

                train_uid = rec.get("CIF_train_uid")
                runs_from = rec.get("schedule_start_date")
                runs_to = rec.get("schedule_end_date")
                days_run = rec.get("schedule_days_runs")

                seg = rec.get("schedule_segment") or {}
                locations = seg.get("schedule_location") or []

                seq = 0
                for loc in locations:
                    seq += 1
                    tiploc = loc.get("tiploc_code")
                    arrival = loc.get("arrival")
                    departure = loc.get("departure")

                    try:
                        cur.execute(
                            "INSERT INTO schedules (train_uid, runs_from, runs_to, days_run, tiploc, arrival, departure, seq) VALUES (?,?,?,?,?,?,?,?)",
                            (train_uid, runs_from, runs_to, days_run, tiploc, arrival, departure, seq),
                        )
                        schedules_inserted += 1
                        pending_inserts += 1
                    except Exception:
                        # ignore insert errors for individual schedule lines
                        pass

            if pending_inserts >= COMMIT_INTERVAL:
                conn.commit()
                pending_inserts = 0

            

    # final commit
    conn.commit()

    # print final counts
    total_stations = cur.execute("SELECT COUNT(*) FROM stations").fetchone()[0]
    total_schedules = cur.execute("SELECT COUNT(*) FROM schedules").fetchone()[0]
    conn.close()

    print("\nDone")
    print(f"  Lines processed: {line_count}")
    print(f"  Stations inserted: {total_stations}")
    print(f"  Schedule rows inserted: {total_schedules}")

    try:
        shutil.copy(DB_TMP, DB_FINAL)
        print(f"Copied {DB_TMP} -> {DB_FINAL}")
    except Exception as e:
        print(f"Failed to copy DB to {DB_FINAL}: {e}")


if __name__ == "__main__":
    main()

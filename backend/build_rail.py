#!/usr/bin/env python3
"""
build_rail.py
Builds a lightweight Northwest-only rail.db from the existing full rail.db.
Only keeps stations and schedules for Northwest STANOX areas (11xxx, 30xxx).
Run from backend directory: python3 build_rail.py
"""
import sqlite3
from pathlib import Path

SRC = '/workspace/rail.db'
DST = '/tmp/rail_nw.db'
NW_STANOX = ('11', '30')

for p in [DST, DST+'-shm', DST+'-wal']:
    try: Path(p).unlink()
    except: pass

print('Connecting to source rail.db...')
src = sqlite3.connect(SRC)
src.row_factory = sqlite3.Row

print('Creating destination rail_nw.db...')
dst = sqlite3.connect(DST)
dst.executescript('''
    CREATE TABLE IF NOT EXISTS stations (
        tiploc TEXT PRIMARY KEY,
        crs    TEXT,
        name   TEXT,
        stanox TEXT
    );
    CREATE TABLE IF NOT EXISTS schedules (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        train_uid TEXT,
        runs_from TEXT,
        runs_to   TEXT,
        days_run  TEXT,
        tiploc    TEXT,
        arrival   TEXT,
        departure TEXT,
        seq       INTEGER
    );
''')
dst.commit()

# Get all NW stations
print('Copying Northwest stations...')
nw_stations = src.execute(
    "SELECT tiploc, crs, name, stanox FROM stations WHERE stanox LIKE '11%' OR stanox LIKE '30%'"
).fetchall()
nw_tiplocs = set(r['tiploc'] for r in nw_stations)
print(f'  {len(nw_stations)} NW stations found')

dst.executemany(
    'INSERT OR IGNORE INTO stations (tiploc, crs, name, stanox) VALUES (?,?,?,?)',
    [(r['tiploc'], r['crs'], r['name'], r['stanox']) for r in nw_stations]
)
dst.commit()

# Get all train_uids that serve NW stations
print('Finding Northwest train UIDs...')
placeholders = ','.join('?' for _ in nw_tiplocs)
nw_train_uids = set(
    r[0] for r in src.execute(
        f"SELECT DISTINCT train_uid FROM schedules WHERE tiploc IN ({placeholders})",
        list(nw_tiplocs)
    ).fetchall()
)
print(f'  {len(nw_train_uids)} trains serve Northwest')

# Copy only NW schedules (all stops for NW trains, filtered to NW tiplocs only)
print('Copying Northwest schedules...')
count = 0
batch = []
uid_list = list(nw_train_uids)
chunk_size = 500

for i in range(0, len(uid_list), chunk_size):
    chunk = uid_list[i:i+chunk_size]
    ph = ','.join('?' for _ in chunk)
    rows = src.execute(
        f"SELECT train_uid, runs_from, runs_to, days_run, tiploc, arrival, departure, seq "
        f"FROM schedules WHERE train_uid IN ({ph}) AND tiploc IN ({placeholders})",
        chunk + list(nw_tiplocs)
    ).fetchall()
    batch.extend([(r['train_uid'], r['runs_from'], r['runs_to'], r['days_run'],
                   r['tiploc'], r['arrival'], r['departure'], r['seq']) for r in rows])
    count += len(rows)
    if count % 100000 == 0 and count > 0:
        print(f'  {count:,} schedules copied...')
    if len(batch) >= 10000:
        dst.executemany(
            'INSERT INTO schedules (train_uid,runs_from,runs_to,days_run,tiploc,arrival,departure,seq) VALUES (?,?,?,?,?,?,?,?)',
            batch
        )
        dst.commit()
        batch = []

if batch:
    dst.executemany(
        'INSERT INTO schedules (train_uid,runs_from,runs_to,days_run,tiploc,arrival,departure,seq) VALUES (?,?,?,?,?,?,?,?)',
        batch
    )
    dst.commit()

print('\nBuilding indexes...')
dst.executescript('''
    CREATE INDEX IF NOT EXISTS idx_schedules_tiploc     ON schedules(tiploc);
    CREATE INDEX IF NOT EXISTS idx_schedules_uid_seq    ON schedules(train_uid, seq);
    CREATE INDEX IF NOT EXISTS idx_schedules_tiploc_dep ON schedules(tiploc, departure);
''')
dst.commit()

print('\nSummary:')
print(f'  stations:  {dst.execute("SELECT COUNT(*) FROM stations").fetchone()[0]:,}')
print(f'  schedules: {dst.execute("SELECT COUNT(*) FROM schedules").fetchone()[0]:,}')

src.close()
dst.close()
print(f'\nDone: {DST}')
print('Copy with:')
print(f'  cp {DST} /workspace/backend/rail.db')
print(f'  cp {DST} /workspace/rail.db')

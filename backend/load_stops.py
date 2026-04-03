#!/usr/bin/env python3
"""Load bus stops from a NaPTAN XML file into a SQLite database.

Usage:
  python load_stops.py --xml backend/data/naptan.xml --db backend/stops.db

By default the script filters stops to a bounding box covering North West
England (latitude 53.0-55.0, longitude -6.0 to -1.0). These can be changed
with command-line options.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import xml.etree.ElementTree as ET
from typing import Dict, Iterable, List, Optional, Tuple


def parse_stoppoints(xml_path: str, bbox: Tuple[float, float, float, float]) -> Iterable[Dict]:
	lat_min, lat_max, lon_min, lon_max = bbox
	tree = ET.parse(xml_path)
	root = tree.getroot()

	# Determine default namespace if present
	if root.tag.startswith("{"):
		ns_uri = root.tag.split("}")[0].strip("{")
	else:
		ns_uri = ""

	def q(name: str) -> str:
		return f"{{{ns_uri}}}{name}" if ns_uri else name

	for sp in root.findall(f".//{q('StopPoint')}"):
		# Basic identifiers
		atco = (sp.find(q('AtcoCode')) or sp.find(q('AtcoCode')))
		atco_code = atco.text.strip() if atco is not None and atco.text else None
		naptan_el = sp.find(q('NaptanCode'))
		naptan_code = naptan_el.text.strip() if naptan_el is not None and naptan_el.text else None

		# Descriptor
		desc = sp.find(q('Descriptor'))
		common_name = None
		street = None
		indicator = None
		if desc is not None:
			cn = desc.find(q('CommonName'))
			common_name = cn.text.strip() if cn is not None and cn.text else None
			st = desc.find(q('Street'))
			street = st.text.strip() if st is not None and st.text else None
			ind = desc.find(q('Indicator'))
			indicator = ind.text.strip() if ind is not None and ind.text else None

		# Place / location
		place = sp.find(q('Place'))
		suburb = None
		town = None
		latitude = None
		longitude = None
		easting = None
		northing = None
		if place is not None:
			sub = place.find(q('Suburb'))
			suburb = sub.text.strip() if sub is not None and sub.text else None
			t = place.find(q('Town'))
			town = t.text.strip() if t is not None and t.text else None
			loc = place.find(q('Location'))
			if loc is not None:
				trans = loc.find(q('Translation'))
				if trans is not None:
					lon_el = trans.find(q('Longitude'))
					lat_el = trans.find(q('Latitude'))
					east_el = trans.find(q('Easting'))
					north_el = trans.find(q('Northing'))
					try:
						longitude = float(lon_el.text) if lon_el is not None and lon_el.text else None
					except ValueError:
						longitude = None
					try:
						latitude = float(lat_el.text) if lat_el is not None and lat_el.text else None
					except ValueError:
						latitude = None
					try:
						easting = int(east_el.text) if east_el is not None and east_el.text else None
					except ValueError:
						easting = None
					try:
						northing = int(north_el.text) if north_el is not None and north_el.text else None
					except ValueError:
						northing = None

		# Administrative area and classification
		admin = sp.find(q('AdministrativeAreaRef'))
		administrative_area_ref = admin.text.strip() if admin is not None and admin.text else None

		stop_class = sp.find(q('StopClassification'))
		stop_type = None
		bus_stop_type = None
		if stop_class is not None:
			stt = stop_class.find(q('StopType'))
			stop_type = stt.text.strip() if stt is not None and stt.text else None
			onstreet = stop_class.find(q('OnStreet'))
			if onstreet is not None:
				bus = onstreet.find(q('Bus'))
				if bus is not None:
					bst = bus.find(q('BusStopType'))
					bus_stop_type = bst.text.strip() if bst is not None and bst.text else None

		# Filter by bounding box if coordinates present
		if latitude is None or longitude is None:
			continue
		if not (lat_min <= latitude <= lat_max and lon_min <= longitude <= lon_max):
			continue

		if atco_code is None:
			continue

		yield {
			'atco_code': atco_code,
			'naptan_code': naptan_code,
			'common_name': common_name,
			'street': street,
			'indicator': indicator,
			'suburb': suburb,
			'town': town,
			'latitude': latitude,
			'longitude': longitude,
			'easting': easting,
			'northing': northing,
			'administrative_area_ref': administrative_area_ref,
			'stop_type': stop_type,
			'bus_stop_type': bus_stop_type,
		}


def init_db(db_path: str) -> sqlite3.Connection:
	os.makedirs(os.path.dirname(db_path), exist_ok=True) if os.path.dirname(db_path) else None
	conn = sqlite3.connect(db_path)
	cur = conn.cursor()
	cur.execute(
		'''
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
		'''
	)
	conn.commit()
	return conn


def insert_stops(conn: sqlite3.Connection, stops: Iterable[Dict]) -> int:
	cur = conn.cursor()
	rows: List[Tuple] = []
	for s in stops:
		rows.append(
			(
				s['atco_code'],
				s.get('naptan_code'),
				s.get('common_name'),
				s.get('street'),
				s.get('indicator'),
				s.get('suburb'),
				s.get('town'),
				s.get('latitude'),
				s.get('longitude'),
				s.get('easting'),
				s.get('northing'),
				s.get('administrative_area_ref'),
				s.get('stop_type'),
				s.get('bus_stop_type'),
			)
		)

	cur.executemany(
		'''
		INSERT OR REPLACE INTO stops (
			atco_code, naptan_code, common_name, street, indicator,
			suburb, town, latitude, longitude, easting, northing,
			administrative_area_ref, stop_type, bus_stop_type
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		''',
		rows,
	)
	conn.commit()
	return cur.rowcount


def parse_bbox(s: str) -> Tuple[float, float, float, float]:
	parts = [float(p) for p in s.split(',')]
	if len(parts) != 4:
		raise ValueError('BBox must be four comma-separated floats: lat_min,lat_max,lon_min,lon_max')
	return parts[0], parts[1], parts[2], parts[3]


def _get_bus_db_stop_ids(bus_db_path: str) -> set:
	"""Read all distinct stop_ids from bus.db stop_times table."""
	if not os.path.exists(bus_db_path):
		return set()
	import sqlite3 as _sqlite3
	conn = _sqlite3.connect(bus_db_path)
	try:
		cur = conn.execute("SELECT DISTINCT stop_id FROM stop_times WHERE stop_id IS NOT NULL AND stop_id != ''")
		return {row[0] for row in cur.fetchall()}
	except Exception:
		return set()
	finally:
		conn.close()


def parse_stoppoints_for_ids(xml_path: str, wanted_ids: set) -> Iterable[Dict]:
	"""Parse NaPTAN XML and yield only stops whose AtcoCode is in *wanted_ids*.

	No bounding-box filter — this ensures every bus timetable stop is captured
	regardless of geographic location.
	"""
	tree = ET.parse(xml_path)
	root = tree.getroot()

	if root.tag.startswith("{"):
		ns_uri = root.tag.split("}")[0].strip("{")
	else:
		ns_uri = ""

	def q(name: str) -> str:
		return f"{{{ns_uri}}}{name}" if ns_uri else name

	for sp in root.findall(f".//{q('StopPoint')}"):
		atco = sp.find(q('AtcoCode'))
		atco_code = atco.text.strip() if atco is not None and atco.text else None
		if atco_code is None or atco_code not in wanted_ids:
			continue

		naptan_el = sp.find(q('NaptanCode'))
		naptan_code = naptan_el.text.strip() if naptan_el is not None and naptan_el.text else None

		desc = sp.find(q('Descriptor'))
		common_name = street = indicator = None
		if desc is not None:
			cn = desc.find(q('CommonName'))
			common_name = cn.text.strip() if cn is not None and cn.text else None
			st = desc.find(q('Street'))
			street = st.text.strip() if st is not None and st.text else None
			ind = desc.find(q('Indicator'))
			indicator = ind.text.strip() if ind is not None and ind.text else None

		place = sp.find(q('Place'))
		suburb = town = latitude = longitude = easting = northing = None
		if place is not None:
			sub = place.find(q('Suburb'))
			suburb = sub.text.strip() if sub is not None and sub.text else None
			t = place.find(q('Town'))
			town = t.text.strip() if t is not None and t.text else None
			loc = place.find(q('Location'))
			if loc is not None:
				trans = loc.find(q('Translation'))
				if trans is not None:
					try:
						lon_el = trans.find(q('Longitude'))
						lat_el = trans.find(q('Latitude'))
						east_el = trans.find(q('Easting'))
						north_el = trans.find(q('Northing'))
						longitude = float(lon_el.text) if lon_el is not None and lon_el.text else None
						latitude = float(lat_el.text) if lat_el is not None and lat_el.text else None
						easting = int(east_el.text) if east_el is not None and east_el.text else None
						northing = int(north_el.text) if north_el is not None and north_el.text else None
					except (ValueError, TypeError):
						pass

		admin = sp.find(q('AdministrativeAreaRef'))
		administrative_area_ref = admin.text.strip() if admin is not None and admin.text else None

		stop_class = sp.find(q('StopClassification'))
		stop_type = bus_stop_type = None
		if stop_class is not None:
			stt = stop_class.find(q('StopType'))
			stop_type = stt.text.strip() if stt is not None and stt.text else None
			onstreet = stop_class.find(q('OnStreet'))
			if onstreet is not None:
				bus = onstreet.find(q('Bus'))
				if bus is not None:
					bst = bus.find(q('BusStopType'))
					bus_stop_type = bst.text.strip() if bst is not None and bst.text else None

		yield {
			'atco_code': atco_code,
			'naptan_code': naptan_code,
			'common_name': common_name,
			'street': street,
			'indicator': indicator,
			'suburb': suburb,
			'town': town,
			'latitude': latitude,
			'longitude': longitude,
			'easting': easting,
			'northing': northing,
			'administrative_area_ref': administrative_area_ref,
			'stop_type': stop_type,
			'bus_stop_type': bus_stop_type,
		}


def main(argv: Optional[List[str]] = None) -> int:
	p = argparse.ArgumentParser(description='Load NaPTAN stops into SQLite.')
	p.add_argument('--xml', default='backend/data/naptan.xml', help='Path to NaPTAN XML file')
	p.add_argument('--db', default='backend/stops.db', help='Path to output SQLite DB')
	p.add_argument('--bbox', default='53.0,55.0,-6.0,-1.0',
	               help='lat_min,lat_max,lon_min,lon_max (comma separated). '
	                    'Use "none" to disable bbox filtering.')
	p.add_argument('--bus-db', default=None,
	               help='Path to bus.db. When given, ALL stop_ids referenced in '
	                    'bus.db will also be loaded (ignoring bbox) to ensure '
	                    'every timetable stop can be resolved.')
	args = p.parse_args(argv)

	if not os.path.exists(args.xml):
		print(f'XML file not found: {args.xml}', file=sys.stderr)
		return 2

	use_bbox = args.bbox.lower().strip() != 'none'
	if use_bbox:
		try:
			bbox = parse_bbox(args.bbox)
		except Exception as exc:
			print('Invalid bbox: ' + str(exc), file=sys.stderr)
			return 3
	else:
		bbox = (-90.0, 90.0, -180.0, 180.0)

	conn = init_db(args.db)

	# Standard bbox-filtered load
	print(f'Parsing {args.xml} with bbox={bbox if use_bbox else "disabled"}...')
	stops_iter = parse_stoppoints(args.xml, bbox)
	count = insert_stops(conn, stops_iter)
	print(f'Inserted/updated {count} stop records (bbox pass)')

	# Bus-DB cross-reference pass: load any stops referenced in bus.db
	# that were missed by the bbox filter
	if args.bus_db:
		bus_ids = _get_bus_db_stop_ids(args.bus_db)
		if bus_ids:
			# Find which bus stop IDs are still missing from stops.db
			cur = conn.cursor()
			existing = set()
			for chunk_start in range(0, len(bus_ids), 500):
				chunk = list(bus_ids)[chunk_start:chunk_start + 500]
				placeholders = ','.join('?' for _ in chunk)
				rows = cur.execute(
					f'SELECT atco_code FROM stops WHERE atco_code IN ({placeholders})',
					chunk,
				).fetchall()
				existing.update(r[0] for r in rows)
			missing = bus_ids - existing
			if missing:
				print(f'Bus-DB cross-reference: {len(missing)} stop IDs missing, loading from XML...')
				extra_iter = parse_stoppoints_for_ids(args.xml, missing)
				extra_count = insert_stops(conn, extra_iter)
				print(f'Inserted/updated {extra_count} extra stops from bus-DB cross-reference')
			else:
				print('Bus-DB cross-reference: all bus stop IDs already in stops.db')

	conn.close()
	print(f'Done. Database: {args.db}')
	return 0


if __name__ == '__main__':
	raise SystemExit(main())

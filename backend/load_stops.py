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


def main(argv: Optional[List[str]] = None) -> int:
	p = argparse.ArgumentParser(description='Load NaPTAN stops into SQLite (filter NW England by bbox).')
	p.add_argument('--xml', default='backend/data/naptan.xml', help='Path to NaPTAN XML file')
	p.add_argument('--db', default='backend/stops.db', help='Path to output SQLite DB')
	p.add_argument('--bbox', default='53.0,55.0,-6.0,-1.0', help='lat_min,lat_max,lon_min,lon_max (comma separated)')
	args = p.parse_args(argv)

	if not os.path.exists(args.xml):
		print(f'XML file not found: {args.xml}', file=sys.stderr)
		return 2

	try:
		bbox = parse_bbox(args.bbox)
	except Exception as exc:
		print('Invalid bbox: ' + str(exc), file=sys.stderr)
		return 3

	print(f'Parsing {args.xml} and filtering bbox {bbox}...')
	stops_iter = parse_stoppoints(args.xml, bbox)

	conn = init_db(args.db)
	count = insert_stops(conn, stops_iter)
	conn.close()

	print(f'Inserted/updated {count} stop records into {args.db}')
	return 0


if __name__ == '__main__':
	raise SystemExit(main())

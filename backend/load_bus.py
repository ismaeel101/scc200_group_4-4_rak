#!/usr/bin/env python3
"""Simple TransXChange parser for coursework.

Scans backend/data/timetables for .xml files, parses each with ElementTree
using the tx namespace, and extracts:
- stops: AtcoCode -> CommonName
- routes: ServiceCode -> LineName
- journeys: list of (route_id, departure_time)

Skips files that fail to parse.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import Dict, List, Tuple

TX_NS = "http://www.transxchange.org.uk/"
ns = {"tx": TX_NS}

def parse_file(path: str, stops: Dict[str, str], routes: Dict[str, str], journeys: List[Tuple[str, str]]):
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception as e:
        print(f"Skipping {path}: parse error ({e})")
        return

    # STOPS: StopPoint elements with AtcoCode and CommonName
    for sp in root.findall('.//tx:StopPoint', ns):
        atco = sp.find('tx:AtcoCode', ns)
        cname = sp.find('tx:CommonName', ns)
        if atco is not None and atco.text and cname is not None and cname.text:
            stops[atco.text.strip()] = cname.text.strip()

    # ROUTES / SERVICES: Service elements with ServiceCode and LineName
    for svc in root.findall('.//tx:Service', ns):
        sc = svc.find('tx:ServiceCode', ns)
        ln = svc.find('tx:LineName', ns)
        if sc is not None and sc.text:
            code = sc.text.strip()
            name = ln.text.strip() if (ln is not None and ln.text) else ""
            routes[code] = name

    # JOURNEYS: VehicleJourney elements with DepartureTime and JourneyPatternRef
    for vj in root.findall('.//tx:VehicleJourney', ns):
        # route id: try ServiceRef inside VehicleJourney
        route_id = None
        sref = vj.find('tx:ServiceRef', ns)
        if sref is not None and sref.text:
            route_id = sref.text.strip()
        else:
            # fallback: look for ServiceCode anywhere under the VehicleJourney
            sc = vj.find('.//tx:ServiceCode', ns)
            if sc is not None and sc.text:
                route_id = sc.text.strip()

        # departure time
        dt = vj.find('tx:DepartureTime', ns)
        if dt is not None and dt.text and route_id:
            journeys.append((route_id, dt.text.strip()))


def main():
    base = "/workspace/backend/data/timetables"
    stops: Dict[str, str] = {}
    routes: Dict[str, str] = {}
    journeys: List[Tuple[str, str]] = []

    for dirpath, _, filenames in os.walk(base):
        for fn in filenames:
            if not fn.lower().endswith('.xml'):
                continue
            path = os.path.join(dirpath, fn)
            parse_file(path, stops, routes, journeys)

    print(f"Parsed stops: {len(stops)}")
    print(f"Parsed routes: {len(routes)}")
    print(f"Parsed journeys: {len(journeys)}")

if __name__ == '__main__':
    main()

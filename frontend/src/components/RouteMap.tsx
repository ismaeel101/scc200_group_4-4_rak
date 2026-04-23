import React, { useEffect, useMemo, useState } from 'react';
import { MapContainer, TileLayer, Polyline, CircleMarker, useMap } from 'react-leaflet';
import './RouteMap.css';
import 'leaflet/dist/leaflet.css';
import { Coordinates } from '../types/journey';

function FitBounds({ positions }: { positions: Coordinates[] }) {
  const map = useMap();
  useEffect(() => {
    if (!map || !positions || positions.length === 0) return;
    const latlngs = positions.map((p) => [p[0], p[1]] as [number, number]);

    const apply = () => {
      try { map.invalidateSize(); } catch (e) { }
      try { map.fitBounds(latlngs, { padding: [40, 40] }); } catch (e) { }
    };

    if (typeof (map as any).whenReady === 'function') {
      (map as any).whenReady(() => requestAnimationFrame(() => requestAnimationFrame(apply)));
    } else {
      requestAnimationFrame(() => requestAnimationFrame(apply));
    }

    const onResize = () => {
      requestAnimationFrame(() => { try { map.invalidateSize(); } catch (e) { } });
    };

    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [map, positions]);
  return null;
}

const modeColor = (mode: string) => {
  const m = (mode || '').toLowerCase();
  if (m === 'rail' || m === 'train') return '#ef4444';
  if (m === 'bus') return '#2563eb';
  return '#64748b';
};

const toNum = (v: any): number | null => {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

type RawLeg = {
  mode?: string;
  from_lat?: number;
  from_lon?: number;
  to_lat?: number;
  to_lon?: number;
  _waypoints?: [number, number][];
};

type RouteSegment = {
  mode: string;
  points: [number, number][];
};

const RouteMap: React.FC<{ legs?: RawLeg[] }> = ({ legs = [] }) => {
  const MapC: any = MapContainer;
  const TileC: any = TileLayer;
  const PolyC: any = Polyline;
  const CircleC: any = CircleMarker;

  const routeSegments = useMemo(() => {
    return (legs || [])
      .map((leg) => {
        // Use pre-fetched waypoints (real stop coordinates) when available
        const waypoints = (leg as any)._waypoints as [number, number][] | undefined;
        if (waypoints && waypoints.length >= 2) {
          return { mode: (leg?.mode || '').toString(), points: waypoints };
        }
        // Fallback: straight line between origin and destination
        const fromLat = toNum((leg as any)?.from_lat);
        const fromLon = toNum((leg as any)?.from_lon);
        const toLat = toNum((leg as any)?.to_lat);
        const toLon = toNum((leg as any)?.to_lon);
        if (fromLat === null || fromLon === null || toLat === null || toLon === null) return null;
        return {
          mode: (leg?.mode || '').toString(),
          points: [[fromLat, fromLon], [toLat, toLon]] as [number, number][],
        };
      })
      .filter((x): x is RouteSegment => !!x);
  }, [legs]);

  const [routedSegments, setRoutedSegments] = useState<RouteSegment[]>([]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const fetchRoutes = async () => {
      if (!routeSegments.length) {
        setRoutedSegments([]);
        return;
      }

      try {
        const routed = await Promise.all(
          routeSegments.map(async (segment) => {
            // Build OSRM waypoints string from all points (up to 10 to avoid URL limits)
            const pts = segment.points;
            // Sample evenly if too many points
            const MAX_WAYPOINTS = 10;
            let sampled = pts;
            if (pts.length > MAX_WAYPOINTS) {
              const step = (pts.length - 1) / (MAX_WAYPOINTS - 1);
              sampled = Array.from({ length: MAX_WAYPOINTS }, (_, i) => pts[Math.round(i * step)]);
            }
            const coords = sampled.map(p => `${p[1]},${p[0]}`).join(';');
            const url = `https://router.project-osrm.org/route/v1/driving/${coords}?overview=full&geometries=geojson`;
            const res = await fetch(url, { signal: controller.signal });
            if (!res.ok) return segment;
            const data = await res.json();
            const routeCoords = data?.routes?.[0]?.geometry?.coordinates;
            if (!Array.isArray(routeCoords) || routeCoords.length < 2) return segment;

            const points = routeCoords
              .map((c: any) => {
                const lon = toNum(Array.isArray(c) ? c[0] : null);
                const lat = toNum(Array.isArray(c) ? c[1] : null);
                if (lat === null || lon === null) return null;
                return [lat, lon] as [number, number];
              })
              .filter((p: [number, number] | null): p is [number, number] => !!p);

            return points.length >= 2 ? { mode: segment.mode, points } : segment;
          })
        );

        if (!cancelled) setRoutedSegments(routed);
      } catch {
        if (!cancelled) setRoutedSegments(routeSegments);
      }
    };

    fetchRoutes();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [routeSegments]);

  const displaySegments = routedSegments.length ? routedSegments : routeSegments;

  const allPoints = useMemo(
    () => displaySegments.flatMap((s) => s.points).map((p) => [p[0], p[1]] as Coordinates),
    [displaySegments]
  );

  const fallbackCoord: Coordinates | undefined = allPoints.length ? allPoints[0] : undefined;

  const maxBounds: [number, number][] = [
    [53.0, -4.8],
    [55.2, -1.0],
  ];

  return (
    <MapC
      className="route-map"
      center={[fallbackCoord ? fallbackCoord[0] : 54.05, fallbackCoord ? fallbackCoord[1] : -2.8]}
      zoom={10}
      style={{ height: '100%', width: '100%' }}
      minZoom={6}
      maxZoom={13}
      maxBounds={maxBounds}
      maxBoundsViscosity={0.8}
    >
      <TileC
        attribution='&copy; OpenStreetMap contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        subdomains="abc"
        crossOrigin="anonymous"
      />
      {displaySegments.map((segment, idx) => (
        <PolyC
          key={idx}
          positions={segment.points.map((p) => [p[0], p[1]])}
          pathOptions={{ color: modeColor(segment.mode), weight: 5, opacity: 0.95 }}
        />
      ))}

      {allPoints.length > 0 && (
        <CircleC
          center={[allPoints[0][0], allPoints[0][1]]}
          radius={8}
          pathOptions={{ color: '#15803d', fillColor: '#22c55e', fillOpacity: 1, weight: 2 }}
        />
      )}

      {allPoints.length > 1 && (
        <CircleC
          center={[allPoints[allPoints.length - 1][0], allPoints[allPoints.length - 1][1]]}
          radius={8}
          pathOptions={{ color: '#b91c1c', fillColor: '#ef4444', fillOpacity: 1, weight: 2 }}
        />
      )}

      <FitBounds positions={allPoints} />
    </MapC>
  );
};

export default RouteMap;
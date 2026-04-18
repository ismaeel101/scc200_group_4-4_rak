import React, { useEffect } from 'react';
import { MapContainer, TileLayer, Polyline, Marker, useMap } from 'react-leaflet';
import './RouteMap.css';
import 'leaflet/dist/leaflet.css';
import { Journey, Leg, Coordinates } from '../types/journey';

function FitBounds({ positions }: { positions: Coordinates[] }) {
  const map = useMap();
  useEffect(() => {
    if (!map || !positions || positions.length === 0) return;
    const latlngs = positions.map((p) => [p[0], p[1]] as [number, number]);

    const apply = () => {
      try {
        map.invalidateSize();
      } catch (e) {
        // ignore
      }
      try {
        map.fitBounds(latlngs, { padding: [40, 40] });
      } catch (e) {
        // ignore
      }
    };

    if (typeof (map as any).whenReady === 'function') {
      (map as any).whenReady(() => requestAnimationFrame(() => requestAnimationFrame(apply)));
    } else {
      requestAnimationFrame(() => requestAnimationFrame(apply));
    }

    const onResize = () => {
      requestAnimationFrame(() => {
        try {
          map.invalidateSize();
        } catch (e) {
          // ignore
        }
      });
    };

    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [map, positions]);
  return null;
}

const modeColor: Record<string, string> = {
  rail: '#2563eb',
  train: '#2563eb',
  bus: '#f97316',
  tram: '#f59e0b',
  ferry: '#0ea5e9',
  walk: '#10b981',
};

const RouteMap: React.FC<{ legs?: Leg[]; center?: Coordinates | undefined }> = ({ legs = [], center }) => {
  const MapC: any = MapContainer;
  const TileC: any = TileLayer;
  const PolyC: any = Polyline;
  const MarkC: any = Marker;

  // choose center fallback
  const fallbackCoord: Coordinates | undefined =
    center || (legs && legs.length && legs[0] && legs[0].coordinates && legs[0].coordinates.from) || undefined;

  // Bounds roughly for North West UK
  const maxBounds: [number, number][] = [
    [53.0, -4.8],
    [55.2, -1.0],
  ];

  return (
    <MapC className="route-map" center={[fallbackCoord ? fallbackCoord[0] : 54.05, fallbackCoord ? fallbackCoord[1] : -2.8]} zoom={10} style={{ height: '100%', width: '100%' }} minZoom={6} maxZoom={13} maxBounds={maxBounds} maxBoundsViscosity={0.8}>
      <TileC
        attribution='&copy; OpenStreetMap contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {legs.map((leg, idx) => {
        const pts: Coordinates[] = leg.coordinates.polyline && leg.coordinates.polyline.length > 0 ? leg.coordinates.polyline : [leg.coordinates.from, leg.coordinates.to];
        return (
          <PolyC key={idx} positions={pts.map((p) => [p[0], p[1]])} pathOptions={{ color: modeColor[leg.mode || 'train'] || '#2563eb', weight: 4, opacity: 0.95 }} />
        );
      })}

      {/* markers at leg start points */}
      {legs.map((leg, idx) => (
        <MarkC key={`m-${idx}`} position={[leg.coordinates.from[0], leg.coordinates.from[1]]} />
      ))}

      <FitBounds
        positions={legs.flatMap((l) => (l.coordinates.polyline && l.coordinates.polyline.length ? l.coordinates.polyline : [l.coordinates.from, l.coordinates.to]))}
      />
    </MapC>
  );
};

export default RouteMap;

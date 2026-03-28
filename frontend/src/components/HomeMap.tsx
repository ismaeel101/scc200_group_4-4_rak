import React from 'react';
import 'leaflet/dist/leaflet.css';
import { MapContainer, TileLayer } from 'react-leaflet';
import StopMarkers from './StopMarkers';
import LiveStopLayer from './LiveStopLayer';
import { Stop } from '../types/stop';
import './HomeMap.css';

type Props = {
  stops?: Stop[];
};

const HomeMap: React.FC<Props> = ({ stops = [] }) => {
  // Regional centre for North West UK
  const center: [number, number] = [54.1, -2.5];

  // Bounds roughly covering North West England (lat, lng)
  const maxBounds: [number, number][] = [
    [53.0, -4.8], // southWest
    [55.2, -1.0], // northEast
  ];

  const MapC: any = MapContainer;
  const TileC: any = TileLayer;
  return (
    <section className="card homemap-card" aria-label="Home map">
      <h3 className="card__title">Explore the area</h3>
      <div className="homemap-placeholder">
        <div className="map-inner">
          <MapC
            center={center}
            zoom={12}
            minZoom={6}
            maxZoom={18}
            maxBounds={maxBounds}
            maxBoundsViscosity={0.8}
            style={{ height: '100%', width: '100%' }}
          >
            <TileC
              attribution='&copy; OpenStreetMap contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <LiveStopLayer />
            {stops.length > 0 && <StopMarkers stops={stops} />}
          </MapC>
        </div>
      </div>
    </section>
  );
};

export default HomeMap;

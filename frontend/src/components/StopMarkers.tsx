import React, { useEffect, useRef } from 'react';
import { useMap } from 'react-leaflet';
import L from 'leaflet';
import { Stop } from '../types/stop';

type Props = {
    stops: Stop[];
};

const StopMarkers: React.FC<Props> = ({ stops }) => {
    const map = useMap();
    const layerRef = useRef<any>(null);

    useEffect(() => {
        // Remove existing layer
        if (layerRef.current) {
            layerRef.current.remove();
            layerRef.current = null;
        }

        if (!stops || stops.length === 0) return;

        const lg = L.layerGroup();

        stops.forEach((s) => {
            try {
                const marker = L.marker([s.lat, s.lon]);
                marker.bindPopup(s.name);
                lg.addLayer(marker);
            } catch (e) {
                // ignore invalid coords
            }
        });

        layerRef.current = lg;
        lg.addTo(map);

        // Debug: log number of markers added and current zoom
        try {
            console.log('[StopMarkers] added markers:', lg.getLayers().length, 'map zoom', map.getZoom());
        } catch (e) { }

        return () => {
            if (layerRef.current) {
                layerRef.current.remove();
                layerRef.current = null;
            }
        };
    }, [stops, map]);

    return null;
};

export default StopMarkers;

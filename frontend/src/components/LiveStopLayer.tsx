import React, { useEffect, useRef, useState } from 'react';
import { useMap } from 'react-leaflet';
import L from 'leaflet';
import { useUi } from '../contexts/UiContext';

const LiveStopLayer: React.FC = () => {
    const map = useMap();
    const markersRef = useRef<any[]>([]);
    const abortRef = useRef<AbortController | null>(null);
    const ui = useUi();
    const [stops, setStops] = useState<any[]>([]);

    // validStopIds is populated from the backend at app startup (UiContext)

    useEffect(() => {
        const onPopupOpen = (e: any) => {
            try {
                const container = e.popup.getElement();
                if (!container) return;
                const originBtn = container.querySelector('.set-origin');
                const destBtn = container.querySelector('.set-dest');
                if (originBtn) {
                    // use onclick to avoid stacking duplicate listeners and use event.currentTarget.dataset
                    originBtn.onclick = (ev: any) => {
                        const el = ev.currentTarget as HTMLElement;
                        const id = el?.dataset?.id ?? null;
                        const name = el?.dataset?.name ?? null;
                        const stop = { id, name };
                        console.log('Selected stop:', stop);
                        console.log('Using ATCO:', id);
                        if (!id || id.trim().length === 0) {
                            console.warn('Invalid stop ID, ignoring:', stop);
                            return;
                        }
                        console.log('[LiveStopLayer] Set as Origin clicked:', id, name);
                        ui.setSelectedOrigin(id, name);
                        const input = document.getElementById('from-input') as HTMLInputElement | null;
                        if (input) input.value = name || '';
                        try { e.popup._close(); } catch (_) { }
                    };
                }
                if (destBtn) {
                    destBtn.onclick = (ev: any) => {
                        const el = ev.currentTarget as HTMLElement;
                        const id = el?.dataset?.id ?? null;
                        const name = el?.dataset?.name ?? null;
                        const stop = { id, name };
                        console.log('Selected stop:', stop);
                        console.log('Using ATCO:', id);
                        if (!id || id.trim().length === 0) {
                            console.warn('Invalid stop ID, ignoring:', stop);
                            return;
                        }
                        console.log('[LiveStopLayer] Set as Destination clicked:', id, name);
                        ui.setSelectedDestination(id, name);
                        const input = document.getElementById('to-input') as HTMLInputElement | null;
                        if (input) input.value = name || '';
                        try { e.popup._close(); } catch (_) { }
                    };
                }
            } catch (err) { }
        };

        const fetchAndRender = async () => {
            if (abortRef.current) {
                try { abortRef.current.abort(); } catch (e) { }
            }
            abortRef.current = new AbortController();
            const controller = abortRef.current;

            try {
                const bounds = map.getBounds();
                const sw = bounds.getSouthWest();
                const ne = bounds.getNorthEast();

                // Only fetch when zoom >= threshold
                const zoom = map.getZoom();
                const ZOOM_THRESHOLD = 12; // only show stops when zoomed in
                console.log('[LiveStopLayer] map zoom', zoom);
                if (zoom < ZOOM_THRESHOLD) {
                    if (markersRef.current && markersRef.current.length > 0) {
                        markersRef.current.forEach((m) => m.remove());
                        markersRef.current = [];
                    }
                    console.log('[LiveStopLayer] below threshold - cleared markers');
                    return;
                }

                const params = new URLSearchParams({
                    min_lat: String(sw.lat),
                    max_lat: String(ne.lat),
                    min_lon: String(sw.lng),
                    max_lon: String(ne.lng),
                    limit: '500',
                });

                const backendBase = `${location.protocol}//${location.hostname}:8000`;
                const url = `${backendBase}/api/stops?${params.toString()}`;
                console.log('[LiveStopLayer] fetching URL:', url);
                const res = await fetch(url, { signal: controller.signal });
                if (!res.ok) return;
                const stops = await res.json();
                // filter to routable stops using shared validStopIds (populated by UiContext)
                const valid = ui.validStopIds || new Set<string>();
                const totalStops = Array.isArray(stops) ? stops.length : 0;
                console.log('[LiveStopLayer] Valid stop IDs count:', valid.size);
                const filteredStops = Array.isArray(stops)
                    ? (valid.size > 0 ? stops.filter((s: any) => valid.has(s.id)) : stops)
                    : [];
                console.log('[LiveStopLayer] Total stops:', totalStops);
                console.log('[LiveStopLayer] Routable stops:', filteredStops.length);

                // remove existing markers
                if (markersRef.current && markersRef.current.length > 0) {
                    markersRef.current.forEach((m) => m.remove());
                    markersRef.current = [];
                }

                if (!filteredStops || filteredStops.length === 0) {
                    setStops([]);
                    return;
                }

                // store filtered stops locally; shared validStopIds will be set in effect
                setStops(filteredStops);

                const created: any[] = [];
                filteredStops.forEach((s: any) => {
                    try {
                        const circle = L.circleMarker([s.lat, s.lon], {
                            radius: 10,
                            color: '#ffffff',
                            fillColor: '#2563EB',
                            fillOpacity: 1,
                            weight: 2,
                        });
                        circle.bindPopup(
                            `<div style="min-width:160px;padding:6px"><h4 style=\"margin:0 0 8px 0; font-size:14px;\">🚌 ${s.name}</h4><div style=\"display:flex;gap:8px;justify-content:space-between\"><button class=\"set-origin\" data-id=\"${s.id}\" data-name=\"${s.name}\" style=\"background:#10b981;border:0;color:#fff;padding:6px 8px;border-radius:4px;cursor:pointer\">Set as Origin</button><button class=\"set-dest\" data-id=\"${s.id}\" data-name=\"${s.name}\" style=\"background:#ef4444;border:0;color:#fff;padding:6px 8px;border-radius:4px;cursor:pointer\">Set as Destination</button></div></div>`
                        );
                        circle.addTo(map);
                        created.push(circle);
                    } catch (e) {
                        // ignore bad coords
                    }
                });

                markersRef.current = created;
                // attach popup handler
                map.off('popupopen', onPopupOpen);
                map.on('popupopen', onPopupOpen);
            } catch (err) {
                // aborted or network error — ignore
            }
        };

        const onMove = () => {
            // debounce a little
            window.clearTimeout((onMove as any)._t);
            (onMove as any)._t = window.setTimeout(() => fetchAndRender(), 250);
        };

        // initial load once the map is ready
        map.whenReady(() => {
            console.log('[LiveStopLayer] initial ready zoom', map.getZoom());
            fetchAndRender();
        });

        map.on('moveend', onMove);
        map.on('zoomend', onMove);

        return () => {
            map.off('moveend', onMove);
            map.off('zoomend', onMove);
            map.off('popupopen', onPopupOpen);
            if (markersRef.current && markersRef.current.length > 0) {
                markersRef.current.forEach((m) => m.remove());
                markersRef.current = [];
            }
            if (abortRef.current) {
                try { abortRef.current.abort(); } catch (e) { }
                abortRef.current = null;
            }
        };
    }, [map]);

    return null;
};

export default LiveStopLayer;

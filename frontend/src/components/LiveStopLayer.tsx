import React, { useEffect, useRef, useState } from 'react';
import { useMap } from 'react-leaflet';
import L from 'leaflet';
import { useUi } from '../contexts/UiContext';

const LiveStopLayer: React.FC<{ mode?: 'all' | 'bus' | 'rail' }> = ({ mode = 'all' }) => {
    const map = useMap();
    const markersRef = useRef<any[]>([]);
    const abortRef = useRef<AbortController | null>(null);
    const lastFetchAtRef = useRef<number>(0);
    const backoffUntilRef = useRef<number>(0);
    const lastRequestKeyRef = useRef<string>('');
    const cacheRef = useRef<Map<string, any[]>>(new Map());
    const popupHandlerRef = useRef<(e: any) => void>(() => { });
    const ui = useUi();
    const [stops, setStops] = useState<any[]>([]);
    const [zoomLevel, setZoomLevel] = useState<number>(map.getZoom());

    const zoomFetchLimit = (zoom: number): number => {
        if (zoom <= 8) return 160;
        if (zoom <= 11) return 320;
        return 500;
    };

    const zoomRenderConfig = (zoom: number) => {
        if (zoom <= 8) return { cellSize: 0.06, cap: 140 };
        if (zoom <= 10) return { cellSize: 0.03, cap: 240 };
        if (zoom <= 12) return { cellSize: 0.015, cap: 380 };
        return { cellSize: 0, cap: 1000 };
    };

    const sampleByZoom = (rows: any[], zoom: number): any[] => {
        const cfg = zoomRenderConfig(zoom);
        if (cfg.cellSize <= 0) return rows.slice(0, cfg.cap);

        const byCell = new Map<string, any>();
        for (const s of rows) {
            const lat = Number(s?.lat);
            const lon = Number(s?.lon);
            if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
            const latCell = Math.floor(lat / cfg.cellSize);
            const lonCell = Math.floor(lon / cfg.cellSize);
            const key = `${latCell}:${lonCell}`;
            if (!byCell.has(key)) {
                byCell.set(key, s);
            }
            if (byCell.size >= cfg.cap) break;
        }
        return Array.from(byCell.values());
    };

    const quantize = (n: number, digits = 3) => Number(n.toFixed(digits));

    popupHandlerRef.current = (e: any) => {
        try {
            const container = e.popup.getElement();
            if (!container) return;

            // Handle Start here / Go here buttons
            const originBtn = container.querySelector('.set-origin');
            const destBtn = container.querySelector('.set-dest');
            if (originBtn) {
                originBtn.onclick = (ev: any) => {
                    const el = ev.currentTarget as HTMLElement;
                    const id = el?.dataset?.id ?? null;
                    const name = el?.dataset?.name ?? null;
                    if (!id || id.trim().length === 0) return;
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
                    if (!id || id.trim().length === 0) return;
                    ui.setSelectedDestination(id, name);
                    const input = document.getElementById('to-input') as HTMLInputElement | null;
                    if (input) input.value = name || '';
                    try { e.popup._close(); } catch (_) { }
                };
            }

            // Load departures board
            const depContainer = container.querySelector('.departures-board');
            if (!depContainer) return;
            const stopId = (depContainer as HTMLElement).dataset?.stopId;
            if (!stopId) return;

            const backendBase = `${location.protocol}//${location.hostname}:8000`;
            fetch(`${backendBase}/api/departures?stop_id=${encodeURIComponent(stopId)}&limit=5`)
                .then(r => r.ok ? r.json() : null)
                .then(data => {
                    const departures = data?.departures || [];
                    if (departures.length === 0) {
                        depContainer.innerHTML = '<div style="color:#6b7280;font-size:11px;padding:4px 0;">No upcoming departures.</div>';
                        return;
                    }
                    const rows = departures.map((d: any) => `
                        <tr>
                            <td style="padding:3px 8px 3px 0;color:#f59e0b;font-weight:700;font-size:12px;white-space:nowrap;">${d.time}</td>
                            <td style="padding:3px 8px;color:#60a5fa;font-weight:700;font-size:12px;white-space:nowrap;">${d.line}</td>
                            <td style="padding:3px 0;color:#f1f5f9;font-size:12px;">${d.destination}</td>
                        </tr>
                    `).join('');
                    depContainer.innerHTML = `
                        <div style="margin-top:8px;background:#0f172a;border-radius:6px;padding:8px;">
                            <div style="color:#f59e0b;font-weight:800;font-size:10px;letter-spacing:1px;margin-bottom:5px;">DEPARTURES</div>
                            <table style="width:100%;border-collapse:collapse;">
                                <thead>
                                    <tr style="border-bottom:1px solid #1e293b;">
                                        <th style="color:#60a5fa;font-size:9px;font-weight:600;text-align:left;padding:2px 8px 3px 0;letter-spacing:0.5px;">TIME</th>
                                        <th style="color:#60a5fa;font-size:9px;font-weight:600;text-align:left;padding:2px 8px 3px;letter-spacing:0.5px;">LINE</th>
                                        <th style="color:#60a5fa;font-size:9px;font-weight:600;text-align:left;padding:2px 0 3px;letter-spacing:0.5px;">DESTINATION</th>
                                    </tr>
                                </thead>
                                <tbody>${rows}</tbody>
                            </table>
                        </div>
                    `;
                })
                .catch(() => {
                    depContainer.innerHTML = '<div style="color:#f87171;font-size:11px;">Failed to load departures.</div>';
                });
        } catch (err) { }
    };

    useEffect(() => {
        const fetchStops = async () => {
            const nowMs = Date.now();
            if (nowMs < backoffUntilRef.current) return;

            const MIN_FETCH_INTERVAL_MS = 900;
            if (nowMs - lastFetchAtRef.current < MIN_FETCH_INTERVAL_MS) return;

            try {
                const bounds = map.getBounds();
                const sw = bounds.getSouthWest();
                const ne = bounds.getNorthEast();
                const zoom = map.getZoom();
                const dynamicLimit = zoomFetchLimit(zoom);

                const requestKey = [
                    quantize(sw.lat), quantize(ne.lat),
                    quantize(sw.lng), quantize(ne.lng),
                    dynamicLimit,
                ].join('|');

                if (requestKey === lastRequestKeyRef.current && cacheRef.current.has(requestKey)) {
                    const cached = cacheRef.current.get(requestKey) || [];
                    setStops(cached);
                    return;
                }

                if (abortRef.current) {
                    try { abortRef.current.abort(); } catch (e) { }
                }
                abortRef.current = new AbortController();
                const controller = abortRef.current;

                const params = new URLSearchParams({
                    min_lat: String(sw.lat), max_lat: String(ne.lat),
                    min_lon: String(sw.lng), max_lon: String(ne.lng),
                    limit: String(dynamicLimit),
                });

                const backendBase = `${location.protocol}//${location.hostname}:8000`;
                const url = `${backendBase}/api/stops?${params.toString()}`;
                const res = await fetch(url, { signal: controller.signal });
                if (res.status === 429) {
                    backoffUntilRef.current = Date.now() + 4000;
                    return;
                }
                if (!res.ok) return;
                const stops = await res.json();
                const valid = ui.validStopIds || new Set<string>();
                const filteredStops = Array.isArray(stops)
                    ? (valid.size > 0 ? stops.filter((s: any) => valid.has(s.id)) : stops)
                    : [];

                setStops(filteredStops);
                lastFetchAtRef.current = Date.now();
                lastRequestKeyRef.current = requestKey;
                cacheRef.current.set(requestKey, filteredStops);
                if (cacheRef.current.size > 20) {
                    const firstKey = cacheRef.current.keys().next().value;
                    if (firstKey) cacheRef.current.delete(firstKey);
                }
                ui.setAvailableStops(
                    (filteredStops || []).map((s: any) => ({
                        id: String(s.id),
                        name: String(s.name),
                        type: s.type === 'rail' ? 'rail' : 'bus',
                        lat: Number(s.lat),
                        lon: Number(s.lon),
                    }))
                );
            } catch (err) { }
        };

        const onMove = () => {
            window.clearTimeout((onMove as any)._t);
            (onMove as any)._t = window.setTimeout(() => fetchStops(), 250);
        };

        const onZoom = () => {
            setZoomLevel(map.getZoom());
            onMove();
        };

        const handlePopupOpen = (e: any) => {
            popupHandlerRef.current(e);
        };

        map.whenReady(() => {
            setZoomLevel(map.getZoom());
            fetchStops();
        });

        map.on('moveend', onMove);
        map.on('zoomend', onZoom);
        map.on('popupopen', handlePopupOpen);

        return () => {
            map.off('moveend', onMove);
            map.off('zoomend', onZoom);
            map.off('popupopen', handlePopupOpen);
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

    useEffect(() => {
        if (markersRef.current && markersRef.current.length > 0) {
            markersRef.current.forEach((m) => m.remove());
            markersRef.current = [];
        }

        if (!stops || stops.length === 0) return;

        const visibleStops = (stops || []).filter((s: any) => {
            const stopType = String(s?.type || '').toLowerCase();
            const isRail = stopType === 'rail' || stopType === 'train';
            if (mode === 'bus') return !isRail;
            if (mode === 'rail') return isRail;
            return true;
        });

        const sampledStops = sampleByZoom(visibleStops, zoomLevel);

        const created: any[] = [];
        sampledStops.forEach((s: any) => {
            try {
                const stopType = String(s?.type || '').toLowerCase();
                const isRail = stopType === 'rail' || stopType === 'train';
                const markerFill = isRail ? '#EF4444' : '#2563EB';
                const markerIcon = isRail ? '🚆' : '🚌';
                const circle = L.circleMarker([s.lat, s.lon], {
                    radius: 10,
                    color: '#ffffff',
                    fillColor: markerFill,
                    fillOpacity: 1,
                    weight: 2,
                });
                circle.bindPopup(
                    `<div style="min-width:240px;max-width:280px;background:#0b2136;color:#e6eefb;border-radius:12px;padding:12px;box-shadow:0 10px 28px rgba(2,6,23,0.28);border:1px solid rgba(255,255,255,0.08);font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;">
                        <div style="display:flex;align-items:center;gap:8px;margin:0 0 4px 0;">
                            <span style="font-size:16px;line-height:1;">${markerIcon}</span>
                            <h4 style="margin:0;font-size:14px;font-weight:700;color:#ffffff;line-height:1.3;">${s.name}</h4>
                        </div>
                        <div style="font-size:11px;color:#c7d6ea;margin:0 0 8px 0;">${isRail ? 'Rail stop' : 'Bus stop'}</div>
                        <div style="display:flex;gap:8px;margin-bottom:6px;">
                            <button class="set-origin" data-id="${s.id}" data-name="${s.name}" style="flex:1;background:#10b981;border:1px solid rgba(255,255,255,0.08);color:#ffffff;padding:7px 10px;border-radius:8px;cursor:pointer;font-weight:700;font-size:12px;">🟢 Start here</button>
                            <button class="set-dest" data-id="${s.id}" data-name="${s.name}" style="flex:1;background:#1e3a8a;border:1px solid rgba(255,255,255,0.1);color:#ffffff;padding:7px 10px;border-radius:8px;cursor:pointer;font-weight:700;font-size:12px;">🔴 Go here</button>
                        </div>
                        <div class="departures-board" data-stop-id="${s.id}" style="font-size:11px;color:#6b7280;">Loading departures…</div>
                    </div>`,
                    { className: 'stop-popup-clean' }
                );
                circle.addTo(map);
                created.push(circle);
            } catch (e) { }
        });

        markersRef.current = created;

        return () => {
            if (markersRef.current && markersRef.current.length > 0) {
                markersRef.current.forEach((m) => m.remove());
                markersRef.current = [];
            }
        };
    }, [map, mode, stops, zoomLevel]);

    return null;
};

export default LiveStopLayer;
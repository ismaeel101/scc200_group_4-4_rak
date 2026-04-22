import React, { useEffect, useMemo, useState } from 'react';
import translations from '../translations';
import { useUi } from '../contexts/UiContext';
import './LiveDeparturesPage.css';

type LiveLeg = {
    mode?: string;
    line?: string;
    service_id?: string;
    from_stop?: string;
    to_stop?: string;
    from?: string;
    to?: string;
    depart?: string;
    live_status?: {
        available?: boolean;
        delay_minutes?: number;
        disrupted_flag?: boolean;
    };
};

const BACKEND_BASE = 'http://127.0.0.1:8000';
const EXAMPLE_JOURNEY_REQUEST = {
    origin_id: '2500918',
    destination_id: '2500LA00220',
    time_type: 'depart_at' as const,
    modes: 'mixed',
    max_options: 8,
};

const LiveDeparturesPage: React.FC = () => {
    const ui = useUi();
    const t = translations[ui.language.code] || translations.en;
    const liveDeparturesLabel = typeof t.liveDepartures === 'string' ? t.liveDepartures : 'Live Departures';

    const [loading, setLoading] = useState(true);
    const [busLegs, setBusLegs] = useState<LiveLeg[]>([]);
    const [openRoute, setOpenRoute] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;

        const load = async () => {
            setLoading(true);
            try {
                const nowIso = new Date().toISOString();
                const payload = { ...EXAMPLE_JOURNEY_REQUEST, time_iso: nowIso };
                console.log('[LiveDepartures] Using request payload:', payload);
                const journeyRes = await fetch(`${BACKEND_BASE}/journeys`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                if (!journeyRes.ok) {
                    console.warn('[LiveDepartures] /journeys failed with status', journeyRes.status);
                    if (!cancelled) setBusLegs([]);
                    return;
                }

                const journeyBody = await journeyRes.json();
                const journeys = Array.isArray(journeyBody?.journeys) ? journeyBody.journeys : [];
                const legs = journeys
                    .flatMap((j: any) => (Array.isArray(j?.legs) ? j.legs : []))
                    .filter((leg: LiveLeg) => String(leg?.mode || '').toLowerCase() === 'bus');

                console.log('[LiveDepartures] Journeys fetched:', journeys.length);
                console.log('[LiveDepartures] Bus legs extracted:', legs.length);

                const uniqueLegs = Array.from(
                    new Map<string, LiveLeg>(
                        legs.map((leg: LiveLeg) => {
                            const key = [leg.service_id, leg.line, leg.from_stop || leg.from, leg.to_stop || leg.to, leg.depart].join('|');
                            return [key, leg] as [string, LiveLeg];
                        })
                    ).values()
                );

                if (!cancelled) setBusLegs(uniqueLegs);
            } catch {
                if (!cancelled) {
                    setBusLegs([]);
                }
            } finally {
                if (!cancelled) setLoading(false);
            }
        };

        load();
        const timer = window.setInterval(load, 60000);
        return () => {
            cancelled = true;
            window.clearInterval(timer);
        };
    }, []);

    const routesWithStops = useMemo(() => {
        const legsSorted = [...busLegs].sort((a, b) => {
            const ta = a.depart ? new Date(a.depart).getTime() : 0;
            const tb = b.depart ? new Date(b.depart).getTime() : 0;
            return ta - tb;
        });

        const routeMap = new Map<string, string[]>();
        legsSorted.forEach((leg) => {
            const route = String(leg.line || leg.service_id || '').trim();
            if (!route) return;
            const from = String(leg.from_stop || leg.from || '').trim();
            const to = String(leg.to_stop || leg.to || '').trim();
            if (!routeMap.has(route)) routeMap.set(route, []);
            const stops = routeMap.get(route)!;
            if (from && !stops.includes(from)) stops.push(from);
            if (to && !stops.includes(to)) stops.push(to);
        });

        const routes = Array.from(routeMap.entries())
            .map(([route, stops]) => ({ route, stops }))
            .filter((r) => r.stops.length > 0)
            .sort((a, b) => a.route.localeCompare(b.route));

        console.log('[LiveDepartures] Routes derived from data:', routes);
        return routes;
    }, [busLegs]);

    useEffect(() => {
        if (!openRoute && routesWithStops.length > 0) {
            setOpenRoute(routesWithStops[0].route);
        }
    }, [routesWithStops, openRoute]);

    return (
        <main className="live-page">
            <div className="live-page__container">
                <h2 className="live-page__title">{liveDeparturesLabel}</h2>

                {loading && <div className="live-card">Loading live departures…</div>}

                {!loading && (
                    <section className="live-card live-card--full">
                        <h3 className="live-card__title">Available bus routes</h3>
                        {routesWithStops.length === 0 ? (
                            <p className="live-empty">No routes available right now.</p>
                        ) : (
                            <div className="route-accordion" role="list">
                                {routesWithStops.map((row) => {
                                    const isOpen = openRoute === row.route;
                                    return (
                                        <div key={row.route} className="route-accordion__item" role="listitem">
                                            <button
                                                type="button"
                                                className="route-accordion__toggle"
                                                onClick={() => setOpenRoute(isOpen ? null : row.route)}
                                                aria-expanded={isOpen}
                                            >
                                                <span className="live-pill">Bus {row.route}</span>
                                                <span className="route-accordion__hint">{isOpen ? 'Hide stops' : 'Show stops'}</span>
                                            </button>
                                            {isOpen && (
                                                <ol className="route-stops">
                                                    {row.stops.map((stop, idx) => (
                                                        <li key={`${row.route}-${stop}-${idx}`}>{stop}</li>
                                                    ))}
                                                </ol>
                                            )}
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </section>
                )}
            </div>
        </main>
    );
};

export default LiveDeparturesPage;

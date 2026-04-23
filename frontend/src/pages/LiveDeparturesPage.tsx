import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import translations from '../translations';
import { useUi } from '../contexts/UiContext';
import './LiveDeparturesPage.css';

const ROUTES = [
    {
        id: "100",
        name: "Bus 100",
        description: "Lancaster University → Morecambe via Bowerham",
        operator: "Stagecoach",
        stops: [
            "Lancaster University (Underpass)",
            "Hala Square",
            "Bowerham Hotel",
            "Lancaster Common Garden Street",
            "Lancaster Bus Station",
            "Torrisholme Square",
            "Bare (Mayfield Drive)",
            "Morecambe Bus Station"
        ],
        // Departures from first stop (Underpass), every 15 mins Mon-Fri
        firstStopTimes: [
            "06:26", "06:41", "06:56", "07:14", "07:48", "08:08", "08:18", "08:33",
            "08:48", "09:03", "09:18", "09:33", "09:48", "10:03", "10:18", "10:33",
            "10:48", "11:03", "11:18", "11:33", "11:48", "12:03", "12:18", "12:33",
            "12:48", "13:03", "13:18", "13:33", "13:48", "14:03", "14:18", "14:33",
            "14:48", "15:03", "15:18", "15:35", "15:50", "16:05", "16:20", "16:35",
            "16:50", "17:05", "17:20", "17:35", "17:50", "18:05", "18:18", "18:33",
            "18:48", "19:00", "19:26", "19:46", "20:06", "20:26", "20:46", "21:06",
            "21:26", "21:46", "22:06", "22:26", "22:46", "23:06", "23:26", "23:46"
        ],
        // Minutes after first stop for each subsequent stop
        offsets: [0, 7, 14, 22, 28, 9, 15, 23]
    },
    {
        id: "1A",
        name: "Bus 1 / 1A",
        description: "Lancaster University → Lancaster → Heysham",
        operator: "Stagecoach",
        stops: [
            "Lancaster University (Underpass)",
            "Greaves (Belle Vue Terrace)",
            "Lancaster Infirmary",
            "Lancaster Common Garden Street",
            "Lancaster Bus Station",
            "Skerton (Greyhound Bridge)",
            "Scale Hall (Spar)",
            "Torrisholme Square",
            "Morecambe (County Garage)",
            "Sandylands (Battery)",
            "Heysham (Towers)"
        ],
        // Every 10 mins Mon-Sat during term time from ~07:00
        firstStopTimes: [
            "07:00", "07:10", "07:20", "07:30", "07:40", "07:50",
            "08:00", "08:10", "08:20", "08:30", "08:40", "08:50",
            "09:00", "09:10", "09:20", "09:30", "09:40", "09:50",
            "10:00", "10:10", "10:20", "10:30", "10:40", "10:50",
            "11:00", "11:10", "11:20", "11:30", "11:40", "11:50",
            "12:00", "12:10", "12:20", "12:30", "12:40", "12:50",
            "13:00", "13:10", "13:20", "13:30", "13:40", "13:50",
            "14:00", "14:10", "14:20", "14:30", "14:40", "14:50",
            "15:00", "15:10", "15:20", "15:30", "15:40", "15:50",
            "16:00", "16:10", "16:20", "16:30", "16:40", "16:50",
            "17:00", "17:10", "17:20", "17:30", "17:40", "17:50",
            "18:00", "18:20", "18:40", "19:00", "19:30", "20:00",
            "20:30", "21:00", "21:30", "22:00", "22:30"
        ],
        offsets: [0, 4, 8, 10, 14, 15, 18, 21, 26, 30, 36]
    },
    {
        id: "18",
        name: "Bus 18",
        description: "Lancaster City Centre Circular via Williamson Park",
        operator: "Kirkby Lonsdale Coaches",
        stops: [
            "Lancaster Bus Station",
            "Common Garden Street",
            "Williamson Park Gates",
            "Bowerham Leisure Park",
            "Lancaster Farms Prison",
            "Lancaster Bus Station (return)"
        ],
        firstStopTimes: [
            "06:55", "07:25", "07:57", "08:30", "09:05", "09:35",
            "10:05", "10:35", "11:05", "11:35", "12:05", "12:35",
            "13:05", "13:35", "14:05", "14:35", "15:10", "15:50",
            "16:30", "17:10", "17:50", "18:30"
        ],
        offsets: [0, 5, 9, 10, 15, 26]
    },
    {
        id: "41",
        name: "Bus 41",
        description: "Preston → Lancaster → Morecambe",
        operator: "Stagecoach",
        stops: [
            "Preston Bus Station",
            "Garstang",
            "Lancaster Bus Station",
            "Lancaster Common Garden Street",
            "Skerton (Greyhound Bridge)",
            "Scale Hall",
            "Torrisholme Square",
            "Morecambe Bus Station"
        ],
        firstStopTimes: [
            "06:30", "07:00", "07:30", "08:00", "08:30", "09:00", "09:30",
            "10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00",
            "13:30", "14:00", "14:30", "15:00", "15:30", "16:00", "16:30",
            "17:00", "17:30", "18:00", "18:30", "19:00", "19:30", "20:00"
        ],
        offsets: [0, 25, 50, 53, 56, 59, 63, 72]
    },
    {
        id: "X4",
        name: "Bus X4",
        description: "Lancaster University → Rail Station → Lancaster Bus Station",
        operator: "Stagecoach",
        stops: [
            "Lancaster University (Graduate College)",
            "Lancaster University (Underpass)",
            "Bailrigg (Health Innovation Campus)",
            "Lancaster Rail Station",
            "Lancaster Bus Station",
            "Lancaster Common Garden Street"
        ],
        firstStopTimes: [
            "07:08", "07:23", "07:38", "07:53", "08:08", "08:23", "08:38", "08:53",
            "09:08", "09:23", "09:38", "09:53", "10:08", "10:23", "10:38", "10:53",
            "11:08", "11:23", "11:38", "11:53", "12:08", "12:23", "12:38", "12:53",
            "13:08", "13:23", "13:38", "13:53", "14:08", "14:23", "14:38", "14:53",
            "15:08", "15:23", "15:38", "15:53", "16:08", "16:23", "16:38", "16:53",
            "17:08", "17:23", "17:38", "17:53", "18:08", "18:23"
        ],
        offsets: [0, 10, 12, 17, 22, 25]
    }
];

const parseTimeToMinutes = (value: string): number | null => {
    const m = value.match(/^(\d{2}):(\d{2})$/);
    if (!m) return null;
    const hh = Number(m[1]);
    const mm = Number(m[2]);
    if (!Number.isFinite(hh) || !Number.isFinite(mm) || hh < 0 || hh > 23 || mm < 0 || mm > 59) return null;
    return hh * 60 + mm;
};

const formatMinutesToTime = (mins: number): string => {
    const total = ((mins % 1440) + 1440) % 1440;
    const hh = String(Math.floor(total / 60)).padStart(2, '0');
    const mm = String(total % 60).padStart(2, '0');
    return `${hh}:${mm}`;
};

const addOffset = (baseTime: string, offset: number): string | null => {
    const base = parseTimeToMinutes(baseTime);
    if (base === null || !Number.isFinite(offset)) return null;
    return formatMinutesToTime(base + offset);
};

const LiveDeparturesPage: React.FC = () => {
    const navigate = useNavigate();
    const ui = useUi();
    const t = translations[ui.language.code] || translations.en;
    const liveDeparturesLabel = typeof t.liveDepartures === 'string' ? t.liveDepartures : 'Daily Timetable';

    const [selectedRouteId, setSelectedRouteId] = useState<string>(ROUTES[0].id);
    const [now, setNow] = useState<Date>(new Date());

    useEffect(() => {
        const timer = window.setInterval(() => setNow(new Date()), 30000);
        return () => window.clearInterval(timer);
    }, []);

    const selectedRoute = useMemo(
        () => ROUTES.find((r) => r.id === selectedRouteId) || ROUTES[0],
        [selectedRouteId]
    );

    const nowMinutes = useMemo(() => now.getHours() * 60 + now.getMinutes(), [now]);

    const departureMeta = useMemo(() => {
        const withMins = selectedRoute.firstStopTimes.map((time, idx) => ({
            idx,
            time,
            mins: parseTimeToMinutes(time),
        }));
        const nextIdx = withMins.findIndex((d) => d.mins !== null && d.mins >= nowMinutes);
        return withMins.map((d) => ({
            ...d,
            isPast: d.mins !== null ? d.mins < nowMinutes : false,
            isNext: nextIdx >= 0 && d.idx === nextIdx,
        }));
    }, [selectedRoute, nowMinutes]);

    const nextDeparture = useMemo(() => {
        const next = departureMeta.find((d) => d.isNext);
        return next ? next.time : null;
    }, [departureMeta]);

    return (
        <main className="live-page">
            <div className="live-page__container">
                <div className="live-page__header-row">
                    <h2 className="live-page__title">{liveDeparturesLabel}</h2>
                    <button
                        type="button"
                        className="live-page__plan-btn"
                        onClick={() => navigate('/')}
                    >
                        Plan Journey
                    </button>
                </div>

                <section className="live-layout">
                    <div className="live-card live-routes">
                        <h3 className="live-card__title">Bus routes</h3>
                        <div className="route-accordion" role="list">
                            {ROUTES.map((route) => {
                                const isOpen = selectedRoute.id === route.id;
                                return (
                                    <div key={route.id} className={`route-accordion__item ${isOpen ? 'route-accordion__item--active' : ''}`} role="listitem">
                                        <button
                                            type="button"
                                            className="route-accordion__toggle"
                                            onClick={() => setSelectedRouteId(route.id)}
                                            aria-expanded={isOpen}
                                        >
                                            <span className="live-pill">{route.name}</span>
                                            <span className="route-accordion__hint">{route.operator}</span>
                                        </button>
                                        {isOpen && (
                                            <div style={{ padding: '0 0.9rem 0.8rem', fontSize: '0.9rem', color: '#334155' }}>
                                                {route.description}
                                            </div>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    </div>

                    <div className="live-card live-timetable">
                        <div className="live-timetable__header">
                            <h3 className="live-card__title">{selectedRoute.name} timetable</h3>
                            <div className="next-departure" role="status" aria-live="polite">
                                Next departure: <strong>{nextDeparture || '—'}</strong>
                            </div>
                        </div>

                        <div className="timetable-wrap">
                            <table className="timetable-grid">
                                <thead>
                                    <tr>
                                        <th
                                            style={{
                                                position: 'sticky',
                                                left: 0,
                                                zIndex: 3,
                                                background: '#ffffff',
                                            }}
                                        >
                                            Stop
                                        </th>
                                        {departureMeta.map((dep) => (
                                            <th
                                                key={`${selectedRoute.id}-h-${dep.idx}`}
                                                style={{
                                                    background: dep.isNext ? '#dbeafe' : dep.isPast ? '#f1f5f9' : undefined,
                                                    color: dep.isNext ? '#1d4ed8' : dep.isPast ? '#64748b' : undefined,
                                                }}
                                            >
                                                {dep.time}
                                            </th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {selectedRoute.stops.map((stopName, stopIdx) => {
                                        const offset = selectedRoute.offsets[stopIdx];
                                        return (
                                            <tr key={`${selectedRoute.id}-stop-${stopIdx}`}>
                                                <td
                                                    className="timetable-stop"
                                                    style={{
                                                        position: 'sticky',
                                                        left: 0,
                                                        zIndex: 2,
                                                        background: '#ffffff',
                                                    }}
                                                >
                                                    {stopName}
                                                </td>
                                                {departureMeta.map((dep) => {
                                                    const timeAtStop = Number.isFinite(offset) ? addOffset(dep.time, Number(offset)) : null;
                                                    return (
                                                        <td
                                                            key={`${selectedRoute.id}-${stopIdx}-${dep.idx}`}
                                                            style={{
                                                                background: dep.isNext ? 'rgba(37, 99, 235, 0.08)' : dep.isPast ? '#f8fafc' : undefined,
                                                            }}
                                                        >
                                                            <span
                                                                className={`time-chip ${dep.isPast ? 'time-chip--past' : 'time-chip--upcoming'} ${dep.isNext ? 'time-chip--next' : ''}`}
                                                            >
                                                                {timeAtStop || '—'}
                                                            </span>
                                                        </td>
                                                    );
                                                })}
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </section>
            </div>
        </main>
    );
};

export default LiveDeparturesPage;

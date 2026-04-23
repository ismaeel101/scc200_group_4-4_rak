import React, { useState, useMemo, useEffect, useCallback } from "react";
import { useLocation, useNavigate } from 'react-router-dom';
import "./ResultsPage.css";
import translations from '../translations';
import { useUi } from '../contexts/UiContext';
import { Train, Bus, Clock, ArrowRight, ChevronDown, ChevronUp, MapPin } from "lucide-react";
import { Journey } from '../types/journey';
import { formatTime } from '../utils/formatTime';
import RouteMap from '../components/RouteMap';
import WeatherWidget from '../components/WeatherWidget';

const ResultsPage: React.FC = () => {
  const navigate = useNavigate();
  const { language } = useUi();
  const t = translations[language.code] || translations.en;
  const journeyResultsLabel = typeof t.journeyResults === 'string' ? t.journeyResults : 'Journey results';
  const journeyOptionsLabel = typeof t.journeyOptions === 'string' ? t.journeyOptions : 'Journey options';
  const routeMapLabel = typeof t.routeMap === 'string' ? t.routeMap : 'Route map';
  const journeyBreakdownLabel = typeof t.journeyBreakdown === 'string' ? t.journeyBreakdown : 'Journey breakdown';
  const reliabilityLabel = typeof t.reliability === 'string' ? t.reliability : 'Reliability';
  const reliabilityHighMsg = typeof t.reliabilityMessage_high === 'string' ? t.reliabilityMessage_high : 'High reliability';
  const reliabilityMediumMsg = typeof t.reliabilityMessage_medium === 'string' ? t.reliabilityMessage_medium : 'Medium reliability';
  const reliabilityLowMsg = typeof t.reliabilityMessage_low === 'string' ? t.reliabilityMessage_low : 'Low reliability';
  const fromLabel = typeof t.fromLabel === 'string' ? t.fromLabel : 'From';
  const toLabel = typeof t.toLabel === 'string' ? t.toLabel : 'To';
  const transferAtLabel = typeof t.transferAt === 'string' ? t.transferAt : 'Transfer at';

  // Read journeys and origin/destination names from router state
  const location = useLocation();
  const state = (location && (location.state as any)) || {};
  const search = state.search || (state.data && state.data.search) || null;
  const originName = state.origin || (state.search && state.search.from) || (state.data && state.data.from) || '';
  const destinationName = state.destination || (state.search && state.search.to) || (state.data && state.data.to) || '';
  const passedJourneys: any[] = state.journeys || (state.data && state.data.journeys) || [];
  const [journeys, setJourneys] = useState<any[]>(Array.isArray(passedJourneys) ? passedJourneys : []);
  const [requestCompleted, setRequestCompleted] = useState<boolean>(Array.isArray(passedJourneys) && passedJourneys.length > 0);

  useEffect(() => {
    let cancelled = false;

    const loadJourneys = async () => {
      if (!search || !search.origin_id || !search.destination_id || !search.time_type || !search.time_iso) {
        if (!cancelled) {
          setJourneys(Array.isArray(passedJourneys) ? passedJourneys : []);
          setRequestCompleted(true);
        }
        return;
      }

      if (!cancelled) {
        setRequestCompleted(false);
      }

      try {
        const payload = {
          origin_id: search.origin_id,
          destination_id: search.destination_id,
          time_type: search.time_type,
          time_iso: search.time_iso,
          modes: search.modes || 'mixed',
          max_options: search.max_options || 5,
        };

        console.log("SENDING REQUEST", payload);
        const res = await fetch('http://127.0.0.1:8000/journeys', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        if (!res.ok) throw new Error('Planner request failed');
        const body = await res.json();
        const journeysRaw = Array.isArray(body?.journeys) ? body.journeys : [];

        const selectedTime = new Date(search.time_iso);
        const validSelectedTime = Number.isFinite(selectedTime.getTime());
        const twoHoursMs = 2 * 60 * 60 * 1000;
        const filtered = validSelectedTime
          ? journeysRaw.filter((j: any) => {
            if (search.time_type === 'arrive_by') {
              const arrive = new Date(j?.arrive_time || j?.arriveTime || '').getTime();
              return Number.isFinite(arrive)
                && arrive <= selectedTime.getTime()
                && arrive >= selectedTime.getTime() - twoHoursMs;
            }
            const depart = new Date(j?.depart_time || j?.departureTime || '').getTime();
            return Number.isFinite(depart)
              && depart >= selectedTime.getTime()
              && depart <= selectedTime.getTime() + twoHoursMs;
          })
          : journeysRaw;

        if (!cancelled) {
          setJourneys(filtered);
          setRequestCompleted(true);
        }
      } catch (e) {
        if (!cancelled) {
          setJourneys([]);
          setRequestCompleted(true);
        }
      }
    };

    loadJourneys();
    return () => { cancelled = true; };
  }, [search]);

  const filteredBySearch = journeys;

  const [selectedJourney, setSelectedJourney] = useState<Journey | null>(null);
  useEffect(() => {
    const first = Array.isArray(filteredBySearch) && filteredBySearch.length ? filteredBySearch[0] : null;
    setSelectedJourney(first || null);
  }, [filteredBySearch]);

  const journeysToRender: any[] = Array.isArray(filteredBySearch) ? filteredBySearch : [];
  const fastestDurationMin = useMemo(() => {
    const durations = journeysToRender
      .map((j: any) => Number(j?.total_duration_min))
      .filter((n: number) => Number.isFinite(n));
    if (!durations.length) return null;
    return Math.min(...durations);
  }, [journeysToRender]);
  const activeJourney = selectedJourney || (journeysToRender && journeysToRender[0]) || null;
  const activeLegs = Array.isArray((activeJourney as any)?.legs)
    ? (activeJourney as any).legs.filter((leg: any) => {
      const mode = (leg?.mode || '').toString().toLowerCase();
      return mode === 'bus' || mode === 'rail' || mode === 'train';
    })
    : [];

  const weatherCoords = useMemo(() => {
    const firstLeg = Array.isArray(activeLegs) && activeLegs.length > 0 ? activeLegs[0] : null;
    const latCandidates = [firstLeg?.from_lat, firstLeg?.to_lat, 54.1];
    const lonCandidates = [firstLeg?.from_lon, firstLeg?.to_lon, -2.5];
    const lat = latCandidates.map((v: any) => Number(v)).find((n) => Number.isFinite(n));
    const lon = lonCandidates.map((v: any) => Number(v)).find((n) => Number.isFinite(n));
    return {
      lat: Number.isFinite(lat as number) ? (lat as number) : 54.1,
      lon: Number.isFinite(lon as number) ? (lon as number) : -2.5,
    };
  }, [activeLegs]);

  // Intermediate stops state: keyed by leg index
  const [expandedLegs, setExpandedLegs] = useState<Record<number, boolean>>({});
  const [legStops, setLegStops] = useState<Record<number, { name: string; arrival_time: string; departure_time: string }[]>>({});
  const [legStopsLoading, setLegStopsLoading] = useState<Record<number, boolean>>({});

  // Map waypoints: auto-fetched when selected journey changes so each bus line draws its own route
  const [mapLegs, setMapLegs] = useState<any[]>([]);

  useEffect(() => {
    if (!activeJourney) { setMapLegs([]); return; }
    const vehicle = (activeJourney.legs || []).filter((l: any) =>
      l.mode === 'bus' || l.mode === 'rail' || l.mode === 'train'
    );
    if (!vehicle.length) { setMapLegs(activeLegs); return; }

    let cancelled = false;
    Promise.all(vehicle.map(async (leg: any) => {
      if (!leg.service_id || leg.from_seq == null || leg.to_seq == null) return leg;
      try {
        const params = new URLSearchParams({
          service_id: leg.service_id,
          mode: leg.mode === 'train' ? 'rail' : leg.mode,
          from_seq: String(leg.from_seq),
          to_seq: String(leg.to_seq),
        });
        const res = await fetch(`http://127.0.0.1:8000/api/leg-stops?${params}`);
        if (!res.ok) return leg;
        const data = await res.json();
        const stops: any[] = data.stops || [];
        const waypoints: [number, number][] = [
          [leg.from_lat, leg.from_lon],
          ...stops
            .filter((s: any) => s.lat != null && s.lon != null)
            .map((s: any) => [s.lat, s.lon] as [number, number]),
          [leg.to_lat, leg.to_lon],
        ].filter(([a, b]) => a != null && b != null) as [number, number][];
        return { ...leg, _waypoints: waypoints };
      } catch {
        return leg;
      }
    })).then(enriched => { if (!cancelled) setMapLegs(enriched); });

    return () => { cancelled = true; };
  }, [activeJourney]);

  // Reset expanded legs when selected journey changes
  useEffect(() => {
    setExpandedLegs({});
    setLegStops({});
    setLegStopsLoading({});
  }, [selectedJourney]);

  const toggleLegStops = useCallback(async (legIdx: number, leg: any) => {
    setExpandedLegs(prev => ({ ...prev, [legIdx]: !prev[legIdx] }));
    if (!legStops[legIdx] && leg?.service_id && leg?.from_seq != null && leg?.to_seq != null && leg?.mode !== 'walk') {
      setLegStopsLoading(prev => ({ ...prev, [legIdx]: true }));
      try {
        const params = new URLSearchParams({
          service_id: leg.service_id,
          mode: leg.mode === 'train' ? 'rail' : leg.mode,
          from_seq: String(leg.from_seq),
          to_seq: String(leg.to_seq),
        });
        const res = await fetch(`http://127.0.0.1:8000/api/leg-stops?${params}`);
        if (res.ok) {
          const data = await res.json();
          setLegStops(prev => ({ ...prev, [legIdx]: data.stops || [] }));
        }
      } catch (e) {
        // ignore
      } finally {
        setLegStopsLoading(prev => ({ ...prev, [legIdx]: false }));
      }
    }
  }, [legStops]);

  const formatTimeSafe = (v: any) => (v ? formatTime(v) : '');
  const reliabilityText = (j: any) => (j && (j.reliability_band || j.reliability || '')).toString() || 'unknown';
  const reliabilityClass = (j: any) => {
    const label = reliabilityText(j).toLowerCase();
    return label || 'unknown';
  };
  const reliabilityScore = (j: any): number | null => {
    if (!j) return null;
    const raw = j.reliability_score ?? j.reliabilityScore ?? null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  };

  return (
    <div className="resultspage">
      <div className="resultspage__container">
        <div className="resultspage__header-row">
          <h2 className="resultspage__title">{journeyResultsLabel}</h2>
          <button
            type="button"
            className="resultspage__plan-btn"
            onClick={() => navigate('/')}
          >
            Plan Journey
          </button>
        </div>

        <div className="resultspage__grid">
          <aside className="resultspage__left">
            <section className="card journey-options">
              <h3 className="card__title">{journeyOptionsLabel}</h3>
              <div className="route-summary">{originName ? originName : (activeJourney ? activeJourney.origin : '')} <span className="route-arrow">→</span> {destinationName ? destinationName : (activeJourney ? activeJourney.destination : '')}</div>
            </section>

            <div className="routes-list">
              {!requestCompleted ? (
                <div className="card no-results">Loading routes…</div>
              ) : journeysToRender.length === 0 ? (
                <div className="card no-results">No routes found for {originName || '—'} → {destinationName || '—'}</div>
              ) : (
                (journeysToRender || []).map((j: any, idx: number) => {
                  const durationMin = Number(j?.total_duration_min) || 0;
                  const durationH = Math.floor(durationMin / 60);
                  const durationM = durationMin % 60;
                  const changes = Number.isFinite(Number(j?.changes)) ? Number(j?.changes) : 0;
                  const legs = Array.isArray(j?.legs) ? j.legs : [];
                  const relText = reliabilityText(j);
                  const relClass = reliabilityClass(j);
                  const isFastest = fastestDurationMin !== null && durationMin === fastestDurationMin;
                  return (
                    <article key={idx} className={`route-card ${selectedJourney === j ? 'route-card--selected' : ''} ${isFastest ? 'route-card--fastest' : ''}`} onClick={() => setSelectedJourney((prev) => (prev === j ? null : j))}>
                      {isFastest && <span className="route-card__fastest-badge">Fastest</span>}
                      <div className="route-card__main">
                        <div className="route-times">
                          <div className="time">{formatTimeSafe(j?.depart_time)}</div>
                          <ArrowRight className="time-arrow" size={16} />
                          <div className="time">{formatTimeSafe(j?.arrive_time)}</div>
                        </div>
                        <div className="route-meta">
                          <div className="duration">{durationH > 0 ? `${durationH}h ` : ''}{durationM}m</div>
                          <div className="changes">{changes} change{changes !== 1 ? 's' : ''}</div>
                          {Number(j?.total_walk_minutes) > 0 && (
                            <div className="walk-time"><MapPin size={12} style={{ display: 'inline', verticalAlign: 'middle', marginRight: 2 }} />{j.total_walk_minutes}m walk</div>
                          )}
                        </div>
                      </div>
                      <div className="route-card__foot">
                        <div className="route-card__foot-left">
                          <div className="lines" style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                            {(legs || []).map((leg: any, i: number) => {
                              // Skip walking legs if you only want to show vehicles in the summary
                              if (leg.mode === 'walk') return null;
                              return (
                                <span key={i} className="line" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                                  <span className="line-badge">
                                    {(leg.mode === 'rail' || leg.mode === 'train') ? <Train size={16} /> : <Bus size={16} />}
                                  </span>
                                  <span className="line-label" style={{ fontWeight: 'bold' }}>
                                    {leg.line || leg.service_id || ''}
                                  </span>
                                  {/* Add an arrow between legs if it's not the last vehicle leg */}
                                  {i < legs.length - 1 && legs[i + 1].mode !== 'walk' && <ArrowRight size={12} className="leg-separator" />}
                                </span>
                              );
                            })}
                          </div>

                          <span className={`badge badge--${relClass}`}>{relText}</span>

                          <button className="details" type="button" onClick={(e) => { e.stopPropagation(); setSelectedJourney((prev) => (prev === j ? null : j)); }}>{'Show details'}</button>
                        </div>
                      </div>
                    </article>
                  );
                })
              )}
            </div>
          </aside>

          <main className="resultspage__right">
            <section className="card weather-card">
              <WeatherWidget variant="results" lat={weatherCoords.lat} lon={weatherCoords.lon} />
            </section>

            <section className="card map-card">
              <h3 className="card__title">{routeMapLabel}</h3>
              <div className="map-placeholder" role="region" aria-label={routeMapLabel}>
                <div className="map-inner" style={{ height: '100%' }}>
                  {activeJourney && activeLegs.length > 0 ? (
                    <RouteMap legs={mapLegs.length ? mapLegs : activeLegs} />
                  ) : (
                    activeJourney ? <div style={{ padding: 12 }}>{routeMapLabel}</div> : null
                  )}
                </div>
              </div>
            </section>

            {selectedJourney && (
              <>
                <section className="card breakdown-card">
                  <h3 className="card__title">{journeyBreakdownLabel}</h3>
                  <ul className="legs">
                    {(selectedJourney?.legs || []).map((leg: any, idx: number) => {
                      const legsArr = Array.isArray(selectedJourney?.legs) ? selectedJourney.legs : [];
                      const isLast = idx === legsArr.length - 1;
                      const next = !isLast ? legsArr[idx + 1] : null;
                      let waitMins: number | null = null;
                      if (next) {
                        try {
                          const nextLeg: any = next as any;
                          if (leg?.arrive && nextLeg?.depart) {
                            const a = new Date(leg.arrive).getTime();
                            const b = new Date(nextLeg.depart).getTime();
                            const diff = Math.round((b - a) / 60000);
                            waitMins = Number.isFinite(diff) ? Math.max(0, diff) : null;
                          }
                        } catch (e) {
                          waitMins = null;
                        }
                      }

                      const modeLabel = (leg?.mode || '').toString();
                      const fromVal = leg?.from_stop || leg?.from || '';
                      const toVal = leg?.to_stop || leg?.to || '';
                      const durationVal = Number.isFinite(Number(leg?.durationMinutes)) ? Number(leg?.durationMinutes) : '';
                      const durationText = modeLabel === 'walk' ? `${durationVal} walking` : durationVal !== '' ? `${durationVal} m` : '';

                      return (
                        <React.Fragment key={idx}>
                          <li className={`leg ${modeLabel === 'walk' ? 'leg--walk' : 'leg--vehicle'}`}>
                            <div className="leg__left">
                              <span className="leg__icon">{(modeLabel === 'rail' || modeLabel === 'train') ? <Train size={20} /> : modeLabel === 'walk' ? <MapPin size={20} /> : <Bus size={20} />}</span>
                              <div className="leg__meta">
                                <div className="leg__title">{modeLabel.toUpperCase()}{leg.line ? ` ${leg.line}` : ''}{durationText ? <span className="leg__duration"> ({durationText})</span> : null}</div>
                                <div className="leg__secondary">
                                  <div className="leg__stop leg__stop--from"><MapPin size={14} style={{ display: 'inline', verticalAlign: 'middle', marginRight: 4 }} />{fromLabel}: {fromVal}</div>

                                  {modeLabel !== 'walk' && leg?.service_id && leg?.from_seq != null && leg?.to_seq != null && (leg.to_seq - leg.from_seq > 1) && (
                                    <button
                                      className="leg__stops-toggle"
                                      type="button"
                                      onClick={(e) => { e.stopPropagation(); toggleLegStops(idx, leg); }}
                                      style={{ background: 'none', border: 'none', color: '#3b82f6', cursor: 'pointer', fontSize: 12, padding: '4px 0', display: 'flex', alignItems: 'center', gap: 4 }}
                                    >
                                      {expandedLegs[idx] ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                                      {expandedLegs[idx] ? 'Hide' : 'Show'} {leg.to_seq - leg.from_seq - 1} intermediate stop{leg.to_seq - leg.from_seq - 1 !== 1 ? 's' : ''}
                                    </button>
                                  )}

                                  {expandedLegs[idx] && (
                                    <div className="leg__intermediate-stops" style={{ marginLeft: 18, borderLeft: '2px dashed #d1d5db', paddingLeft: 10, marginTop: 4, marginBottom: 4 }}>
                                      {legStopsLoading[idx] && <div style={{ fontSize: 12, color: '#9ca3af' }}>Loading stops...</div>}
                                      {legStops[idx] && legStops[idx].length === 0 && !legStopsLoading[idx] && (
                                        <div style={{ fontSize: 12, color: '#9ca3af' }}>No intermediate stops</div>
                                      )}
                                      {legStops[idx] && legStops[idx].map((stop, sIdx) => (
                                        <div key={sIdx} style={{ fontSize: 12, color: '#4b5563', padding: '2px 0', display: 'flex', alignItems: 'center', gap: 4 }}>
                                          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#9ca3af', display: 'inline-block', flexShrink: 0 }} />
                                          <span>{stop.name}</span>
                                          {stop.departure_time && <span style={{ color: '#9ca3af', marginLeft: 'auto' }}>{stop.departure_time}</span>}
                                        </div>
                                      ))}
                                    </div>
                                  )}

                                  <div className="leg__stop leg__stop--to"><MapPin size={14} style={{ display: 'inline', verticalAlign: 'middle', marginRight: 4 }} />{toLabel}: {toVal}</div>
                                </div>
                              </div>
                            </div>
                            <div className="leg__right">{formatTimeSafe(leg?.depart)} – {formatTimeSafe(leg?.arrive)}</div>
                          </li>

                          {next && (
                            <li className="transfer-block" aria-hidden>
                              <div className="transfer-inner">
                                <div className="transfer-text">{transferAtLabel}: {leg.to_stop || leg.to || ''}</div>
                                <div className="transfer-wait">{waitMins !== null ? `${waitMins}m` : ''}</div>
                              </div>
                            </li>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </ul>
                </section>

                <section className="card reliability-card" aria-labelledby="reliability-heading">
                  <div className={`reliability-panel reliability--${reliabilityClass(selectedJourney)}`} id="reliability-heading">
                    <div className="reliability-title">{reliabilityLabel}: {reliabilityText(selectedJourney)}</div>
                    <div className="reliability-body">{
                      (((selectedJourney as any)?.reliability_band || (selectedJourney as any)?.reliability) === 'High') ? reliabilityHighMsg : (((selectedJourney as any)?.reliability_band || (selectedJourney as any)?.reliability) === 'Medium') ? reliabilityMediumMsg : reliabilityLowMsg
                    }</div>
                    {reliabilityScore(selectedJourney) !== null && (
                      <div className="reliability-score">Score: {reliabilityScore(selectedJourney)}/100</div>
                    )}
                  </div>
                </section>

                <section className="card reliability-card">
                  <button
                    type="button"
                    className="tickets-cta-panel"
                    onClick={() => navigate('/tickets')}
                    aria-label="Buy tickets here"
                  >
                    <div className="tickets-cta-title">Buy tickets here</div>
                    <div className="tickets-cta-body">Purchase tickets directly from official transport providers.</div>
                  </button>
                </section>
              </>
            )}
          </main>
        </div>
      </div>
    </div>
  );
};

export default ResultsPage;
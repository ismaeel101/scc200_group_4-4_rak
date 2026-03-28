import React, { useState, useMemo, useEffect } from "react";
import { useLocation } from 'react-router-dom';
import "./ResultsPage.css";
import translations from '../translations';
import { useUi } from '../contexts/UiContext';
import { Train, Bus, Clock, ArrowRight } from "lucide-react";
import { Journey } from '../types/journey';
import { formatTime } from '../utils/formatTime';

const ResultsPage: React.FC = () => {
  const { language } = useUi();
  const t = translations[language.code] || translations.en;

  // Read journeys and origin/destination names from router state
  const location = useLocation();
  const state = (location && (location.state as any)) || {};
  const search = state.search || null;
  const originName = state.origin || (state.search && state.search.from) || '';
  const destinationName = state.destination || (state.search && state.search.to) || '';
  const passedJourneys: any[] = state.journeys || [];
  const allJourneys: any[] = passedJourneys;

  // We expect the router to pass pre-filtered journeys in state; use them directly
  const filteredBySearch = allJourneys;

  const [selectedJourney, setSelectedJourney] = useState<Journey | null>(null);
  useEffect(() => {
    setSelectedJourney(filteredBySearch && filteredBySearch.length ? filteredBySearch[0] : null);
  }, [filteredBySearch]);

  const journeysToRender = filteredBySearch;
  const activeJourney = selectedJourney || (journeysToRender && journeysToRender[0]) || null;

  return (
    <div className="resultspage">
      <div className="resultspage__container">
        <h2 className="resultspage__title">{t.journeyResults}</h2>

        <div className="resultspage__grid">
          <aside className="resultspage__left">
            <section className="card journey-options">
              <h3 className="card__title">{t.journeyOptions}</h3>
              <div className="route-summary">{originName ? originName : (activeJourney ? activeJourney.origin : '')} <span className="route-arrow">→</span> {destinationName ? destinationName : (activeJourney ? activeJourney.destination : '')}</div>
            </section>

            <div className="routes-list">
              {journeysToRender.length === 0 ? (
                <div className="card no-results">No routes found for {originName || '—'} → {destinationName || '—'}</div>
              ) : (
                journeysToRender.map((j: any, idx: number) => (
                  <article key={idx} className={`route-card ${selectedJourney === j ? 'route-card--selected' : ''}`} onClick={() => setSelectedJourney((prev) => (prev === j ? null : j))}>
                    <div className="route-card__main">
                      <div className="route-times">
                        <div className="time">{formatTime(j.depart_time)}</div>
                        <ArrowRight className="time-arrow" size={16} />
                        <div className="time">{formatTime(j.arrive_time)}</div>
                      </div>
                      <div className="route-meta">
                        <div className="duration">{Math.floor((j.total_duration_min || 0) / 60) > 0 ? Math.floor((j.total_duration_min || 0) / 60) + 'h ' : ''}{(j.total_duration_min || 0) % 60}m</div>
                        <div className="changes">{j.changes} change{j.changes !== 1 ? 's' : ''}</div>
                      </div>
                    </div>
                    <div className="route-card__foot">
                      <div className="route-card__foot-left">
                        <div className="lines">
                          {(j.legs || []).slice(0, 2).map((leg: any, i: number) => (
                            <span key={i} className="line">
                              <span className="line-badge">{(leg.mode === 'rail' || leg.mode === 'train') ? <Train size={16} /> : leg.mode === 'bus' ? <Bus size={16} /> : <span style={{ width: 16 }} />}</span>
                              <span className="line-label">{leg.line || ''}</span>
                            </span>
                          ))}
                          <span className="connect-arrow" aria-hidden>
                            <ArrowRight size={14} />
                          </span>
                        </div>

                        <span className={`badge badge--${(j.reliability_band || j.reliability || '').toString().toLowerCase()}`}>{j.reliability_band || j.reliability || ''}</span>

                        <button className="details" type="button" onClick={(e) => { e.stopPropagation(); setSelectedJourney((prev) => (prev === j ? null : j)); }}>{'Show details'}</button>
                      </div>
                    </div>
                  </article>
                ))
              )}
            </div>
          </aside>

          <main className="resultspage__right">
            <section className="card map-card">
              <h3 className="card__title">{t.routeMap}</h3>
              <div className="map-placeholder" role="region" aria-label={t.routeMap}>
                <div className="map-inner" style={{ height: '100%' }}>
                  {/* Route map rendering not required for basic flow; keep placeholder */}
                  {activeJourney ? <div style={{ padding: 12 }}>{t.routeMap}</div> : null}
                </div>
              </div>
            </section>

            {selectedJourney && (
              <>
                <section className="card breakdown-card">
                  <h3 className="card__title">{t.journeyBreakdown}</h3>
                  <ul className="legs">
                    {selectedJourney.legs.map((leg: any, idx: number) => {
                      const isLast = idx === selectedJourney.legs.length - 1;
                      const next = !isLast ? selectedJourney.legs[idx + 1] : null;
                      let waitMins: number | null = null;
                      if (next) {
                        try {
                          const a = new Date(leg.arrive).getTime();
                          const b = new Date(next.depart).getTime();
                          const diff = Math.round((b - a) / 60000);
                          waitMins = Number.isFinite(diff) ? Math.max(0, diff) : null;
                        } catch (e) {
                          waitMins = null;
                        }
                      }

                      return (
                        <React.Fragment key={idx}>
                          <li className={`leg ${leg.mode === 'walk' ? 'leg--walk' : 'leg--vehicle'}`}>
                            <div className="leg__left">
                              <span className="leg__icon">{(leg.mode === 'rail' || leg.mode === 'train') ? <Train size={20} /> : <Bus size={20} />}</span>
                              <div className="leg__meta">
                                <div className="leg__title">{leg.mode.toUpperCase()}{leg.line ? ` ${leg.line}` : ''} <span className="leg__duration">({leg.durationMinutes || ''}{leg.mode === 'walk' ? ' walking' : ' m'})</span></div>
                                <div className="leg__secondary">
                                  <div>{t.fromLabel}: {leg.from_stop || leg.from || ''}</div>
                                  <div>{t.toLabel}: {leg.to_stop || leg.to || ''}</div>
                                </div>
                              </div>
                            </div>
                            <div className="leg__right">{formatTime(leg.depart)} – {formatTime(leg.arrive)}</div>
                          </li>

                          {next && (
                            <li className="transfer-block" aria-hidden>
                              <div className="transfer-inner">
                                <div className="transfer-text">{t.transferAt}: {leg.to_stop || leg.to}</div>
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
                  <div className={`reliability-panel reliability--${(selectedJourney.reliability_band || selectedJourney.reliability || '').toString().toLowerCase()}`} id="reliability-heading">
                    <div className="reliability-title">{t.reliability}: {selectedJourney.reliability_band || selectedJourney.reliability || ''}</div>
                    <div className="reliability-body">{
                      (selectedJourney.reliability_band || selectedJourney.reliability) === 'High' ? t.reliabilityMessage_high : (selectedJourney.reliability_band || selectedJourney.reliability) === 'Medium' ? t.reliabilityMessage_medium : t.reliabilityMessage_low
                    }</div>
                  </div>
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

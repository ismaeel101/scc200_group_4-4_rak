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
  const allJourneys: any[] = passedJourneys;

  // We expect the router to pass pre-filtered journeys in state; use them directly
  const filteredBySearch = allJourneys;

  const [selectedJourney, setSelectedJourney] = useState<Journey | null>(null);
  useEffect(() => {
    const first = Array.isArray(filteredBySearch) && filteredBySearch.length ? filteredBySearch[0] : null;
    setSelectedJourney(first || null);
  }, [filteredBySearch]);

  const journeysToRender: any[] = Array.isArray(filteredBySearch) ? filteredBySearch : [];
  const activeJourney = selectedJourney || (journeysToRender && journeysToRender[0]) || null;

  const formatTimeSafe = (v: any) => (v ? formatTime(v) : '');
  const reliabilityText = (j: any) => (j && (j.reliability_band || j.reliability || '')).toString() || 'unknown';
  const reliabilityClass = (j: any) => {
    const label = reliabilityText(j).toLowerCase();
    return label || 'unknown';
  };

  return (
    <div className="resultspage">
      <div className="resultspage__container">
        <h2 className="resultspage__title">{journeyResultsLabel}</h2>

        <div className="resultspage__grid">
          <aside className="resultspage__left">
            <section className="card journey-options">
              <h3 className="card__title">{journeyOptionsLabel}</h3>
              <div className="route-summary">{originName ? originName : (activeJourney ? activeJourney.origin : '')} <span className="route-arrow">→</span> {destinationName ? destinationName : (activeJourney ? activeJourney.destination : '')}</div>
            </section>

            <div className="routes-list">
              {journeysToRender.length === 0 ? (
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
                  return (
                    <article key={idx} className={`route-card ${selectedJourney === j ? 'route-card--selected' : ''}`} onClick={() => setSelectedJourney((prev) => (prev === j ? null : j))}>
                      <div className="route-card__main">
                        <div className="route-times">
                          <div className="time">{formatTimeSafe(j?.depart_time)}</div>
                          <ArrowRight className="time-arrow" size={16} />
                          <div className="time">{formatTimeSafe(j?.arrive_time)}</div>
                        </div>
                        <div className="route-meta">
                          <div className="duration">{durationH > 0 ? `${durationH}h ` : ''}{durationM}m</div>
                          <div className="changes">{changes} change{changes !== 1 ? 's' : ''}</div>
                        </div>
                      </div>
                      <div className="route-card__foot">
                        <div className="route-card__foot-left">
                          <div className="lines">
                            {(legs || []).slice(0, 2).map((leg: any, i: number) => (
                              <span key={i} className="line">
                                <span className="line-badge">{(leg.mode === 'rail' || leg.mode === 'train') ? <Train size={16} /> : leg.mode === 'bus' ? <Bus size={16} /> : <span style={{ width: 16 }} />}</span>
                                <span className="line-label">{leg.line || ''}</span>
                              </span>
                            ))}
                            <span className="connect-arrow" aria-hidden>
                              <ArrowRight size={14} />
                            </span>
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
            <section className="card map-card">
              <h3 className="card__title">{routeMapLabel}</h3>
              <div className="map-placeholder" role="region" aria-label={routeMapLabel}>
                <div className="map-inner" style={{ height: '100%' }}>
                  {/* Route map rendering not required for basic flow; keep placeholder */}
                  {activeJourney ? <div style={{ padding: 12 }}>{routeMapLabel}</div> : null}
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

                      return (
                        <React.Fragment key={idx}>
                          <li className={`leg ${modeLabel === 'walk' ? 'leg--walk' : 'leg--vehicle'}`}>
                            <div className="leg__left">
                              <span className="leg__icon">{(modeLabel === 'rail' || modeLabel === 'train') ? <Train size={20} /> : <Bus size={20} />}</span>
                              <div className="leg__meta">
                                <div className="leg__title">{modeLabel.toUpperCase()}{leg.line ? ` ${leg.line}` : ''} <span className="leg__duration">({durationVal}{modeLabel === 'walk' ? ' walking' : durationVal !== '' ? ' m' : ''})</span></div>
                                <div className="leg__secondary">
                                  <div>{fromLabel}: {fromVal}</div>
                                  <div>{toLabel}: {toVal}</div>
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

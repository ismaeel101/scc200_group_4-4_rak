import React from "react";
import translations from '../translations';
import { useUi } from '../contexts/UiContext';
import { Train, Bus, ArrowRight } from "lucide-react";
import { Journey } from '../types/journey';
import { formatTime } from '../utils/formatTime';

type Props = {
    journey: Journey;
    idx: number;
    isSelected: boolean;
    onSelect: (j: Journey) => void;
};

const RouteCard: React.FC<Props> = ({ journey, idx, isSelected, onSelect }) => {
    const startTime = formatTime(journey.departureTime || (journey.legs[0] && journey.legs[0].departureTime) || '');
    const endTime = formatTime(journey.arrivalTime || (journey.legs[journey.legs.length - 1] && journey.legs[journey.legs.length - 1].arrivalTime) || '');
    const duration = `${Math.floor(journey.totalDurationMinutes / 60) > 0 ? Math.floor(journey.totalDurationMinutes / 60) + 'h ' : ''}${journey.totalDurationMinutes % 60}m`;
    return (
        <article
            key={journey.id}
            className={"route-card " + (isSelected ? 'route-card--selected' : '')}
        >
            <div className="route-card__main">
                <div className="route-times">
                    <div className="time">{startTime}</div>
                    <ArrowRight className="time-arrow" size={16} />
                    <div className="time">{endTime}</div>
                </div>

                <div className="route-meta">
                    <div className="duration">{duration}</div>
                    <div className="changes">{Math.max(0, journey.legs.length - 1)} change{Math.max(0, journey.legs.length - 1) !== 1 ? 's' : ''}</div>
                </div>
            </div>

            <div className="route-card__foot">
                <div className="route-card__foot-left">
                    <div className="lines">
                        {journey.legs.slice(0, 2).map((leg, i) => (
                            <span key={leg.id} className="line">
                                <span className="line-badge">{(leg.mode === 'rail' || leg.mode === 'train') ? <Train size={16} /> : leg.mode === 'bus' ? <Bus size={16} /> : <span style={{ width: 16 }} />}</span>
                                <span className="line-label">{leg.routeNumber || ''}</span>
                            </span>
                        ))}

                        <span className="connect-arrow" aria-hidden>
                            <ArrowRight size={14} />
                        </span>
                    </div>

                    <span className={"badge badge--" + (journey.reliability === 'High' ? 'high' : journey.reliability === 'Medium' ? 'medium' : 'low')}>
                        {journey.reliability}
                    </span>

                    <button className="details" type="button" onClick={(e) => { e.stopPropagation(); onSelect(journey); }}>{'Show details'}</button>
                </div>

                <div className="route-card__foot-right" aria-hidden="true">
                    {/* reserved for future actions */}
                </div>
            </div>
        </article>
    );
};

export default RouteCard;

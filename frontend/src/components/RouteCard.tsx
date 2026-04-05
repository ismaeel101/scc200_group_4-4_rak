import React from "react";
import translations from '../translations';
import { useUi } from '../contexts/UiContext';
import { Train, Bus, ArrowRight, AlertTriangle, Info } from "lucide-react"; // Added icons
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

    // Task R4: Style configuration for reliability badges [cite: 33, 34, 39]
    const getReliabilityStyles = (band: string) => {
        switch (band) {
            case 'High': 
                return { color: '#22c55e', icon: null };
            case 'Medium': 
                return { color: '#f59e0b', icon: <AlertTriangle size={12} /> };
            case 'Low': 
                return { color: '#ef4444', icon: <AlertTriangle size={12} /> };
            default: 
                return { color: '#6b7280', icon: null };
        }
    };

    // Note: The brief uses "reliability_band", but your current file uses "reliability" [cite: 36]
    const relBand = (journey as any).reliability_band || journey.reliability || 'Low';
    const relStyle = getReliabilityStyles(relBand);

    return (
        <article
            key={journey.id}
            className={"route-card " + (isSelected ? 'route-card--selected' : '')}
            style={{ position: 'relative' }} // Needed for top-right badge [cite: 29]
        >
            {/* Task R4: Reliability Pill Badge [cite: 29, 38, 40] */}
            <div 
                className="reliability-badge"
                style={{
                    position: 'absolute',
                    top: '12px',
                    right: '12px',
                    backgroundColor: relStyle.color,
                    color: 'white',
                    padding: '4px 8px',
                    borderRadius: '999px',
                    fontSize: '12px',
                    fontWeight: 'bold',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px'
                }}
            >
                {relStyle.icon}
                {relBand}
            </div>

            <div className="route-card__main" onClick={() => onSelect(journey)}>
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
                    </div>

                    <button className="details" type="button" onClick={(e) => { e.stopPropagation(); onSelect(journey); }}>
                        {isSelected ? 'Hide details' : 'Show details'}
                    </button>
                </div>
            </div>

            {/* Task R5 & R6: Expanded Reliability Panel [cite: 43, 45, 53] */}
            {isSelected && (
                <div 
                    className="reliability-panel"
                    style={{
                        margin: '12px',
                        padding: '12px',
                        backgroundColor: '#eff6ff', // Light blue info box [cite: 45, 51]
                        border: '1px solid #bfdbfe',
                        borderRadius: '8px'
                    }}
                >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                        <Info size={16} color="#1e40af" />
                        <span style={{ fontWeight: 'bold', color: relStyle.color }}>
                            Reliability: {relBand}
                        </span>
                    </div>

                    {/* Task R6: Numeric Reliability Score [cite: 55, 57] */}
                    <div style={{ fontSize: '12px', color: '#6b7280', marginBottom: '8px', marginLeft: '24px' }}>
                        Score: {(journey as any).reliability_score || 0}/100 [cite: 56]
                    </div>

                    {/* Task R5: Explanations Bullet Points [cite: 47, 50] */}
                    <ul style={{ margin: '0 0 0 24px', padding: 0, listStyleType: 'disc' }}>
                        {((journey as any).reliability_explanations || []).map((explanation: string, i: number) => (
                            <li key={i} style={{ fontSize: '12px', color: '#4b5563', marginBottom: '4px' }}>
                                {explanation}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </article>
    );
};

export default RouteCard;
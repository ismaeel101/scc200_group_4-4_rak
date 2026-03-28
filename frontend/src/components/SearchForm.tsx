import React, { useState, useEffect, useRef } from "react";
import translations from '../translations';
import { searchStops } from '../utils/searchStops';
import { Stop } from '../types/stop';
import { useUi } from '../contexts/UiContext';
import { MapPin, Clock, Bus, Train, Shuffle } from "lucide-react";

type SearchFormProps = {
  onSearch?: (data: { from: string; to: string; date: string; time: string; mode: string }) => void;
  isLoading?: boolean;
  onSelectFrom?: (stop: Stop) => void;
};

function capitalizeWords(s: string) {
  return s.replace(/\b\w/g, (c) => c.toUpperCase());
}

const SUGGESTED_CITIES = [
  'Manchester', 'Salford', 'Bolton', 'Bury', 'Oldham', 'Rochdale', 'Stockport', 'Tameside', 'Trafford', 'Wigan', 'Liverpool', 'Birkenhead', 'St Helens', 'Southport', 'Widnes', 'Runcorn', 'Preston', 'Lancaster', 'Blackburn', 'Burnley', 'Blackpool', 'Chorley', 'Morecambe', 'Accrington', 'Lytham St Annes', 'Skelmersdale', 'Carlisle', 'Kendal', 'Barrow-in-Furness', 'Workington', 'Whitehaven', 'Penrith'
];

const SearchForm: React.FC<SearchFormProps> = ({ onSearch, isLoading = false }) => {
  const ui = useUi();
  const { language, setSelectedOrigin, setSelectedDestination } = ui;
  const t = translations[language.code] || translations.en;
  const [from, setFrom] = useState('');
  const [fromSuggestions, setFromSuggestions] = useState<Stop[]>([]);
  const [to, setTo] = useState('');
  const [journeys, setJourneys] = useState<any[] | null>(null);
  const [selectedDate, setSelectedDate] = useState('');
  const [selectedTime, setSelectedTime] = useState('');
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [selectedMode, setSelectedMode] = useState('All modes');
  const [journeyType, setJourneyType] = useState('All');
  const [rotating, setRotating] = useState(false);
  const [isDepart, setIsDepart] = useState(true);

  const dateRef = useRef<HTMLInputElement | null>(null);
  const timeRef = useRef<HTMLInputElement | null>(null);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!onSearch) return;
    if (isLoading) return;
    const errors: Record<string, string> = {};
    // validation: From/To required and not identical
    if (!from.trim()) errors.from = 'Please enter a origin';
    if (!to.trim()) errors.to = 'Please enter a destination';
    if (from.trim() && to.trim() && from.trim().toLowerCase() === to.trim().toLowerCase()) errors.to = 'Origin and destination cannot be the same';

    // date validation
    const now = new Date();
    const selDate = selectedDate ? new Date(selectedDate + 'T00:00:00') : null;
    if (!selDate) errors.date = 'Please select a date';
    else {
      const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      if (selDate < today) errors.date = 'Date cannot be in the past';
    }

    // time validation if date is today
    if (!selectedTime) errors.time = 'Please select a time';
    else if (selectedDate) {
      const selectedDateTime = new Date(selectedDate + 'T' + selectedTime + ':00');
      const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      if (selDate && selDate.getTime() === today.getTime()) {
        const nowTime = new Date();
        if (selectedDateTime < nowTime) errors.time = 'Time cannot be earlier than now';
      }
    }

    setFieldErrors(errors);
    if (Object.keys(errors).length) return;

    // Resolve origin/destination IDs (AtcoCode) if not already selected
    // Read latest values directly from context to avoid stale closures
    let origin_id = ui.selectedOriginId;
    let destination_id = ui.selectedDestinationId;

    console.log('[SearchForm] context values at submit time:', {
      selectedOriginId: ui.selectedOriginId,
      selectedDestinationId: ui.selectedDestinationId,
      selectedOriginName: ui.selectedOriginName,
      selectedDestinationName: ui.selectedDestinationName,
    });

    try {
      if (!origin_id && from && from.length > 1) {
        const r = await searchStops(from, 1);
        if (r && r.length > 0) origin_id = r[0].id;
      }
      if (!destination_id && to && to.length > 1) {
        const r = await searchStops(to, 1);
        if (r && r.length > 0) destination_id = r[0].id;
      }
    } catch (e) {
      // ignore lookup failures
    }

    // Build ISO datetime from selected date + time (local)
    const dtParts = selectedDate.split('-');
    const timeParts = selectedTime.split(':');
    let time_iso = new Date().toISOString();
    try {
      if (dtParts.length === 3 && timeParts.length >= 2) {
        const y = Number(dtParts[0]);
        const m = Number(dtParts[1]) - 1;
        const d = Number(dtParts[2]);
        const hh = Number(timeParts[0]);
        const mm = Number(timeParts[1]);
        const composed = new Date(y, m, d, hh, mm, 0);
        time_iso = composed.toISOString();
      }
    } catch (e) {
      // fallback to now
      time_iso = new Date().toISOString();
    }

    const modeLower = selectedMode.toLowerCase();
    let modes = 'mixed';
    if (modeLower === 'bus') modes = 'bus';
    else if (modeLower === 'rail') modes = 'rail';

    const payload = {
      origin_id,
      destination_id,
      time_type: isDepart ? 'depart_at' : 'arrive_by',
      time_iso,
      modes,
      max_options: 5,
      // keep human-readable fields for UI
      from,
      to,
      date: selectedDate,
      time: selectedTime,
    };

    console.log('[SearchForm] payload before validation:', { origin_id: payload.origin_id, destination_id: payload.destination_id });
    // Ensure we have AtcoCodes (origin_id/destination_id) before searching
    if (!payload.origin_id || !payload.destination_id) {
      setFieldErrors((prev) => ({
        ...prev,
        from: payload.origin_id ? prev.from : 'Please select an origin from the suggestions',
        to: payload.destination_id ? prev.to : 'Please select a destination from the suggestions',
      }));
      return;
    }

    try {
      const result = await onSearch(payload as any);
      if (result && Array.isArray(result)) setJourneys(result);
      else setJourneys(null);
    } catch (e) {
      setJourneys(null);
    }
  };

  const handleSwap = () => {
    setRotating(true);
    const temp = from;
    setFrom(to);
    setTo(temp);
    setTimeout(() => setRotating(false), 200);
  };

  useEffect(() => {
    // set default date = today and time = current rounded to nearest 5 minutes
    const now = new Date();
    const pad = (n: number) => String(n).padStart(2, '0');
    const roundTo = (d: Date, minutes = 5) => {
      const ms = 1000 * 60 * minutes;
      return new Date(Math.ceil(d.getTime() / ms) * ms);
    };
    const rounded = roundTo(now, 5);
    const hh = pad(rounded.getHours());
    const mm = pad(rounded.getMinutes());
    const yyyy = now.getFullYear();
    const mmn = pad(now.getMonth() + 1);
    const dd = pad(now.getDate());
    setSelectedDate(`${yyyy}-${mmn}-${dd}`);
    setSelectedTime(`${hh}:${mm}`);
  }, []);

  // Sync inputs when user selects a stop from the map
  useEffect(() => {
    if (ui.selectedOriginName) setFrom(ui.selectedOriginName);
  }, [ui.selectedOriginName]);

  useEffect(() => {
    if (ui.selectedDestinationName) setTo(ui.selectedDestinationName);
  }, [ui.selectedDestinationName]);

  useEffect(() => {
    let active = true;
    const doSearch = async () => {
      if (!from || from.length < 2) {
        setFromSuggestions([]);
        return;
      }
      try {
        const results = await searchStops(from, 5);
        if (active) setFromSuggestions(results);
      } catch (e) {
        setFromSuggestions([]);
      }
    };
    doSearch();
    return () => { active = false; };
  }, [from]);

  // Auto-adjust time if user picks earlier time for today
  useEffect(() => {
    if (!selectedDate || !selectedTime) return;
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const selDate = new Date(selectedDate + 'T00:00:00');
    if (selDate.getTime() === today.getTime()) {
      const selectedDateTime = new Date(selectedDate + 'T' + selectedTime + ':00');
      if (selectedDateTime < now) {
        // adjust to current time rounded to nearest 5
        const ms = 1000 * 60 * 5;
        const adjusted = new Date(Math.ceil(now.getTime() / ms) * ms);
        const pad = (n: number) => String(n).padStart(2, '0');
        setSelectedTime(`${pad(adjusted.getHours())}:${pad(adjusted.getMinutes())}`);
      }
    }
  }, [selectedDate, selectedTime]);

  return (
    <form className="searchform" onSubmit={handleSubmit}>
      <div className="searchform__grid">
        <div className="searchform__field">
          <label htmlFor="from-input" className="visually-hidden">{t.fromLabel}</label>
          <input
            id="from-input"
            name="from"
            list="city-suggestions"
            value={from}
            onChange={(e) => setFrom(capitalizeWords(e.target.value))}
            className="searchform__input"
            placeholder={t.fromPlaceholder as string}
            aria-label={t.fromLabel as string}
          />
          {fieldErrors.from && <div className="field-error" role="alert">{fieldErrors.from}</div>}
        </div>

        <div className="searchform__swap-wrap">
          <button className="searchform__swap" type="button" aria-label={t.swap as string} onClick={handleSwap}>
            <Shuffle className={`searchform__swap-icon switch-icon ${rotating ? 'rotate' : ''}`} size={18} strokeWidth={2} aria-hidden />
          </button>
        </div>

        <div className="searchform__field">
          <label htmlFor="to-input" className="visually-hidden">{t.toLabel}</label>
          <input
            id="to-input"
            name="to"
            list="city-suggestions"
            value={to}
            onChange={(e) => setTo(capitalizeWords(e.target.value))}
            className="searchform__input"
            placeholder={t.toPlaceholder as string}
            aria-label={t.toLabel as string}
          />
          {fieldErrors.to && <div className="field-error" role="alert">{fieldErrors.to}</div>}
        </div>
      </div>
      <div className="searchform__grid-2">
        <div className="toggle-wrap" aria-label={`${t.depart} / ${t.arrive}`}>
          <span className="visually-hidden" id="timeToggleLabel">{t.depart} / {t.arrive}</span>
          <button aria-pressed={isDepart} aria-labelledby="timeToggleLabel" type="button" className={`toggle-btn ${isDepart ? 'mode__btn--active' : ''}`} onClick={() => setIsDepart(true)}>{t.depart}</button>
          <button aria-pressed={!isDepart} aria-labelledby="timeToggleLabel" type="button" className={`toggle-btn ${!isDepart ? 'mode__btn--active' : ''}`} onClick={() => setIsDepart(false)}>{t.arrive}</button>
        </div>

        <div className="date-time-stacked">
          <div className="date-input-wrap">
            <label htmlFor="date-input" className="visually-hidden">{t.date}</label>
            <input
              id="date-input"
              ref={dateRef}
              name="date"
              type="date"
              className="searchform__input"
              aria-label={t.date}
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
            />
          </div>

          <div className="time-input-wrap">
            <label htmlFor="time-input" className="visually-hidden">{t.time}</label>
            <Clock className="clock-icon" size={18} strokeWidth={2} aria-hidden />
            <input
              id="time-input"
              ref={timeRef}
              name="time"
              type="time"
              className="searchform__input"
              aria-label={t.time}
              value={selectedTime}
              onChange={(e) => setSelectedTime(e.target.value)}
            />
          </div>

          {(fieldErrors.date || fieldErrors.time) && (
            <div className="field-error" role="alert">{fieldErrors.date || fieldErrors.time}</div>
          )}
        </div>
      </div>

      <div className="searchform__journey">
        <label className="searchform__label">{t.journeyType}</label>
        <div className="searchform__journey-toggle" role="tablist" aria-label="Journey type">
          <button type="button" className={`mode__btn ${journeyType === 'All' ? 'mode__btn--active' : ''}`} onClick={() => setJourneyType('All')}>{t.all}</button>
          <button type="button" className={`mode__btn ${journeyType === 'Fastest' ? 'mode__btn--active' : ''}`} onClick={() => setJourneyType('Fastest')}>{t.fastest}</button>
          <button type="button" className={`mode__btn ${journeyType === 'Reliable' ? 'mode__btn--active' : ''}`} onClick={() => setJourneyType('Reliable')}>{t.reliable}</button>
        </div>
      </div>

      <div className="searchform__modes">
        <button type="button" className={`mode__btn ${selectedMode === 'All modes' ? 'mode__btn--active' : ''}`} onClick={() => setSelectedMode('All modes')}>
          <MapPin className="mode__icon" size={18} strokeWidth={2} aria-hidden />
          {t.allModes}
        </button>
        <button type="button" className={`mode__btn ${selectedMode === 'Bus' ? 'mode__btn--active' : ''}`} onClick={() => setSelectedMode('Bus')}>
          <Bus className="mode__icon" size={18} strokeWidth={2} aria-hidden />
          {t.bus}
        </button>
        <button type="button" className={`mode__btn ${selectedMode === 'Rail' ? 'mode__btn--active' : ''}`} onClick={() => setSelectedMode('Rail')}>
          <Train className="mode__icon" size={18} strokeWidth={2} aria-hidden />
          {t.rail}
        </button>
      </div>

      <datalist id="city-suggestions">
        {SUGGESTED_CITIES.map((c) => (
          <option key={c} value={c} />
        ))}
      </datalist>

      {fromSuggestions.length > 0 && (
        <ul className="suggestions" role="listbox">
          {fromSuggestions.map((s) => (
            <li key={s.id} role="option" onClick={() => { setFrom(s.name); setSelectedOrigin(s.id, s.name); if (onSelectFrom) onSelectFrom(s); }}>{s.name} — {s.type}</li>
          ))}
        </ul>
      )}

      <div className="searchform__actions">
        <button className="searchform__button" type="submit" disabled={isLoading} aria-disabled={isLoading} aria-busy={isLoading}>
          {t.findRoutes}
        </button>
      </div>

      {journeys && (
        <div className="journey-results">
          <h3>Journey Results</h3>
          {journeys.length === 0 && <div>No journeys found</div>}
          <ul>
            {journeys.map((j: any, idx: number) => (
              <li key={idx} className="journey-card">
                <div><strong>Duration:</strong> {j.total_duration_min} mins</div>
                <div><strong>Changes:</strong> {j.changes}</div>
                <div><strong>Reliability:</strong> <span style={{ color: j.reliability_band === 'High' ? 'green' : j.reliability_band === 'Medium' ? 'orange' : 'red' }}>{j.reliability_band}</span></div>
                <div>
                  <strong>Legs:</strong>
                  <ol>
                    {j.legs.map((leg: any, i: number) => (
                      <li key={i}>{leg.mode} from {leg.from} to {leg.to} ({new Date(leg.depart).toLocaleString()} - {new Date(leg.arrive).toLocaleString()})</li>
                    ))}
                  </ol>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {isLoading && (
        <div role="status" aria-live="polite" className="visually-hidden">Planning your journey…</div>
      )}
    </form>
  );
};

export default SearchForm;

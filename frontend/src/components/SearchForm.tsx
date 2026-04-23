import React, { useState, useEffect, useRef } from "react";
import translations from '../translations';
import { Stop } from '../types/stop';
import { useUi } from '../contexts/UiContext';
import { searchStops } from '../utils/searchStops';
import { MapPin, Bus, Train, Shuffle, Search } from "lucide-react";

type SearchFormProps = {
  onSearch?: (data: {
    from: string;
    to: string;
    date: string;
    time: string;
    mode: string;
    time_type: 'depart_at' | 'arrive_by';
    time_iso: string;
  }) => void;
  isLoading?: boolean;
  onSelectFrom?: (stop: Stop) => void;
  onModeChange?: (mode: 'all' | 'bus' | 'rail') => void;
};

function capitalizeWords(s: string) {
  return s.replace(/\b\w/g, (c) => c.toUpperCase());
}

function escapeRegExp(text: string) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function isSubsequence(query: string, target: string) {
  let qi = 0;
  let ti = 0;
  while (qi < query.length && ti < target.length) {
    if (query[qi] === target[ti]) qi += 1;
    ti += 1;
  }
  return qi === query.length;
}

function scoreMatch(query: string, text: string) {
  const q = query.toLowerCase().trim();
  const t = text.toLowerCase().trim();
  if (!q || !t) return 0;
  if (t.startsWith(q)) return 300 - t.length;
  if (t.includes(q)) return 200 - t.indexOf(q);
  if (isSubsequence(q, t)) return 100;
  return -1;
}

function getUkNowParts(base: Date = new Date()) {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/London',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(base);

  const pick = (type: string) => parts.find((p) => p.type === type)?.value || '';

  return {
    year: pick('year'),
    month: pick('month'),
    day: pick('day'),
    hour: pick('hour'),
    minute: pick('minute'),
    second: pick('second') || '00',
  };
}

function buildIsoLocal(year: string, month: string, day: string, hour: string, minute: string, second = '00') {
  return `${year}-${month}-${day}T${hour}:${minute}:${second}`;
}

function getUkTomorrowDateString() {
  const ukNow = getUkNowParts();
  const y = Number(ukNow.year);
  const m = Number(ukNow.month);
  const d = Number(ukNow.day);
  const utc = new Date(Date.UTC(y, m - 1, d) + 24 * 60 * 60 * 1000);
  const yyyy = String(utc.getUTCFullYear()).padStart(4, '0');
  const mm = String(utc.getUTCMonth() + 1).padStart(2, '0');
  const dd = String(utc.getUTCDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

const SUGGESTED_CITIES = [
  'Manchester', 'Salford', 'Bolton', 'Bury', 'Oldham', 'Rochdale', 'Stockport', 'Tameside', 'Trafford', 'Wigan', 'Liverpool', 'Birkenhead', 'St Helens', 'Southport', 'Widnes', 'Runcorn', 'Preston', 'Lancaster', 'Blackburn', 'Burnley', 'Blackpool', 'Chorley', 'Morecambe', 'Accrington', 'Lytham St Annes', 'Skelmersdale', 'Carlisle', 'Kendal', 'Barrow-in-Furness', 'Workington', 'Whitehaven', 'Penrith'
];

const SearchForm: React.FC<SearchFormProps> = ({ onSearch, isLoading = false, onSelectFrom, onModeChange }) => {
  const ui = useUi();
  const {
    language,
    setSelectedOrigin,
    setSelectedDestination,
    selectedOriginId,
    selectedDestinationId,
    validStopIds,
    availableStops,
  } = ui;
  const t = translations[language.code] || translations.en;
  const fromLabel = typeof t.fromLabel === 'string' ? t.fromLabel : 'From';
  const toLabel = typeof t.toLabel === 'string' ? t.toLabel : 'To';
  const departLabel = typeof t.depart === 'string' ? t.depart : 'Depart';
  const arriveLabel = typeof t.arrive === 'string' ? t.arrive : 'Arrive';
  const dateLabel = typeof t.date === 'string' ? t.date : 'Date';
  const timeLabel = typeof t.time === 'string' ? t.time : 'Time';
  const allModesLabel = typeof t.allModes === 'string' ? t.allModes : 'All modes';
  const busLabel = typeof t.bus === 'string' ? t.bus : 'Bus';
  const railLabel = typeof t.rail === 'string' ? t.rail : 'Rail';
  const findRoutesLabel = typeof t.findRoutes === 'string' ? t.findRoutes : 'Find routes';
  const [from, setFrom] = useState('');
  const [fromSuggestions, setFromSuggestions] = useState<Stop[]>([]);
  const [to, setTo] = useState('');
  const [toSuggestions, setToSuggestions] = useState<Stop[]>([]);
  const [openDropdown, setOpenDropdown] = useState<'from' | 'to' | null>(null);
  const [activeFromIndex, setActiveFromIndex] = useState(-1);
  const [activeToIndex, setActiveToIndex] = useState(-1);
  const [journeys, setJourneys] = useState<any[] | null>(null);
  const [selectedDate, setSelectedDate] = useState('');
  const [selectedTime, setSelectedTime] = useState('');
  const [dateTouched, setDateTouched] = useState(false);
  const [timeTouched, setTimeTouched] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [selectedMode, setSelectedMode] = useState('All modes');
  const [rotating, setRotating] = useState(false);
  const [isDepart, setIsDepart] = useState(true);
  const formRef = useRef<HTMLFormElement | null>(null);

  useEffect(() => {
    const modeLower = selectedMode.toLowerCase();
    const mapMode: 'all' | 'bus' | 'rail' = modeLower === 'bus' ? 'bus' : modeLower === 'rail' ? 'rail' : 'all';
    if (onModeChange) onModeChange(mapMode);
  }, [selectedMode, onModeChange]);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!onSearch) return;
    if (isLoading) return;
    const errors: Record<string, string> = {};
    if (!from.trim()) errors.from = 'Please enter a origin';
    if (!to.trim()) errors.to = 'Please enter a destination';
    if (from.trim() && to.trim() && from.trim().toLowerCase() === to.trim().toLowerCase()) errors.to = 'Origin and destination cannot be the same';

    const now = new Date();
    const selDate = selectedDate ? new Date(selectedDate + 'T00:00:00') : null;
    if (!selDate) errors.date = 'Please select a date';
    else {
      const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      if (selDate < today) errors.date = 'Date cannot be in the past';
    }

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

    let origin_id = ui.selectedOriginId;
    let destination_id = ui.selectedDestinationId;

    console.log('[SearchForm] context values at submit time:', {
      selectedOriginId: ui.selectedOriginId,
      selectedDestinationId: ui.selectedDestinationId,
      selectedOriginName: ui.selectedOriginName,
      selectedDestinationName: ui.selectedDestinationName,
    });

    const valid = validStopIds || new Set<string>();
    const localStops = Array.isArray(availableStops) ? availableStops : [];

    if (!origin_id && from && from.length > 1) {
      const exact = localStops.find((s) => valid.has(String(s.id)) && s.name.toLowerCase() === from.trim().toLowerCase());
      if (exact) origin_id = exact.id;
    }
    if (!destination_id && to && to.length > 1) {
      const exact = localStops.find((s) => valid.has(String(s.id)) && s.name.toLowerCase() === to.trim().toLowerCase());
      if (exact) destination_id = exact.id;
    }

    const untouchedDateTime = !dateTouched && !timeTouched;
    let time_iso = '';
    const dtParts = selectedDate.split('-');
    const timeParts = selectedTime.split(':');
    try {
      if (dtParts.length === 3 && timeParts.length >= 2) {
        const y = Number(dtParts[0]);
        const m = Number(dtParts[1]) - 1;
        const d = Number(dtParts[2]);
        const hh = Number(timeParts[0]);
        const mm = Number(timeParts[1]);
        const yyyy = String(y).padStart(4, '0');
        const month = String(m + 1).padStart(2, '0');
        const day = String(d).padStart(2, '0');
        const hour = String(hh).padStart(2, '0');
        const minute = String(mm).padStart(2, '0');
        time_iso = buildIsoLocal(yyyy, month, day, hour, minute, '00');
      }
    } catch (e) { }

    if (!time_iso) {
      const ukNow = getUkNowParts();
      time_iso = buildIsoLocal(ukNow.year, ukNow.month, ukNow.day, ukNow.hour, ukNow.minute, ukNow.second);
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
      from,
      to,
      date: selectedDate,
      time: selectedTime,
    };

    console.log('SELECTED DATE/TIME', { selectedDate, selectedTime, dateTouched, timeTouched, untouchedDateTime, time_iso });
    console.log('[SearchForm] payload before validation:', { origin_id: payload.origin_id, destination_id: payload.destination_id });

    if (!payload.origin_id || !payload.destination_id) {
      setFieldErrors((prev) => ({
        ...prev,
        from: payload.origin_id ? prev.from : 'Please select an origin from the suggestions',
        to: payload.destination_id ? prev.to : 'Please select a destination from the suggestions',
      }));
      return;
    }

    try {
      console.log("SENDING REQUEST", payload);
      const result = await onSearch(payload as any);
      if (Array.isArray(result)) setJourneys(result);
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

  const handleClearLocations = () => {
    setFrom('');
    setTo('');
    setSelectedOrigin(null, null);
    setSelectedDestination(null, null);
  };

  useEffect(() => {
    setSelectedDate(getUkTomorrowDateString());
    setSelectedTime('15:00');
  }, []);

  useEffect(() => {
    if (ui.selectedOriginName) setFrom(ui.selectedOriginName);
  }, [ui.selectedOriginName]);

  useEffect(() => {
    if (ui.selectedDestinationName) setTo(ui.selectedDestinationName);
  }, [ui.selectedDestinationName]);

  const filterAndRank = (results: Stop[], query: string, routableIds: Set<string>): Stop[] => {
    const q = query.trim().toLowerCase();
    const rows = (results || [])
      .map((stop) => {
        const id = String(stop?.id || '');
        const isRoutable = routableIds.size > 0 && routableIds.has(id);
        return {
          stop,
          id,
          isRoutable,
          nameKey: String(stop?.name || '').trim().toLowerCase(),
          score: scoreMatch(q, stop?.name || ''),
        };
      })
      .filter((row) => row.score >= 0)
      .sort((a, b) => {
        if (a.isRoutable !== b.isRoutable) return a.isRoutable ? -1 : 1;
        if (a.score !== b.score) return b.score - a.score;
        return (a.stop.name || '').localeCompare(b.stop.name || '');
      });

    const groupedByName = new Map<string, typeof rows>();
    rows.forEach((row) => {
      const key = row.nameKey;
      if (!groupedByName.has(key)) groupedByName.set(key, []);
      groupedByName.get(key)!.push(row);
    });

    const preferredRows: typeof rows = [];
    groupedByName.forEach((group) => {
      const hasRoutable = group.some((r) => r.isRoutable);
      if (hasRoutable) preferredRows.push(...group.filter((r) => r.isRoutable));
      else preferredRows.push(...group);
    });

    const dedupedById = new Map<string, Stop>();
    preferredRows.forEach((row) => {
      if (!row.id) return;
      if (!dedupedById.has(row.id)) dedupedById.set(row.id, row.stop);
    });

    return Array.from(dedupedById.values()).slice(0, 12);
  };

  const fetchSuggestions = async (query: string): Promise<Stop[]> => {
    if (!query || query.trim().length < 2) return [];

    const valid = validStopIds || new Set<string>();
    const localSource = Array.isArray(availableStops) ? availableStops : [];

    let remote: Stop[] = [];
    try {
      remote = await searchStops(query, 30);
    } catch (e) {
      remote = [];
    }

    const remoteNormalized = (remote || []).map((s) => ({
      id: String(s.id),
      name: String(s.name),
      type: s.type,
      lat: Number(s.lat),
      lon: Number(s.lon),
      street: (s as any).street,
      indicator: (s as any).indicator,
      town: (s as any).town,
    } as Stop));

    const byId = new Map<string, Stop>();
    [...localSource, ...remoteNormalized].forEach((s) => {
      if (s?.id) byId.set(String(s.id), s);
    });

    return filterAndRank(Array.from(byId.values()), query, valid);
  };

  useEffect(() => {
    let cancelled = false;
    const t = window.setTimeout(() => {
      fetchSuggestions(from).then((list) => {
        if (!cancelled) {
          setFromSuggestions(list);
          setActiveFromIndex(list.length ? 0 : -1);
        }
      });
    }, 300);
    return () => { cancelled = true; window.clearTimeout(t); };
  }, [from, validStopIds, availableStops]);

  useEffect(() => {
    let cancelled = false;
    const t = window.setTimeout(() => {
      fetchSuggestions(to).then((list) => {
        if (!cancelled) {
          setToSuggestions(list);
          setActiveToIndex(list.length ? 0 : -1);
        }
      });
    }, 300);
    return () => { cancelled = true; window.clearTimeout(t); };
  }, [to, validStopIds, availableStops]);

  useEffect(() => {
    const onDocPointer = (ev: MouseEvent) => {
      if (!formRef.current) return;
      if (!formRef.current.contains(ev.target as Node)) setOpenDropdown(null);
    };
    document.addEventListener('mousedown', onDocPointer);
    return () => document.removeEventListener('mousedown', onDocPointer);
  }, []);

  const selectFromSuggestion = (s: Stop) => {
    setFrom(s.name);
    setSelectedOrigin(s.id, s.name);
    if (onSelectFrom) onSelectFrom(s);
    setOpenDropdown(null);
  };

  const selectToSuggestion = (s: Stop) => {
    setTo(s.name);
    setSelectedDestination(s.id, s.name);
    setOpenDropdown(null);
  };

  const handleFromKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!fromSuggestions.length) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); setOpenDropdown('from'); setActiveFromIndex((prev) => Math.min(fromSuggestions.length - 1, prev + 1)); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); setOpenDropdown('from'); setActiveFromIndex((prev) => Math.max(0, prev - 1)); return; }
    if (e.key === 'Enter' && openDropdown === 'from') {
      const idx = activeFromIndex >= 0 ? activeFromIndex : 0;
      const chosen = fromSuggestions[idx];
      if (chosen) { e.preventDefault(); selectFromSuggestion(chosen); }
      return;
    }
    if (e.key === 'Escape') setOpenDropdown(null);
  };

  const handleToKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!toSuggestions.length) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); setOpenDropdown('to'); setActiveToIndex((prev) => Math.min(toSuggestions.length - 1, prev + 1)); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); setOpenDropdown('to'); setActiveToIndex((prev) => Math.max(0, prev - 1)); return; }
    if (e.key === 'Enter' && openDropdown === 'to') {
      const idx = activeToIndex >= 0 ? activeToIndex : 0;
      const chosen = toSuggestions[idx];
      if (chosen) { e.preventDefault(); selectToSuggestion(chosen); }
      return;
    }
    if (e.key === 'Escape') setOpenDropdown(null);
  };

  const renderHighlightedName = (name: string, query: string) => {
    const q = (query || '').trim();
    if (!q) return name;
    const re = new RegExp(`(${escapeRegExp(q)})`, 'ig');
    const parts = name.split(re);
    return (
      <>
        {parts.map((part, idx) => (
          part.toLowerCase() === q.toLowerCase()
            ? <strong key={`${part}-${idx}`}>{part}</strong>
            : <span key={`${part}-${idx}`}>{part}</span>
        ))}
      </>
    );
  };

  const renderStopDetail = (s: Stop) => {
    const parts = [(s as any).indicator, (s as any).street, (s as any).town].filter(Boolean);
    if (!parts.length) return null;
    return (
      <span style={{ fontSize: '11px', color: '#888', display: 'block', marginTop: '1px' }}>
        {parts.join(', ')}
      </span>
    );
  };

  return (
    <form ref={formRef} className="searchform" onSubmit={handleSubmit}>
      <div className="searchform__grid">
        <div className="searchform__field">
          <label htmlFor="from-input" className="visually-hidden">{fromLabel}</label>
          <div className="searchform__input-wrap">
            <Search className="searchform__input-icon" size={16} aria-hidden />
            <input
              id="from-input"
              name="from"
              value={from}
              onFocus={() => setOpenDropdown('from')}
              onKeyDown={handleFromKeyDown}
              onChange={(e) => {
                setFrom(capitalizeWords(e.target.value));
                if (selectedOriginId) setSelectedOrigin(null, null);
                setOpenDropdown('from');
              }}
              className="searchform__input searchform__input--with-icon"
              placeholder={t.fromPlaceholder as string}
              aria-label={fromLabel}
              autoComplete="off"
            />
          </div>
          {openDropdown === 'from' && from.trim().length > 0 && fromSuggestions.length > 0 && (
            <ul className="searchform__suggestions" role="listbox" aria-label="Origin suggestions">
              {fromSuggestions.map((s, idx) => (
                <li
                  key={s.id}
                  role="option"
                  aria-selected={idx === activeFromIndex}
                  className={`searchform__suggestion-item ${idx === activeFromIndex ? 'is-active' : ''}`}
                  onMouseEnter={() => setActiveFromIndex(idx)}
                  onMouseDown={(ev) => ev.preventDefault()}
                  onClick={() => selectFromSuggestion(s)}
                >
                  <span>{renderHighlightedName(s.name, from)}</span>
                  {renderStopDetail(s)}
                </li>
              ))}
            </ul>
          )}
          {fieldErrors.from && <div className="field-error" role="alert">{fieldErrors.from}</div>}
        </div>

        <div className="searchform__swap-wrap">
          <button className="searchform__swap" type="button" aria-label={t.swap as string} onClick={handleSwap}>
            <Shuffle className={`searchform__swap-icon switch-icon ${rotating ? 'rotate' : ''}`} size={18} strokeWidth={2} aria-hidden />
          </button>
        </div>

        <div className="searchform__field">
          <label htmlFor="to-input" className="visually-hidden">{toLabel}</label>
          <div className="searchform__input-wrap">
            <Search className="searchform__input-icon" size={16} aria-hidden />
            <input
              id="to-input"
              name="to"
              value={to}
              onFocus={() => setOpenDropdown('to')}
              onKeyDown={handleToKeyDown}
              onChange={(e) => {
                setTo(capitalizeWords(e.target.value));
                if (selectedDestinationId) setSelectedDestination(null, null);
                setOpenDropdown('to');
              }}
              className="searchform__input searchform__input--with-icon"
              placeholder={t.toPlaceholder as string}
              aria-label={toLabel}
              autoComplete="off"
            />
          </div>
          {openDropdown === 'to' && to.trim().length > 0 && toSuggestions.length > 0 && (
            <ul className="searchform__suggestions" role="listbox" aria-label="Destination suggestions">
              {toSuggestions.map((s, idx) => (
                <li
                  key={s.id}
                  role="option"
                  aria-selected={idx === activeToIndex}
                  className={`searchform__suggestion-item ${idx === activeToIndex ? 'is-active' : ''}`}
                  onMouseEnter={() => setActiveToIndex(idx)}
                  onMouseDown={(ev) => ev.preventDefault()}
                  onClick={() => selectToSuggestion(s)}
                >
                  <span>{renderHighlightedName(s.name, to)}</span>
                  {renderStopDetail(s)}
                </li>
              ))}
            </ul>
          )}
          {fieldErrors.to && <div className="field-error" role="alert">{fieldErrors.to}</div>}
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <button
          type="button"
          onClick={handleClearLocations}
          disabled={isLoading}
          aria-disabled={isLoading}
          style={{
            background: 'transparent',
            border: 'none',
            color: '#64748b',
            font: 'inherit',
            fontSize: '0.88rem',
            padding: 0,
            cursor: isLoading ? 'not-allowed' : 'pointer',
          }}
        >
          Clear
        </button>
      </div>

      <div className="searchform__grid-2">
        <div className="toggle-wrap" aria-label={`${departLabel} / ${arriveLabel}`}>
          <span className="visually-hidden" id="timeToggleLabel">{departLabel} / {arriveLabel}</span>
          <button aria-pressed={isDepart} aria-labelledby="timeToggleLabel" type="button" className={`toggle-btn ${isDepart ? 'mode__btn--active' : ''}`} onClick={() => setIsDepart(true)}>{departLabel}</button>
          <button aria-pressed={!isDepart} aria-labelledby="timeToggleLabel" type="button" className={`toggle-btn ${!isDepart ? 'mode__btn--active' : ''}`} onClick={() => setIsDepart(false)}>{arriveLabel}</button>
        </div>

        <div className="searchform__date-time-simple">
          <label htmlFor="date-input" className="visually-hidden">{dateLabel}</label>
          <input
            id="date-input"
            name="date"
            type="date"
            className="searchform__input"
            aria-label={dateLabel}
            value={selectedDate}
            onChange={(e) => { setDateTouched(true); setSelectedDate(e.target.value); }}
          />

          <label htmlFor="time-input" className="visually-hidden">{timeLabel}</label>
          <input
            id="time-input"
            name="time"
            type="time"
            className="searchform__input"
            aria-label={timeLabel}
            value={selectedTime}
            onChange={(e) => { setTimeTouched(true); setSelectedTime(e.target.value); }}
          />

          {(fieldErrors.date || fieldErrors.time) && (
            <div className="field-error" role="alert">{fieldErrors.date || fieldErrors.time}</div>
          )}
        </div>
      </div>

      <div className="searchform__modes">
        <button type="button" className={`mode__btn ${selectedMode === 'All modes' ? 'mode__btn--active' : ''}`} onClick={() => setSelectedMode('All modes')}>
          <MapPin className="mode__icon" size={18} strokeWidth={2} aria-hidden />
          {allModesLabel}
        </button>
        <button type="button" className={`mode__btn ${selectedMode === 'Bus' ? 'mode__btn--active' : ''}`} onClick={() => setSelectedMode('Bus')}>
          <Bus className="mode__icon" size={18} strokeWidth={2} aria-hidden />
          {busLabel}
        </button>
        <button type="button" className={`mode__btn ${selectedMode === 'Rail' ? 'mode__btn--active' : ''}`} onClick={() => setSelectedMode('Rail')}>
          <Train className="mode__icon" size={18} strokeWidth={2} aria-hidden />
          {railLabel}
        </button>
      </div>

      <div className="searchform__actions">
        <button className="searchform__button" type="submit" disabled={isLoading} aria-disabled={isLoading} aria-busy={isLoading}>
          {findRoutesLabel}
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
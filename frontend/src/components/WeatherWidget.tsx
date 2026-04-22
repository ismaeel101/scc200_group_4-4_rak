import React, { useState, useEffect, useMemo, useRef } from 'react';
import './WeatherWidget.css';
const BACKEND_BASE = 'http://127.0.0.1:8000';
const DEFAULT_LAT = 54.1;
const DEFAULT_LON = -2.5;

interface WeatherData {
  temperature_c: number;
  windspeed_kmh: number;
  description: string;
  is_adverse: boolean;
  available: boolean;
}

type WeatherWidgetProps = {
  lat?: number;
  lon?: number;
  variant?: 'navbar' | 'results' | 'default';
};

const iconForDescription = (description: string): string => {
  const d = (description || '').toLowerCase();
  if (d.includes('rain') || d.includes('drizzle') || d.includes('shower') || d.includes('storm')) return '🌧️';
  if (d.includes('cloud') || d.includes('overcast') || d.includes('mist') || d.includes('fog')) return '☁️';
  if (d.includes('snow') || d.includes('sleet') || d.includes('ice')) return '❄️';
  return '☀️';
};

const WeatherWidget: React.FC<WeatherWidgetProps> = ({ lat, lon, variant = 'default' }) => {
  const [weather, setWeather] = useState<WeatherData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [open, setOpen] = useState<boolean>(false);
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const latToUse = Number.isFinite(Number(lat)) ? Number(lat) : DEFAULT_LAT;
    const lonToUse = Number.isFinite(Number(lon)) ? Number(lon) : DEFAULT_LON;
    const weatherApi = `${BACKEND_BASE}/api/weather?${new URLSearchParams({
      lat: String(latToUse),
      lon: String(lonToUse),
    }).toString()}`;

    setLoading(true);
    fetch(weatherApi)
      .then((res) => {
        if (!res.ok) throw new Error(`Weather request failed (${res.status})`);
        return res.json();
      })
      .then((data) => {
        if (data.available) setWeather(data);
        setLoading(false);
      })
      .catch(() => {
        // Silent failure as per Task W5/W8 [cite: 68, 109]
        setLoading(false);
      });
  }, [lat, lon]);

  useEffect(() => {
    if (variant !== 'navbar') return;
    const onDocClick = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('click', onDocClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('click', onDocClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [variant]);

  const weatherIcon = useMemo(() => iconForDescription(weather?.description || ''), [weather?.description]);

  if (loading) {
    if (variant === 'navbar') {
      return (
        <div className="navbar-weather" ref={wrapperRef}>
          <button className="navbar-weather__btn" type="button" aria-label="Weather" disabled>
            <span className="navbar-weather__icon" aria-hidden>⛅</span>
            <span className="navbar-weather__temp">--.-°C</span>
          </button>
        </div>
      );
    }
    return <div className="weather-widget__loading">Loading weather...</div>;
  }
  if (!weather || !weather.available) return null;

  if (variant === 'navbar') {
    return (
      <div className="navbar-weather" ref={wrapperRef}>
        <button
          className="navbar-weather__btn"
          type="button"
          aria-haspopup="menu"
          aria-expanded={open}
          aria-label="Current weather"
          onClick={() => setOpen((v) => !v)}
        >
          <span className="navbar-weather__icon" aria-hidden>{weatherIcon}</span>
          <span className="navbar-weather__temp">{Number(weather.temperature_c).toFixed(1)}°C</span>
        </button>

        {open && (
          <div className="navbar-weather__menu" role="menu">
            <div className="navbar-weather__card">
              <div className="navbar-weather__row">
                <span className="navbar-weather__icon-lg" aria-hidden>{weatherIcon}</span>
                <div>
                  <p className="navbar-weather__condition">{weather.description}</p>
                  <p className="navbar-weather__temperature">{Number(weather.temperature_c).toFixed(1)}°C</p>
                </div>
              </div>
              <div className="navbar-weather__meta">💨 Wind: {weather.windspeed_kmh} km/h</div>
              <div className="navbar-weather__meta">{weather.is_adverse ? '⚠️ Adverse weather' : '✅ No adverse weather alert'}</div>
            </div>
          </div>
        )}
      </div>
    );
  }

  if (variant === 'results') {
    return (
      <div className="weather-strip" aria-label="Current weather">
        <span className="weather-strip__icon" aria-hidden>{weatherIcon}</span>
        <span className="weather-strip__temp">{Number(weather.temperature_c).toFixed(1)}°C</span>
        <span className="weather-strip__condition">{weather.description}</span>
        <span className="weather-strip__wind" aria-hidden>💨</span>
        <span className="weather-strip__wind-speed">{weather.windspeed_kmh} km/h</span>
      </div>
    );
  }

  return (
    <div className="weather-widget">
      {/* Adverse Weather Banner (Task W6) [cite: 75, 77] */}
      {weather.is_adverse && (
        <div className="weather-widget__adverse">
          ⚠️ Adverse weather in this region may affect journey reliability
        </div>
      )}

      {/* Main Widget Styled with Navy/Teal [cite: 67, 72] */}
      <div className="weather-widget__card">
        <div>
          <p className="weather-widget__label">Current Weather</p>
          <p className="weather-widget__temperature">{weather.temperature_c}°C</p>
        </div>
        <div className="weather-widget__right">
          <p className="weather-widget__pill">
            {weather.description}
          </p>
          <p className="weather-widget__wind">Wind: {weather.windspeed_kmh} km/h</p>
        </div>
      </div>
    </div>
  );
};

export default WeatherWidget;
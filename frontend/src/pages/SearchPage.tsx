import React, { useState } from "react";
import { useNavigate } from 'react-router-dom';
import SearchForm from "../components/SearchForm";
import HomeMap from "../components/HomeMap";
import WeatherWidget from "../components/WeatherWidget"; // Added import for W7
import "./SearchPage.css";
import translations from '../translations';
import { useUi } from '../contexts/UiContext';
import WeatherWidget from '../components/WeatherWidget';

const SearchPage: React.FC = () => {
  const navigate = useNavigate();
  const { language, validStopIds } = useUi();
  const t = translations[language.code] || translations.en;
  const planLabel = typeof t.planYourJourney === 'string' ? t.planYourJourney : 'Plan your journey';
  const [loading, setLoading] = useState(false);
  const [stops, setStops] = useState<any[]>([]);
  const [mapMode, setMapMode] = useState<'all' | 'bus' | 'rail'>('all');
  const overlayRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    if (loading) {
      const prev = document.activeElement as HTMLElement | null;
      document.body.style.overflow = 'hidden';
      overlayRef.current?.focus();
      return () => {
        document.body.style.overflow = '';
        prev?.focus();
      };
    }
    return;
  }, [loading]);

  return (
    <main className="searchpage">
      <div className="searchpage__split">
        {loading && (
          <div className="loading-overlay" role="alertdialog" aria-modal="true" aria-live="polite" ref={overlayRef} tabIndex={-1}>
            <div className="loading-card" aria-hidden={false}>
              <div className="loading-logo">OptiRoute</div>
              <div className="loading-sub">Finding best routes...</div>
            </div>
          </div>
        )}
        <aside className="searchpage__panel" role="complementary" aria-label={`${planLabel} panel`}>
          <div className="searchpage__panel-inner">
            <h2 className="searchpage__panel-title">{planLabel}</h2>

            {/* Added WeatherWidget here for Task W7 */}
            <div style={{ marginBottom: '1rem' }}>
              <WeatherWidget />
            </div>

            <div className="searchpage__card">
              <WeatherWidget />
              <SearchForm
                isLoading={loading}
                onModeChange={setMapMode}
                onSelectFrom={(s) => {
                  const valid = validStopIds || new Set<string>();
                  if (!valid.has(s.id)) {
                    console.warn('Blocked invalid stop:', s);
                    return;
                  }
                  setStops([s]);
                }}
                onSearch={async (data: any) => {
                  setLoading(true);
                  navigate('/results', {
                    state: {
                      search: {
                        origin_id: data.origin_id,
                        destination_id: data.destination_id,
                        time_type: data.time_type,
                        time_iso: data.time_iso,
                        modes: data.modes,
                        max_options: data.max_options || 5,
                      },
                      origin: data.from || '',
                      destination: data.to || '',
                    }
                  });
                  setLoading(false);
                  return null;
                }}
              />
            </div>
          </div>
        </aside>

        <section className="searchpage__map" role="main">
          <HomeMap stops={stops} mode={mapMode} />
        </section>
      </div>
    </main>
  );
};

export default SearchPage;
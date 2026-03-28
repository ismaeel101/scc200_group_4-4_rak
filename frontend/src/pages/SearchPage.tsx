import React, { useState } from "react";
import { useNavigate } from 'react-router-dom';
import SearchForm from "../components/SearchForm";
import HomeMap from "../components/HomeMap";
import "./SearchPage.css";
import translations from '../translations';
import { useUi } from '../contexts/UiContext';

const SearchPage: React.FC = () => {
  const navigate = useNavigate();
  const { language } = useUi();
  const t = translations[language.code] || translations.en;
  const [loading, setLoading] = useState(false);
  const [stops, setStops] = useState<any[]>([]);
  // const { reduceMotion } = useUi();
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
        <aside className="searchpage__panel" role="complementary" aria-label={`${t.planYourJourney} panel`}>
          <div className="searchpage__panel-inner">
            <h2 className="searchpage__panel-title">{t.planYourJourney}</h2>
            <div className="searchpage__card">
              <SearchForm
                isLoading={loading}
                onSelectFrom={(s) => {
                  setStops([s]);
                }}
                onSearch={async (data: any) => {
                  setLoading(true);
                  try {
                    const res = await fetch('http://127.0.0.1:8000/journeys', {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({
                        origin_id: data.origin_id,
                        destination_id: data.destination_id,
                        time_type: data.time_type,
                        time_iso: data.time_iso,
                        modes: data.modes,
                        max_options: data.max_options || 5,
                      }),
                    });
                    if (!res.ok) throw new Error('Planner request failed');
                    const body = await res.json();
                    const journeys = body.journeys || [];
                    setLoading(false);
                    // Navigate to results page with real journeys and human-readable origin/destination
                    navigate('/results', { state: { journeys, origin: data.from || '', destination: data.to || '' } });
                    return journeys;
                  } catch (e) {
                    setLoading(false);
                    // fallback: navigate with empty journeys but still include origin/destination
                    navigate('/results', { state: { journeys: [], origin: data.from || '', destination: data.to || '' } });
                    return [];
                  }
                }}
              />
            </div>
          </div>
        </aside>

        <section className="searchpage__map" role="main">
          <HomeMap stops={stops} />
        </section>
      </div>
    </main>
  );
};

export default SearchPage;
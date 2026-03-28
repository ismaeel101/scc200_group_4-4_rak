import React, { useEffect, useRef, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import "./Navbar.css";
import { useUi, Language } from '../contexts/UiContext';
import translations from '../translations';

const LANG_OPTIONS: Language[] = [
  { code: 'en', label: 'English', flag: '🇬🇧' },
  { code: 'fr', label: 'Français', flag: '🇫🇷' },
  { code: 'es', label: 'Español', flag: '🇪🇸' },
];

const Navbar: React.FC = () => {
  const navigate = useNavigate();
  const { language, setLanguage, highContrast, setHighContrast, largeText, setLargeText, reduceMotion, setReduceMotion } = useUi();
  const [menuOpen, setMenuOpen] = useState(false);
  const [langOpen, setLangOpen] = useState(false);
  const [accOpen, setAccOpen] = useState(false);
  const langRef = useRef<HTMLDivElement | null>(null);
  const accRef = useRef<HTMLDivElement | null>(null);
  const langMenuRef = useRef<HTMLDivElement | null>(null);
  const accMenuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (langRef.current && !langRef.current.contains(e.target as Node)) setLangOpen(false);
      if (accRef.current && !accRef.current.contains(e.target as Node)) setAccOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setLangOpen(false);
        setAccOpen(false);
      }
    };
    document.addEventListener('click', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('click', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, []);

  // basic focus trapping for small menus
  useEffect(() => {
    if (langOpen && langMenuRef.current) {
      const container = langMenuRef.current;
      const items = Array.from(container.querySelectorAll('button, [href], input, [tabindex]:not([tabindex="-1"])')) as HTMLElement[];
      if (items.length) items[0].focus();
      const onKey = (e: KeyboardEvent) => {
        if (e.key !== 'Tab') return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      };
      document.addEventListener('keydown', onKey);
      return () => document.removeEventListener('keydown', onKey);
    }
  }, [langOpen]);

  useEffect(() => {
    if (accOpen && accMenuRef.current) {
      const container = accMenuRef.current;
      const items = Array.from(container.querySelectorAll('button, input, [tabindex]:not([tabindex="-1"])')) as HTMLElement[];
      if (items.length) items[0].focus();
      const onKey = (e: KeyboardEvent) => {
        if (e.key !== 'Tab') return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      };
      document.addEventListener('keydown', onKey);
      return () => document.removeEventListener('keydown', onKey);
    }
  }, [accOpen]);

  return (
    <nav className="navbar">
      <div className="navbar__inner">
        <button
          className="navbar__brand"
          onClick={() => navigate('/')}
          aria-label={translations[language.code]?.brand || translations.en.brand}
        >
          {translations[language.code]?.brand || translations.en.brand}
        </button>

        <button className="navbar__toggle" aria-expanded={menuOpen} aria-label="Toggle navigation" onClick={() => setMenuOpen((v) => !v)}>
          ☰
        </button>

        <div className={`navbar__links ${menuOpen ? 'navbar__links--open' : ''}`}>
          <NavLink to="/" end className={({ isActive }) => `navbar__link${isActive ? ' navbar__link--active' : ''}`}>
            {translations[language.code]?.planJourney || translations.en.planJourney}
          </NavLink>
          <NavLink to="/live" className={({ isActive }) => `navbar__link${isActive ? ' navbar__link--active' : ''}`}>
            {translations[language.code]?.liveDepartures || translations.en.liveDepartures}
          </NavLink>
          <NavLink to="/support" className={({ isActive }) => `navbar__link${isActive ? ' navbar__link--active' : ''}`}>
            {translations[language.code]?.support || translations.en.support}
          </NavLink>
        </div>

        <div className="navbar__actions">
          <div className="navbar__lang" ref={langRef}>
            <button
              className="navbar__lang-btn"
              aria-haspopup="menu"
              aria-expanded={langOpen}
              onClick={() => setLangOpen((v) => !v)}
              aria-label={`Language: ${language.label}`}
            >
              <span className="navbar__lang-flag" aria-label={`${language.label} flag`}>{language.flag}</span>
              <span className="navbar__lang-code">{language.code.toUpperCase()}</span>
            </button>

            {langOpen && (
              <div className="navbar__lang-menu" role="menu" ref={langMenuRef}>
                {LANG_OPTIONS.map((lo) => (
                  <button
                    key={lo.code}
                    role="menuitem"
                    className="navbar__lang-item"
                    onClick={() => { setLanguage(lo); setLangOpen(false); }}
                  >
                    <span className="lang-flag" aria-hidden>{lo.flag}</span>
                    <span className="lang-label">{lo.label}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="navbar__access" ref={accRef}>
            <button className="navbar__access-btn" aria-haspopup="menu" aria-expanded={accOpen} onClick={() => setAccOpen((v) => !v)} aria-label="Accessibility options">{translations[language.code]?.accessibility || translations.en.accessibility}</button>
            {accOpen && (
              <div className="navbar__access-menu" role="menu" ref={accMenuRef}>
                <label className="access-row">
                  <input type="checkbox" checked={highContrast} onChange={(e) => setHighContrast(e.target.checked)} />
                  <span>High Contrast</span>
                </label>
                <label className="access-row">
                  <input type="checkbox" checked={largeText} onChange={(e) => setLargeText(e.target.checked)} />
                  <span>Larger Text</span>
                </label>
                <label className="access-row">
                  <input type="checkbox" checked={reduceMotion} onChange={(e) => setReduceMotion(e.target.checked)} />
                  <span>Reduce Motion</span>
                </label>
              </div>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
};

export default Navbar;

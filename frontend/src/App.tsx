import React from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Navbar from "./components/Navbar";
import { UiProvider, useUi } from './contexts/UiContext';
import translations from './translations';
import SearchPage from "./pages/SearchPage";
import ResultsPage from "./pages/ResultsPage";
import LiveDeparturesPage from "./pages/LiveDeparturesPage";
import TicketsPage from "./pages/TicketsPage";
const MapPage = () => {
    const { language } = useUi();
    const t = translations[language.code] || translations.en;
    const mapLabel = typeof t.map === 'string' ? t.map : 'Map';
    return <h1>{mapLabel}</h1>;
};
const SupportPage = () => {
    const { language } = useUi();
    const t = translations[language.code] || translations.en;
    const supportLabel = typeof t.support === 'string' ? t.support : 'Support';
    return <h1>{supportLabel}</h1>;
};

function App() {
    return (
        <BrowserRouter>
            <UiProvider>
                <Navbar />
                <Routes>
                    <Route path="/" element={<SearchPage />} />
                    <Route path="/live" element={<LiveDeparturesPage />} />
                    <Route path="/tickets" element={<TicketsPage />} />
                    <Route path="/map" element={<MapPage />} />
                    <Route path="/support" element={<SupportPage />} />
                    <Route path="/results" element={<ResultsPage />} />
                </Routes>
            </UiProvider>
        </BrowserRouter>
    );
}

export default App;
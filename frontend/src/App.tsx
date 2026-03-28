import React from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Navbar from "./components/Navbar";
import { UiProvider, useUi } from './contexts/UiContext';
import translations from './translations';
import SearchPage from "./pages/SearchPage";
import ResultsPage from "./pages/ResultsPage";

const LivePage = () => {
    const { language } = useUi();
    const t = translations[language.code] || translations.en;
    return <h1>{t.liveDepartures}</h1>;
};
const MapPage = () => {
    const { language } = useUi();
    const t = translations[language.code] || translations.en;
    return <h1>{t.map}</h1>;
};
const SupportPage = () => {
    const { language } = useUi();
    const t = translations[language.code] || translations.en;
    return <h1>{t.support}</h1>;
};

function App() {
    return (
        <BrowserRouter>
            <UiProvider>
                <Navbar />
                <Routes>
                    <Route path="/" element={<SearchPage />} />
                    <Route path="/live" element={<LivePage />} />
                    <Route path="/map" element={<MapPage />} />
                    <Route path="/support" element={<SupportPage />} />
                    <Route path="/results" element={<ResultsPage />} />
                </Routes>
            </UiProvider>
        </BrowserRouter>
    );
}

export default App;
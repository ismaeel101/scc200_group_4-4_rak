import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';

type Language = { code: string; label: string; flag: string };

type UiContextType = {
    language: Language;
    setLanguage: (l: Language) => void;
    highContrast: boolean;
    setHighContrast: (v: boolean) => void;
    largeText: boolean;
    setLargeText: (v: boolean) => void;
    reduceMotion: boolean;
    setReduceMotion: (v: boolean) => void;
    // Selected stops from map
    selectedOriginId?: string | null;
    selectedOriginName?: string | null;
    setSelectedOrigin: (id: string | null, name?: string | null) => void;
    selectedDestinationId?: string | null;
    selectedDestinationName?: string | null;
    setSelectedDestination: (id: string | null, name?: string | null) => void;
};

const defaultLang: Language = { code: 'en', label: 'English', flag: '🇬🇧' };

const UiContext = createContext<UiContextType | undefined>(undefined);

export const UiProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [language, setLanguage] = useState<Language>(defaultLang);
    const [highContrast, setHighContrast] = useState(false);
    const [largeText, setLargeText] = useState(false);
    const [reduceMotion, setReduceMotion] = useState(false);
    const [selectedOriginId, setSelectedOriginId] = useState<string | null>(null);
    const [selectedOriginName, setSelectedOriginName] = useState<string | null>(null);
    const [selectedDestinationId, setSelectedDestinationId] = useState<string | null>(null);
    const [selectedDestinationName, setSelectedDestinationName] = useState<string | null>(null);

    // apply classes to root element
    useEffect(() => {
        const root = document.documentElement;
        if (highContrast) root.classList.add('ux-high-contrast'); else root.classList.remove('ux-high-contrast');
        if (largeText) root.classList.add('ux-large-text'); else root.classList.remove('ux-large-text');
        if (reduceMotion) root.classList.add('ux-reduce-motion'); else root.classList.remove('ux-reduce-motion');
    }, [highContrast, largeText, reduceMotion]);

    const value = {
        language,
        setLanguage,
        highContrast,
        setHighContrast,
        largeText,
        setLargeText,
        reduceMotion,
        setReduceMotion,
        selectedOriginId,
        selectedOriginName,
        setSelectedOrigin: (id: string | null, name: string | null = null) => {
            console.log('[UiContext] setSelectedOrigin called:', id, name);
            setSelectedOriginId(id);
            setSelectedOriginName(name);
        },
        selectedDestinationId,
        selectedDestinationName,
        setSelectedDestination: (id: string | null, name: string | null = null) => {
            console.log('[UiContext] setSelectedDestination called:', id, name);
            setSelectedDestinationId(id);
            setSelectedDestinationName(name);
        },
    };

    return <UiContext.Provider value={value}>{children}</UiContext.Provider>;
};

export const useUi = () => {
    const ctx = useContext(UiContext);
    if (!ctx) throw new Error('useUi must be used within UiProvider');
    return ctx;
};

export type { Language };

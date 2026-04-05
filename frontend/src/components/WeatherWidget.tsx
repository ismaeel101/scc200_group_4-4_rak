import React, { useState, useEffect } from 'react';
const BACKEND_PORT = '8000'; 
const WEATHER_API = `http://localhost:${BACKEND_PORT}/api/weather`;

interface WeatherData {
  temperature_c: number;
  windspeed_kmh: number;
  description: string;
  is_adverse: boolean;
  available: boolean;
}

const WeatherWidget: React.FC = () => {
  const [weather, setWeather] = useState<WeatherData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    fetch(WEATHER_API)
      .then((res) => res.json())
      .then((data) => {
        if (data.available) setWeather(data);
        setLoading(false);
      })
      .catch(() => {
        // Silent failure as per Task W5/W8 [cite: 68, 109]
        setLoading(false);
      });
  }, []);

  if (loading) return <div className="text-xs animate-pulse">Loading weather...</div>;
  if (!weather || !weather.available) return null; 

  return (
    <div className="flex flex-col mb-4">
      {/* Adverse Weather Banner (Task W6) [cite: 75, 77] */}
      {weather.is_adverse && (
        <div className="bg-amber-100 border-l-4 border-amber-500 text-amber-800 p-2 mb-2 text-sm font-medium">
          ⚠️ Adverse weather in this region may affect journey reliability
        </div>
      )}

      {/* Main Widget Styled with Navy/Teal [cite: 67, 72] */}
      <div className="bg-[#1E3A5F] text-white p-3 rounded-lg flex justify-between items-center shadow-sm">
        <div>
          <p className="text-xs uppercase opacity-80">Current Weather</p>
          <p className="font-bold text-lg">{weather.temperature_c}°C</p>
        </div>
        <div className="text-right">
          <p className="text-sm font-medium text-[#0D6E8A] bg-white px-2 py-0.5 rounded-full inline-block">
            {weather.description}
          </p>
          <p className="text-xs mt-1">Wind: {weather.windspeed_kmh} km/h</p>
        </div>
      </div>
    </div>
  );
};

export default WeatherWidget;
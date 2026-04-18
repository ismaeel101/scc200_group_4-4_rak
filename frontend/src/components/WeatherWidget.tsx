import React, { useEffect, useState } from "react";

type WeatherDto = {
    available: boolean;
    is_adverse: boolean;
    description: string;
    temperature_c: number | null;
    windspeed_kmh: number | null;
};

const WeatherWidget: React.FC = () => {
    const [loading, setLoading] = useState<boolean>(true);
    const [weather, setWeather] = useState<WeatherDto | null>(null);

    useEffect(() => {
        let mounted = true;
        fetch("http://localhost:8000/api/weather?lat=54.047&lon=-2.801")
            .then((res) => {
                if (!res.ok) throw new Error("Network response was not ok");
                return res.json();
            })
            .then((data: WeatherDto) => {
                if (mounted) setWeather(data);
            })
            .catch(() => {
                if (mounted)
                    setWeather({
                        available: false,
                        is_adverse: false,
                        description: "",
                        temperature_c: null,
                        windspeed_kmh: null,
                    });
            })
            .finally(() => {
                if (mounted) setLoading(false);
            });
        return () => {
            mounted = false;
        };
    }, []);

    if (loading) {
        return <div style={{ fontFamily: "sans-serif", fontSize: 14 }}>Loading...</div>;
    }

    if (!weather || !weather.available) {
        return null;
    }

    const icon = weather.is_adverse ? "☁️" : "☀️";

    return (
        <div
            style={{
                fontFamily: "sans-serif",
                border: "1px solid #e6e6e6",
                padding: 12,
                borderRadius: 6,
                display: "inline-block",
                minWidth: 220,
            }}
        >
            {weather.is_adverse && (
                <div
                    style={{
                        background: "#fff3cd",
                        color: "#856404",
                        padding: "8px 10px",
                        borderRadius: 4,
                        marginBottom: 8,
                        fontSize: 13,
                    }}
                >
                    ⚠️ Adverse weather may affect reliability scores
                </div>
            )}

            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div style={{ fontSize: 32, lineHeight: 1 }}>{icon}</div>

                <div>
                    <div style={{ fontWeight: 600, fontSize: 15 }}>{weather.description || "Unknown"}</div>
                    <div style={{ fontSize: 13, color: "#333", marginTop: 6 }}>
                        Temp: {weather.temperature_c !== null ? `${weather.temperature_c}°C` : "N/A"} • Wind:{" "}
                        {weather.windspeed_kmh !== null ? `${weather.windspeed_kmh} km/h` : "N/A"}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default WeatherWidget;

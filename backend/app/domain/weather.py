from dataclasses import dataclass
from typing import Dict, Set


@dataclass
class WeatherInfo:
    available: bool
    is_adverse: bool
    description: str
    temperature_c: float
    windspeed_kmh: float


WEATHER_CODE_LOOKUP: Dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Foggy",
    48: "Icy fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    80: "Light showers",
    81: "Showers",
    82: "Heavy showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Heavy thunderstorm",
}

ADVERSE_CODES: Set[int] = {61, 62, 63, 64, 65, 71, 72, 73, 74, 75, 80, 81, 82, 85, 86, 95, 96, 99}


def fetch_weather(lat: float, lon: float) -> WeatherInfo:
    try:
        import httpx

        url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        )
        resp = httpx.get(url, timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
        current = data.get("current_weather") or {}

        # Extract values with safe fallbacks and type coercion
        try:
            temperature = float(current.get("temperature", 0.0))
        except Exception:
            temperature = 0.0
        try:
            windspeed = float(current.get("windspeed", 0.0))
        except Exception:
            windspeed = 0.0
        try:
            weathercode = int(current.get("weathercode"))
        except Exception:
            weathercode = -1

        is_adverse = (windspeed > 50) or (weathercode in ADVERSE_CODES)
        description = WEATHER_CODE_LOOKUP.get(weathercode, "Unknown conditions")

        return WeatherInfo(
            available=True,
            is_adverse=is_adverse,
            description=description,
            temperature_c=temperature,
            windspeed_kmh=windspeed,
        )
    except Exception:
        return WeatherInfo(
            available=False,
            is_adverse=False,
            description="Weather data unavailable",
            temperature_c=0.0,
            windspeed_kmh=0.0,
        )

from typing import Any, Dict
import httpx

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


async def fetch_weather(lat: float, lon: float) -> Dict[str, Any]:
    """
    Fetch current weather from Open-Meteo and return a simple summary.

    Returned dict keys:
    - available: bool
    - is_adverse: bool
    - description: str
    - temperature_c: float | None
    - windspeed_kmh: float | None

    Adverse: windspeed_kmh > 40 or precipitation > 0.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "current_weather": True,
        "hourly": "precipitation",
        "timezone": "UTC",
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(OPEN_METEO_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        current = data.get("current_weather", {}) or {}
        temp = current.get("temperature")
        wind = current.get("windspeed")

        # Determine precipitation for the current hour (if available)
        precip = 0.0
        hourly = data.get("hourly", {}) or {}
        times = hourly.get("time", [])
        precips = hourly.get("precipitation", [])
        current_time = current.get("time")
        if current_time and times and precips:
            try:
                idx = times.index(current_time)
                precip = float(precips[idx] or 0.0)
            except ValueError:
                precip = 0.0

        wind_val = float(wind) if wind is not None else None
        temp_val = float(temp) if temp is not None else None
        is_adverse = False
        if (wind_val is not None and wind_val > 40.0) or (precip and float(precip) > 0.0):
            is_adverse = True

        if precip and float(precip) > 0.0:
            description = "Precipitation"
        elif wind_val is not None and wind_val > 40.0:
            description = "High winds"
        else:
            description = "Normal"

        return {
            "available": True,
            "is_adverse": is_adverse,
            "description": description,
            "temperature_c": temp_val,
            "windspeed_kmh": wind_val,
        }

    except Exception:
        return {
            "available": False,
            "is_adverse": False,
            "description": "Weather service unavailable",
            "temperature_c": None,
            "windspeed_kmh": None,
        }

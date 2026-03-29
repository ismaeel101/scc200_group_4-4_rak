from pydantic import BaseModel

class WeatherInfo(BaseModel):
    condition: str
    severity: int
    source: str

def get_weather_stub() -> WeatherInfo:
    return WeatherInfo(
        condition="normal",
        severity=0,
        source="stub"
    )

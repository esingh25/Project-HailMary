"""Open-Meteo live weather feed (DESIGN.md §5 Phase 0) — keyless, free.

Fetches current conditions for an outdoor venue's coordinates and shapes them
into WeatherRecord. The venue coordinate lookup comes from the caller (the
schedule knows the venue; this module only knows the API).
"""

from datetime import UTC, datetime

import httpx

from hailmary.schemas.internal import WeatherRecord

API_URL = "https://api.open-meteo.com/v1/forecast"
CURRENT_FIELDS = "temperature_2m,wind_speed_10m,precipitation_probability"


def weather_record_from_response(
    game_id: str, payload: dict, captured_at: datetime
) -> WeatherRecord:
    """Shape one Open-Meteo /forecast response into a WeatherRecord."""
    current = payload["current"]
    return WeatherRecord(
        game_id=game_id,
        temperature_f=float(current["temperature_2m"]),
        wind_mph=float(current["wind_speed_10m"]),
        precipitation_pct=float(current.get("precipitation_probability") or 0.0),
        captured_at=captured_at,
    )


async def fetch_weather(
    game_id: str, latitude: float, longitude: float, client: httpx.AsyncClient
) -> list[WeatherRecord]:
    response = await client.get(
        API_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "current": CURRENT_FIELDS,
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
        },
        timeout=10.0,
    )
    response.raise_for_status()
    return [weather_record_from_response(game_id, response.json(), datetime.now(UTC))]

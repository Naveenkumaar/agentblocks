"""Open-Meteo weather connector — a real, key-free external tool.

Turns a free-text destination into a live current-weather reading by calling two
public Open-Meteo endpoints (geocoding -> forecast). No API key, no signup — so
the trip-planner agent calls a genuinely live service out of the box.

Like every connector, it runs *below* the model and behind
:meth:`Connector.invoke`, which catches network errors and degrades gracefully
(the turn still completes; the trace records ``ok: false``).
"""
from __future__ import annotations

import re
from typing import Any

from .base import Connector

# A compact slice of the WMO weather-code table Open-Meteo returns.
_WMO = {
    0: "clear sky",
    1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog",
    51: "light drizzle", 53: "drizzle", 55: "dense drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow",
    80: "rain showers", 81: "rain showers", 82: "violent rain showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail",
}

# Pull a destination out of "... in Paris", "weather for Tokyo", etc.
_DEST = re.compile(
    r"\b(?:in|for|to|at|near)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})"
)


class OpenMeteoConnector(Connector):
    def _extract_city(self, params: dict[str, Any]) -> str:
        if params.get("city"):
            return str(params["city"])
        query = str(params.get("query", ""))
        if (m := _DEST.search(query)):
            return m.group(1).strip()
        return self.config.get("default_city", "London")

    def _call(self, params: dict[str, Any]) -> Any:
        import httpx

        city = self._extract_city(params)
        with httpx.Client(timeout=15) as client:
            geo = client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": "en", "format": "json"},
            )
            geo.raise_for_status()
            results = geo.json().get("results") or []
            if not results:
                return {"city": city, "error": "location not found"}
            place = results[0]

            fc = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": place["latitude"],
                    "longitude": place["longitude"],
                    "current": "temperature_2m,wind_speed_10m,weather_code",
                },
            )
            fc.raise_for_status()
            current = fc.json().get("current", {})

        code = current.get("weather_code")
        return {
            "city": place.get("name", city),
            "country": place.get("country", ""),
            "temperature_c": current.get("temperature_2m"),
            "wind_kmh": current.get("wind_speed_10m"),
            "conditions": _WMO.get(code, "unknown"),
        }

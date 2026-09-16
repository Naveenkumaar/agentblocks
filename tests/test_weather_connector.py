"""Tests for the Open-Meteo weather connector.

The city-extraction and graceful-degradation logic is tested offline. The one
live-network test is skipped automatically when there is no connectivity, so the
suite stays green in an offline CI.
"""
import pytest

from app.connectors import OpenMeteoConnector


def _conn():
    return OpenMeteoConnector("weather", {"default_city": "London"})


def test_extracts_city_from_query():
    c = _conn()
    assert c._extract_city({"query": "what's the weather in Paris tomorrow?"}) == "Paris"
    assert c._extract_city({"query": "planning a trip to New York"}) == "New York"


def test_falls_back_to_default_city():
    assert _conn()._extract_city({"query": "how's the weather?"}) == "London"


def test_explicit_city_param_wins():
    assert _conn()._extract_city({"query": "in Paris", "city": "Berlin"}) == "Berlin"


def test_invoke_never_raises_when_offline():
    # base Connector.invoke() must swallow network errors into ok=False,
    # so a turn can always complete even with no connectivity.
    res = OpenMeteoConnector("weather", {"default_city": "Nowhereville-XYZ"}).invoke(
        {"query": "weather in Nowhereville-XYZ"}
    )
    assert res.connector == "weather"
    assert isinstance(res.ok, bool)


@pytest.mark.parametrize("city", ["Paris"])
def test_live_lookup(city):
    try:
        import httpx

        httpx.get("https://geocoding-api.open-meteo.com/v1/search",
                  params={"name": city, "count": 1}, timeout=5)
    except Exception:
        pytest.skip("no network — skipping live Open-Meteo test")

    res = _conn().invoke({"query": f"weather in {city}"})
    assert res.ok
    assert res.data["city"] == city
    assert isinstance(res.data["temperature_c"], (int, float))

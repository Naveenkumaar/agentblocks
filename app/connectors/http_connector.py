"""HTTP connector — calls a public REST API (e.g. the trip-planner's weather)."""
from __future__ import annotations

from typing import Any

from .base import Connector


class HttpConnector(Connector):
    def _call(self, params: dict[str, Any]) -> Any:
        import httpx

        base_url = self.config.get("base_url", "")
        path = params.pop("path", self.config.get("path", ""))
        method = self.config.get("method", "GET").upper()
        url = f"{base_url}{path}"

        with httpx.Client(timeout=30) as client:
            resp = client.request(method, url, params=params)
            resp.raise_for_status()
            ctype = resp.headers.get("content-type", "")
            return resp.json() if "application/json" in ctype else resp.text

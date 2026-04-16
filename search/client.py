"""Serper API client — raw HTTP layer."""
import os
import requests
from typing import Any, Optional


class SerperClient:
    """Low-level Serper API wrapper (news + web search)."""

    BASE_URL = "https://google.serper.dev"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("SERPER_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Serper API key required. Set SERPER_API_KEY environment variable."
            )
        self._headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }

    def news(
        self,
        query: str,
        time_range: str = "qdr:w",
        autocorrect: bool = False,
    ) -> dict[str, Any]:
        """Search news (default: past week)."""
        return self._post("/news", query, time_range, autocorrect)

    def search(
        self,
        query: str,
        time_range: str = "qdr:w",
        autocorrect: bool = False,
    ) -> dict[str, Any]:
        """Web search (default: past week)."""
        return self._post("/search", query, time_range, autocorrect)

    def _post(
        self, path: str, query: str, time_range: str, autocorrect: bool
    ) -> dict[str, Any]:
        url = self.BASE_URL + path
        payload = {"q": query, "autocorrect": autocorrect, "tbs": time_range}
        response = requests.post(url, headers=self._headers, json=payload)
        response.raise_for_status()
        return response.json()

"""Fetch the Wikimedia Featured Feed for a given date."""
import requests
from datetime import date


class FeaturedFeedFetcher:
    BASE_URL = "https://api.wikimedia.org/feed/v1/wikipedia/en/featured"

    def fetch(self, target_date: date = None) -> dict:
        """Fetch the featured feed for a given date (default today)."""
        if target_date is None:
            target_date = date.today()

        url = f"{self.BASE_URL}/{target_date.year}/{target_date.month:02}/{target_date.day:02}"
        headers = {
            "User-Agent": "WikiChronicleSurf/2.0 (https://github.com/codfed/wiki-chronicle-surf; cjfeda@gmail.com)"
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

        if "mostread" not in data or "articles" not in data.get("mostread", {}):
            raise RuntimeError(
                f"Featured feed for {target_date.isoformat()} is missing the 'mostread' section. "
                "This usually means the data is not yet available; re-run this date later."
            )

        return data

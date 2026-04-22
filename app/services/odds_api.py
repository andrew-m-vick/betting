"""The Odds API client.

The free tier allows 500 requests/month. The API's cost model charges
1 credit per (sport × region × market) combination per call, so a single
call for `regions=us&markets=h2h,spreads,totals` costs 3 credits.

Budget math (once-daily refresh):
  7 sports x 3 markets = 21 credits/day x 30 days = 630/month (OVER budget)
  5 sports x 3 markets = 15 credits/day x 30 days = 450/month (OK)

In practice several sports are out of season at any time (NFL Feb-Aug,
MLB Nov-Mar, etc.) so the fetcher skips sports with no upcoming games.
Every response includes `x-requests-remaining` / `x-requests-used`
headers that we log after each call so usage is observable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10  # seconds


class OddsAPIError(Exception):
    """Raised when the Odds API returns an error or unexpected response."""


class OddsAPIRateLimitError(OddsAPIError):
    """Raised when quota is exhausted (HTTP 429 or remaining == 0)."""


@dataclass(frozen=True)
class QuotaStatus:
    used: int | None
    remaining: int | None
    last_cost: int | None

    @classmethod
    def from_headers(cls, headers: dict[str, str]) -> "QuotaStatus":
        def _int(v: str | None) -> int | None:
            try:
                return int(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        return cls(
            used=_int(headers.get("x-requests-used")),
            remaining=_int(headers.get("x-requests-remaining")),
            last_cost=_int(headers.get("x-requests-last")),
        )


class OddsAPIClient:
    def __init__(self, api_key: str, base_url: str = "https://api.the-odds-api.com/v4"):
        if not api_key:
            raise ValueError("ODDS_API_KEY is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._last_quota: QuotaStatus | None = None

    @property
    def last_quota(self) -> QuotaStatus | None:
        return self._last_quota

    def _request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        params = {**(params or {}), "apiKey": self.api_key}
        url = f"{self.base_url}{path}"
        try:
            resp = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        except requests.RequestException as e:
            raise OddsAPIError(f"network error calling {path}: {e}") from e

        self._last_quota = QuotaStatus.from_headers(resp.headers)
        logger.info(
            "odds_api path=%s status=%s used=%s remaining=%s last_cost=%s",
            path, resp.status_code,
            self._last_quota.used, self._last_quota.remaining, self._last_quota.last_cost,
        )

        if resp.status_code == 429:
            raise OddsAPIRateLimitError("rate limit exceeded (HTTP 429)")
        if resp.status_code == 401:
            raise OddsAPIError("invalid API key (HTTP 401)")
        if resp.status_code >= 400:
            raise OddsAPIError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        if self._last_quota.remaining is not None and self._last_quota.remaining <= 0:
            logger.warning("odds_api quota exhausted; subsequent calls will fail")

        return resp.json()

    def list_sports(self, all_sports: bool = False) -> list[dict[str, Any]]:
        """List available sports. Does NOT count against quota."""
        return self._request("/sports", {"all": "true" if all_sports else "false"})

    def get_scores(
        self, sport_key: str, days_from: int = 3
    ) -> list[dict[str, Any]]:
        """Fetch scores for recent + upcoming games.

        Costs ~1 credit per call (much cheaper than /odds which is
        multiplied by markets). `days_from` caps how far back to fetch
        completed games; valid range 1-3.
        """
        if not 1 <= days_from <= 3:
            raise ValueError("days_from must be between 1 and 3")
        return self._request(
            f"/sports/{sport_key}/scores", {"daysFrom": days_from}
        )

    def get_odds(
        self,
        sport_key: str,
        regions: str = "us",
        markets: tuple[str, ...] = ("h2h", "spreads", "totals"),
        bookmakers: tuple[str, ...] | None = None,
        odds_format: str = "american",
    ) -> list[dict[str, Any]]:
        """Fetch current odds for a sport.

        Cost = number of markets * number of regions per the Odds API docs.
        Passing `bookmakers` filters results but does not reduce cost.
        """
        params: dict[str, Any] = {
            "regions": regions,
            "markets": ",".join(markets),
            "oddsFormat": odds_format,
        }
        if bookmakers:
            params["bookmakers"] = ",".join(bookmakers)
        return self._request(f"/sports/{sport_key}/odds", params)


def parse_commence_time(iso_str: str) -> datetime:
    """Parse The Odds API's ISO8601 timestamp (always UTC 'Z' suffix)."""
    return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))

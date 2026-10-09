"""Shared Semantic Scholar Graph API client: API key header, throttle, retry with backoff."""
import asyncio
import logging
import random
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

PAPER_FIELDS = "paperId,title,authors,year,abstract,url,openAccessPdf,externalIds"


class S2Error(Exception):
    """Base class for Semantic Scholar failures."""


class S2TransientError(S2Error):
    """429 / 5xx / timeout / network error that persisted after retries."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class S2AuthError(S2Error):
    """401/403: the API key is missing, invalid, or not allowed. A config bug."""


class S2BadRequest(S2Error):
    """400: the request itself is malformed (e.g. an invalid query)."""


class S2NotFound(S2Error):
    """404: no paper for this identifier."""


class S2Client:
    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        *,
        min_interval: float = 1.0,
        max_attempts: int = 3,
        timeout: float = 10.0,
        user_agent: str = "ResearchAssistant/0.1",
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.min_interval = min_interval
        self.max_attempts = max_attempts
        self.timeout = timeout
        self.user_agent = user_agent
        self._transport = transport
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def _throttle(self) -> None:
        # Space out calls to stay under the per-key rate limit (1 req/s by default).
        async with self._lock:
            wait = self._last_call + self.min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        headers = {"User-Agent": self.user_agent}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        reason = "unknown"
        retry_after: float | None = None
        async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
            for attempt in range(self.max_attempts):
                if attempt:
                    await asyncio.sleep(self._backoff(attempt, retry_after))
                retry_after = None
                await self._throttle()
                try:
                    resp = await client.get(f"{self.base_url}{path}", params=params, headers=headers)
                except httpx.TimeoutException:
                    reason = "s2_timeout"
                    log.info("S2 timeout on %s (attempt %d)", path, attempt + 1)
                    continue
                except httpx.HTTPError as exc:
                    reason = "s2_network_error"
                    log.info("S2 network error on %s: %s (attempt %d)", path, exc, attempt + 1)
                    continue

                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 429 or resp.status_code >= 500:
                    reason = "s2_rate_limited" if resp.status_code == 429 else f"s2_http_{resp.status_code}"
                    retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                    log.info("S2 %s on %s (attempt %d)", resp.status_code, path, attempt + 1)
                    continue
                if resp.status_code in (401, 403):
                    raise S2AuthError(f"S2 returned {resp.status_code}: {resp.text[:200]}")
                if resp.status_code == 404:
                    raise S2NotFound(path)
                raise S2BadRequest(f"S2 returned {resp.status_code}: {resp.text[:200]}")

        raise S2TransientError(reason)

    @staticmethod
    def _backoff(attempt: int, retry_after: float | None) -> float:
        base = 2 ** (attempt - 1)  # 1s, 2s, 4s ...
        delay = base + random.uniform(0, 0.5)
        if retry_after is not None:
            delay = max(delay, min(retry_after, 30.0))
        return delay

    # ---- typed helpers ----

    async def search(self, query: str, limit: int = 20) -> list[dict]:
        data = await self.get(
            "/paper/search", {"query": query, "limit": limit, "fields": PAPER_FIELDS}
        )
        return data.get("data") or []

    async def lookup(self, identifier: str) -> dict:
        """identifier is e.g. 'arXiv:2106.09685' or 'DOI:10.18653/v1/N19-1423'."""
        return await self.get(f"/paper/{identifier}", {"fields": PAPER_FIELDS})


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None

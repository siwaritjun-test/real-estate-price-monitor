"""A small polite HTTP client: one browser-honest UA, retries, and rate limiting."""

from __future__ import annotations

import logging
import random
import time

import requests

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 "
    "real-estate-price-monitor/0.1 (personal price tracker)"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,th;q=0.8",
    "Upgrade-Insecure-Requests": "1",
}


class FetchError(RuntimeError):
    """Raised when a page could not be retrieved after retries."""


class Fetcher:
    """Shared session with a minimum gap between requests to the same host."""

    def __init__(
        self,
        *,
        delay: float = 1.0,
        timeout: int = 30,
        retries: int = 3,
    ) -> None:
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self._last_request_at = 0.0

    def _wait(self) -> None:
        gap = time.monotonic() - self._last_request_at
        if gap < self.delay:
            time.sleep(self.delay - gap + random.uniform(0, 0.25))
        self._last_request_at = time.monotonic()

    def get(self, url: str) -> str:
        """Fetch a URL as text, retrying transient failures with backoff."""
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self._wait()
            try:
                response = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = exc
                log.warning("GET %s failed (%s), attempt %d", url, exc, attempt)
            else:
                if response.status_code == 200:
                    # Thai pages are UTF-8 but some responses mislabel the charset.
                    return response.content.decode("utf-8", errors="replace")
                last_error = FetchError(f"HTTP {response.status_code} for {url}")
                if response.status_code in (401, 403, 404, 410):
                    # A hard refusal will not become a 200 by trying again.
                    raise last_error
                log.warning("GET %s -> HTTP %s, attempt %d", url, response.status_code, attempt)
            time.sleep(min(2**attempt, 10))
        raise FetchError(f"could not fetch {url}: {last_error}")

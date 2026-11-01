"""HTTP client with retries, backoff, Retry-After support and a circuit breaker."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

import httpx

from app.core.errors import ProviderError, RateLimitedError
from app.providers.rate_limit import TokenBucket

logger = logging.getLogger(__name__)

USER_AGENT = "LiquidGlassCryptoLab/1.0 (+paper-trading; read-only market data)"


class ProviderHTTP:
    def __init__(
        self,
        name: str,
        base_url: str,
        *,
        timeout: float = 15.0,
        max_retries: int = 3,
        limiter: TokenBucket | None = None,
        client: httpx.AsyncClient | None = None,
        circuit_threshold: int = 5,
        circuit_cooldown: float = 300.0,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.max_retries = max(0, max_retries)
        self.limiter = limiter or TokenBucket(name, 60)
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )
        self._owns_client = client is None
        self._failures = 0
        self._open_until = 0.0
        self._circuit_threshold = circuit_threshold
        self._circuit_cooldown = circuit_cooldown
        self.last_error: str | None = None
        self.request_count = 0

    @property
    def circuit_open(self) -> bool:
        return time.monotonic() < self._open_until

    def health(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "circuit_open": self.circuit_open,
            "consecutive_failures": self._failures,
            "last_error": self.last_error,
            "requests": self.request_count,
            "rate_limit": self.limiter.snapshot() if self.limiter else None,
        }

    def _record_success(self) -> None:
        self._failures = 0
        self._open_until = 0.0

    def _record_failure(self, error: str) -> None:
        self._failures += 1
        self.last_error = error
        if self._failures >= self._circuit_threshold:
            self._open_until = time.monotonic() + self._circuit_cooldown
            logger.warning(
                "provider_circuit_open", extra={"provider": self.name, "failures": self._failures}
            )

    async def get_json(
        self, path: str, params: dict[str, Any] | None = None, *, acquire: bool = True
    ) -> Any:
        return await self._request("GET", path, params=params, acquire=acquire)

    async def post_json(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
        acquire: bool = True,
    ) -> Any:
        return await self._request(
            "POST", path, json=payload, headers=headers, acquire=acquire, allow_empty=True
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        acquire: bool = True,
        allow_empty: bool = False,
    ) -> Any:
        if self.circuit_open:
            raise ProviderError(
                f"{self.name} temporarily unavailable (circuit open)",
                code="PROVIDER_CIRCUIT_OPEN",
                details={"provider": self.name},
            )
        if acquire and self.limiter:
            await self.limiter.acquire()

        url = path if path.startswith("http") else f"{self.base_url}{path}"
        attempt = 0
        rate_limited_retry = False
        while True:
            attempt += 1
            try:
                self.request_count += 1
                response = await self._client.request(
                    method, url, params=params, json=json, headers=headers
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt > self.max_retries:
                    self._record_failure(str(exc))
                    raise ProviderError(
                        f"{self.name} request failed after {attempt} attempts",
                        details={"provider": self.name, "error": str(exc)},
                    ) from exc
                await asyncio.sleep(self._backoff(attempt))
                continue

            if response.status_code == 429:
                retry_after = self._retry_after(response)
                if not rate_limited_retry:
                    # One short courtesy retry: bursts at the minute boundary are
                    # common and must not fail the whole scan stage.
                    rate_limited_retry = True
                    await asyncio.sleep(min(retry_after, 3.0))
                    continue
                self._record_failure("429 rate limited")
                raise RateLimitedError(
                    f"{self.name} rate limited",
                    details={"provider": self.name, "retry_after": retry_after},
                )

            if response.status_code >= 500:
                if attempt > self.max_retries:
                    self._record_failure(f"HTTP {response.status_code}")
                    raise ProviderError(
                        f"{self.name} responded {response.status_code}",
                        details={"provider": self.name, "status": response.status_code},
                    )
                await asyncio.sleep(self._backoff(attempt))
                continue

            if response.status_code >= 400:
                self._record_failure(f"HTTP {response.status_code}")
                raise ProviderError(
                    f"{self.name} rejected request ({response.status_code})",
                    details={"provider": self.name, "status": response.status_code},
                )

            self._record_success()
            if response.status_code == 204 or not response.content:
                return None if allow_empty else {}
            try:
                return response.json()
            except ValueError as exc:
                self._record_failure("invalid json")
                raise ProviderError(
                    f"{self.name} returned invalid JSON",
                    details={"provider": self.name},
                ) from exc

    @staticmethod
    def _retry_after(response: httpx.Response) -> float:
        raw = response.headers.get("Retry-After")
        if not raw:
            return 60.0
        try:
            return float(raw)
        except ValueError:
            return 60.0

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(8.0, 0.4 * (2 ** (attempt - 1))) + random.uniform(0, 0.2)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

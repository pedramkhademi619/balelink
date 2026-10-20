"""Delivering events to a webhook: signed, retried, never blocking the client."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Any, Awaitable, Callable, Dict, Optional, Set

log = logging.getLogger("balelink.gateway")

SIGNATURE_HEADER = "X-Balelink-Signature"
Poster = Callable[[str, bytes, Dict[str, str]], Awaitable[int]]


def sign(secret: str, body: bytes) -> str:
    """``sha256=<hex>`` - HMAC of the raw request body. Receivers should compare
    it with ``hmac.compare_digest``."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class WebhookSender:
    """Fire-and-forget delivery with retries (1s, 3s, 9s ... between tries).

    A 2xx answer is success; anything else, or a network error, is retried.
    Failures are logged and dropped - a slow receiver must not hold up Bale.
    """

    def __init__(
        self,
        attempts: int = 4,
        timeout: float = 10.0,
        poster: Optional[Poster] = None,
        base_delay: float = 1.0,
    ) -> None:
        self.attempts = max(1, attempts)
        self.base_delay = base_delay
        self._poster = poster or self._default_poster(timeout)
        self._tasks: Set[asyncio.Task[Any]] = set()

    @staticmethod
    def _default_poster(timeout: float) -> Poster:
        async def post(url: str, body: bytes, headers: Dict[str, str]) -> int:
            import httpx

            async with httpx.AsyncClient(timeout=timeout) as http:
                return (await http.post(url, content=body, headers=headers)).status_code

        return post

    def send(
        self,
        url: str,
        secret: Optional[str],
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        attempts: Optional[int] = None,
    ) -> None:
        task = asyncio.create_task(self._deliver(url, secret, payload, headers, attempts))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _deliver(
        self,
        url: str,
        secret: Optional[str],
        payload: Dict[str, Any],
        extra_headers: Optional[Dict[str, str]] = None,
        attempts: Optional[int] = None,
    ) -> bool:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        headers = {"Content-Type": "application/json", "User-Agent": "balelink-gateway"}
        headers.update(extra_headers or {})
        tries = max(1, attempts or self.attempts)
        if secret:
            headers[SIGNATURE_HEADER] = sign(secret, body)
        delay = self.base_delay
        for attempt in range(1, tries + 1):
            try:
                status = await self._poster(url, body, headers)
                if 200 <= status < 300:
                    return True
                log.warning("webhook %s answered %s (try %s)", url, status, attempt)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("webhook %s failed: %s (try %s)", url, type(e).__name__, attempt)
            if attempt < tries:
                await asyncio.sleep(delay)
                delay *= 3
        log.error("webhook %s gave up after %s tries", url, tries)
        return False

    async def close(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

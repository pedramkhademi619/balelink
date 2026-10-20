"""Fetching a file from a URL so it can be sent - without becoming an SSRF hole."""

from __future__ import annotations

import ipaddress
import socket
from typing import Optional, Tuple
from urllib.parse import urlparse

from .manager import GatewayError

MAX_BYTES = 50 * 1024 * 1024


def _blocked(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return True
    return False


def check_url(url: str, allow_private: bool) -> None:
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise GatewayError(422, "INVALID_URL", "Only http(s) URLs are accepted.")
    if not allow_private and _blocked(parts.hostname):
        raise GatewayError(
            422,
            "URL_NOT_ALLOWED",
            "That address is private or unreachable. Set BALELINK_ALLOW_PRIVATE_URLS=1 to allow it.",
        )


async def fetch(url: str, allow_private: bool = False) -> Tuple[bytes, Optional[str], str]:
    """``(bytes, content_type, file_name)`` of [url]. Redirects are not followed
    (a redirect could point at a private address after the check)."""
    import httpx

    check_url(url, allow_private)
    data = bytearray()
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as http:
            async with http.stream("GET", url) as response:
                if response.status_code != 200:
                    raise GatewayError(
                        422, "URL_FETCH_FAILED", f"The URL answered {response.status_code}."
                    )
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise GatewayError(413, "FILE_TOO_LARGE", "The file is over 50 MB.")
                ctype = response.headers.get("content-type", "").split(";")[0] or None
    except httpx.HTTPError as e:
        raise GatewayError(422, "URL_FETCH_FAILED", "Could not download that URL.") from e
    name = urlparse(url).path.rsplit("/", 1)[-1] or "file"
    return bytes(data), ctype, name

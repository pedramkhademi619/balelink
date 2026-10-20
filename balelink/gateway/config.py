"""Gateway settings, read from ``BALELINK_*`` environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional


def _flag(value: Optional[str], default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """
    host / port       where to listen (default 127.0.0.1:8787 - local only)
    api_key           required in the ``X-Api-Key`` header when set. Without
                      one anybody who can reach the port controls your accounts,
                      so only leave it empty on a trusted machine.
    directory         where logins and gateway state live (default ~/.balelink)
    autostart         reconnect every saved session when the gateway starts
    webhook_timeout   seconds to wait for a webhook receiver
    webhook_attempts  deliveries tried per event before giving up
    public_url        this gateway's address as receivers see it; used for media links
    allow_private_urls  let `url` file sources point at private/loopback addresses
    """

    host: str = "127.0.0.1"
    port: int = 8787
    api_key: Optional[str] = None
    directory: Optional[str] = None
    autostart: bool = True
    webhook_timeout: float = 10.0
    webhook_attempts: int = 4
    public_url: Optional[str] = None
    allow_private_urls: bool = False

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> Settings:
        e = os.environ if env is None else env
        return cls(
            host=e.get("BALELINK_HOST", cls.host),
            port=int(e.get("BALELINK_PORT", cls.port)),
            api_key=e.get("BALELINK_API_KEY") or None,
            directory=e.get("BALELINK_HOME") or None,
            autostart=_flag(e.get("BALELINK_AUTOSTART"), True),
            webhook_timeout=float(e.get("BALELINK_WEBHOOK_TIMEOUT", cls.webhook_timeout)),
            webhook_attempts=int(e.get("BALELINK_WEBHOOK_ATTEMPTS", cls.webhook_attempts)),
            public_url=e.get("BALELINK_PUBLIC_URL") or None,
            allow_private_urls=_flag(e.get("BALELINK_ALLOW_PRIVATE_URLS"), False),
        )

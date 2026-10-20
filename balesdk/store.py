"""Where logins are kept.

A saved login is a file that *is* the account: whoever can read it can act as
you. So it is created readable by its owner only, and kept out of the way in a
directory of its own.
"""

from __future__ import annotations

import os
import pathlib
import re
from typing import List

_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def default_directory() -> pathlib.Path:
    env = os.environ.get("BALESDK_HOME")
    if env:
        return pathlib.Path(env).expanduser()
    return pathlib.Path.home() / ".balesdk"


class SessionStore:
    """A directory of saved logins, one ``<name>.bale`` file each."""

    suffix = ".bale"

    def __init__(self, directory: str | os.PathLike[str] | None = None) -> None:
        self.directory = pathlib.Path(directory).expanduser() if directory else default_directory()

    @staticmethod
    def check_name(name: str) -> str:
        if not _NAME.fullmatch(name or ""):
            raise ValueError("A session name is 1-64 letters, digits, '_', '-' or '.'")
        return name

    def path(self, name: str) -> pathlib.Path:
        return self.directory / f"{self.check_name(name)}{self.suffix}"

    def ensure_directory(self) -> pathlib.Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.directory, 0o700)
        except OSError:  # pragma: no cover - not every filesystem allows it
            pass
        return self.directory

    def exists(self, name: str) -> bool:
        p = self.path(name)
        return p.is_file() and p.stat().st_size > 0

    def names(self) -> List[str]:
        if not self.directory.is_dir():
            return []
        return sorted(p.stem for p in self.directory.glob(f"*{self.suffix}"))

    def secure(self, name: str) -> None:
        """Make the file readable by its owner only (it holds a login)."""
        p = self.path(name)
        if p.exists():
            try:
                os.chmod(p, 0o600)
            except OSError:  # pragma: no cover
                pass

    def delete(self, name: str) -> bool:
        p = self.path(name)
        if p.exists():
            p.unlink()
            return True
        return False

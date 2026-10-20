"""Splitting long text into messages Bale will accept."""

from __future__ import annotations

from typing import List

DEFAULT_LIMIT = 4000


def split_text(text: str, limit: int = DEFAULT_LIMIT) -> List[str]:
    """Break [text] into pieces of at most [limit] characters.

    Prefers to cut at a blank line, then a line break, then a space, and only
    cuts mid-word when there is nothing else (a very long word or URL).
    Nothing is lost: joining the pieces back gives [text] without the
    whitespace at each cut.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if len(text) <= limit:
        return [text]

    pieces: List[str] = []
    rest = text
    while len(rest) > limit:
        window = rest[:limit]
        cut = -1
        for sep in ("\n\n", "\n", " "):
            at = window.rfind(sep)
            if at > limit // 2:  # not so early that the piece is tiny
                cut = at
                break
        if cut == -1:
            pieces.append(window)
            rest = rest[limit:]
        else:
            pieces.append(rest[:cut])
            rest = rest[cut:].lstrip("\n ")
    if rest:
        pieces.append(rest)
    return [p for p in pieces if p]

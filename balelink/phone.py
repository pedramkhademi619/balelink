"""Phone numbers the way Bale wants them: digits only, Iran's leading 0 as 98."""

from __future__ import annotations

import re

# Persian and Arabic-Indic digits -> ASCII, so a number typed on a Persian keyboard works.
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_phone(raw: str | int) -> str:
    """``0912 123 4567``, ``+98 912 123 4567``, ``00989121234567`` -> ``989121234567``."""
    digits = re.sub(r"\D", "", str(raw or "").translate(_DIGITS))
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = "98" + digits[1:]
    return digits


def is_plausible_phone(normalized: str) -> bool:
    """10 to 15 digits - the range of a real international number."""
    return re.fullmatch(r"[0-9]{10,15}", normalized) is not None

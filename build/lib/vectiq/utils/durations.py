from __future__ import annotations

import re

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_PART = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)


class DurationError(ValueError):
    pass


def parse_duration(text: str) -> int:
    """``90m``, ``1h30m``, ``2d`` -> seconds. A bare number means minutes."""
    text = text.strip().lower()
    if text.isdigit():
        return int(text) * 60
    parts = _PART.findall(text)
    if not parts or _PART.sub("", text).strip():
        raise DurationError(f"can't read {text!r} as a duration (try 30m, 2h, 1d12h)")
    total = sum(int(n) * _UNITS[u.lower()] for n, u in parts)
    if total <= 0:
        raise DurationError("duration must be positive")
    return total


def format_duration(seconds: int) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    out = []
    for name, size in (("d", 86400), ("h", 3600), ("m", 60)):
        n, seconds = divmod(seconds, size)
        if n:
            out.append(f"{n}{name}")
    return "".join(out[:2]) or "0m"

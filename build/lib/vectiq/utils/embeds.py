"""Small helpers so every cog builds messages the same way."""

from __future__ import annotations

import datetime
from collections.abc import Iterable

import vector


def embed(title: str, description: str = "", *, fields: Iterable[tuple[str, str, bool]] = (),
          footer: str | None = None, timestamp: bool = False) -> vector.Embed:
    e = vector.Embed(title=title, description=description or None)
    if timestamp:
        e.timestamp = datetime.datetime.now(datetime.timezone.utc)   # shown in the footer in each reader's local time
    for name, value, inline in fields:
        e.add_field(name=name, value=value or "-", inline=inline)
    if footer:
        e.set_footer(text=footer)
    return e


def ok(text: str) -> str:
    return f"✅ {text}"


def fail(text: str) -> str:
    return f"❌ {text}"


def name_of(user, fallback: str = "someone") -> str:
    """A display name that never raises, with a short npub as the last resort."""
    for attr in ("display_name", "name"):
        value = getattr(user, attr, None)
        if value:
            return str(value)
    ident = str(getattr(user, "id", "") or getattr(user, "npub", "") or fallback)
    return ident[:12] + "…" if len(ident) > 14 else ident


def short(ident: object) -> str:
    s = str(ident)
    return s[:12] + "…" if len(s) > 14 else s


def table(rows: list[tuple[str, ...]], header: tuple[str, ...] | None = None) -> str:
    """A plain-text table in a code block (works the same everywhere)."""
    data = ([header] if header else []) + rows
    if not data:
        return ""
    widths = [max(len(str(r[i])) for r in data) for i in range(len(data[0]))]
    lines = ["  ".join(str(c).ljust(w) for c, w in zip(r, widths, strict=True)).rstrip() for r in data]
    if header:
        lines.insert(1, "  ".join("-" * w for w in widths))
    return "```\n" + "\n".join(lines) + "\n```"


async def avatar_bytes(member, *, timeout: float = 4.0, limit: int = 2_000_000):
    """A member's profile picture as bytes, or None (no picture, slow host, too big, anything at all)."""
    import asyncio

    try:
        asset = getattr(member, "display_avatar", None)
        if not asset:
            return None
        data = await asyncio.wait_for(asset.read(), timeout)
        return data if data and len(data) <= limit else None
    except Exception:  # noqa: BLE001 - an avatar is decoration, never a reason to fail a command
        return None

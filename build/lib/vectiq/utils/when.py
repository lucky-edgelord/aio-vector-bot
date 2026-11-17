"""Reading and writing event times the way people type them, in a community's time zone.

``parse_when("friday 8pm", tz)``, ``"tomorrow at 18:30"``, ``"nov 20 7:30pm"``, ``"2026-11-20 20:00"``,
``"11/20"``, ``"in 2h"``, ``"tonight"``, ``"noon"``. Everything returns an aware UTC datetime.
"""

from __future__ import annotations

import calendar
import datetime as dt
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = dt.timezone.utc

WEEKDAYS = {name: i for i, names in enumerate((
    ("mon", "monday"), ("tue", "tues", "tuesday"), ("wed", "weds", "wednesday"), ("thu", "thur", "thurs", "thursday"),
    ("fri", "friday"), ("sat", "saturday"), ("sun", "sunday"))) for name in names}
MONTHS = {name: i for i, names in enumerate((
    ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
    ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
    ("dec", "december")), start=1) for name in names}
UNITS = {"m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60, "h": 3600, "hr": 3600, "hrs": 3600,
         "hour": 3600, "hours": 3600, "d": 86400, "day": 86400, "days": 86400, "w": 604800, "week": 604800,
         "weeks": 604800}

REPEATS = ("none", "daily", "weekly", "biweekly", "monthly")


class WhenError(ValueError):
    pass


def zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo((name or "UTC").strip())
    except (ZoneInfoNotFoundError, ValueError):
        raise WhenError(f"unknown time zone {name!r} (try America/New_York, Europe/London, UTC)") from None


_TIME = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm|a|p)?$")
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:t(\d{1,2}):(\d{2}))?$")
_SLASH = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$")
_IN = re.compile(r"^in\s+(.+)$")
_SPAN = re.compile(r"(\d+(?:\.\d+)?)\s*([a-z]+)")


def _time(tok: str) -> tuple[int, int] | None:
    if tok in ("noon", "midday"):
        return 12, 0
    if tok == "midnight":
        return 0, 0
    m = _TIME.match(tok)
    if not m:
        return None
    h, mi, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if mi > 59:
        return None
    if ampm:
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if ampm.startswith("p") else 0)
    elif h > 23:
        return None
    return h, mi


def parse_span(text: str) -> int:
    """``2h``, ``90m``, ``1h30m``, ``1.5 hours``, ``45`` (minutes) -> seconds."""
    t = text.strip().lower()
    if re.fullmatch(r"\d+", t):
        return int(t) * 60
    parts = _SPAN.findall(t)
    if not parts or _SPAN.sub("", t).replace("and", "").replace(",", "").strip():
        raise WhenError(f"can't read {text!r} as a length of time (try 30m, 2h, 1h30m)")
    total = 0.0
    for n, unit in parts:
        if unit not in UNITS:
            raise WhenError(f"unknown unit {unit!r}")
        total += float(n) * UNITS[unit]
    if total <= 0:
        raise WhenError("must be longer than zero")
    return int(total)


def parse_when(text: str, tz: ZoneInfo, now: dt.datetime | None = None) -> dt.datetime:
    """A start time as typed, read in ``tz``. Raises WhenError with a hint when it can't be read."""
    now = (now or dt.datetime.now(UTC)).astimezone(tz)
    raw = text
    text = re.sub(r"\s+", " ", text.strip().lower().replace(",", " ")).strip()
    if not text:
        raise WhenError("say when, e.g. `friday 8pm`, `tomorrow 18:30`, `nov 20 7pm` or `in 2h`")
    if text == "now":
        return now.astimezone(UTC).replace(microsecond=0)
    if (m := _IN.match(text)):
        return (now + dt.timedelta(seconds=parse_span(m.group(1)))).astimezone(UTC).replace(second=0, microsecond=0)

    # glue "8 pm" -> "8pm", drop filler words
    text = re.sub(r"(\d)\s+(am|pm|a\.m\.|p\.m\.)\b", r"\1\2", text).replace("a.m.", "am").replace("p.m.", "pm")
    toks = [t for t in text.split(" ") if t not in ("at", "on", "the", "@", "this")]

    date: dt.date | None = None
    clock: tuple[int, int] | None = None
    year_given = False
    nxt = False
    i = 0
    while i < len(toks):
        tok = toks[i]
        if tok == "next":
            nxt = True
        elif tok in ("today",):
            date = now.date()
        elif tok == "tonight":
            date = now.date()
            clock = clock or (20, 0)
        elif tok == "tomorrow" or tok == "tmrw":
            date = now.date() + dt.timedelta(days=1)
        elif tok in ("morning", "afternoon", "evening"):
            clock = clock or {"morning": (9, 0), "afternoon": (15, 0), "evening": (19, 0)}[tok]
        elif tok in WEEKDAYS:
            ahead = (WEEKDAYS[tok] - now.weekday()) % 7
            if nxt and ahead == 0:
                ahead = 7
            date = now.date() + dt.timedelta(days=ahead)
        elif (m := _ISO.match(tok)):
            if m.group(4):
                clock = (int(m.group(4)), int(m.group(5)))
            date = _date(int(m.group(1)), int(m.group(2)), int(m.group(3)), raw)
            year_given = True
        elif (m := _SLASH.match(tok)):
            y = m.group(3)
            year = (int(y) + (2000 if len(y) == 2 else 0)) if y else now.year
            date = _date(year, int(m.group(1)), int(m.group(2)), raw)
            year_given = bool(y)
        elif tok in MONTHS:
            month = MONTHS[tok]
            day = None
            if i + 1 < len(toks) and re.fullmatch(r"\d{1,2}(st|nd|rd|th)?", toks[i + 1]):
                day = int(re.match(r"\d+", toks[i + 1]).group())
                i += 1
            elif i > 0 and re.fullmatch(r"\d{1,2}(st|nd|rd|th)?", toks[i - 1]) and date is None:
                day = int(re.match(r"\d+", toks[i - 1]).group())
                clock = None if clock == _time(toks[i - 1]) else clock
            if day is None:
                raise WhenError(f"which day of {tok}? e.g. `{tok} 20 7pm`")
            year = now.year
            if i + 1 < len(toks) and re.fullmatch(r"\d{4}", toks[i + 1]):
                year, year_given = int(toks[i + 1]), True
                i += 1
            date = _date(year, month, day, raw)
        elif re.fullmatch(r"\d{1,2}(st|nd|rd|th)", tok):
            pass   # handled by the month that follows ("20th nov")
        elif (c := _time(tok)) is not None:
            # a bare number right before a month name is a day, not a time ("20 nov")
            if i + 1 < len(toks) and toks[i + 1] in MONTHS and re.fullmatch(r"\d{1,2}", tok):
                pass
            else:
                clock = c
        else:
            raise WhenError(f"I don't understand {tok!r} in {raw!r}. Try `friday 8pm`, `tomorrow 18:30`, "
                            "`nov 20 7pm`, `2026-11-20 20:00` or `in 2h`.")
        i += 1

    if date is None and clock is None:
        raise WhenError(f"can't find a date or time in {raw!r}")
    if date is None:
        assert clock is not None
        date = now.date()
        if (clock[0], clock[1]) <= (now.hour, now.minute):
            date += dt.timedelta(days=1)          # "8pm" after 8pm means tomorrow
    if clock is None:
        clock = (12, 0)                            # a date alone means midday
    when = dt.datetime(date.year, date.month, date.day, clock[0], clock[1], tzinfo=tz)
    if when < now - dt.timedelta(minutes=1):
        if not year_given and date.year == now.year and (date.month, date.day) < (now.month, now.day):
            when = when.replace(year=now.year + 1)  # "jan 3" in December means next year
        elif date == now.date() and any(t in WEEKDAYS for t in toks):
            when += dt.timedelta(days=7)           # "friday 8pm" late on a Friday means next week
    return _real(when, tz).astimezone(UTC)


def _date(y: int, m: int, d: int, raw: str) -> dt.date:
    try:
        return dt.date(y, m, d)
    except ValueError:
        raise WhenError(f"{raw!r} isn't a real date") from None


def _real(local: dt.datetime, tz: ZoneInfo) -> dt.datetime:
    """Normalise a wall-clock time that falls in a DST gap (2:30 on spring-forward day -> 3:30)."""
    return local.astimezone(UTC).astimezone(tz)


def next_occurrence(start: dt.datetime, repeat: str, tz: ZoneInfo) -> dt.datetime:
    """The next start of a repeating event, keeping the same local wall-clock time across DST changes."""
    local = start.astimezone(tz)
    naive = local.replace(tzinfo=None)
    if repeat == "daily":
        naive += dt.timedelta(days=1)
    elif repeat == "weekly":
        naive += dt.timedelta(days=7)
    elif repeat == "biweekly":
        naive += dt.timedelta(days=14)
    elif repeat == "monthly":
        y, m = (naive.year + 1, 1) if naive.month == 12 else (naive.year, naive.month + 1)
        naive = naive.replace(year=y, month=m, day=min(naive.day, calendar.monthrange(y, m)[1]))
    else:
        raise WhenError(f"{repeat!r} doesn't repeat")
    return _real(naive.replace(tzinfo=tz), tz).astimezone(UTC)


def fmt_when(start: dt.datetime, end: dt.datetime | None, tz: ZoneInfo) -> str:
    """``Fri, Nov 20 · 8:00 PM – 10:00 PM EST`` (the end shows its date only when it's another day)."""
    s = start.astimezone(tz)
    out = f"{s:%a, %b} {s.day} · {_clock(s)}"
    if end is not None:
        e = end.astimezone(tz)
        out += f" – {_clock(e)}" if e.date() == s.date() else f" – {e:%a, %b} {e.day} · {_clock(e)}"
    return f"{out} {s.tzname()}"


def _clock(t: dt.datetime) -> str:
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def fmt_relative(when: dt.datetime, now: dt.datetime | None = None) -> str:
    """``in 3 days``, ``in 2h 15m``, ``5m ago``."""
    now = now or dt.datetime.now(UTC)
    secs = int((when - now).total_seconds())
    past, secs = secs < 0, abs(secs)
    if secs < 60:
        text = "under a minute"
    elif secs < 3600:
        text = f"{secs // 60}m"
    elif secs < 86400:
        h, m = divmod(secs // 60, 60)
        text = f"{h}h {m}m" if m else f"{h}h"
    else:
        d, rest = divmod(secs, 86400)
        text = f"{d} day{'s' if d != 1 else ''}" + (f" {rest // 3600}h" if d < 3 and rest >= 3600 else "")
    return f"{text} ago" if past else f"in {text}"


def fmt_span(seconds: int) -> str:
    h, m = divmod(int(seconds) // 60, 60)
    if h and m:
        return f"{h}h {m}m"
    return f"{h}h" if h else f"{m}m"

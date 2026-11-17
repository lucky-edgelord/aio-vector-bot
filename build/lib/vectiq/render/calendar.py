"""The month calendar image (``!calendar``) and a single event card."""

from __future__ import annotations

import calendar as pycal
import datetime as dt
from dataclasses import dataclass

from PIL import Image, ImageDraw

from .cards import ACCENT, ACCENT_DK, BG, CARD, CARD_HI, DIM, LINE, TEXT, TRACK, finish, fit, motif, rounded, text

MUTED = (62, 64, 70)
TODAY = (18, 40, 32)


@dataclass
class Slot:
    """One event occurrence on one local day."""
    day: dt.date
    time: str             # "8:00 PM" (local), "" for an all-day continuation
    title: str
    going: int = 0
    live: bool = False


def calendar_card(year: int, month: int, slots: list[Slot], *, today: dt.date | None = None,
                  community: str = "", tz_label: str = "", first_weekday: int = 0) -> bytes:
    """A month grid in Vector's colours: up to three events per day (two and "+N more" when busier)."""
    W, HEAD, PAD = 1120, 150, 28
    cols = 7
    cal = pycal.Calendar(first_weekday)
    weeks = cal.monthdatescalendar(year, month)
    CELL_W = (W - 2 * PAD) / cols
    CELL_H = 132
    H = HEAD + 40 + len(weeks) * CELL_H + 60
    canvas = Image.new("RGB", (int(W * 2), int(H * 2)), BG)
    d = ImageDraw.Draw(canvas)

    motif(d, 40, 38)
    text(d, (40, 70), f"{pycal.month_name[month].upper()} {year}", "bold", 38, TEXT)
    count = len({(s.day, s.time, s.title) for s in slots if s.day.month == month})
    text(d, (40, 116), f"{community or 'Vectiq'}  ·  {count} event{'s' if count != 1 else ''}", "regular", 20, DIM)
    if tz_label:
        rounded(d, (W - 300, 52, W - 40, 92), 20, fill=CARD, outline=LINE)
        text(d, (W - 170, 72), fit(d, tz_label, "semi", 15, 240), "semi", 15, DIM, "mm")

    names = [pycal.day_abbr[(first_weekday + i) % 7].upper() for i in range(7)]
    for i, n in enumerate(names):
        text(d, (PAD + CELL_W * i + CELL_W / 2, HEAD + 16), n, "semi", 15, DIM, "mm")

    by_day: dict[dt.date, list[Slot]] = {}
    for s_ in sorted(slots, key=lambda x: (x.day, x.time == "", _sort_time(x.time))):
        by_day.setdefault(s_.day, []).append(s_)

    top = HEAD + 40
    for w, week in enumerate(weeks):
        for c, day in enumerate(week):
            x0, y0 = PAD + CELL_W * c + 4, top + CELL_H * w + 4
            x1, y1 = x0 + CELL_W - 8, y0 + CELL_H - 8
            inside = day.month == month
            is_today = day == today
            rounded(d, (x0, y0, x1, y1), 16, fill=TODAY if is_today else (CARD if inside else BG),
                    outline=ACCENT_DK if is_today else (LINE if inside else (24, 24, 27)), width=2 if is_today else 1)
            if is_today:
                d.ellipse([int((x0 + 10) * 2), int((y0 + 8) * 2), int((x0 + 40) * 2), int((y0 + 38) * 2)], fill=ACCENT)
                text(d, (x0 + 25, y0 + 23), str(day.day), "bold", 16, (12, 12, 13), "mm")
            else:
                text(d, (x0 + 14, y0 + 12), str(day.day), "semi", 16, TEXT if inside else MUTED)
            items = by_day.get(day, []) if inside else []
            shown = items if len(items) <= 3 else items[:2]
            for k, ev in enumerate(shown):
                cy = y0 + 44 + k * 26
                fill = ACCENT if ev.live else (CARD_HI if inside else TRACK)
                rounded(d, (x0 + 8, cy, x1 - 8, cy + 22), 8, fill=fill, outline=None if ev.live else ACCENT_DK)
                label = f"{_short(ev.time)} {ev.title}".strip()
                text(d, (x0 + 15, cy + 11), fit(d, label, "semi", 13, int(CELL_W - 34)), "semi", 13,
                     (12, 12, 13) if ev.live else TEXT, "lm")
            if len(items) > 3:
                text(d, (x0 + 15, y0 + 44 + 2 * 26 + 11), f"+{len(items) - 2} more", "semi", 13, ACCENT, "lm")

    text(d, (W / 2, H - 30), "Vectiq  ·  !event list for details  ·  react on an event post to RSVP",
         "regular", 15, (90, 92, 98), "mm")
    return finish(canvas, W, H)


def _sort_time(t: str) -> tuple[int, int]:
    try:
        hm, ap = t.split(" ")
        h, m = (int(x) for x in hm.split(":"))
        return (h % 12 + (12 if ap == "PM" else 0), m)
    except ValueError:
        return (0, 0)


def _short(t: str) -> str:
    """``8:00 PM`` -> ``8p``, ``8:30 AM`` -> ``8:30a``."""
    if not t:
        return ""
    hm, ap = t.split(" ")
    h, m = hm.split(":")
    return f"{h}{'' if m == '00' else ':' + m}{ap[0].lower()}"


def event_card(title: str, day: str, time_range: str, *, location: str = "", host: str = "", community: str = "",
               repeat: str = "", tz_label: str = "") -> bytes:
    """The banner posted above an event: big date tile, title, time, place."""
    title, location, host, community = (plain(v) for v in (title, location, host, community))
    W, H = 1120, 420
    canvas = Image.new("RGB", (int(W * 2), int(H * 2)), BG)
    d = ImageDraw.Draw(canvas)
    rounded(d, (24, 24, W - 24, H - 24), 34, fill=CARD, outline=LINE)
    # date tile: "NOV" / "20" / "FRI"
    mon, num, wd = (day.split(" ") + ["", "", ""])[:3]
    rounded(d, (64, 72, 304, 348), 30, fill=TODAY, outline=ACCENT_DK, width=2)
    rounded(d, (64, 72, 304, 140), 30, fill=ACCENT)
    d.rectangle([int(64 * 2), int(110 * 2), int(304 * 2), int(140 * 2)], fill=ACCENT)
    text(d, (184, 106), mon.upper(), "bold", 30, (12, 12, 13), "mm")
    text(d, (184, 228), num, "bold", 110, TEXT, "mm")
    text(d, (184, 316), wd.upper(), "semi", 24, ACCENT, "mm")
    x = 348
    motif(d, x, 74, size=16)
    text(d, (x, 104), fit(d, (community or "Vectiq").upper() + "  ·  EVENT", "semi", 18, W - x - 70), "semi", 18, DIM)
    words, lines, cur = title.split(), [], ""
    for w in words:                                   # wrap the title over at most two lines
        trial = f"{cur} {w}".strip()
        if d.textlength(trial, font=_f("bold", 50)) <= (W - x - 70) * 2 or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    if len(lines) > 2:
        lines = [lines[0], fit(d, " ".join(lines[1:]), "bold", 50, W - x - 70)]
    y = 140
    for ln in lines:
        text(d, (x, y), fit(d, ln, "bold", 50, W - x - 70), "bold", 50, TEXT)
        y += 62
    y += 10
    text(d, (x, y), time_range, "semi", 26, ACCENT)
    y += 40
    extra = [p for p in (location and f"at {location}", repeat and repeat != "none" and f"repeats {repeat}",
                         host and f"hosted by {host}") if p]
    if extra:
        text(d, (x, y), fit(d, "  ·  ".join(extra), "regular", 22, W - x - 70), "regular", 22, DIM)
    if tz_label:
        text(d, (x, H - 78), fit(d, f"Times in {tz_label}  ·  react on the post below to RSVP", "regular", 16,
                                 W - x - 70), "regular", 16, (90, 92, 98))
    return finish(canvas, W, H)


def plain(value: str) -> str:
    """Drop emoji and box-drawing decorations the bundled font can't draw ("🤖┊Bot Test" -> "Bot Test")."""
    out = "".join(c for c in str(value) if ord(c) < 0x2190 or 0x2010 <= ord(c) <= 0x2027 or c in "€£¥")
    return " ".join(out.split())


def _f(weight: str, size: int):
    from .cards import font
    return font(weight, size)

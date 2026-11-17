"""iCalendar (.ics) files, so members can add events to Google Calendar, Apple Calendar or Outlook."""

from __future__ import annotations

import datetime as dt

RRULE = {"daily": "FREQ=DAILY", "weekly": "FREQ=WEEKLY", "biweekly": "FREQ=WEEKLY;INTERVAL=2", "monthly": "FREQ=MONTHLY"}


def _esc(text: str) -> str:
    return (str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _stamp(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fold(line: str) -> list[str]:
    """RFC 5545 lines are at most 75 octets; longer ones continue on lines starting with a space."""
    out, raw = [], line.encode()
    while len(raw) > 75:
        cut = 75 if not out else 74
        while cut and (raw[cut] & 0xC0) == 0x80:      # don't split a UTF-8 character
            cut -= 1
        out.append(raw[:cut].decode())
        raw = raw[cut:]
    out.append(raw.decode())
    return [out[0]] + [" " + x for x in out[1:]]


def vevent(event, *, community: str = "", host: str = "vectiq") -> list[str]:
    lines = ["BEGIN:VEVENT", f"UID:event-{event.id}@{host}", f"DTSTAMP:{_stamp(event.created_at or event.starts_at)}",
             f"DTSTART:{_stamp(event.starts_at)}", f"DTEND:{_stamp(event.ends_at)}", f"SUMMARY:{_esc(event.title)}"]
    desc = event.description + (f"\n\n{community}" if community else "")
    if desc.strip():
        lines.append(f"DESCRIPTION:{_esc(desc.strip())}")
    if event.location:
        lines.append(f"LOCATION:{_esc(event.location)}")
    if event.repeat in RRULE:
        lines.append(f"RRULE:{RRULE[event.repeat]}")
    if event.status == "cancelled":
        lines.append("STATUS:CANCELLED")
    for minutes in event.remind or []:
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(event.title)}",
                  f"TRIGGER:-PT{int(minutes)}M", "END:VALARM"]
    lines.append("END:VEVENT")
    return lines


def calendar_file(events, *, name: str = "Vectiq events", community: str = "") -> bytes:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Vectiq//Events//EN", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{_esc(name)}"]
    for e in events:
        lines += vevent(e, community=community)
    lines.append("END:VCALENDAR")
    return ("\r\n".join(x for line in lines for x in _fold(line)) + "\r\n").encode()

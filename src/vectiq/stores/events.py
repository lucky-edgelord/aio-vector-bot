"""Scheduled events, RSVPs and which reminders went out."""

from __future__ import annotations

import datetime as dt
import json
import time
from dataclasses import dataclass, field

from ..db import Database

UTC = dt.timezone.utc
EDITABLE = ("title", "description", "location", "image_path", "image_message_id", "footer_message_id",
 "starts_at", "ends_at", "tz", "repeat", "remind",
            "capacity", "role_id", "channel_id")
RSVP = ("going", "maybe", "no")


@dataclass
class Event:
    id: int
    guild_id: str
    channel_id: str
    message_id: str | None
    image_message_id: str | None
    footer_message_id: str | None
    creator_id: str
    title: str
    description: str
    location: str
    image_path: str
    starts_at: int
    ends_at: int
    tz: str
    repeat: str
    remind: list[int] = field(default_factory=list)
    capacity: int = 0
    role_id: str = ""
    status: str = "scheduled"
    created_at: int = 0

    @property
    def start(self) -> dt.datetime:
        return dt.datetime.fromtimestamp(self.starts_at, UTC)

    @property
    def end(self) -> dt.datetime:
        return dt.datetime.fromtimestamp(self.ends_at, UTC)

    @property
    def open(self) -> bool:
        return self.status in ("scheduled", "live")


@dataclass
class Attendees:
    going: list[str]          # in RSVP order, capped at capacity
    waitlist: list[str]       # said "going" after it was full
    maybe: list[str]
    no: list[str]

    def status_of(self, user_id: str) -> str | None:
        for name in ("going", "waitlist", "maybe", "no"):
            if user_id in getattr(self, name):
                return name
        return None


def _e(r) -> Event:
    d = dict(r)
    d["remind"] = json.loads(d.get("remind") or "[]")
    return Event(**d)


class EventStore:
    def __init__(self, db: Database):
        self.db = db

    async def create(self, guild_id: str, channel_id: str, creator_id: str, title: str, starts_at: int,
                     ends_at: int, *, tz: str = "UTC", description: str = "", location: str = "",
                     image_path: str = "", repeat: str = "none", remind: list[int] | None = None,
                     capacity: int = 0, role_id: str = "") -> Event:
        eid = await self.db.insert(
            "INSERT INTO events (guild_id,channel_id,creator_id,title,description,location,image_path,starts_at,"
            "ends_at,tz,repeat,remind,capacity,role_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (guild_id, channel_id, creator_id, title, description, location, image_path, int(starts_at),
             int(ends_at), tz, repeat, json.dumps(sorted(set(remind or []), reverse=True)), capacity, role_id,
             int(time.time())))
        return await self.get(eid)

    async def get(self, event_id: int) -> Event | None:
        r = await self.db.one("SELECT * FROM events WHERE id=?", (event_id,))
        return _e(r) if r else None

    async def by_message(self, message_id: str) -> Event | None:
        r = await self.db.one("SELECT * FROM events WHERE message_id=? OR footer_message_id=?", (message_id, message_id))
        return _e(r) if r else None

    async def update(self, event_id: int, **changes) -> Event | None:
        bad = set(changes) - set(EDITABLE) - {"message_id", "status"}
        if bad:
            raise ValueError(f"can't change {', '.join(sorted(bad))}")
        if "remind" in changes:
            changes["remind"] = json.dumps(sorted(set(int(x) for x in changes["remind"]), reverse=True))
        if changes:
            cols = ", ".join(f"{k}=?" for k in changes)
            await self.db.execute(f"UPDATE events SET {cols} WHERE id=?", (*changes.values(), event_id))  # noqa: S608
        return await self.get(event_id)

    async def delete(self, event_id: int) -> bool:
        return bool(await self.db.execute("DELETE FROM events WHERE id=?", (event_id,)))

    async def upcoming(self, guild_id: str, limit: int = 25) -> list[Event]:
        rows = await self.db.all("SELECT * FROM events WHERE guild_id=? AND status IN ('scheduled','live') "
                                 "ORDER BY starts_at LIMIT ?", (guild_id, limit))
        return [_e(r) for r in rows]

    async def between(self, guild_id: str, start: int, end: int) -> list[Event]:
        """Events touching [start, end), plus every open repeating event (the caller expands those)."""
        rows = await self.db.all(
            "SELECT * FROM events WHERE guild_id=? AND status!='cancelled' AND "
            "((starts_at<? AND ends_at>=?) OR (repeat!='none' AND status IN ('scheduled','live') AND starts_at<?)) "
            "ORDER BY starts_at", (guild_id, end, start, end))
        return [_e(r) for r in rows]

    async def recent(self, guild_id: str, limit: int = 20) -> list[Event]:
        rows = await self.db.all("SELECT * FROM events WHERE guild_id=? AND status IN ('ended','cancelled') "
                                 "ORDER BY starts_at DESC LIMIT ?", (guild_id, limit))
        return [_e(r) for r in rows]

    async def open_events(self) -> list[Event]:
        rows = await self.db.all("SELECT * FROM events WHERE status IN ('scheduled','live') ORDER BY starts_at")
        return [_e(r) for r in rows]

    # -- RSVPs ------------------------------------------------------------------------------

    async def rsvp(self, event_id: int, user_id: str, status: str | None) -> None:
        """Set someone's answer. ``None`` clears it. Changing going -> going keeps their place in line."""
        if status is None:
            await self.db.execute("DELETE FROM event_rsvps WHERE event_id=? AND user_id=?", (event_id, user_id))
            return
        if status not in RSVP:
            raise ValueError(f"RSVP must be one of {', '.join(RSVP)}")
        await self.db.execute(
            "INSERT INTO event_rsvps (event_id,user_id,status,at) VALUES (?,?,?,?) ON CONFLICT(event_id,user_id) "
            "DO UPDATE SET at=CASE WHEN status=excluded.status THEN at ELSE excluded.at END, status=excluded.status",
            (event_id, user_id, status, time.time()))

    async def attendees(self, event: Event) -> Attendees:
        rows = await self.db.all("SELECT user_id, status FROM event_rsvps WHERE event_id=? ORDER BY at, rowid",
                                 (event.id,))
        going = [r["user_id"] for r in rows if r["status"] == "going"]
        cap = event.capacity or len(going)
        return Attendees(going=going[:cap], waitlist=going[cap:],
                         maybe=[r["user_id"] for r in rows if r["status"] == "maybe"],
                         no=[r["user_id"] for r in rows if r["status"] == "no"])

    async def clear_rsvps(self, event_id: int) -> None:
        await self.db.execute("DELETE FROM event_rsvps WHERE event_id=?", (event_id,))

    async def counts(self, event_ids: list[int]) -> dict[int, dict[str, int]]:
        if not event_ids:
            return {}
        marks = ",".join("?" * len(event_ids))
        rows = await self.db.all(f"SELECT event_id, status, COUNT(*) AS n FROM event_rsvps WHERE event_id IN ({marks}) "  # noqa: S608
                                 "GROUP BY event_id, status", tuple(event_ids))
        out: dict[int, dict[str, int]] = {i: {"going": 0, "maybe": 0, "no": 0} for i in event_ids}
        for r in rows:
            out[r["event_id"]][r["status"]] = r["n"]
        return out

    # -- reminders --------------------------------------------------------------------------

    async def mark_reminded(self, event_id: int, starts_at: int, minutes: int) -> bool:
        """True the first time only, so a reminder is never sent twice (even across restarts)."""
        return bool(await self.db.execute(
            "INSERT OR IGNORE INTO event_reminders (event_id,starts_at,minutes) VALUES (?,?,?)",
            (event_id, starts_at, minutes)))

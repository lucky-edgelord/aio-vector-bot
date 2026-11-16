from __future__ import annotations

import time
from dataclasses import dataclass

from ..db import Database


@dataclass
class Ticket:
    id: int
    guild_id: str
    channel_id: str | None
    user_id: str
    subject: str
    status: str
    claimed_by: str | None
    created_at: int
    closed_at: int | None


def _t(r) -> Ticket:
    return Ticket(r["id"], r["guild_id"], r["channel_id"], r["user_id"], r["subject"], r["status"],
                  r["claimed_by"], r["created_at"], r["closed_at"])


class TicketStore:
    def __init__(self, db: Database):
        self.db = db

    async def open_count(self, guild_id: str, user_id: str) -> int:
        return await self.db.scalar("SELECT COUNT(*) FROM tickets WHERE guild_id=? AND user_id=? AND status='open'",
                                    (guild_id, user_id), 0)

    async def create(self, guild_id: str, user_id: str, subject: str) -> Ticket:
        now = int(time.time())
        tid = await self.db.insert("INSERT INTO tickets (guild_id,user_id,subject,created_at) VALUES (?,?,?,?)",
                                   (guild_id, user_id, subject, now))
        return Ticket(tid, guild_id, None, user_id, subject, "open", None, now, None)

    async def set_channel(self, ticket_id: int, channel_id: str) -> None:
        await self.db.execute("UPDATE tickets SET channel_id=? WHERE id=?", (channel_id, ticket_id))

    async def get(self, ticket_id: int) -> Ticket | None:
        r = await self.db.one("SELECT * FROM tickets WHERE id=?", (ticket_id,))
        return _t(r) if r else None

    async def by_channel(self, channel_id: str) -> Ticket | None:
        r = await self.db.one("SELECT * FROM tickets WHERE channel_id=?", (channel_id,))
        return _t(r) if r else None

    async def claim(self, ticket_id: int, staff_id: str) -> bool:
        return bool(await self.db.execute(
            "UPDATE tickets SET claimed_by=? WHERE id=? AND status='open' AND claimed_by IS NULL", (staff_id, ticket_id)))

    async def close(self, ticket_id: int, closer: str) -> bool:
        return bool(await self.db.execute(
            "UPDATE tickets SET status='closed', closed_at=?, closed_by=? WHERE id=? AND status='open'",
            (int(time.time()), closer, ticket_id)))

    async def log(self, ticket_id: int, author_id: str, content: str) -> None:
        await self.db.execute("INSERT INTO ticket_messages (ticket_id,author_id,content,sent_at) VALUES (?,?,?,?)",
                              (ticket_id, author_id, content, int(time.time())))

    async def transcript(self, ticket_id: int) -> list:
        return await self.db.all("SELECT author_id, content, sent_at FROM ticket_messages WHERE ticket_id=? ORDER BY id",
                                 (ticket_id,))

    async def open_tickets(self, guild_id: str) -> list[Ticket]:
        rows = await self.db.all("SELECT * FROM tickets WHERE guild_id=? AND status='open' ORDER BY id", (guild_id,))
        return [_t(r) for r in rows]

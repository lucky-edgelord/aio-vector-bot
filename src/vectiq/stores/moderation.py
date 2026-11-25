from __future__ import annotations

import time
from dataclasses import dataclass

from ..db import Database


@dataclass
class Case:
    id: int
    guild_id: str
    user_id: str
    moderator: str
    action: str
    reason: str
    created_at: int
    expires_at: int | None
    active: bool


def _case(r) -> Case:
    return Case(r["id"], r["guild_id"], r["user_id"], r["moderator"], r["action"], r["reason"],
                r["created_at"], r["expires_at"], bool(r["active"]))


class ModerationStore:
    def __init__(self, db: Database):
        self.db = db

    async def add(self, guild_id: str, user_id: str, moderator: str, action: str, reason: str = "",
                  *, expires_at: int | None = None) -> Case:
        now = int(time.time())
        cid = await self.db.insert(
            "INSERT INTO mod_cases (guild_id,user_id,moderator,action,reason,created_at,expires_at)"
            " VALUES (?,?,?,?,?,?,?)", (guild_id, user_id, moderator, action, reason, now, expires_at))
        return Case(cid, guild_id, user_id, moderator, action, reason, now, expires_at, True)

    async def get(self, guild_id: str, case_id: int) -> Case | None:
        r = await self.db.one("SELECT * FROM mod_cases WHERE guild_id=? AND id=?", (guild_id, case_id))
        return _case(r) if r else None

    async def for_user(self, guild_id: str, user_id: str, *, action: str | None = None,
                       active_only: bool = False) -> list[Case]:
        sql, args = "SELECT * FROM mod_cases WHERE guild_id=? AND user_id=?", [guild_id, user_id]
        if action:
            sql += " AND action=?"
            args.append(action)
        if active_only:
            sql += " AND active=1"
        rows = await self.db.all(sql + " ORDER BY id DESC", args)
        return [_case(r) for r in rows]

    async def warnings(self, guild_id: str, user_id: str) -> list[Case]:
        return await self.for_user(guild_id, user_id, action="warn", active_only=True)

    async def deactivate(self, guild_id: str, case_id: int) -> bool:
        return bool(await self.db.execute(
            "UPDATE mod_cases SET active=0 WHERE guild_id=? AND id=? AND active=1", (guild_id, case_id)))

    async def clear_warnings(self, guild_id: str, user_id: str) -> int:
        return await self.db.execute(
            "UPDATE mod_cases SET active=0 WHERE guild_id=? AND user_id=? AND action='warn' AND active=1",
            (guild_id, user_id))

    async def due_expiries(self, now: int | None = None) -> list[Case]:
        rows = await self.db.all(
            "SELECT * FROM mod_cases WHERE active=1 AND expires_at IS NOT NULL AND expires_at<=?",
            (now or int(time.time()),))
        return [_case(r) for r in rows]

    async def recent(self, guild_id: str, limit: int = 10, action: str | None = None) -> list[Case]:
        sql, args = "SELECT * FROM mod_cases WHERE guild_id=?", [guild_id]
        if action:
            sql += " AND action=?"
            args.append(action)
        rows = await self.db.all(sql + " ORDER BY id DESC LIMIT ?", (*args, limit))
        return [_case(r) for r in rows]

    async def warning_counts(self, guild_id: str) -> dict[str, int]:
        rows = await self.db.all("SELECT user_id, COUNT(*) n FROM mod_cases WHERE guild_id=? AND action='warn' AND active=1"
                                 " GROUP BY user_id", (guild_id,))
        return {r["user_id"]: r["n"] for r in rows}


@dataclass
class Appeal:
    id: int
    guild_id: str
    user_id: str
    text: str
    status: str          # drafting | pending | approved | denied | cancelled
    channel_id: str
    message_id: str
    created_at: int
    decided_at: int | None


def _appeal(r) -> Appeal:
    return Appeal(r["id"], r["guild_id"], r["user_id"], r["text"], r["status"], r["channel_id"], r["message_id"],
                  r["created_at"], r["decided_at"])


class AppealStore:
    def __init__(self, db: Database):
        self.db = db

    async def start(self, guild_id: str, user_id: str) -> Appeal:
        """Begin a draft. An older unfinished draft of theirs is cancelled."""
        await self.db.execute("UPDATE ban_appeals SET status='cancelled' WHERE user_id=? AND status='drafting'",
                              (user_id,))
        now = int(time.time())
        aid = await self.db.insert("INSERT INTO ban_appeals (guild_id,user_id,status,created_at)"
                                   " VALUES (?,?,'drafting',?)", (guild_id, user_id, now))
        return Appeal(aid, guild_id, user_id, "", "drafting", "", "", now, None)

    async def get(self, appeal_id: int) -> Appeal | None:
        r = await self.db.one("SELECT * FROM ban_appeals WHERE id=?", (appeal_id,))
        return _appeal(r) if r else None

    async def draft_of(self, user_id: str) -> Appeal | None:
        r = await self.db.one("SELECT * FROM ban_appeals WHERE user_id=? AND status='drafting'"
                              " ORDER BY id DESC LIMIT 1", (user_id,))
        return _appeal(r) if r else None

    async def by_message(self, message_id: str) -> Appeal | None:
        r = await self.db.one("SELECT * FROM ban_appeals WHERE message_id=? AND status='pending'", (message_id,))
        return _appeal(r) if r else None

    async def latest(self, guild_id: str, user_id: str, *statuses: str) -> Appeal | None:
        marks = ",".join("?" * len(statuses))
        r = await self.db.one(f"SELECT * FROM ban_appeals WHERE guild_id=? AND user_id=? AND status IN ({marks})"
                              " ORDER BY id DESC LIMIT 1", (guild_id, user_id, *statuses))
        return _appeal(r) if r else None

    async def pending(self, guild_id: str) -> list[Appeal]:
        rows = await self.db.all("SELECT * FROM ban_appeals WHERE guild_id=? AND status='pending' ORDER BY id",
                                 (guild_id,))
        return [_appeal(r) for r in rows]

    async def submit(self, appeal_id: int, text: str, channel_id: str, message_id: str) -> None:
        await self.db.execute("UPDATE ban_appeals SET text=?, status='pending', channel_id=?, message_id=?"
                              " WHERE id=?", (text, channel_id, message_id, appeal_id))

    async def vote(self, appeal_id: int, voter_id: str, approve: bool) -> tuple[int, int]:
        """Record (or change) one moderator's vote. Returns (approvals, denials)."""
        await self.db.execute("INSERT INTO ban_appeal_votes (appeal_id,voter_id,approve,at) VALUES (?,?,?,?)"
                              " ON CONFLICT(appeal_id,voter_id) DO UPDATE SET approve=excluded.approve, at=excluded.at",
                              (appeal_id, voter_id, int(approve), int(time.time())))
        return await self.tally(appeal_id)

    async def tally(self, appeal_id: int) -> tuple[int, int]:
        rows = await self.db.all("SELECT approve, COUNT(*) AS n FROM ban_appeal_votes WHERE appeal_id=?"
                                 " GROUP BY approve", (appeal_id,))
        n = {int(r["approve"]): r["n"] for r in rows}
        return n.get(1, 0), n.get(0, 0)

    async def decide(self, appeal_id: int, status: str) -> bool:
        return bool(await self.db.execute("UPDATE ban_appeals SET status=?, decided_at=? WHERE id=? AND status='pending'",
                                          (status, int(time.time()), appeal_id)))

    async def cancel(self, appeal_id: int) -> None:
        await self.db.execute("UPDATE ban_appeals SET status='cancelled' WHERE id=? AND status='drafting'",
                              (appeal_id,))

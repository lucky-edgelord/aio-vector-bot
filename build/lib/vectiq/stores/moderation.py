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

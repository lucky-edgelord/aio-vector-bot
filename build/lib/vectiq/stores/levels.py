from __future__ import annotations

import random
import time
from dataclasses import dataclass

from ..db import Database


def xp_for_level(level: int) -> int:
    """Total XP needed to *reach* ``level`` (MEE6's curve: 5n^2 + 50n + 100 per step)."""
    return sum(5 * n * n + 50 * n + 100 for n in range(level))


def level_for_xp(xp: int) -> int:
    level = 0
    while xp >= xp_for_level(level + 1):
        level += 1
    return level


@dataclass
class Rank:
    user_id: str
    xp: int
    level: int
    messages: int
    position: int = 0

    @property
    def into_level(self) -> int:
        return self.xp - xp_for_level(self.level)

    @property
    def level_span(self) -> int:
        return xp_for_level(self.level + 1) - xp_for_level(self.level)


class LevelStore:
    def __init__(self, db: Database):
        self.db = db

    async def award(self, guild_id: str, user_id: str, *, xp_min: int, xp_max: int, cooldown: float,
                    now: float | None = None, rng: random.Random | None = None):
        """Give message XP unless the user is on cooldown.

        Returns ``(rank, leveled_up)`` or ``None`` when on cooldown.
        """
        now = time.time() if now is None else now
        amount = (rng or random).randint(xp_min, xp_max)
        async with self.db.transaction() as tx:
            row = await tx.one("SELECT xp, level, messages, last_xp_at FROM levels WHERE guild_id=? AND user_id=?",
                               (guild_id, user_id))
            if row is None:
                await tx.execute("INSERT INTO levels (guild_id,user_id) VALUES (?,?)", (guild_id, user_id))
                xp, level, messages, last = 0, 0, 0, 0.0
            else:
                xp, level, messages, last = row["xp"], row["level"], row["messages"], row["last_xp_at"]
            if now - last < cooldown:
                await tx.execute("UPDATE levels SET messages=messages+1 WHERE guild_id=? AND user_id=?",
                                 (guild_id, user_id))
                return None
            xp += amount
            new_level = level_for_xp(xp)
            await tx.execute("UPDATE levels SET xp=?, level=?, messages=messages+1, last_xp_at=?"
                             " WHERE guild_id=? AND user_id=?", (xp, new_level, now, guild_id, user_id))
        return Rank(user_id, xp, new_level, messages + 1), new_level > level

    async def add_xp(self, guild_id: str, user_id: str, amount: int) -> Rank:
        """Admin grant / removal (never below zero)."""
        async with self.db.transaction() as tx:
            await tx.execute("INSERT OR IGNORE INTO levels (guild_id,user_id) VALUES (?,?)", (guild_id, user_id))
            xp = max(0, (await tx.scalar("SELECT xp FROM levels WHERE guild_id=? AND user_id=?",
                                         (guild_id, user_id), 0)) + amount)
            level = level_for_xp(xp)
            await tx.execute("UPDATE levels SET xp=?, level=? WHERE guild_id=? AND user_id=?",
                             (xp, level, guild_id, user_id))
        return await self.rank(guild_id, user_id)

    async def rank(self, guild_id: str, user_id: str) -> Rank:
        r = await self.db.one("SELECT xp, level, messages FROM levels WHERE guild_id=? AND user_id=?",
                              (guild_id, user_id))
        xp, level, messages = (r["xp"], r["level"], r["messages"]) if r else (0, 0, 0)
        ahead = await self.db.scalar("SELECT COUNT(*) FROM levels WHERE guild_id=? AND xp>?", (guild_id, xp), 0)
        return Rank(user_id, xp, level, messages, ahead + 1)

    async def leaderboard(self, guild_id: str, limit: int = 10, offset: int = 0) -> list[Rank]:
        rows = await self.db.all(
            "SELECT user_id, xp, level, messages FROM levels WHERE guild_id=? ORDER BY xp DESC, user_id LIMIT ? OFFSET ?",
            (guild_id, limit, offset))
        return [Rank(r["user_id"], r["xp"], r["level"], r["messages"], offset + i + 1) for i, r in enumerate(rows)]

    async def count(self, guild_id: str) -> int:
        return await self.db.scalar("SELECT COUNT(*) FROM levels WHERE guild_id=?", (guild_id,), 0)

    async def many(self, guild_id: str, user_ids: list[str]) -> dict[str, tuple[int, int]]:
        """{user_id: (xp, level)} for the given members (missing = never chatted)."""
        out: dict[str, tuple[int, int]] = {}
        for i in range(0, len(user_ids), 500):
            chunk = user_ids[i:i + 500]
            rows = await self.db.all(f"SELECT user_id, xp, level FROM levels WHERE guild_id=? AND user_id IN "
                                     f"({','.join('?' * len(chunk))})", (guild_id, *chunk))
            out.update({r["user_id"]: (r["xp"], r["level"]) for r in rows})
        return out

    async def reset(self, guild_id: str, user_id: str) -> None:
        await self.db.execute("DELETE FROM levels WHERE guild_id=? AND user_id=?", (guild_id, user_id))

    async def set_reward(self, guild_id: str, level: int, role_id: str) -> None:
        await self.db.execute("INSERT INTO level_rewards (guild_id,level,role_id) VALUES (?,?,?)"
                              " ON CONFLICT(guild_id,level) DO UPDATE SET role_id=excluded.role_id",
                              (guild_id, level, role_id))

    async def remove_reward(self, guild_id: str, level: int) -> bool:
        return bool(await self.db.execute("DELETE FROM level_rewards WHERE guild_id=? AND level=?", (guild_id, level)))

    async def rewards(self, guild_id: str) -> dict[int, str]:
        rows = await self.db.all("SELECT level, role_id FROM level_rewards WHERE guild_id=? ORDER BY level", (guild_id,))
        return {r["level"]: r["role_id"] for r in rows}

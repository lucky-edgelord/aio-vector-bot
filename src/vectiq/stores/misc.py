from __future__ import annotations

import json
import random
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from ..db import Database


class SettingsStore:
    """Per-community overrides set at runtime (``!set``); config.yaml supplies the defaults."""

    def __init__(self, db: Database):
        self.db = db

    async def get(self, guild_id: str, key: str, default=None):
        r = await self.db.one("SELECT value FROM guild_settings WHERE guild_id=? AND key=?", (guild_id, key))
        return json.loads(r["value"]) if r else default

    async def set(self, guild_id: str, key: str, value) -> None:
        await self.db.execute("INSERT INTO guild_settings (guild_id,key,value) VALUES (?,?,?)"
                              " ON CONFLICT(guild_id,key) DO UPDATE SET value=excluded.value",
                              (guild_id, key, json.dumps(value)))

    async def unset(self, guild_id: str, key: str) -> None:
        await self.db.execute("DELETE FROM guild_settings WHERE guild_id=? AND key=?", (guild_id, key))

    async def all(self, guild_id: str) -> dict:
        rows = await self.db.all("SELECT key, value FROM guild_settings WHERE guild_id=? ORDER BY key", (guild_id,))
        return {r["key"]: json.loads(r["value"]) for r in rows}


class VerificationStore:
    """Pending member verification challenges (a small arithmetic question)."""

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def make_question(rng: random.Random | None = None) -> tuple[str, str]:
        rng = rng or random.SystemRandom()
        a, b = rng.randint(2, 12), rng.randint(2, 12)
        return f"What is {a} + {b}?", str(a + b)

    async def start(self, guild_id: str, user_id: str) -> str:
        question, answer = self.make_question()
        await self.db.execute(
            "INSERT INTO verifications (guild_id,user_id,question,answer,created_at) VALUES (?,?,?,?,?)"
            " ON CONFLICT(guild_id,user_id) DO UPDATE SET question=excluded.question, answer=excluded.answer,"
            " attempts=0, created_at=excluded.created_at",
            (guild_id, user_id, question, answer, int(time.time())))
        return question

    async def pending(self, guild_id: str, user_id: str):
        return await self.db.one("SELECT question, attempts FROM verifications WHERE guild_id=? AND user_id=?",
                                 (guild_id, user_id))

    async def attempt(self, guild_id: str, user_id: str, given: str, max_attempts: int) -> str:
        """Returns ``ok``, ``wrong``, ``locked`` or ``none`` (no challenge pending)."""
        async with self.db.transaction() as tx:
            r = await tx.one("SELECT answer, attempts FROM verifications WHERE guild_id=? AND user_id=?",
                             (guild_id, user_id))
            if r is None:
                return "none"
            if r["attempts"] >= max_attempts:
                return "locked"
            if secrets.compare_digest(r["answer"], given.strip()):
                await tx.execute("DELETE FROM verifications WHERE guild_id=? AND user_id=?", (guild_id, user_id))
                return "ok"
            await tx.execute("UPDATE verifications SET attempts=attempts+1 WHERE guild_id=? AND user_id=?",
                             (guild_id, user_id))
            return "locked" if r["attempts"] + 1 >= max_attempts else "wrong"

    async def clear(self, guild_id: str, user_id: str) -> None:
        await self.db.execute("DELETE FROM verifications WHERE guild_id=? AND user_id=?", (guild_id, user_id))


@dataclass
class RoleMenu:
    id: int
    guild_id: str
    channel_id: str
    message_id: str
    title: str


class RoleMenuStore:
    def __init__(self, db: Database):
        self.db = db

    async def create(self, guild_id: str, channel_id: str, message_id: str, title: str) -> RoleMenu:
        mid = await self.db.insert("INSERT INTO role_menus (guild_id,channel_id,message_id,title) VALUES (?,?,?,?)",
                                   (guild_id, channel_id, message_id, title))
        return RoleMenu(mid, guild_id, channel_id, message_id, title)

    async def add_option(self, menu_id: int, emoji: str, role_id: str, label: str = "") -> None:
        await self.db.execute("INSERT INTO role_menu_options (menu_id,emoji,role_id,label) VALUES (?,?,?,?)"
                              " ON CONFLICT(menu_id,emoji) DO UPDATE SET role_id=excluded.role_id, label=excluded.label",
                              (menu_id, emoji, role_id, label))

    async def options(self, menu_id: int):
        return await self.db.all("SELECT emoji, role_id, label FROM role_menu_options WHERE menu_id=? ORDER BY rowid",
                                 (menu_id,))

    async def by_message(self, message_id: str) -> RoleMenu | None:
        r = await self.db.one("SELECT * FROM role_menus WHERE message_id=?", (message_id,))
        return RoleMenu(r["id"], r["guild_id"], r["channel_id"], r["message_id"], r["title"]) if r else None

    async def role_for(self, message_id: str, emoji: str) -> str | None:
        r = await self.db.one("SELECT o.role_id FROM role_menu_options o JOIN role_menus m ON m.id=o.menu_id"
                              " WHERE m.message_id=? AND o.emoji=?", (message_id, emoji))
        return r["role_id"] if r else None

    async def menus(self, guild_id: str) -> list[RoleMenu]:
        rows = await self.db.all("SELECT * FROM role_menus WHERE guild_id=? ORDER BY id", (guild_id,))
        return [RoleMenu(r["id"], r["guild_id"], r["channel_id"], r["message_id"], r["title"]) for r in rows]

    async def delete(self, guild_id: str, menu_id: int) -> bool:
        return bool(await self.db.execute("DELETE FROM role_menus WHERE guild_id=? AND id=?", (guild_id, menu_id)))


@dataclass
class Giveaway:
    id: int
    guild_id: str
    channel_id: str
    message_id: str | None
    host_id: str
    prize: str
    winners: int
    ends_at: int
    ended: bool


def _g(r) -> Giveaway:
    return Giveaway(r["id"], r["guild_id"], r["channel_id"], r["message_id"], r["host_id"], r["prize"],
                    r["winners"], r["ends_at"], bool(r["ended"]))


class GiveawayStore:
    def __init__(self, db: Database):
        self.db = db

    async def create(self, guild_id: str, channel_id: str, host_id: str, prize: str, winners: int,
                     ends_at: int) -> Giveaway:
        gid = await self.db.insert(
            "INSERT INTO giveaways (guild_id,channel_id,host_id,prize,winners,ends_at) VALUES (?,?,?,?,?,?)",
            (guild_id, channel_id, host_id, prize, winners, ends_at))
        return Giveaway(gid, guild_id, channel_id, None, host_id, prize, winners, ends_at, False)

    async def set_message(self, giveaway_id: int, message_id: str) -> None:
        await self.db.execute("UPDATE giveaways SET message_id=? WHERE id=?", (message_id, giveaway_id))

    async def get(self, giveaway_id: int) -> Giveaway | None:
        r = await self.db.one("SELECT * FROM giveaways WHERE id=?", (giveaway_id,))
        return _g(r) if r else None

    async def by_message(self, message_id: str) -> Giveaway | None:
        r = await self.db.one("SELECT * FROM giveaways WHERE message_id=?", (message_id,))
        return _g(r) if r else None

    async def active(self, guild_id: str) -> list[Giveaway]:
        rows = await self.db.all("SELECT * FROM giveaways WHERE guild_id=? AND ended=0 ORDER BY ends_at", (guild_id,))
        return [_g(r) for r in rows]

    async def due(self, now: int | None = None) -> list[Giveaway]:
        rows = await self.db.all("SELECT * FROM giveaways WHERE ended=0 AND ends_at<=?", (now or int(time.time()),))
        return [_g(r) for r in rows]

    async def enter(self, giveaway_id: int, user_id: str) -> bool:
        return bool(await self.db.execute("INSERT OR IGNORE INTO giveaway_entries (giveaway_id,user_id) VALUES (?,?)",
                                          (giveaway_id, user_id)))

    async def leave(self, giveaway_id: int, user_id: str) -> None:
        await self.db.execute("DELETE FROM giveaway_entries WHERE giveaway_id=? AND user_id=?", (giveaway_id, user_id))

    async def entries(self, giveaway_id: int) -> list[str]:
        rows = await self.db.all("SELECT user_id FROM giveaway_entries WHERE giveaway_id=? ORDER BY rowid", (giveaway_id,))
        return [r["user_id"] for r in rows]

    async def finish(self, giveaway_id: int, rng: random.Random | None = None) -> list[str]:
        """Mark ended (once) and draw winners. Returns ``[]`` if it was already ended or nobody entered."""
        async with self.db.transaction() as tx:
            r = await tx.one("SELECT winners FROM giveaways WHERE id=? AND ended=0", (giveaway_id,))
            if r is None:
                return []
            await tx.execute("UPDATE giveaways SET ended=1 WHERE id=?", (giveaway_id,))
            rows = await tx.all("SELECT user_id FROM giveaway_entries WHERE giveaway_id=?", (giveaway_id,))
        pool = [x["user_id"] for x in rows]
        return (rng or random.SystemRandom()).sample(pool, min(r["winners"], len(pool)))

    async def cancel(self, giveaway_id: int) -> bool:
        return bool(await self.db.execute("UPDATE giveaways SET ended=1 WHERE id=? AND ended=0", (giveaway_id,)))


class GameStatsStore:
    def __init__(self, db: Database):
        self.db = db

    async def record(self, guild_id: str, user_id: str, game: str, *, won: bool = False, drawn: bool = False,
                     score: int = 0) -> None:
        await self.db.execute(
            "INSERT INTO game_stats (guild_id,user_id,game,played,won,drawn,score) VALUES (?,?,?,1,?,?,?)"
            " ON CONFLICT(guild_id,user_id,game) DO UPDATE SET played=played+1, won=won+excluded.won,"
            " drawn=drawn+excluded.drawn, score=score+excluded.score",
            (guild_id, user_id, game, int(won), int(drawn), score))

    async def for_user(self, guild_id: str, user_id: str):
        return await self.db.all("SELECT game, played, won, drawn, score FROM game_stats WHERE guild_id=? AND user_id=?"
                                 " ORDER BY game", (guild_id, user_id))

    async def leaderboard(self, guild_id: str, game: str, limit: int = 10):
        return await self.db.all(
            "SELECT user_id, played, won, drawn, score FROM game_stats WHERE guild_id=? AND game=?"
            " ORDER BY won DESC, score DESC, user_id LIMIT ?", (guild_id, game, limit))


class ActivityStore:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def today(now: float | None = None) -> str:
        return datetime.fromtimestamp(now or time.time(), timezone.utc).strftime("%Y-%m-%d")

    async def bump(self, guild_id: str, channel_id: str, *, messages: int = 0, joins: int = 0, leaves: int = 0,
                   day: str | None = None) -> None:
        await self.db.execute(
            "INSERT INTO activity (guild_id,day,channel_id,messages,joins,leaves) VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(guild_id,day,channel_id) DO UPDATE SET messages=messages+excluded.messages,"
            " joins=joins+excluded.joins, leaves=leaves+excluded.leaves",
            (guild_id, day or self.today(), channel_id, messages, joins, leaves))

    async def daily(self, guild_id: str, days: int = 7):
        return await self.db.all(
            "SELECT day, SUM(messages) m, SUM(joins) j, SUM(leaves) l FROM activity WHERE guild_id=?"
            " GROUP BY day ORDER BY day DESC LIMIT ?", (guild_id, days))

    async def top_channels(self, guild_id: str, limit: int = 5):
        return await self.db.all(
            "SELECT channel_id, SUM(messages) m FROM activity WHERE guild_id=? AND channel_id!=''"
            " GROUP BY channel_id ORDER BY m DESC LIMIT ?", (guild_id, limit))


class OnboardingStore:
    """Where each new member is in the onboarding flow (verify, pick roles, done)."""

    STEPS = ("verified_at", "picked_at")

    def __init__(self, db: Database):
        self.db = db

    async def start(self, guild_id: str, user_id: str) -> None:
        await self.db.execute("INSERT OR REPLACE INTO onboarding (guild_id,user_id,started_at) VALUES (?,?,?)",
                              (guild_id, user_id, int(time.time())))

    async def mark(self, guild_id: str, user_id: str, step: str) -> bool:
        """Record a step (once). Returns False if there is no onboarding in progress or it was already marked."""
        if step not in self.STEPS:
            raise ValueError(step)
        return bool(await self.db.execute(
            f"UPDATE onboarding SET {step}=? WHERE guild_id=? AND user_id=? AND {step} IS NULL AND completed_at IS NULL",
            (int(time.time()), guild_id, user_id)))

    async def get(self, guild_id: str, user_id: str):
        return await self.db.one("SELECT * FROM onboarding WHERE guild_id=? AND user_id=?", (guild_id, user_id))

    async def complete(self, guild_id: str, user_id: str) -> bool:
        return bool(await self.db.execute(
            "UPDATE onboarding SET completed_at=? WHERE guild_id=? AND user_id=? AND completed_at IS NULL",
            (int(time.time()), guild_id, user_id)))

    async def counts(self, guild_id: str) -> dict:
        r = await self.db.one("SELECT COUNT(*) n, COUNT(completed_at) done FROM onboarding WHERE guild_id=?", (guild_id,))
        return {"started": r["n"], "completed": r["done"]}

"""Image guard blocklist and stream/video alert feeds."""

from __future__ import annotations

import time

from ..db import Database


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


class ImageBlockStore:
    def __init__(self, db: Database):
        self.db = db

    async def add(self, guild_id: str, hash_: str, note: str = "", by_id: str = "") -> int:
        await self.db.execute("INSERT OR IGNORE INTO image_blocks (guild_id,hash,note,by_id,at) VALUES (?,?,?,?,?)",
                              (guild_id, hash_, note[:200], by_id, int(time.time())))
        return await self.db.scalar("SELECT id FROM image_blocks WHERE guild_id=? AND hash=?", (guild_id, hash_))

    async def remove(self, guild_id: str, block_id: int) -> bool:
        return await self.db.execute("DELETE FROM image_blocks WHERE guild_id=? AND id=?", (guild_id, block_id)) > 0

    async def list(self, guild_id: str) -> list:
        return await self.db.all("SELECT * FROM image_blocks WHERE guild_id=? ORDER BY id DESC", (guild_id,))

    async def match(self, guild_id: str, hash_: str, distance: int) -> dict | None:
        """The closest blocked picture within ``distance`` differing bits, or None."""
        best = None
        for r in await self.db.all("SELECT id, hash, note FROM image_blocks WHERE guild_id=?", (guild_id,)):
            d = hamming(r["hash"], hash_)
            if d <= distance and (best is None or d < best["distance"]):
                best = {"id": r["id"], "note": r["note"], "distance": d}
        return best


class NotifyStore:
    def __init__(self, db: Database):
        self.db = db

    async def add(self, guild_id: str, kind: str, source: str, channel_id: str, message: str = "", role: str = "",
                  by_id: str = "") -> int:
        await self.db.execute("INSERT OR REPLACE INTO notify_feeds (guild_id,kind,source,channel_id,message,role,by_id,at)"
                              " VALUES (?,?,?,?,?,?,?,?)",
                              (guild_id, kind, source, channel_id, message, role, by_id, int(time.time())))
        return await self.db.scalar("SELECT id FROM notify_feeds WHERE guild_id=? AND kind=? AND source=? AND channel_id=?",
                                    (guild_id, kind, source, channel_id))

    async def remove(self, guild_id: str, feed_id: int) -> bool:
        return await self.db.execute("DELETE FROM notify_feeds WHERE guild_id=? AND id=?", (guild_id, feed_id)) > 0

    async def feeds(self, guild_id: str | None = None) -> list:
        if guild_id is None:
            return await self.db.all("SELECT * FROM notify_feeds ORDER BY id")
        return await self.db.all("SELECT * FROM notify_feeds WHERE guild_id=? ORDER BY id", (guild_id,))

    async def seen(self, feed_key: str) -> set[str]:
        return {r["item_id"] for r in await self.db.all("SELECT item_id FROM notify_seen WHERE feed_key=?", (feed_key,))}

    async def mark(self, feed_key: str, item_ids) -> None:
        now = int(time.time())
        await self.db.executemany("INSERT OR IGNORE INTO notify_seen (feed_key,item_id,at) VALUES (?,?,?)",
                                  [(feed_key, i, now) for i in item_ids])

    async def prune(self, days: int = 90) -> None:
        await self.db.execute("DELETE FROM notify_seen WHERE at < ?", (int(time.time()) - days * 86400,))

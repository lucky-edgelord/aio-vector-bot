"""Verification records, one-time web links, device marks and softbans.

The ideas here come from GateBot (https://gitworkshop.dev/henk.tech/Gatebot, MIT):
verification is stored, not just a role, so it survives a lost role or a rejoin; a
device can verify only one account per community for a while; and a softbanned member
is kicked on sight instead of being banned on the relay.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time

from ..db import Database

DAY = 86400


def canonical_fingerprint(raw: str) -> str | None:
    """Bound and normalise the browser's fingerprint before hashing.

    It is an untrusted anti-abuse signal, not proof of identity, so anything that
    doesn't look like what our page sends is refused.
    """
    if not isinstance(raw, str) or len(raw) > 4096:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    if (not isinstance(value, list) or len(value) != 11 or value[0] != "v1" or not value[1]
            or any(not isinstance(v, str) or len(v) > 512 or any(ord(c) < 32 for c in v) for v in value)):
        return None
    return json.dumps(value, separators=(",", ":"))


class GateStore:
    def __init__(self, db: Database):
        self.db = db
        self._key: bytes | None = None

    # -- the secret that keys device hashes ------------------------------------------------

    async def key(self) -> bytes:
        """A random secret kept in the database, so hashes can't be reversed by guessing IPs."""
        if self._key is None:
            r = await self.db.one("SELECT value FROM guild_settings WHERE guild_id='*' AND key='gate:hash_key'")
            if r is None:
                value = secrets.token_hex(32)
                await self.db.execute("INSERT OR IGNORE INTO guild_settings (guild_id,key,value) VALUES ('*','gate:hash_key',?)",
                                      (json.dumps(value),))
                r = await self.db.one("SELECT value FROM guild_settings WHERE guild_id='*' AND key='gate:hash_key'")
            self._key = bytes.fromhex(json.loads(r["value"]))
        return self._key

    async def device_hashes(self, guild_id: str, *, ip: str | None, cookie: str | None, fingerprint: str | None) -> list[str]:
        key = await self.key()
        parts = [f"fingerprint:{fingerprint}" if fingerprint else None,
                 f"cookie:{cookie}" if cookie else None,
                 f"ip:{ip}" if ip else None]
        return sorted({hmac.new(key, f"{guild_id}|{p}".encode(), hashlib.sha256).hexdigest() for p in parts if p})

    # -- verified records -------------------------------------------------------------------

    async def is_verified(self, guild_id: str, user_id: str) -> bool:
        return await self.db.one("SELECT 1 FROM verified_members WHERE guild_id=? AND user_id=?",
                                 (guild_id, user_id)) is not None

    async def is_adult(self, guild_id: str, user_id: str) -> bool:
        r = await self.db.one("SELECT is_adult FROM verified_members WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        return bool(r and r["is_adult"])

    async def mark_verified(self, guild_id: str, user_id: str, *, method: str, is_adult: bool = False) -> None:
        await self.db.execute(
            "INSERT INTO verified_members (guild_id,user_id,verified_at,is_adult,method) VALUES (?,?,?,?,?)"
            " ON CONFLICT(guild_id,user_id) DO UPDATE SET verified_at=excluded.verified_at,"
            " is_adult=MAX(is_adult, excluded.is_adult), method=excluded.method",
            (guild_id, user_id, int(time.time()), int(is_adult), method))

    async def try_mark_device_verified(self, guild_id: str, user_id: str, hashes: list[str], *,
                                       days: int, is_adult: bool, method: str = "captcha") -> bool:
        """Record the verification unless any of the device hashes was used in the last ``days``.

        Done in one transaction so two tabs can't both get through. Returns False on a duplicate.
        Only the hashes are stored, never which member they belong to.
        """
        now = int(time.time())
        cutoff = now - days * DAY
        async with self.db.transaction() as tx:
            await tx.execute("DELETE FROM verify_marks WHERE at <= ?", (cutoff,))
            for h in hashes:
                if await tx.one("SELECT 1 FROM verify_marks WHERE guild_id=? AND hash=?", (guild_id, h)):
                    return False
            for h in hashes:
                await tx.execute("INSERT OR REPLACE INTO verify_marks (guild_id,hash,at) VALUES (?,?,?)", (guild_id, h, now))
            await tx.execute(
                "INSERT INTO verified_members (guild_id,user_id,verified_at,is_adult,method) VALUES (?,?,?,?,?)"
                " ON CONFLICT(guild_id,user_id) DO UPDATE SET verified_at=excluded.verified_at,"
                " is_adult=MAX(is_adult, excluded.is_adult), method=excluded.method",
                (guild_id, user_id, now, int(is_adult), method))
        return True

    async def unverify(self, guild_id: str, user_id: str) -> bool:
        return await self.db.execute("DELETE FROM verified_members WHERE guild_id=? AND user_id=?", (guild_id, user_id)) > 0

    async def reset(self, guild_id: str) -> None:
        """Forget every verification, link and device mark for a community."""
        for table in ("verified_members", "verify_links", "verify_marks"):
            await self.db.execute(f"DELETE FROM {table} WHERE guild_id=?", (guild_id,))  # noqa: S608 - fixed names

    async def count(self, guild_id: str) -> int:
        r = await self.db.one("SELECT COUNT(*) AS n FROM verified_members WHERE guild_id=?", (guild_id,))
        return r["n"]

    async def prune(self, *, mark_days: int, link_minutes: int) -> None:
        now = int(time.time())
        await self.db.execute("DELETE FROM verify_marks WHERE at <= ?", (now - mark_days * DAY,))
        await self.db.execute("DELETE FROM verify_links WHERE created_at <= ?", (now - max(link_minutes * 60, 3600),))

    # -- one-time links -----------------------------------------------------------------------

    async def new_link(self, guild_id: str, user_id: str, channel_id: str = "") -> str:
        """A fresh link replaces the member's older ones, so only the newest works."""
        token = secrets.token_urlsafe(24)
        async with self.db.transaction() as tx:
            await tx.execute("DELETE FROM verify_links WHERE guild_id=? AND user_id=?", (guild_id, user_id))
            await tx.execute("INSERT INTO verify_links (token,guild_id,user_id,channel_id,created_at) VALUES (?,?,?,?,?)",
                             (token, guild_id, user_id, channel_id, int(time.time())))
        return token

    async def link(self, token: str, minutes: int):
        """The link, or None if it doesn't exist or has expired. A used link is returned with used=1."""
        r = await self.db.one("SELECT * FROM verify_links WHERE token=?", (token,))
        if r is None or r["created_at"] < time.time() - minutes * 60:
            return None
        return r

    async def set_age(self, token: str, age: int) -> None:
        await self.db.execute("UPDATE verify_links SET age=? WHERE token=? AND used=0", (age, token))

    async def claim(self, token: str) -> bool:
        """Mark a link used. Only one request can win."""
        return await self.db.execute("UPDATE verify_links SET used=1 WHERE token=? AND used=0", (token,)) > 0

    async def release(self, token: str) -> None:
        await self.db.execute("UPDATE verify_links SET used=0 WHERE token=?", (token,))

    # -- softbans -------------------------------------------------------------------------------

    async def softban(self, guild_id: str, user_id: str, reason: str = "", by: str = "") -> None:
        await self.db.execute(
            "INSERT INTO softbans (guild_id,user_id,reason,by_id,kicks,banned_at) VALUES (?,?,?,?,0,?)"
            " ON CONFLICT(guild_id,user_id) DO UPDATE SET reason=excluded.reason, by_id=excluded.by_id",
            (guild_id, user_id, reason, by, int(time.time())))

    async def is_softbanned(self, guild_id: str, user_id: str) -> bool:
        return await self.db.one("SELECT 1 FROM softbans WHERE guild_id=? AND user_id=?", (guild_id, user_id)) is not None

    async def add_kick(self, guild_id: str, user_id: str) -> int:
        """Count a kick-on-sight and return the total."""
        await self.db.execute("UPDATE softbans SET kicks=kicks+1 WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        r = await self.db.one("SELECT kicks FROM softbans WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        return r["kicks"] if r else 0

    async def unsoftban(self, guild_id: str, user_id: str) -> bool:
        return await self.db.execute("DELETE FROM softbans WHERE guild_id=? AND user_id=?", (guild_id, user_id)) > 0

    async def softbans(self, guild_id: str):
        return await self.db.all("SELECT * FROM softbans WHERE guild_id=? ORDER BY banned_at DESC", (guild_id,))

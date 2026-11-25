"""Web dashboard state: one-time sign-in codes, sessions, the audit log and settings edited in the browser.

Codes, links and session tokens are only ever stored as SHA-256 hashes, so a copy of the database
can't be used to sign in.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any

from ..db import Database


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


# -- passwords: scrypt from the standard library, stored as scrypt$n$r$p$salt$hash ----------------

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1
USERNAME = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
MIN_PASSWORD = 10


class PasswordError(ValueError):
    pass


def check_new_password(password: str, username: str = "") -> None:
    if len(password) < MIN_PASSWORD:
        raise PasswordError(f"Use at least {MIN_PASSWORD} characters.")
    if len(password) > 256:
        raise PasswordError("That password is too long.")
    if username and password.lower() == username.lower():
        raise PasswordError("The password can't be the username.")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32,
                        maxmem=64 * 1024 * 1024)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        kind, n, r, p, salt, want = stored.split("$")
        if kind != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                            dklen=len(want) // 2, maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(dk.hex(), want)
    except (ValueError, TypeError):
        return False


# A real hash, so a login for a username that doesn't exist takes as long as a wrong password.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(12))


@dataclass
class Session:
    npub: str
    created_at: int
    expires_at: int


class DashboardStore:
    MAX_ATTEMPTS = 5

    def __init__(self, db: Database):
        self.db = db

    # -- sign-in ----------------------------------------------------------------------

    async def new_login(self, npub: str, ttl: int) -> tuple[str, str]:
        """Make a 6-digit code and a link token for ``npub``. Returns (code, link_token)."""
        code = f"{secrets.randbelow(1_000_000):06d}"
        link = secrets.token_urlsafe(32)
        now = int(time.time())
        await self.db.execute("DELETE FROM dash_logins WHERE expires_at<? OR (npub=? AND used=0)", (now, npub))
        await self.db.insert("INSERT INTO dash_logins (npub,code_hash,link_hash,expires_at) VALUES (?,?,?,?)",
                             (npub, digest(f"{npub}:{code}"), digest(link), now + ttl))
        return code, link

    async def recent_logins(self, npub: str, window: int) -> int:
        """How many codes were requested for ``npub`` in the last ``window`` seconds (for rate limiting)."""
        return await self.db.scalar("SELECT COUNT(*) FROM dash_logins WHERE npub=? AND expires_at>?",
                                    (npub, int(time.time()) - window), 0)

    async def redeem_code(self, npub: str, code: str) -> bool:
        now = int(time.time())
        r = await self.db.one("SELECT id, code_hash, attempts FROM dash_logins WHERE npub=? AND used=0 AND expires_at>=?"
                              " ORDER BY id DESC LIMIT 1", (npub, now))
        if r is None or r["attempts"] >= self.MAX_ATTEMPTS:
            return False
        if hmac.compare_digest(r["code_hash"], digest(f"{npub}:{code.strip()}")):
            await self.db.execute("UPDATE dash_logins SET used=1 WHERE id=?", (r["id"],))
            return True
        await self.db.execute("UPDATE dash_logins SET attempts=attempts+1 WHERE id=?", (r["id"],))
        return False

    async def redeem_link(self, link: str) -> str | None:
        """Use a one-time link. Returns the npub it was made for."""
        r = await self.db.one("SELECT id, npub FROM dash_logins WHERE link_hash=? AND used=0 AND expires_at>=?",
                              (digest(link), int(time.time())))
        if r is None:
            return None
        await self.db.execute("UPDATE dash_logins SET used=1 WHERE id=?", (r["id"],))
        return r["npub"]

    # -- sessions ---------------------------------------------------------------------

    async def new_session(self, npub: str, ttl: int, user_agent: str = "") -> str:
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        await self.db.execute("DELETE FROM dash_sessions WHERE expires_at<?", (now,))
        await self.db.execute("INSERT INTO dash_sessions (token_hash,npub,created_at,expires_at,last_seen,user_agent)"
                              " VALUES (?,?,?,?,?,?)", (digest(token), npub, now, now + ttl, now, user_agent[:200]))
        return token

    async def session(self, token: str) -> Session | None:
        if not token:
            return None
        now = int(time.time())
        r = await self.db.one("SELECT npub, created_at, expires_at, last_seen FROM dash_sessions"
                              " WHERE token_hash=? AND expires_at>=?", (digest(token), now))
        if r is None:
            return None
        if now - r["last_seen"] > 60:
            await self.db.execute("UPDATE dash_sessions SET last_seen=? WHERE token_hash=?", (now, digest(token)))
        return Session(r["npub"], r["created_at"], r["expires_at"])

    async def end_session(self, token: str) -> None:
        await self.db.execute("DELETE FROM dash_sessions WHERE token_hash=?", (digest(token),))

    async def end_all_sessions(self, npub: str) -> int:
        return await self.db.execute("DELETE FROM dash_sessions WHERE npub=?", (npub,))

    # -- accounts (username + password) -----------------------------------------------

    LOCK_AFTER, LOCK_SECONDS = 5, 15 * 60

    async def users(self):
        return await self.db.all("SELECT username, npub, created_at, updated_at, created_by, last_login, locked_until"
                                 " FROM dash_users ORDER BY username")

    async def user(self, username: str):
        return await self.db.one("SELECT * FROM dash_users WHERE username=?", (username,))

    async def users_for(self, npub: str):
        return await self.db.all("SELECT username FROM dash_users WHERE npub=? ORDER BY username", (npub,))

    async def create_user(self, username: str, npub: str, password: str, created_by: str = "") -> None:
        if not USERNAME.match(username):
            raise PasswordError("Usernames are 3–32 letters, numbers, dots, dashes or underscores.")
        check_new_password(password, username)
        if await self.user(username):
            raise PasswordError("That username is taken.")
        pw = await asyncio.to_thread(hash_password, password)
        now = int(time.time())
        await self.db.execute("INSERT INTO dash_users (username,npub,pw_hash,created_at,updated_at,created_by)"
                              " VALUES (?,?,?,?,?,?)", (username, npub, pw, now, now, created_by))

    async def set_password(self, username: str, password: str) -> None:
        check_new_password(password, username)
        pw = await asyncio.to_thread(hash_password, password)
        await self.db.execute("UPDATE dash_users SET pw_hash=?, updated_at=?, failed=0, locked_until=0 WHERE username=?",
                              (pw, int(time.time()), username))

    async def delete_user(self, username: str) -> bool:
        return bool(await self.db.execute("DELETE FROM dash_users WHERE username=?", (username,)))

    async def check_login(self, username: str, password: str) -> tuple[str | None, str]:
        """Returns (npub, "") on success or (None, reason). Locks the account after repeated failures."""
        row = await self.user(username)
        now = int(time.time())
        if row is None:
            await asyncio.to_thread(verify_password, password, _DUMMY_HASH)
            return None, "Wrong username or password."
        if row["locked_until"] > now:
            return None, f"Too many wrong passwords. Try again in {max(1, (row['locked_until'] - now) // 60)} min."
        if not await asyncio.to_thread(verify_password, password, row["pw_hash"]):
            failed = row["failed"] + 1
            locked = now + self.LOCK_SECONDS if failed >= self.LOCK_AFTER else 0
            await self.db.execute("UPDATE dash_users SET failed=?, locked_until=? WHERE username=?",
                                  (0 if locked else failed, locked, row["username"]))
            return None, "Wrong username or password."
        await self.db.execute("UPDATE dash_users SET failed=0, locked_until=0, last_login=? WHERE username=?",
                              (now, row["username"]))
        return row["npub"], ""

    # -- audit ------------------------------------------------------------------------

    async def audit(self, npub: str, action: str, detail: str = "", guild_id: str = "") -> None:
        await self.db.insert("INSERT INTO dash_audit (at,npub,guild_id,action,detail) VALUES (?,?,?,?,?)",
                             (int(time.time()), npub, guild_id, action, detail[:500]))

    async def audit_log(self, guild_id: str | None = None, limit: int = 100, offset: int = 0):
        if guild_id is None:
            return await self.db.all("SELECT * FROM dash_audit ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))
        return await self.db.all("SELECT * FROM dash_audit WHERE guild_id IN (?, '') ORDER BY id DESC LIMIT ? OFFSET ?",
                                 (guild_id, limit, offset))

    async def audit_count(self, guild_id: str) -> int:
        return await self.db.scalar("SELECT COUNT(*) FROM dash_audit WHERE guild_id IN (?, '')", (guild_id,), 0)

    # -- dashboard access by role --------------------------------------------------------

    async def access_rules(self) -> dict[str, dict]:
        rows = await self.db.all("SELECT guild_id, rules FROM dash_access")
        return {r["guild_id"]: json.loads(r["rules"]) for r in rows}

    async def set_access_rules(self, guild_id: str, rules: dict, npub: str) -> None:
        await self.db.execute(
            "INSERT INTO dash_access (guild_id,rules,updated_by,updated_at) VALUES (?,?,?,?)"
            " ON CONFLICT(guild_id) DO UPDATE SET rules=excluded.rules, updated_by=excluded.updated_by,"
            " updated_at=excluded.updated_at", (guild_id, json.dumps(rules), npub, int(time.time())))

    # -- settings overrides -----------------------------------------------------------

    async def overrides(self) -> dict[str, Any]:
        rows = await self.db.all("SELECT path, value FROM config_overrides ORDER BY path")
        return {r["path"]: json.loads(r["value"]) for r in rows}

    async def set_override(self, path: str, value: Any, npub: str) -> None:
        await self.db.execute(
            "INSERT INTO config_overrides (path,value,updated_by,updated_at) VALUES (?,?,?,?)"
            " ON CONFLICT(path) DO UPDATE SET value=excluded.value, updated_by=excluded.updated_by,"
            " updated_at=excluded.updated_at", (path, json.dumps(value), npub, int(time.time())))

    async def clear_override(self, path: str) -> bool:
        return bool(await self.db.execute("DELETE FROM config_overrides WHERE path=?", (path,)))

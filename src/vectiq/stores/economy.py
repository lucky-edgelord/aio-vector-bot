from __future__ import annotations

import random
import time
from dataclasses import dataclass

from ..db import Database

DAY = 86400


class InsufficientFunds(Exception):
    def __init__(self, needed: int, have: int):
        super().__init__(f"needs {needed}, has {have}")
        self.needed, self.have = needed, have


@dataclass
class Wallet:
    user_id: str
    balance: int
    bank: int
    daily_streak: int = 0

    @property
    def total(self) -> int:
        return self.balance + self.bank


@dataclass
class Item:
    id: int
    name: str
    price: int
    description: str
    role_id: str | None
    stock: int | None


def _item(r) -> Item:
    return Item(r["id"], r["name"], r["price"], r["description"], r["role_id"], r["stock"])


class EconomyStore:
    def __init__(self, db: Database):
        self.db = db

    # -- wallets ---------------------------------------------------------------------

    async def wallet(self, guild_id: str, user_id: str, *, start: int = 0) -> Wallet:
        await self.db.execute("INSERT OR IGNORE INTO wallets (guild_id,user_id,balance) VALUES (?,?,?)",
                              (guild_id, user_id, start))
        r = await self.db.one("SELECT balance, bank, daily_streak FROM wallets WHERE guild_id=? AND user_id=?",
                              (guild_id, user_id))
        return Wallet(user_id, r["balance"], r["bank"], r["daily_streak"])

    async def adjust(self, guild_id: str, user_id: str, amount: int, reason: str, *, start: int = 0) -> int:
        """Add (or remove, if negative) coins from the wallet. Raises InsufficientFunds rather than going below 0."""
        async with self.db.transaction() as tx:
            await tx.execute("INSERT OR IGNORE INTO wallets (guild_id,user_id,balance) VALUES (?,?,?)",
                             (guild_id, user_id, start))
            have = await tx.scalar("SELECT balance FROM wallets WHERE guild_id=? AND user_id=?", (guild_id, user_id), 0)
            if have + amount < 0:
                raise InsufficientFunds(-amount, have)
            await tx.execute("UPDATE wallets SET balance=balance+? WHERE guild_id=? AND user_id=?",
                             (amount, guild_id, user_id))
            await tx.execute("INSERT INTO transactions (guild_id,user_id,amount,reason,created_at) VALUES (?,?,?,?,?)",
                             (guild_id, user_id, amount, reason, int(time.time())))
        return have + amount

    async def transfer(self, guild_id: str, sender: str, receiver: str, amount: int, *, start: int = 0) -> None:
        if amount <= 0 or sender == receiver:
            raise ValueError("amount must be positive and the receiver someone else")
        now = int(time.time())
        async with self.db.transaction() as tx:
            for uid in (sender, receiver):
                await tx.execute("INSERT OR IGNORE INTO wallets (guild_id,user_id,balance) VALUES (?,?,?)",
                                 (guild_id, uid, start))
            have = await tx.scalar("SELECT balance FROM wallets WHERE guild_id=? AND user_id=?", (guild_id, sender), 0)
            if have < amount:
                raise InsufficientFunds(amount, have)
            await tx.execute("UPDATE wallets SET balance=balance-? WHERE guild_id=? AND user_id=?",
                             (amount, guild_id, sender))
            await tx.execute("UPDATE wallets SET balance=balance+? WHERE guild_id=? AND user_id=?",
                             (amount, guild_id, receiver))
            await tx.execute("INSERT INTO transactions (guild_id,user_id,amount,reason,created_at) VALUES (?,?,?,?,?)",
                             (guild_id, sender, -amount, f"pay {receiver}", now))
            await tx.execute("INSERT INTO transactions (guild_id,user_id,amount,reason,created_at) VALUES (?,?,?,?,?)",
                             (guild_id, receiver, amount, f"pay from {sender}", now))

    async def deposit(self, guild_id: str, user_id: str, amount: int) -> None:
        await self._move(guild_id, user_id, amount, to_bank=True)

    async def withdraw(self, guild_id: str, user_id: str, amount: int) -> None:
        await self._move(guild_id, user_id, amount, to_bank=False)

    async def _move(self, guild_id: str, user_id: str, amount: int, *, to_bank: bool) -> None:
        if amount <= 0:
            raise ValueError("amount must be positive")
        src, dst = ("balance", "bank") if to_bank else ("bank", "balance")
        async with self.db.transaction() as tx:
            have = await tx.scalar(f"SELECT {src} FROM wallets WHERE guild_id=? AND user_id=?", (guild_id, user_id), 0)
            if have < amount:
                raise InsufficientFunds(amount, have)
            await tx.execute(f"UPDATE wallets SET {src}={src}-?, {dst}={dst}+? WHERE guild_id=? AND user_id=?",
                             (amount, amount, guild_id, user_id))

    async def leaderboard(self, guild_id: str, limit: int = 10) -> list[Wallet]:
        rows = await self.db.all(
            "SELECT user_id, balance, bank, daily_streak FROM wallets WHERE guild_id=?"
            " ORDER BY balance+bank DESC, user_id LIMIT ?", (guild_id, limit))
        return [Wallet(r["user_id"], r["balance"], r["bank"], r["daily_streak"]) for r in rows]

    async def history(self, guild_id: str, user_id: str, limit: int = 10):
        return await self.db.all("SELECT amount, reason, created_at FROM transactions WHERE guild_id=? AND user_id=?"
                                 " ORDER BY id DESC LIMIT ?", (guild_id, user_id, limit))

    # -- timed rewards ---------------------------------------------------------------

    async def claim_daily(self, guild_id: str, user_id: str, *, amount: int, bonus: int, cap: int,
                          start: int = 0, now: int | None = None):
        """Returns ``(paid, streak)``; ``paid`` is ``None`` with the seconds to wait as ``streak`` if too early."""
        now = int(time.time()) if now is None else now
        async with self.db.transaction() as tx:
            await tx.execute("INSERT OR IGNORE INTO wallets (guild_id,user_id,balance) VALUES (?,?,?)",
                             (guild_id, user_id, start))
            r = await tx.one("SELECT daily_at, daily_streak FROM wallets WHERE guild_id=? AND user_id=?",
                             (guild_id, user_id))
            since = now - r["daily_at"]
            if r["daily_at"] and since < DAY:
                return None, DAY - since
            streak = r["daily_streak"] + 1 if r["daily_at"] and since < 2 * DAY else 1
            paid = amount + bonus * min(streak - 1, cap)
            await tx.execute("UPDATE wallets SET balance=balance+?, daily_at=?, daily_streak=? WHERE guild_id=? AND user_id=?",
                             (paid, now, streak, guild_id, user_id))
            await tx.execute("INSERT INTO transactions (guild_id,user_id,amount,reason,created_at) VALUES (?,?,?,?,?)",
                             (guild_id, user_id, paid, "daily", now))
        return paid, streak

    async def claim_work(self, guild_id: str, user_id: str, *, low: int, high: int, cooldown: int,
                         start: int = 0, now: int | None = None, rng: random.Random | None = None):
        now = int(time.time()) if now is None else now
        async with self.db.transaction() as tx:
            await tx.execute("INSERT OR IGNORE INTO wallets (guild_id,user_id,balance) VALUES (?,?,?)",
                             (guild_id, user_id, start))
            last = await tx.scalar("SELECT work_at FROM wallets WHERE guild_id=? AND user_id=?", (guild_id, user_id), 0)
            if last and now - last < cooldown:
                return None, cooldown - (now - last)
            paid = (rng or random).randint(low, high)
            await tx.execute("UPDATE wallets SET balance=balance+?, work_at=? WHERE guild_id=? AND user_id=?",
                             (paid, now, guild_id, user_id))
            await tx.execute("INSERT INTO transactions (guild_id,user_id,amount,reason,created_at) VALUES (?,?,?,?,?)",
                             (guild_id, user_id, paid, "work", now))
        return paid, 0

    # -- shop ------------------------------------------------------------------------

    async def add_item(self, guild_id: str, name: str, price: int, description: str = "",
                       role_id: str | None = None, stock: int | None = None) -> Item:
        iid = await self.db.insert(
            "INSERT INTO shop_items (guild_id,name,price,description,role_id,stock) VALUES (?,?,?,?,?,?)",
            (guild_id, name, price, description, role_id, stock))
        return Item(iid, name, price, description, role_id, stock)

    async def remove_item(self, guild_id: str, name: str) -> bool:
        return bool(await self.db.execute("DELETE FROM shop_items WHERE guild_id=? AND name=? COLLATE NOCASE",
                                          (guild_id, name)))

    async def shop(self, guild_id: str) -> list[Item]:
        rows = await self.db.all("SELECT * FROM shop_items WHERE guild_id=? ORDER BY price, name", (guild_id,))
        return [_item(r) for r in rows]

    async def item(self, guild_id: str, name: str) -> Item | None:
        r = await self.db.one("SELECT * FROM shop_items WHERE guild_id=? AND name=? COLLATE NOCASE", (guild_id, name))
        return _item(r) if r else None

    async def buy(self, guild_id: str, user_id: str, name: str, *, start: int = 0) -> Item:
        """Atomically charge the buyer, take stock and add to the inventory."""
        async with self.db.transaction() as tx:
            r = await tx.one("SELECT * FROM shop_items WHERE guild_id=? AND name=? COLLATE NOCASE", (guild_id, name))
            if r is None:
                raise KeyError(name)
            item = _item(r)
            if item.stock is not None and item.stock <= 0:
                raise LookupError("out of stock")
            await tx.execute("INSERT OR IGNORE INTO wallets (guild_id,user_id,balance) VALUES (?,?,?)",
                             (guild_id, user_id, start))
            have = await tx.scalar("SELECT balance FROM wallets WHERE guild_id=? AND user_id=?", (guild_id, user_id), 0)
            if have < item.price:
                raise InsufficientFunds(item.price, have)
            await tx.execute("UPDATE wallets SET balance=balance-? WHERE guild_id=? AND user_id=?",
                             (item.price, guild_id, user_id))
            if item.stock is not None:
                await tx.execute("UPDATE shop_items SET stock=stock-1 WHERE id=?", (item.id,))
            await tx.execute("INSERT INTO inventory (guild_id,user_id,item_id) VALUES (?,?,?)"
                             " ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET quantity=quantity+1",
                             (guild_id, user_id, item.id))
            await tx.execute("INSERT INTO transactions (guild_id,user_id,amount,reason,created_at) VALUES (?,?,?,?,?)",
                             (guild_id, user_id, -item.price, f"bought {item.name}", int(time.time())))
        return item

    async def inventory(self, guild_id: str, user_id: str):
        return await self.db.all(
            "SELECT s.name, i.quantity FROM inventory i JOIN shop_items s ON s.id=i.item_id"
            " WHERE i.guild_id=? AND i.user_id=? ORDER BY s.name", (guild_id, user_id))

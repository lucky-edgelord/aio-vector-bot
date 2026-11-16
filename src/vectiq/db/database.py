"""A small async facade over the standard-library ``sqlite3`` module.

One connection is shared by the whole bot. Every call runs in a worker thread
behind a lock, so the event loop never blocks and writes never interleave.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from .migrations import MIGRATIONS


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> Database:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        for pragma in ("journal_mode=WAL", "foreign_keys=ON", "synchronous=NORMAL", "busy_timeout=5000"):
            self._conn.execute(f"PRAGMA {pragma}")
        await self.migrate()
        return self

    async def close(self) -> None:
        if self._conn is not None:
            await asyncio.to_thread(self._conn.close)
            self._conn = None

    # -- migrations -------------------------------------------------------------------

    async def migrate(self) -> int:
        """Apply any migration newer than ``PRAGMA user_version``; return the final version."""
        assert self._conn is not None
        current = self._conn.execute("PRAGMA user_version").fetchone()[0]
        for version, script in enumerate(MIGRATIONS, start=1):
            if version <= current:
                continue
            self._conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;")
        return len(MIGRATIONS)

    @property
    def version(self) -> int:
        assert self._conn is not None
        return self._conn.execute("PRAGMA user_version").fetchone()[0]

    # -- queries ----------------------------------------------------------------------

    def _run(self, fn):
        assert self._conn is not None, "Database.connect() was not awaited"
        return fn(self._conn)

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Run one statement; return the number of rows it changed."""
        async with self._lock:
            return await asyncio.to_thread(self._run, lambda c: c.execute(sql, params).rowcount)

    async def insert(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Run an INSERT; return the new rowid."""
        async with self._lock:
            return await asyncio.to_thread(self._run, lambda c: c.execute(sql, params).lastrowid)

    async def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        async with self._lock:
            await asyncio.to_thread(self._run, lambda c: c.executemany(sql, list(rows)))

    async def one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        async with self._lock:
            return await asyncio.to_thread(self._run, lambda c: c.execute(sql, params).fetchone())

    async def all(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        async with self._lock:
            return await asyncio.to_thread(self._run, lambda c: c.execute(sql, params).fetchall())

    async def scalar(self, sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
        row = await self.one(sql, params)
        return default if row is None or row[0] is None else row[0]

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Transaction]:
        """``async with db.transaction() as tx:`` groups statements; an exception rolls all back."""
        async with self._lock:
            await asyncio.to_thread(self._run, lambda c: c.execute("BEGIN IMMEDIATE"))
            tx = Transaction(self)
            try:
                yield tx
            except BaseException:
                await asyncio.to_thread(self._run, lambda c: c.execute("ROLLBACK"))
                raise
            else:
                await asyncio.to_thread(self._run, lambda c: c.execute("COMMIT"))


class Transaction:
    """The same query helpers, run on the already-locked connection."""

    def __init__(self, db: Database):
        self._db = db

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        return await asyncio.to_thread(self._db._run, lambda c: c.execute(sql, params).rowcount)

    async def insert(self, sql: str, params: Sequence[Any] = ()) -> int:
        return await asyncio.to_thread(self._db._run, lambda c: c.execute(sql, params).lastrowid)

    async def one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        return await asyncio.to_thread(self._db._run, lambda c: c.execute(sql, params).fetchone())

    async def all(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        return await asyncio.to_thread(self._db._run, lambda c: c.execute(sql, params).fetchall())

    async def scalar(self, sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
        row = await self.one(sql, params)
        return default if row is None or row[0] is None else row[0]

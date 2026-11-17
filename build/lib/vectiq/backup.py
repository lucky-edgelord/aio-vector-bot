"""Restore points, like System Restore: go back to how the bot was at an earlier moment.

A restore point is one zip file holding the database, config.yaml, the settings with any
dashboard changes applied, and event pictures. The bot's key in .env is never included.

Points are made
- on a schedule (``backup.every_hours``),
- automatically before something risky: importing settings, saving the setup wizard,
  upgrading the database to a new version, and rolling back,
- by hand, with your own description (``!restorepoint create``, the dashboard, or
  ``vectiq --backup "before the event season"``).

Rolling back first makes a point of the current state, so a rollback can be undone too.
It happens while the bot runs: the database is replaced in place and settings reload.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import shutil
import sqlite3
import tempfile
import time
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from . import __version__
from .db.migrations import MIGRATIONS

log = logging.getLogger("vectiq.backup")

KINDS = ("scheduled", "automatic", "manual")
NAME = re.compile(r"^vectiq-(\d{8}-\d{6})-[0-9a-f]{4}\.zip$")


@dataclass
class Point:
    id: str              # the file name without .zip
    label: str
    kind: str            # scheduled | automatic | manual
    created_at: float
    version: str
    schema: int
    size: int
    files: int

    @property
    def when(self) -> str:
        return datetime.fromtimestamp(self.created_at).strftime("%Y-%m-%d %H:%M")

    def as_dict(self) -> dict:
        return asdict(self) | {"when": self.when}


class RestorePoints:
    def __init__(self, config, db=None):
        self.cfg, self.db = config, db
        self._lock = asyncio.Lock()

    @property
    def dir(self) -> Path:
        d = str(self.cfg.get("backup.dir", "") or "").strip()
        return Path(d) if d else Path(self.cfg.data_dir) / "restore-points"

    def _pictures(self) -> Path:
        return Path(self.cfg.data_dir) / "event-images"

    # -- reading ----------------------------------------------------------------------------

    def list(self) -> list[Point]:
        out = []
        if not self.dir.exists():
            return out
        for f in self.dir.glob("vectiq-*.zip"):
            if not NAME.match(f.name):
                continue
            try:
                with zipfile.ZipFile(f) as z:
                    m = json.loads(z.read("manifest.json"))
                    files = len(z.namelist()) - 1
            except (zipfile.BadZipFile, KeyError, ValueError, OSError):
                log.warning("skipping unreadable restore point %s", f.name)
                continue
            out.append(Point(f.stem, m.get("label", ""), m.get("kind", "manual"), m.get("created_at", f.stat().st_mtime),
                             m.get("version", "?"), m.get("schema", 0), f.stat().st_size, files))
        return sorted(out, key=lambda p: p.created_at, reverse=True)

    def get(self, ident: str) -> Point | None:
        """By id, or by its number in the list (1 = newest)."""
        points = self.list()
        if ident.isdigit() and 1 <= int(ident) <= len(points):
            return points[int(ident) - 1]
        return next((p for p in points if p.id == ident), None)

    def path(self, point: Point) -> Path:
        return self.dir / f"{point.id}.zip"

    def last(self, kind: str | None = None) -> Point | None:
        return next((p for p in self.list() if kind is None or p.kind == kind), None)

    # -- making -----------------------------------------------------------------------------

    async def create(self, label: str, kind: str = "manual") -> Point:
        assert kind in KINDS
        async with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            now = time.time()
            stamp = datetime.fromtimestamp(now).strftime("%Y%m%d-%H%M%S")
            ident = f"vectiq-{stamp}-{secrets.token_hex(2)}"
            final = self.dir / f"{ident}.zip"
            with tempfile.TemporaryDirectory() as tmp:
                db_copy = Path(tmp) / "vectiq.db"
                if self.db is not None:
                    await self.db.snapshot(db_copy)
                elif Path(self.cfg.db_path).exists():
                    await asyncio.to_thread(_offline_copy, self.cfg.db_path, db_copy)
                schema = _schema(db_copy) if db_copy.exists() else 0
                from .config_io import export_yaml

                manifest = {"label": label.strip()[:200] or kind, "kind": kind, "created_at": now,
                            "version": __version__, "schema": schema,
                            "pictures": bool(self.cfg.get("backup.include_pictures", True))}
                part = final.with_suffix(".part")

                def write():
                    with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
                        z.writestr("manifest.json", json.dumps(manifest, indent=2))
                        if db_copy.exists():
                            z.write(db_copy, "vectiq.db")
                        if self.cfg.path and Path(self.cfg.path).exists():
                            z.write(self.cfg.path, "config.yaml")
                        z.writestr("settings-export.yaml", export_yaml(self.cfg))
                        if self.cfg.get("backup.include_pictures", True) and self._pictures().is_dir():
                            for pic in sorted(self._pictures().iterdir()):
                                if pic.is_file():
                                    z.write(pic, f"event-images/{pic.name}")
                    part.replace(final)
                await asyncio.to_thread(write)
            self._prune()
            point = self.get(ident)
            log.info("restore point %s: %s (%s)", ident, manifest["label"], kind)
            return point

    def _prune(self) -> None:
        """Keep the newest ``keep_automatic`` scheduled/automatic points and ``keep_manual`` manual ones."""
        points = self.list()
        auto = [p for p in points if p.kind != "manual"]
        manual = [p for p in points if p.kind == "manual"]
        for group, keep in ((auto, int(self.cfg.get("backup.keep_automatic", 14))),
                            (manual, int(self.cfg.get("backup.keep_manual", 20)))):
            for old in group[max(keep, 1):]:
                self.path(old).unlink(missing_ok=True)

    def delete(self, point: Point) -> None:
        self.path(point).unlink(missing_ok=True)

    # -- going back -------------------------------------------------------------------------

    async def rollback(self, point: Point) -> dict:
        """Go back to ``point``. Saves the current state first. Returns what changed."""
        safety = await self.create(f"Before rolling back to {point.when} ({point.label})", "automatic")
        src = self.path(point)
        result = {"undo": safety.id, "database": False, "config": False, "pictures": 0, "restart": False}
        with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(src) as z:
            names = set(z.namelist())
            if "vectiq.db" in names:
                z.extract("vectiq.db", tmp)
                if self.db is not None:
                    await self.db.restore_from(Path(tmp) / "vectiq.db")
                else:
                    await asyncio.to_thread(_offline_restore, Path(tmp) / "vectiq.db", self.cfg.db_path)
                result["database"] = True
            if "config.yaml" in names and self.cfg.path:
                new = z.read("config.yaml")
                cur = Path(self.cfg.path)
                if not cur.exists() or cur.read_bytes() != new:
                    cur.write_bytes(new)
                    result["config"] = True
            manifest = json.loads(z.read("manifest.json"))
            pics = [n for n in names if n.startswith("event-images/") and not n.endswith("/")]
            if manifest.get("pictures", bool(pics)):   # the point saved pictures: make the folder match it
                folder = self._pictures()
                if folder.exists():
                    shutil.rmtree(folder)
                folder.mkdir(parents=True, exist_ok=True)
                for n in pics:
                    (folder / Path(n).name).write_bytes(z.read(n))
                result["pictures"] = len(pics)
        result["restart"] = await self._reload_settings()
        log.warning("rolled back to restore point %s (%s); undo with %s", point.id, point.label, safety.id)
        return result

    async def _reload_settings(self) -> bool:
        """Load config.yaml and the restored dashboard settings into the running bot.

        Returns True when something only a restart can apply has changed (modules, ports...)."""
        if self.db is None:
            return False
        from .stores.dashboard import DashboardStore

        before = {m: self.cfg.enabled(m) for m in self.cfg["modules"]}
        try:
            overrides = await DashboardStore(self.db).overrides()
            self.cfg.overrides = overrides
            self.cfg.reload()
        except Exception as exc:  # noqa: BLE001 - keep running on the old settings
            log.error("rolled back, but the restored settings didn't load: %s", exc)
            return True
        return before != {m: self.cfg.enabled(m) for m in self.cfg["modules"]}


def _schema(path: Path) -> int:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return con.execute("PRAGMA user_version").fetchone()[0]
    finally:
        con.close()


def _offline_copy(src: str, dest: Path) -> None:
    a, b = sqlite3.connect(src), sqlite3.connect(str(dest))
    try:
        a.backup(b)
    finally:
        a.close()
        b.close()


def _offline_restore(src: Path, dest: str) -> None:
    if _schema(src) > len(MIGRATIONS):
        raise ValueError("that restore point is from a newer version of Vectiq")
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    _offline_copy(str(src), Path(dest))


def needs_upgrade(db_path: str) -> bool:
    """Is there a database that the next start will migrate (so a restore point is worth making)?"""
    p = Path(db_path)
    if not p.exists() or p.stat().st_size == 0:
        return False
    try:
        return 0 < _schema(p) < len(MIGRATIONS)
    except sqlite3.Error:
        return False


# -- the terminal ----------------------------------------------------------------------------

def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


async def cli(config, args) -> int:
    rp = RestorePoints(config)
    if args.list_backups:
        points = rp.list()
        if not points:
            print(f"No restore points yet in {rp.dir}.")
            return 0
        print(f"Restore points in {rp.dir} (newest first):")
        for n, p in enumerate(points, 1):
            print(f"  {n:>2}. {p.when}  {p.kind:<9}  {_size(p.size):>8}  {p.label}")
        return 0
    if args.restore:
        point = rp.get(args.restore)
        if point is None:
            print(f"No restore point {args.restore!r}. See vectiq --list-backups.")
            return 2
        print(f"Roll back to {point.when}: {point.label}?")
        print("The bot should be stopped. I'll save how things are now first, so you can undo this.")
        if not getattr(args, "yes", False) and input("Roll back? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Nothing changed.")
            return 0
        try:
            r = await rp.rollback(point)
        except ValueError as exc:
            print(f"Can't roll back: {exc}")
            return 2
        print(f"Rolled back. To undo, run: vectiq --restore {r['undo']}")
        return 0
    label = args.backup if isinstance(args.backup, str) and args.backup.strip() else "Made from the terminal"
    p = await rp.create(label, "manual")
    print(f"Made restore point {p.id} ({_size(p.size)}) in {rp.dir}")
    return 0

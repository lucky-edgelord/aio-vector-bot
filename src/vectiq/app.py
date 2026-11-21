"""The bot: wiring only. Behaviour lives in the cogs."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import vector
from vector.ext import commands

from .config import Config
from .db import Database
from .modules import CORE_COGS, REGISTRY, owner_of, prime
from .stores import Stores
from .utils.embeds import embed

log = logging.getLogger("vectiq")

# Every feature is a module in vectiq.modules.REGISTRY; only the ones switched on are imported.
COGS = tuple(("core", c) for c in CORE_COGS) + tuple((m.name, c) for m in REGISTRY for c in m.cogs)


def guard_subcommands(cog) -> None:
    """A group's checks (owner only, Manage Messages...) also protect its subcommands.

    With ``invoke_without_command=True`` the command framework (like discord.py) skips the parent's checks when a
    subcommand is used, so ``!module off music`` would skip the owner check on ``!module``. Copy them down."""
    for cmd in cog.walk_commands():
        parent = getattr(cmd, "parent", None)
        chain = []
        while parent is not None:
            chain.extend(parent.checks)
            parent = getattr(parent, "parent", None)
        for check in chain:
            if check not in cmd.checks:
                cmd.checks.insert(0, check)


class VectiqBot(commands.Bot):
    def __init__(self, config: Config, db: Database):
        super().__init__(command_prefix=config.prefix, help_command=commands.EmbedHelpCommand(),
                         data_dir=config.data_dir, intents=vector.Intents.all(),
                         webhook_base_url=config.get("webhooks.server.base_url"),
                         webhook_db=str(Path(config.data_dir) / "webhooks.db"))
        self.config = config
        self.db = db
        self.stores = Stores(db)
        self._joined_file = Path(config.data_dir) / ".joined"
        self._modules_lock = asyncio.Lock()
        self.module_problems: dict[str, str] = {}     # module -> why it isn't running although switched on

    # -- lifecycle --------------------------------------------------------------------

    async def setup_hook(self) -> None:
        await self.sync_modules()

    async def sync_modules(self) -> dict[str, list[str]]:
        """Load the modules that are switched on and unload the ones that are off, while running.

        Returns {"loaded": [...], "unloaded": [...], "problems": [...]} with module names."""
        async with self._modules_lock:
            done: dict[str, list[str]] = {"loaded": [], "unloaded": [], "problems": []}
            for cog in CORE_COGS:
                if cog not in self.extensions:
                    await self.load_extension(cog)
            want: dict[str, str] = {}
            problems: dict[str, str] = {}
            taken: dict[str, str] = {}
            for m in REGISTRY:
                if not self.config.enabled(m.name):
                    continue
                if m.slot in taken:                    # config validation stops this; be safe anyway
                    problems[m.name] = f"{taken[m.slot]} already does {m.slot}; switch one off"
                    continue
                taken[m.slot] = m.name
                if (missing := m.missing()):
                    problems[m.name] = f"needs {', '.join(missing)}: {m.install_hint()}"
                    continue
                want.update({c: m.name for c in m.cogs})
            for ext in [e for e in self.extensions if e not in CORE_COGS]:
                if ext not in want:
                    try:
                        await self.unload_extension(ext)
                        done["unloaded"].append(owner_of(ext))
                        log.info("module off: %s", owner_of(ext))
                    except Exception as exc:  # noqa: BLE001
                        log.error("could not unload %s: %s", ext, exc)
            for ext, name in want.items():
                if ext in self.extensions:
                    continue
                try:
                    prime(ext)
                    await self.load_extension(ext)
                    done["loaded"].append(name)
                    log.info("module on: %s", name)
                except Exception as exc:  # noqa: BLE001 - one broken module must not stop the others
                    problems[name] = f"failed to start: {exc}"
                    log.exception("module %s failed to start", name)
            for cog in self.cogs.values():
                guard_subcommands(cog)
            self.module_problems = problems
            done["problems"] = sorted(problems)
            for name, why in problems.items():
                log.warning("module %s is on but not running: %s", name, why)
            return done

    NATIVE_LIMIT = 64          # Vector shows at most this many slash commands per bot

    def _register_native(self, command) -> None:
        """Publish slash commands until Vector's limit; the rest keep working with the ! prefix.

        Core and the modules listed first in the registry (moderation, safety...) get the slots first."""
        reg = getattr(self, "_native_registered", {})
        name = command.native_name() if hasattr(command, "native_name") else None
        if name is not None and name not in reg and len(reg) >= self.NATIVE_LIMIT:
            if not getattr(self, "_native_full_logged", False):
                self._native_full_logged = True
                log.info("Vector allows %d slash commands; the rest (from /%s on) work with the %s prefix",
                         self.NATIVE_LIMIT, name, self.config.prefix)
            return
        super()._register_native(command)

    async def apply_settings(self) -> dict[str, list[str]]:
        """Settings changed (config.yaml, dashboard, import, rollback): tell the modules, then switch modules."""
        result = await self.sync_modules()
        self.dispatch("vectiq_config_reload")
        return result

    async def set_module(self, name: str, on: bool, by: str) -> dict[str, list[str]]:
        """Switch a module on or off from a command, kept like a dashboard change (survives restarts).

        Switching one on switches off any module filling the same slot, so this also swaps modules."""
        from .modules import same_slot

        changes = {name: on}
        if on:
            changes.update({m.name: False for m in same_slot(name) if self.config.enabled(m.name)})
        merged = dict(self.config.overrides)
        for mod, value in changes.items():
            path = f"modules.{mod}"
            if value == bool(self.config.from_file(path, False)):
                merged.pop(path, None)
            else:
                merged[path] = value
        self.config.apply_overrides(merged)
        for mod in changes:
            path = f"modules.{mod}"
            if path in merged:
                await self.stores.dashboard.set_override(path, merged[path], by)
            else:
                await self.stores.dashboard.clear_override(path)
        return await self.apply_settings()

    async def reload_module(self, name: str) -> list[str]:
        """Load a module's code again from disk (for plugin authors and updated plugins). Returns its cogs."""
        from .modules import BY_NAME, drop_bytecode

        m = BY_NAME[name]
        drop_bytecode(name)
        async with self._modules_lock:
            for ext in m.cogs:
                if ext in self.extensions:
                    await self.unload_extension(ext)
            for ext in m.cogs:
                prime(ext)
                await self.load_extension(ext)
            for cog in self.cogs.values():
                guard_subcommands(cog)
        return list(m.cogs)

    def rescan_plugins(self) -> list[str]:
        """Look for newly installed or added plugins. Returns the names of new ones."""
        from .config import plugin_dirs
        from .modules import BY_NAME, NAMES, discover

        before = set(NAMES)
        raw = {"plugins": self.config.get("plugins", {})}
        discover(plugin_dirs(raw, Path(self.config.path or "config.yaml").resolve(), self.config.data_dir), force=True)
        from .jsonmods.library import discover as discover_json

        discover_json(self.config.data_dir)
        for name in NAMES:
            if name not in before:
                self.config.data["modules"].setdefault(name, False)
                self.config.file_data.setdefault("modules", {}).setdefault(name, False)
                m = BY_NAME[name]
                if m.defaults:
                    self.config.data.setdefault(name, dict(m.defaults))
                    self.config.file_data.setdefault(name, dict(m.defaults))
        return [n for n in NAMES if n not in before]

    def when_ready(self, coro_fn) -> None:
        """Run ``coro_fn()`` once the bot is ready, or now if it already is (modules can start later)."""
        if self.is_ready():
            asyncio.get_running_loop().create_task(coro_fn())
        else:
            self.add_listener(coro_fn, "on_ready")

    async def on_ready(self) -> None:
        log.info("ready as %s in %d communities", self.user, len(self.guilds))
        await self.join_invites()

    async def close(self) -> None:
        await super().close()
        await self.db.close()

    async def join_invites(self) -> None:
        """Join each ``VECTIQ_INVITE_URLS`` community once (remembered in data/.joined)."""
        done = set(self._joined_file.read_text().split()) if self._joined_file.exists() else set()
        for url in self.config.invite_urls:
            if url in done:
                continue
            try:
                await self.join(url)
                done.add(url)
                log.info("joined %s", url[:60])
            except Exception as exc:  # noqa: BLE001 - one bad invite must not stop the bot
                log.warning("could not join an invite: %s", exc)
        self._joined_file.parent.mkdir(parents=True, exist_ok=True)
        self._joined_file.write_text("\n".join(sorted(done)))

    # -- shared helpers ---------------------------------------------------------------

    def serves(self, guild: Any) -> bool:
        """Is this community in scope (``communities`` in config.yaml; empty = all)?"""
        wanted = [str(c).lower() for c in self.config["communities"]]
        if not wanted or guild is None:
            return True
        return str(guild.id).lower() in wanted or str(getattr(guild, "name", "")).lower() in wanted

    @staticmethod
    def find_channel(guild: Any, ref: str):
        ref = str(ref).strip().lstrip("#")
        if not ref:
            return None
        for ch in guild.text_channels:
            if str(ch.id) == ref or ch.name.lower() == ref.lower():
                return ch
        # Loose match, so "mod-log" finds "🛡┊mod-log" and "announcements" finds "📣┊Announcements".
        want = "".join(c for c in ref.lower() if c.isalnum())
        if not want:
            return None
        return next((ch for ch in guild.text_channels
                     if want in "".join(c for c in ch.name.lower() if c.isalnum())), None)

    @staticmethod
    def find_role(guild: Any, ref: str):
        ref = str(ref).strip().lstrip("@")
        for role in guild.roles:
            if str(role.id) == ref or role.name.lower() == ref.lower():
                return role
        return None

    async def ensure_role(self, guild: Any, name: str):
        role = self.find_role(guild, name)
        return role or await guild.create_role(name=name, reason="Vectiq")

    def emit(self, guild: Any, kind: str, title: str, text: str = "") -> None:
        """Announce something that happened. Webhook hooks (config.yaml) subscribe to ``kind``."""
        self.dispatch("vectiq_event", guild, kind, title, text)

    async def log_to(self, guild: Any, ref: str, title: str, text: str = "") -> None:
        ch = self.find_channel(guild, ref)
        if ch is not None:
            try:
                await ch.send(embed=embed(title, text))
            except Exception as exc:  # noqa: BLE001
                log.warning("log channel send failed: %s", exc)

    async def on_command_error(self, ctx: commands.Context, error: Exception) -> None:
        error = getattr(error, "original", error)
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, (commands.CheckFailure, commands.MissingPermissions)):
            await ctx.send(f"❌ {error or 'You can not do that.'}")
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Slow down, try again in {error.retry_after:.0f}s.")
        elif isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument, commands.UserInputError)):
            usage = f"{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}".strip()
            await ctx.send(f"❌ {error}\nUsage: `{usage}`")
        else:
            log.exception("command %s failed", getattr(ctx.command, "qualified_name", "?"), exc_info=error)
            await ctx.send("❌ Something went wrong. It has been logged.")


async def build(config: Config | None = None) -> VectiqBot:
    config = config or Config.load()
    from .backup import RestorePoints, needs_upgrade

    if needs_upgrade(config.db_path):   # a new version is about to change the database: keep the old one
        try:
            await RestorePoints(config).create("Before upgrading the database", "automatic")
        except Exception as exc:  # noqa: BLE001
            log.error("couldn't make a restore point before upgrading: %s", exc)
    db = await Database(config.db_path).connect()
    overrides = await Stores(db).dashboard.overrides()
    if overrides:
        from .config import upgrade_overrides

        overrides, dropped = upgrade_overrides(overrides)
        if dropped:
            log.warning("dashboard settings no longer used, skipped: %s", ", ".join(dropped))
        try:
            config.apply_overrides(overrides)
            log.info("applied %d setting(s) changed in the dashboard", len(overrides))
        except Exception as exc:  # noqa: BLE001 - a bad saved setting must not stop the bot
            log.error("ignoring dashboard settings: %s", exc)
    return VectiqBot(config, db)

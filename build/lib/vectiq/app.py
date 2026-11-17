"""The bot: wiring only. Behaviour lives in the cogs."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import vector
from vector.ext import commands

from .config import Config
from .db import Database
from .stores import Stores
from .utils.embeds import embed

log = logging.getLogger("vectiq")

# (module name in config.yaml, python module). `core` always loads.
COGS = (
    ("core", "vectiq.cogs.core"),
    ("core", "vectiq.cogs.restorepoints"),
    ("moderation", "vectiq.cogs.moderation"),
    ("leveling", "vectiq.cogs.leveling"),
    ("economy", "vectiq.cogs.economy"),
    ("tickets", "vectiq.cogs.tickets"),
    ("verification", "vectiq.cogs.verification"),
    ("roles", "vectiq.cogs.roles"),
    ("giveaways", "vectiq.cogs.giveaways"),
    ("games", "vectiq.cogs.games"),
    ("welcome", "vectiq.cogs.welcome"),
    ("onboarding", "vectiq.cogs.onboarding"),
    ("utility", "vectiq.cogs.utility"),
    ("webhooks", "vectiq.cogs.webhooks"),
    ("events", "vectiq.cogs.events"),
    ("securitycam", "vectiq.cogs.securitycam"),
    ("dashboard", "vectiq.cogs.dashboard"),
)


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

    # -- lifecycle --------------------------------------------------------------------

    async def setup_hook(self) -> None:
        for name, module in COGS:
            if name == "core" or self.config.enabled(name):
                await self.load_extension(module)
                log.info("loaded %s", name)

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
        try:
            config.apply_overrides(overrides)
            log.info("applied %d setting(s) changed in the dashboard", len(overrides))
        except Exception as exc:  # noqa: BLE001 - a bad saved setting must not stop the bot
            log.error("ignoring dashboard settings: %s", exc)
    return VectiqBot(config, db)

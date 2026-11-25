"""Update check and one-click updater: tells the owners when a newer Vectiq exists and installs it on request."""

from __future__ import annotations

import asyncio
import logging
import time

from vector.ext import commands, tasks

from .. import updates
from ..utils.checks import is_owner
from ..utils.embeds import embed, fail, ok

log = logging.getLogger("vectiq.updates")
NOTIFIED = "updates:notified"


class Updates(commands.Cog, name="Updates"):
    """Is there a newer Vectiq, and install it."""

    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.config
        self.info: updates.UpdateInfo | None = None
        self._lock = asyncio.Lock()
        self.loop.start()

    async def cog_unload(self):
        self.loop.cancel()

    def v(self, key, default=None):
        return self.cfg.get(f"updates.{key}", default)

    async def refresh(self, force: bool = False) -> updates.UpdateInfo:
        every = float(self.v("every_hours", 12) or 12) * 3600
        if force or self.info is None or time.time() - self.info.checked_at >= every:
            self.info = await updates.check(self.v("repo", "lucky-edgelord/aio-vector-bot"))
        return self.info

    @tasks.loop(minutes=30)
    async def loop(self):
        if not self.v("check", True):
            return
        info = await self.refresh()
        if info.error or info.behind <= 0 or not self.v("notify", True):
            return
        settings = self.bot.stores.settings
        if await settings.get("", NOTIFIED, "") == info.latest:
            return
        await settings.set("", NOTIFIED, info.latest)
        text = (f"A newer Vectiq is ready ({info.current} → {info.latest}"
                f"{f', {info.behind} changes' if info.kind == 'git' else ''}). "
                f"Update from the dashboard's Updates page, or send me `{self.cfg['prefix']}update now`.")
        for owner in self.cfg.owners:
            user = self.bot.get_user(owner)
            try:
                if user is not None:
                    await user.send(text)
            except Exception as exc:  # noqa: BLE001 - closed DMs are normal
                log.debug("couldn't tell %s about the update: %s", owner, exc)

    @loop.before_loop
    async def _wait(self):
        await self.bot.wait_until_ready()

    async def install(self, who: str = "") -> tuple[bool, str]:
        """Restore point, pull, packages, restart. Shared by the chat command and the dashboard."""
        if self._lock.locked():
            return False, "An update is already running."
        async with self._lock:
            info = await self.refresh(force=True)
            if info.error:
                return False, f"Couldn't reach GitHub: {info.error}"
            if info.behind <= 0:
                return False, f"You're up to date ({info.current})."
            if not info.can_update:
                return False, info.how or "This copy can't update itself."
            points = getattr(self.bot, "restore_points", None)
            if points is not None:
                try:
                    await points.create(f"Before updating to {info.latest}", "automatic")
                except Exception as exc:  # noqa: BLE001
                    return False, f"Couldn't make a restore point first, so I didn't update: {exc}"
            good, message = await updates.apply()
            if not good:
                return False, message
            log.info("updated by %s to %s", who or "someone", info.latest)
            self.info = None
            if self.v("restart", True):
                asyncio.get_running_loop().call_later(3, updates.restart)
                return True, "Updated. Restarting in a few seconds; I'll be back shortly."
            return True, "Updated. Restart Vectiq to run the new version."

    # -- chat -----------------------------------------------------------------------------

    @commands.group(name="update", invoke_without_command=True)
    @is_owner()
    async def update(self, ctx):
        """Check for a newer Vectiq."""
        info = await self.refresh(force=True)
        if info.error:
            return await ctx.send(fail(f"Couldn't check: {info.error}"))
        if info.behind <= 0:
            return await ctx.send(ok(f"You're up to date ({info.current})."))
        fields = [("Now", info.current, True), ("Newest", info.latest, True)]
        if info.changes:
            fields.append(("What's new", "\n".join(f"• {c}" for c in info.changes[:8]), False))
        hint = f"`{ctx.prefix}update now` installs it" if info.can_update else info.how
        await ctx.send(embed=embed("A newer Vectiq is available", hint, fields=fields))

    @update.command(name="now")
    @is_owner()
    async def update_now(self, ctx):
        """Install the newest Vectiq and restart."""
        await ctx.send("⏳ Updating…")
        good, message = await self.install(str(ctx.author.id))
        await ctx.send(ok(message) if good else fail(message))


async def setup(bot):
    await bot.add_cog(Updates(bot))

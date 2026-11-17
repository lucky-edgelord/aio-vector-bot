"""Scheduled restore points, and ``!restorepoint`` for bot owners."""

from __future__ import annotations

import logging
import time

from vector.ext import commands, tasks

from ..backup import RestorePoints, _size
from ..utils.checks import is_owner
from ..utils.embeds import embed, fail, ok

log = logging.getLogger("vectiq.backup")


class RestorePointsCog(commands.Cog, name="Restore points"):
    """Restore points of the database and settings, like System Restore."""

    def __init__(self, bot):
        self.bot = bot
        self.points = RestorePoints(bot.config, bot.db)
        bot.restore_points = self.points

    async def cog_load(self):
        self.schedule.start()

    async def cog_unload(self):
        self.schedule.cancel()

    @tasks.loop(minutes=15)
    async def schedule(self):
        hours = float(self.bot.config.get("backup.every_hours", 24) or 0)
        if hours <= 0:
            return
        last = self.points.last("scheduled")
        if last is not None and time.time() - last.created_at < hours * 3600:
            return
        try:
            await self.points.create("Scheduled restore point", "scheduled")
        except Exception as exc:  # noqa: BLE001
            log.error("scheduled restore point failed: %s", exc)
            for owner in self.bot.config.owners:
                try:
                    user = self.bot.get_user(owner)
                    if user:
                        await user.send(f"⚠️ I couldn't make the scheduled restore point: {exc}")
                except Exception:  # noqa: BLE001
                    pass

    @commands.group(name="restorepoint", aliases=["restorepoints", "backup"], invoke_without_command=True)
    @is_owner()
    async def restorepoint(self, ctx):
        """List restore points, newest first."""
        points = self.points.list()[:15]
        if not points:
            return await ctx.send(ok("No restore points yet. Make one with `restorepoint create <description>`."))
        lines = [f"`{n:>2}` {p.when} · {p.kind} · {_size(p.size)}\n      {p.label}" for n, p in enumerate(points, 1)]
        await ctx.send(embed("Restore points", "\n".join(lines) +
                             "\n\nGo back with `restorepoint rollback <number>`."))

    @restorepoint.command(name="create")
    @is_owner()
    async def create(self, ctx, *, description: str = ""):
        """Make a restore point now, with a description to remember it by."""
        p = await self.points.create(description or f"Made in chat by {ctx.author.display_name}", "manual")
        await ctx.send(ok(f"Made a restore point: **{p.label}** ({_size(p.size)})."))

    @restorepoint.command(name="rollback")
    @is_owner()
    async def rollback(self, ctx, number: str, confirm: str = ""):
        """Go back to a restore point. Add `confirm` to do it."""
        p = self.points.get(number)
        if p is None:
            return await ctx.send(fail("No restore point with that number. See `restorepoint`."))
        if confirm.lower() != "confirm":
            return await ctx.send(f"This takes everything back to **{p.when}** ({p.label}). "
                                  f"I'll save how things are now first, so you can undo it.\n"
                                  f"Type `restorepoint rollback {number} confirm` to go ahead.")
        try:
            r = await self.points.rollback(p)
        except ValueError as exc:
            return await ctx.send(fail(f"Can't roll back: {exc}"))
        await self.bot.apply_settings()
        note = " Features that were switched on or off there have been switched back." if r["restart"] else ""
        await ctx.send(ok(f"Rolled back to {p.when}.{note} To undo, roll back to the newest point "
                          f"(`restorepoint rollback 1 confirm`)."))


async def setup(bot):
    await bot.add_cog(RestorePointsCog(bot))

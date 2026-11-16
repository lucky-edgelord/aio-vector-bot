"""Runs the web dashboard inside the bot's process and adds ``!dashboard`` (DMs you a sign-in link)."""

from __future__ import annotations

import asyncio
import logging

from vector.ext import commands

from ..dashboard.access import Access
from ..utils.embeds import fail, ok

log = logging.getLogger("vectiq.dashboard")


class Dashboard(commands.Cog, name="Dashboard"):
    """The web dashboard."""

    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.config
        self.access = Access(bot)
        self.app = None
        self._server = None
        self._task: asyncio.Task | None = None

    async def cog_load(self):
        try:
            import uvicorn  # noqa: F401
            from fastapi import FastAPI  # noqa: F401
        except ImportError:
            log.error("the dashboard needs FastAPI and uvicorn: pip install -e '.[dashboard]'")
            return
        from ..dashboard.server import create_app

        self.app = create_app(self.bot)
        self.bot.add_listener(self._start_once, "on_ready")

    async def cog_unload(self):
        if self._server is not None:
            self._server.should_exit = True

    async def _start_once(self):
        if self._task is not None or self.app is None:
            return
        import uvicorn

        d = self.cfg["dashboard"]
        self._server = uvicorn.Server(uvicorn.Config(self.app, host=str(d["host"]), port=int(d["port"]),
                                                     log_level="warning", proxy_headers=True,
                                                     forwarded_allow_ips="127.0.0.1"))
        self._server.install_signal_handlers = lambda: None   # the bot owns signals
        self._task = asyncio.ensure_future(self._server.serve())
        log.info("dashboard on %s:%s, open %s", d["host"], d["port"], d["base_url"])
        # Load members' names and pictures in the background so the first visit already shows them.
        self.app.state.profiles.want(m.npub for g in self.access.communities() for m in g.members)

    @commands.command(name="dashboard", aliases=["dash"])
    async def dashboard(self, ctx):
        """DM you a one-time sign-in link for the web dashboard."""
        if self.app is None:
            return await ctx.send(fail("The dashboard isn't running (FastAPI/uvicorn missing?)."))
        npub = str(ctx.author.npub)
        if not self.access.may_sign_in(npub):
            return await ctx.send(fail("The dashboard is for community admins and bot owners."))
        await self.app.state.send_link(npub)
        if ctx.guild is not None:
            await ctx.send(ok("Sent you a sign-in link by DM."))


async def setup(bot):
    await bot.add_cog(Dashboard(bot))

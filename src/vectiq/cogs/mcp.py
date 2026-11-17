"""The MCP server module: lets Claude or any MCP client manage your communities through Vectiq."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from vector.ext import commands

from ..utils.checks import is_owner
from ..utils.embeds import embed

log = logging.getLogger("vectiq.mcp")


class MCP(commands.Cog, name="MCP"):
    """Serves Vectiq's tools over MCP (Model Context Protocol) for AI assistants."""

    dashboard_page = {"label": "MCP", "icon": "⌘", "scope": "bot", "owner_only": True}

    def __init__(self, bot):
        self.bot = bot
        self._server = None
        self._task: asyncio.Task | None = None
        self.token = ""
        self.error = ""

    @property
    def cfg(self) -> dict:
        return self.bot.config.get("mcp", {})

    def url(self) -> str:
        c = self.cfg
        host = "127.0.0.1" if c["host"] in ("0.0.0.0", "::") else c["host"]
        return f"http://{host}:{c['port']}{c['path']}"

    async def cog_load(self):
        self.bot.when_ready(self._start_once)

    async def cog_unload(self):
        self.bot.remove_listener(self._start_once, "on_ready")
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._task, 5)

    async def _start_once(self):
        if self._task is not None:
            return
        try:
            import uvicorn

            from ..mcp_server import build, token_for
        except ImportError:
            self.error = 'MCP needs FastMCP: pip install "vectiq[mcp]"'
            log.error(self.error)
            return
        c = self.cfg
        self.token = token_for(self.bot.config, self.bot.config.data_dir)
        server = build(self.bot, token=self.token, read_only=bool(c.get("read_only")))
        app = server.http_app(path=c["path"])
        self._server = uvicorn.Server(uvicorn.Config(app, host=str(c["host"]), port=int(c["port"]),
                                                     log_level="warning", lifespan="on"))
        self._server.install_signal_handlers = lambda: None
        self._task = asyncio.ensure_future(self._server.serve())
        self._started_with = {k: c.get(k) for k in ("host", "port", "path", "read_only")}
        log.info("MCP server on %s (token in %s/mcp-token or $%s)", self.url(), self.bot.config.data_dir,
                 c.get("token_env") or "VECTIQ_MCP_TOKEN")

    async def restart(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._task, 5)
        self._task = None
        await self._start_once()

    @commands.Cog.listener()
    async def on_vectiq_config_reload(self):
        now = {k: self.cfg.get(k) for k in ("host", "port", "path", "read_only")}
        if getattr(self, "_started_with", None) not in (None, now):
            log.info("MCP settings changed; restarting the MCP server")
            await self.restart()

    def how_to(self) -> str:
        return (f"**Address:** `{self.url()}`\n**Token:** sent as `Authorization: Bearer <token>`. It's in "
                f"`{self.bot.config.data_dir}/mcp-token` on the bot's computer (or ${self.cfg.get('token_env')}).\n"
                "**Claude Desktop and other stdio apps:** add a server that runs `vectiq --mcp` in the bot's folder.\n"
                f"**Mode:** {'read-only' if self.cfg.get('read_only') else 'can change things'}")

    @commands.command(name="mcp")
    @is_owner()
    async def mcp_cmd(self, ctx):
        """How to connect an AI assistant to Vectiq over MCP."""
        state = "🟢 running" if self._task and not self._task.done() else f"🔴 not running {self.error}"
        await ctx.send(embed=embed("MCP", f"**State:** {state}\n" + self.how_to()))

    async def dashboard_panel(self, guild, viewer) -> dict:
        running = bool(self._task and not self._task.done())
        n = 0
        with contextlib.suppress(Exception):
            from ..mcp_server import build

            n = len(await build(self.bot, token=None, read_only=bool(self.cfg.get("read_only"))).list_tools())
        return {"title": "MCP", "subtitle": "Let Claude or another AI assistant manage your communities.",
                "sections": [
                    {"type": "status", "items": [
                        {"label": "Server", "value": "Running" if running else "Not running",
                         "tone": "green" if running else "red"},
                        {"label": "Tools", "value": n},
                        {"label": "Mode", "value": "Read-only" if self.cfg.get("read_only") else "Can change things"},
                        {"label": "Address", "value": self.url(), "mono": True}]},
                    {"type": "text", "title": "Connect",
                     "text": "Remote clients: use the address above with the header Authorization: Bearer <token>. "
                             f"The token is in {self.bot.config.data_dir}/mcp-token on the bot's computer.\n"
                             "Claude Desktop: add a server whose command is `vectiq --mcp`, run in the bot's folder; "
                             "it reads the token itself.\nEverything an assistant changes is in the audit log as "
                             "'mcp'." + (f"\n⚠️ {self.error}" if self.error else "")},
                    {"type": "actions", "items": [{"id": "rotate", "label": "New token", "kind": "danger",
                                                   "confirm": "Connected assistants stop working until they get "
                                                              "the new token.", "owner": True}]}]}

    async def dashboard_action(self, action, guild, viewer, data) -> str:
        if action != "rotate":
            raise RuntimeError("unknown action")
        from pathlib import Path

        (Path(self.bot.config.data_dir) / "mcp-token").unlink(missing_ok=True)
        await self.restart()
        return f"New token written to {self.bot.config.data_dir}/mcp-token."


async def setup(bot):
    await bot.add_cog(MCP(bot))

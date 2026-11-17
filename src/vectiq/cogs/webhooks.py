"""Webhooks declared in config.yaml.

Each entry under ``webhooks.hooks`` becomes a real webhook on the named channel. Vectiq creates the
missing ones on start (and on ``!webhooks sync``), DMs the secret URL to whoever ``notify`` names, and
mirrors the listed Vectiq events into the channel. With ``webhooks.server.enabled`` it also serves the
HTTP endpoint so outside tools (GitHub, Grafana, CI...) can post to those URLs.
"""

from __future__ import annotations

import asyncio
import logging
import os

from vector.ext import commands

from ..utils.checks import is_owner
from ..utils.embeds import embed, fail, ok, short

log = logging.getLogger("vectiq.webhooks")
EVENT_KINDS = ("mod", "joins", "leaves", "levels", "tickets", "giveaways", "games", "onboarding", "events")


class Webhooks(commands.Cog, name="Webhooks"):
    """Create and manage webhooks from config.yaml."""

    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.config
        self._server = None
        self._server_task: asyncio.Task | None = None
        self._resolved: dict[str, tuple] = {}     # hook name -> (guild, channel)
        self._synced = False

    # -- lifecycle --------------------------------------------------------------------

    async def cog_load(self):
        self.bot.when_ready(self._on_ready_once)

    async def cog_unload(self):
        self.bot.remove_listener(self._on_ready_once, "on_ready")
        if self._server is not None:
            self._server.should_exit = True

    async def _on_ready_once(self):
        if self._synced:
            return
        self._synced = True
        await self.sync()
        if self.cfg.get("webhooks.server.enabled"):
            await self._start_server()

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        """The first start joins the community *after* on_ready, so hooks for it are set up here."""
        for _ in range(4):
            await asyncio.sleep(5)
            if not any("not found" in line for line in await self.sync()):
                return

    async def _start_server(self):
        try:
            import uvicorn
            from vector.ext.webhooks import create_app
        except ImportError:
            log.error("webhooks.server.enabled needs: pip install 'vector-sdk-py[webhooks]'")
            return
        s = self.cfg["webhooks"]["server"]
        key = os.environ.get(s.get("admin_key_env", "WEBHOOKS_ADMIN_KEY")) or None
        app = create_app(self.bot, self.bot.webhook_store, admin_key=key, base_url=s["base_url"])
        self._server = uvicorn.Server(uvicorn.Config(app, host=s["host"], port=int(s["port"]), log_level="warning"))
        self._server_task = asyncio.ensure_future(self._server.serve())
        log.info("webhook server on %s:%s (public %s)", s["host"], s["port"], s["base_url"])

    # -- sync -------------------------------------------------------------------------

    def _guild_for(self, hook: dict):
        ref = str(hook.get("community", "")).strip().lower()
        guilds = [g for g in self.bot.guilds if self.bot.serves(g)]
        if not ref:
            return guilds[0] if guilds else None
        return next((g for g in guilds if str(g.id).lower() == ref or g.name.lower() == ref), None)

    async def sync(self) -> list[str]:
        """Create what is missing. Returns human-readable lines about what happened."""
        report: list[str] = []
        store = self.bot.webhook_store
        self._resolved.clear()
        for hook in self.cfg.hooks:
            name = hook["name"]
            guild = self._guild_for(hook)
            channel = self.bot.find_channel(guild, hook["channel"]) if guild else None
            if channel is None:
                report.append(f"⚠️ {name}: channel {hook['channel']!r} not found")
                continue
            self._resolved[name] = (guild, channel)
            if any(w.name == name for w in store.list(channel_id=str(channel.id))):
                report.append(f"• {name}: already set up in #{channel.name}")
                continue
            wh = await channel.create_webhook(name=name)
            report.append(f"✅ {name}: created in #{channel.name}")
            await self._deliver(hook, guild, name, channel, wh.url)
        for line in report:
            log.info(line)
        return report

    async def _deliver(self, hook: dict, guild, name: str, channel, url: str) -> None:
        """The URL is a secret and shown once, so it goes by DM to the people ``notify`` names."""
        targets = []
        for who in hook.get("notify", ["owners"]):
            targets.extend(self.cfg.owners if who == "owners" else [str(who)])
        text = (f"**Webhook “{name}”** for #{channel.name} in {guild.name}\n`{url}`\n"
                "Use it anywhere a Discord webhook URL works. Keep it secret.")
        sent = 0
        for npub in dict.fromkeys(targets):
            try:
                user = self.bot.get_user(npub) or await self.bot.fetch_user(npub)
                await user.send(text)
                sent += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("could not DM webhook %s to %s: %s", name, short(npub), exc)
        if not sent:
            log.warning("webhook %s was created but nobody was told its URL; run `!webhooks rotate %s`", name, name)

    # -- mirroring Vectiq events ------------------------------------------------------

    @commands.Cog.listener()
    async def on_vectiq_event(self, guild, kind: str, title: str, text: str = ""):
        for hook in self.cfg.hooks:
            if kind not in hook.get("events", []):
                continue
            target = self._resolved.get(hook["name"])
            if target and str(target[0].id) == str(guild.id):
                try:
                    await target[1].send(embed=embed(title, text, footer=f"{hook['name']} · {kind}"))
                except Exception as exc:  # noqa: BLE001
                    log.warning("mirror to %s failed: %s", hook["name"], exc)

    # -- commands ---------------------------------------------------------------------

    @commands.group(name="webhooks", invoke_without_command=True)
    @is_owner()
    async def webhooks(self, ctx):
        """Hooks declared in config.yaml."""
        rows = []
        for hook in self.cfg.hooks:
            target = self._resolved.get(hook["name"])
            where = f"#{target[1].name}" if target else "⚠️ channel not found"
            rows.append(f"**{hook['name']}** → {where} · events: {', '.join(hook.get('events', [])) or 'none'}")
        await ctx.send(embed=embed("Webhooks", "\n".join(rows) or "None declared. Add some under `webhooks.hooks` "
                                   "in config.yaml, then `webhooks sync`."))

    @webhooks.command(name="sync")
    @is_owner()
    async def sync_(self, ctx):
        """Re-read config.yaml and create any missing hooks."""
        from ..config import ConfigError

        try:
            self.cfg.reload()
        except ConfigError as exc:
            return await ctx.send(fail(str(exc)))
        await ctx.send("\n".join(await self.sync()) or "No hooks declared.")

    @webhooks.command(name="rotate")
    @is_owner()
    async def rotate(self, ctx, name: str):
        """Make a fresh URL for a declared hook (the old one stops working) and DM it."""
        hook = next((h for h in self.cfg.hooks if h["name"] == name), None)
        target = self._resolved.get(name)
        if hook is None or target is None:
            return await ctx.send(fail("No such hook, or its channel was not found."))
        url = await self.rotate_url(name)
        try:
            await ctx.author.send(f"**{name}** → `{url}`")
        except Exception:  # noqa: BLE001
            return await ctx.send(fail("Made a new hook but couldn't DM you the URL."))
        await ctx.send(ok("New URL sent to your DMs."))

    async def rotate_url(self, name: str) -> str:
        """Replace a declared hook with a fresh one and return its URL (the old URL stops working)."""
        guild, channel = self._resolved[name]
        for w in self.bot.webhook_store.list(channel_id=str(channel.id)):
            if w.name == name:
                self.bot.webhook_store.delete(w.id)
        wh = await channel.create_webhook(name=name)
        return wh.url

    def status(self) -> list[dict]:
        """Declared hooks and where they resolved, for the dashboard."""
        out = []
        for hook in self.cfg.hooks:
            target = self._resolved.get(hook["name"])
            out.append({"name": hook["name"], "channel": hook["channel"], "events": hook.get("events", []),
                        "community": str(target[0].id) if target else None,
                        "channel_id": str(target[1].id) if target else None,
                        "channel_name": target[1].name if target else None})
        return out

    @webhooks.command(name="test")
    @is_owner()
    async def test(self, ctx, name: str):
        """Post a test message through a hook's channel."""
        target = self._resolved.get(name)
        if target is None:
            return await ctx.send(fail("No such hook."))
        await target[1].send(embed=embed("Vectiq webhook test", f"Hook **{name}** is wired up."))
        await ctx.send(ok("Sent."))


async def setup(bot):
    await bot.add_cog(Webhooks(bot))

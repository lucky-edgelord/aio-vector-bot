"""Sentire as a module: Vectiq runs the Sentire moderation bot beside itself and manages it."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from pathlib import Path

from vector.ext import commands

from ..sentire import config as sconf
from ..sentire.install import build, find_binary, home, identity
from ..sentire.process import Sidecar
from ..sentire.roles import invite_and_grant, permissions
from ..utils.checks import is_owner
from ..utils.embeds import embed, fail, ok

log = logging.getLogger("vectiq.sentire")


def ago(seconds: float) -> str:
    s = int(seconds)
    if s >= 86400:
        return f"{s // 86400}d {s % 86400 // 3600}h"
    if s >= 3600:
        return f"{s // 3600}h {s % 3600 // 60}m"
    if s >= 60:
        return f"{s // 60}m {s % 60}s"
    return f"{s}s"


class Sentire(commands.Cog, name="Sentire"):
    """Runs the Sentire moderation bot (VectorPrivacy/Sentire) beside Vectiq."""

    def __init__(self, bot):
        self.bot = bot
        self.sidecar: Sidecar | None = None
        self.note = "starting…"
        self.building = False
        self.notes: deque[str] = deque(maxlen=100)      # what Vectiq did while Sentire wasn't running
        self.bot.when_ready(self.boot)

    async def cog_unload(self):
        self.bot.remove_listener(self.boot, "on_ready")
        if self.sidecar is not None:
            await self.sidecar.stop()

    @property
    def cfg(self) -> dict:
        return sconf.deep_merge(sconf.DEFAULTS, self.bot.config.get("sentire", {}) or {})

    @property
    def dir(self) -> Path:
        return home(self.bot.config.data_dir)

    def communities(self) -> list[str]:
        """Community ids for sentinel.toml: the configured ones, or every community Vectiq serves."""
        wanted = [str(x).lower() for x in self.cfg["communities"] or []]
        out = []
        for g in self.bot.guilds:
            if not self.bot.serves(g):
                continue
            if not wanted or str(g.id).lower() in wanted or str(g.name).lower() in wanted:
                out.append(str(g.id))
        return out or ["*"]

    def mod_channel(self) -> str:
        ref = self.cfg["mod_channel"] or self.bot.config.get("moderation.log_channel", "")
        if not ref:
            return ""
        for g in self.bot.guilds:
            ch = self.bot.find_channel(g, ref)
            if ch is not None:
                return ch.name
        return str(ref)

    def config_path(self) -> Path:
        own = self.cfg["config_file"]
        return Path(own).expanduser().resolve() if own else self.dir / "sentinel.toml"

    def write_config(self) -> bool:
        if self.cfg["config_file"]:
            return False
        data = sconf.build(self.cfg, communities=self.communities(), mod_channel=self.mod_channel())
        return sconf.write(self.config_path(), data)

    async def boot(self):
        if self.sidecar is not None and self.sidecar.running:
            return
        binary = find_binary(self.cfg["binary"], self.bot.config.data_dir)
        if binary is None:
            self.note = ("Sentire isn't installed yet. Run `vectiq --install-sentire` on the bot's computer "
                         "(or `!sentire install` as an owner, if plugins.allow_install is on).")
            log.warning("sentire: %s", self.note)
            return
        if (bad := sconf.problems(self.cfg)):
            self.note = "; ".join(bad)
            log.error("sentire: settings refused: %s", self.note)
            return
        nsec = identity(self.bot.config.data_dir)
        self.write_config()
        self.sidecar = Sidecar(binary, self.config_path(), {sconf.NSEC_ENV: nsec, "HOME": str(self.dir)},
                               keep=int(self.cfg["log_lines"]))
        self.sidecar.start()
        self.note = ""

    @commands.Cog.listener()
    async def on_vectiq_config_reload(self):
        if self.sidecar is None:
            return await self.boot()
        if self.write_config() and self.sidecar.running:
            self.sidecar._say("[vectiq] settings changed; restarting Sentire")
            await self.sidecar.restart()

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        if self.sidecar is not None and not self.cfg["communities"] and self.write_config():
            await self.sidecar.restart()

    # -- shared with the dashboard -----------------------------------------------------------

    def status(self) -> dict:
        sc = self.sidecar
        c = self.cfg
        return {"running": bool(sc and sc.running), "npub": sc.npub if sc else "", "pid": sc.proc.pid if sc and
                sc.running and sc.proc else None, "uptime": sc.uptime() if sc else 0, "restarts": sc.restarts if sc
                else 0, "error": (sc.last_error if sc else "") or self.note, "building": self.building,
                "binary": str(find_binary(c["binary"], self.bot.config.data_dir) or ""),
                "config": str(self.config_path()), "own_config": bool(c["config_file"]),
                "armed": [k for k, v in c["arm"].items() if v], "communities": self.communities(),
                "vision": bool(c["vision"]["enabled"]), "log": list(sc.lines) if sc else list(self.notes)}

    def perms(self):
        arm = self.cfg["arm"]
        return permissions(arm["delete"] or arm["warn"], arm["kick"] or arm["raid"],
                           arm["ban"] or (arm["raid"] and self.cfg["raid"]["response"] == "ban"))

    async def invite(self, guild) -> str:
        """Invite this Sentire into ``guild`` and give it a role with what its armed actions need."""
        sc = self.sidecar
        if sc is None or not sc.npub:
            raise RuntimeError("Sentire isn't running yet, so I don't know its Vector ID")
        await invite_and_grant(guild, sc.npub, self.cfg["name"] or "Sentire", self.perms())
        if self.cfg["communities"] and str(guild.id) not in self.communities() and self.write_config():
            await sc.restart()
        return sc.npub

    async def install(self, say) -> Path:
        if self.building:
            raise RuntimeError("a build is already running")
        self.building = True
        loop = asyncio.get_running_loop()
        try:
            out = await asyncio.to_thread(build, self.bot.config.data_dir,
                                          log=lambda m: asyncio.run_coroutine_threadsafe(say(m), loop))
        finally:
            self.building = False
        if self.sidecar is not None:
            await self.sidecar.stop()
            self.sidecar = None
        await self.boot()
        return out

    # -- dashboard page (the general module panel) ---------------------------------------------

    dashboard_page = {"label": "Sentire", "icon": "⛨", "scope": "community"}

    async def dashboard_panel(self, guild, viewer) -> dict:
        st = self.status()
        if st["running"]:
            state, tone = f"Running · {ago(st['uptime'])}", "green"
        elif st["building"]:
            state, tone = "Building…", "yellow"
        else:
            state, tone = "Not running", "red"
        here = guild is not None and (str(guild.id) in st["communities"] or st["communities"] == ["*"])
        joined = bool(guild is not None and st["npub"] and hasattr(guild, "get_member") and guild.get_member(st["npub"]))
        sections: list[dict] = [
            {"type": "status", "items": [
                {"label": "Sentire", "value": state, "tone": tone},
                {"label": "In this community", "value": "Joined" if joined else "Not joined", "tone":
                 "green" if joined else "yellow"},
                {"label": "Watching here", "value": "Yes" if here else "No", "tone": "green" if here else "yellow"},
                {"label": "Armed", "value": ", ".join(st["armed"]) or "Nothing: watches and reports",
                 "tone": "green" if st["armed"] else ""},
                {"label": "Pictures", "value": "Vision model" if st["vision"] else "Not checked"},
                {"label": "Restarts", "value": st["restarts"]},
            ]},
        ]
        if st["npub"]:
            sections[0]["items"].append({"label": "Vector ID", "value": st["npub"], "mono": True})
        if st["error"]:
            sections.append({"type": "text", "tone": "warn", "text": st["error"]})
        actions = []
        if st["running"] and not joined:
            actions.append({"id": "invite", "label": "Invite Sentire here", "kind": "primary",
                            "confirm": "Vectiq invites Sentire into this community and gives it a role for what it's "
                                       "armed to do."})
        actions.append({"id": "restart", "label": "Restart", "owner": True})
        if not st["building"]:
            actions.append({"id": "install", "label": "Update Sentire" if st["binary"] else "Install Sentire",
                            "owner": True, "confirm": "Downloads Sentire's source and builds it with cargo. Takes a "
                                                     "few minutes the first time."})
        sections.append({"type": "actions", "items": actions})
        sections.append({"type": "text", "title": "Settings",
                         "text": "Sentire's rules, ladder, raid response and vision model are under Settings → "
                                 "Sentire. Changes restart it with the new sentinel.toml."
                                 + (f"\nUsing your own file: {st['config']}" if st["own_config"] else "")})
        sections.append({"type": "log", "title": "Sentire's log", "lines": st["log"][-200:]})
        return {"title": "Sentire", "subtitle": "The Sentire moderation bot, run and supervised by Vectiq.",
                "refresh": 5, "sections": sections}

    async def dashboard_action(self, action: str, guild, viewer, data: dict) -> str:
        if action == "invite":
            await self.invite(guild)
            return "Invited. I'll give it its role when it joins."
        if action == "restart":
            if self.sidecar is None:
                await self.boot()
            else:
                self.write_config()
                await self.sidecar.restart()
            return "Restarting Sentire."
        if action == "install":
            if not self.bot.config.get("plugins.allow_install", False):
                raise RuntimeError("Building from the dashboard is off. Run `vectiq --install-sentire` on the bot's "
                                   "computer, or turn on Settings → Plugins → install from chat.")
            asyncio.get_running_loop().create_task(self.install(self._log_note))
            return "Building Sentire. Follow along in the log."
        raise RuntimeError("unknown action")

    async def _log_note(self, text: str) -> None:
        if self.sidecar is not None:
            self.sidecar._say(f"[vectiq] {text}")
        else:
            self.notes.append(f"{time.strftime('%H:%M:%S')} [vectiq] {text}")
            log.info("sentire: %s", text)

    # -- commands --------------------------------------------------------------------------

    @commands.group(name="sentire", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def sentire(self, ctx):
        """Is Sentire running, and what is it allowed to do?"""
        s = self.status()
        state = "🟢 running" if s["running"] else ("🛠️ building" if s["building"] else "🔴 not running")
        lines = [f"**State:** {state}" + (f" for {ago(s['uptime'])}" if s["running"] else "")
                 + (f" · {s['restarts']} restarts" if s["restarts"] else "")]
        if s["npub"]:
            lines.append(f"**Vector ID:** `{s['npub']}`")
        lines.append(f"**Armed:** {', '.join(s['armed']) or 'nothing (it only watches and reports)'}")
        lines.append(f"**Pictures:** {'checked by a vision model' if s['vision'] else 'not checked'}")
        here = str(ctx.guild.id) in s["communities"] or s["communities"] == ["*"]
        lines.append(f"**This community:** {'watched' if here else 'not watched'}")
        if s["error"]:
            lines.append(f"⚠️ {s['error']}")
        lines.append("\n`sentire invite` · `sentire log` · `sentire restart` · settings on the dashboard")
        await ctx.send(embed=embed("Sentire", "\n".join(lines)))

    @sentire.command(name="invite")
    async def invite_cmd(self, ctx):
        """Invite Sentire into this community and give it a role for what it's armed to do."""
        try:
            npub = await self.invite(ctx.guild)
        except Exception as exc:  # noqa: BLE001
            return await ctx.send(fail(str(exc)))
        await ctx.send(ok(f"Invited Sentire (`{npub[:20]}…`). When it joins I'll give it the **{self.cfg['name']}** "
                          "role. Check its permissions under community settings."))

    @sentire.command(name="log", aliases=["logs"])
    async def log_cmd(self, ctx, lines: int = 15):
        """The last lines Sentire printed."""
        tail = self.status()["log"][-max(1, min(lines, 40)):]
        await ctx.send("```\n" + ("\n".join(tail) or "nothing yet")[-1800:] + "\n```")

    @sentire.command(name="restart")
    @is_owner()
    async def restart_cmd(self, ctx):
        """Start Sentire again."""
        if self.sidecar is None:
            await self.boot()
        else:
            self.write_config()
            await self.sidecar.restart()
        await ctx.send(ok("Restarting Sentire.") if self.sidecar else fail(self.note))

    @sentire.command(name="install", aliases=["update"])
    @is_owner()
    async def install_cmd(self, ctx):
        """Download and build Sentire with cargo (needs plugins.allow_install)."""
        if not self.bot.config.get("plugins.allow_install", False):
            return await ctx.send(fail("Building from chat is off. Run `vectiq --install-sentire` on the bot's "
                                       "computer, or set plugins.allow_install: true."))
        await ctx.send("🛠️ Building Sentire. This takes a few minutes the first time…")
        started = time.time()
        try:
            path = await self.install(lambda m: ctx.send(f"… {m}"))
        except Exception as exc:  # noqa: BLE001
            return await ctx.send(fail(f"Build failed: {str(exc)[-400:]}"))
        await ctx.send(ok(f"Sentire built in {ago(time.time() - started)} ({path}) and started."))


async def setup(bot):
    await bot.add_cog(Sentire(bot))

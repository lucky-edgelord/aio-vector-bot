from __future__ import annotations

import asyncio

from vector.ext import commands

from .. import __version__, modules
from ..utils.checks import is_owner
from ..utils.embeds import embed


def _summary(r: dict) -> str:
    on, off, bad = r.get("loaded", []), r.get("unloaded", []), r.get("problems", [])
    return ((f" Switched on: {', '.join(on)}." if on else "") + (f" Switched off: {', '.join(off)}." if off else "")
            + (f" On but not running: {', '.join(bad)} (see `modules`)." if bad else ""))


class Core(commands.Cog, name="Core"):
    """Bot-level commands."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def about(self, ctx):
        """What this bot is."""
        on = [m for m in self.bot.config["modules"] if self.bot.config.enabled(m)]
        await ctx.send(embed=embed(f"Vectiq {__version__}", "Community management for Vector, on SQLite.",
                                   fields=[("Modules", ", ".join(on), False),
                                           ("Communities", str(len(self.bot.guilds)), True),
                                           ("Prefix", self.bot.config.prefix, True)]))

    @commands.command()
    async def ping(self, ctx):
        """Check the bot is alive."""
        await ctx.send("🏓 pong")

    @commands.group(name="vectiq", invoke_without_command=True)
    @is_owner()
    async def vectiq(self, ctx):
        """Owner tools."""
        await ctx.send("`vectiq reload` · `vectiq stats`")

    @vectiq.command(name="reload")
    async def reload_(self, ctx):
        """Re-read config.yaml and switch modules on or off to match. No restart needed."""
        from ..config import ConfigError

        before = set(modules.NAMES)
        try:
            self.bot.config.reload()
        except ConfigError as exc:
            await ctx.send(f"❌ {exc}")
            return
        self.bot.command_prefix = self.bot.config.prefix
        self.bot.rescan_plugins()
        new = [n for n in modules.NAMES if n not in before]
        r = await self.bot.apply_settings()
        found = f" New modules: {', '.join(new)}." if new else ""
        await ctx.send("✅ config.yaml reloaded." + _summary(r) + found)

    # -- modules ------------------------------------------------------------------------

    @commands.command(name="modules", aliases=["features"])
    async def modules_(self, ctx):
        """Every feature, and whether it's on. Plugins are marked 🧩."""
        problems = getattr(self.bot, "module_problems", {})
        parts = []
        for group in modules.GROUPS:
            lines = []
            for m in (x for x in modules.REGISTRY if x.group == group):
                if m.name in problems:
                    mark = "🟠"
                elif self.bot.config.enabled(m.name):
                    mark = "🟢"
                else:
                    mark = "⚪"
                tags = (" 🧩" if not m.builtin else "") + (f" (does {m.slot})" if m.slot != m.name else "")
                note = f" — {problems[m.name]}" if m.name in problems else ""
                lines.append(f"{mark} **{m.label}** `{m.name}`{tags}{note}")
            if lines:
                parts.append(f"__{group}__\n" + "\n".join(lines))
        broken = [f"⚠️ {where}: {why}" for where, why in modules.PROBLEMS.items()]
        if broken:
            parts.append("__Plugins that couldn't load__\n" + "\n".join(broken[:8]))
        await ctx.send(embed=embed("Modules", "\n\n".join(parts) + "\n\nOwners: `module on|off|info|reload|scan "
                                   "<name>`" + (" · `module install <package>`" if self._can_install() else "")))

    @commands.group(name="module", invoke_without_command=True)
    @is_owner()
    async def module(self, ctx):
        """Switch, swap, reload and install modules."""
        await ctx.send("`module on <name>` · `module off <name>` · `module info <name>` · `module reload <name>` · "
                       "`module scan` · `module install <package>` · `module uninstall <name>`")

    @module.command(name="on")
    async def module_on(self, ctx, name: str):
        """Switch a module on now. A module that does the same job is switched off (a swap)."""
        await self._switch(ctx, name, True)

    @module.command(name="off")
    async def module_off(self, ctx, name: str):
        """Switch a module off now."""
        await self._switch(ctx, name, False)

    @module.command(name="info")
    async def module_info(self, ctx, name: str):
        """Where a module comes from, what it does and what it replaces."""
        m = modules.get(name.lower())
        if m is None:
            return await ctx.send(f"❌ No module called `{name}`. See `modules`.")
        rivals = ", ".join(f"`{x.name}`" for x in modules.same_slot(m.name)) or "none"
        lines = [m.help, "", f"**Status:** {'on' if self.bot.config.enabled(m.name) else 'off'}",
                 f"**Source:** {m.source}" + (f" · v{m.version}" if m.version else "")
                 + (f" · by {m.author}" if m.author else ""),
                 f"**Job:** {m.slot} (alternatives: {rivals})"]
        if m.missing():
            lines.append(f"**Needs:** {', '.join(m.missing())} → `{m.install_hint()}`")
        await ctx.send(embed=embed(m.label, "\n".join(lines)))

    @module.command(name="reload")
    async def module_reload(self, ctx, name: str):
        """Load a module's code again from disk, without restarting the bot."""
        m = modules.get(name.lower())
        if m is None:
            return await ctx.send(f"❌ No module called `{name}`.")
        if not self.bot.config.enabled(m.name):
            return await ctx.send(f"❌ {m.label} is off. `module on {m.name}` loads it.")
        try:
            await self.bot.reload_module(m.name)
        except Exception as exc:  # noqa: BLE001
            return await ctx.send(f"❌ {m.label} didn't reload: {exc}")
        await ctx.send(f"🔄 {m.label} reloaded.")

    @module.command(name="scan")
    async def module_scan(self, ctx):
        """Look for plugins added to the modules folder or installed with pip."""
        new = self.bot.rescan_plugins()
        if not new:
            return await ctx.send("No new modules found." + (" Some plugins couldn't load: see `modules`."
                                                             if modules.PROBLEMS else ""))
        await ctx.send("🧩 Found: " + ", ".join(f"**{modules.get(n).label}** `{n}`" for n in new)
                       + ". Switch one on with `module on <name>`.")

    def _can_install(self) -> bool:
        return bool(self.bot.config.get("plugins.allow_install", False))

    @module.command(name="install")
    async def module_install(self, ctx, *, package: str):
        """Install a plugin package with pip (only if plugins.allow_install is on)."""
        from ..plugin_install import InstallError, install

        if not self._can_install():
            return await ctx.send("❌ Installing from chat is off. Run `vectiq --install-module <package>` on the "
                                  "bot's computer, or set `plugins.allow_install: true` in config.yaml.")
        await ctx.send(f"📦 Installing `{package}`…")
        try:
            await asyncio.to_thread(install, package)
        except InstallError as exc:
            return await ctx.send(f"❌ Install failed: {str(exc)[-500:]}")
        new = self.bot.rescan_plugins()
        if not new:
            return await ctx.send("✅ Installed, but it didn't add a new module. If it updated one, `module reload "
                                  "<name>` loads the new code.")
        await ctx.send("✅ Installed: " + ", ".join(f"**{modules.get(n).label}** `{n}`" for n in new)
                       + ". Switch it on with `module on <name>`.")

    @module.command(name="uninstall")
    async def module_uninstall(self, ctx, name: str):
        """Switch off and uninstall a plugin package (only if plugins.allow_install is on)."""
        from ..plugin_install import InstallError, uninstall

        if not self._can_install():
            return await ctx.send("❌ Uninstalling from chat is off (`plugins.allow_install`).")
        m = modules.get(name.lower())
        if m is None or m.builtin:
            return await ctx.send("❌ Only plugins can be uninstalled. Built-in modules can be switched off.")
        if self.bot.config.enabled(m.name):
            await self.bot.set_module(m.name, False, str(ctx.author.id))
        try:
            await asyncio.to_thread(uninstall, m.name)
        except InstallError as exc:
            return await ctx.send(f"❌ {exc}")
        await ctx.send(f"🗑️ {m.label} uninstalled.")

    async def _switch(self, ctx, name: str, on: bool):
        m = modules.get(name.lower())
        if m is None:
            return await ctx.send(f"❌ No module called `{name}`. See `modules`, or `module scan` for new plugins.")
        if on and m.missing():
            return await ctx.send(f"❌ {m.label} needs {', '.join(m.missing())}. Install it with `{m.install_hint()}`, "
                                  "then try again.")
        replaced = [x.label for x in modules.same_slot(m.name) if self.bot.config.enabled(x.name)] if on else []
        r = await self.bot.set_module(m.name, on, str(ctx.author.id))
        if m.name in r["problems"]:
            return await ctx.send(f"⚠️ {m.label} is on but didn't start: {self.bot.module_problems.get(m.name)}")
        swap = f" It replaces {', '.join(replaced)}, which is now off." if replaced else ""
        await ctx.send(f"✅ {m.label} is {'on' if on else 'off'}.{swap}")

    @vectiq.command(name="stats")
    async def stats_(self, ctx):
        """Database size and row counts."""
        db = self.bot.db
        counts = []
        for table in ("mod_cases", "levels", "wallets", "tickets", "giveaways", "game_stats"):
            counts.append((table, str(await db.scalar(f"SELECT COUNT(*) FROM {table}", default=0)), True))
        await ctx.send(embed=embed("Vectiq database", f"schema v{db.version}", fields=counts))


async def setup(bot):
    await bot.add_cog(Core(bot))

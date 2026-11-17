from __future__ import annotations

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

        try:
            self.bot.config.reload()
        except ConfigError as exc:
            await ctx.send(f"❌ {exc}")
            return
        self.bot.command_prefix = self.bot.config.prefix
        r = await self.bot.apply_settings()
        await ctx.send("✅ config.yaml reloaded." + _summary(r))

    # -- modules ------------------------------------------------------------------------

    @commands.command(name="modules", aliases=["features"])
    async def modules_(self, ctx):
        """Every feature, and whether it's on."""
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
                note = f" — {problems[m.name]}" if m.name in problems else ""
                lines.append(f"{mark} **{m.label}** `{m.name}`{note}")
            parts.append(f"__{group}__\n" + "\n".join(lines))
        await ctx.send(embed=embed("Modules", "\n\n".join(parts) + "\n\nOwners: `module on <name>` · `module off <name>`"))

    @commands.group(name="module", invoke_without_command=True)
    @is_owner()
    async def module(self, ctx):
        """Switch a feature on or off: `module on automod`, `module off games`."""
        await ctx.send("`module on <name>` · `module off <name>` · see `modules` for names")

    @module.command(name="on")
    async def module_on(self, ctx, name: str):
        """Switch a module on now."""
        await self._switch(ctx, name, True)

    @module.command(name="off")
    async def module_off(self, ctx, name: str):
        """Switch a module off now."""
        await self._switch(ctx, name, False)

    async def _switch(self, ctx, name: str, on: bool):
        m = modules.get(name.lower())
        if m is None:
            return await ctx.send(f"❌ No module called `{name}`. See `modules`.")
        if on and m.missing():
            return await ctx.send(f"❌ {m.label} needs {', '.join(m.missing())}. Install it with `{m.install_hint()}`, "
                                  "then try again.")
        r = await self.bot.set_module(m.name, on, str(ctx.author.id))
        if m.name in r["problems"]:
            return await ctx.send(f"⚠️ {m.label} is on but didn't start: {self.bot.module_problems.get(m.name)}")
        await ctx.send(f"✅ {m.label} is {'on' if on else 'off'}.")

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

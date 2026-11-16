from __future__ import annotations

from vector.ext import commands

from .. import __version__
from ..utils.checks import is_owner
from ..utils.embeds import embed


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
        """Re-read config.yaml (module toggles need a restart)."""
        from ..config import Config, ConfigError

        try:
            fresh = Config.load(self.bot.config.path)
        except ConfigError as exc:
            await ctx.send(f"❌ {exc}")
            return
        fresh.nsec = self.bot.config.nsec
        self.bot.config.data = fresh.data
        self.bot.dispatch("vectiq_config_reload")
        await ctx.send("✅ config.yaml reloaded. Turning a module on or off needs a restart.")

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

from __future__ import annotations

import vector
from vector.ext import commands

from ..utils.embeds import embed, fail, name_of, short

NUMBERS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]


class Utility(commands.Cog, name="Utility"):
    """Info commands, polls and community analytics."""

    def __init__(self, bot):
        self.bot = bot
        self.activity = bot.stores.activity

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild is not None and not message.author.bot and self.bot.serves(message.guild):
            await self.activity.bump(str(message.guild.id), str(message.channel.id), messages=1)

    @commands.command(aliases=["whois"])
    @commands.guild_only()
    async def userinfo(self, ctx, member: vector.Member = None):
        """About a member."""
        m = member or ctx.author
        roles = [r.name for r in m.roles if r != ctx.guild.default_role]
        await ctx.send(embed=embed(name_of(m), fields=[
            ("ID", short(m.id), True), ("Bot", "yes" if m.bot else "no", True),
            ("Roles", ", ".join(roles) or "none", False)]))

    @commands.command(aliases=["serverinfo", "community"])
    @commands.guild_only()
    async def communityinfo(self, ctx):
        """About this community."""
        g = ctx.guild
        await ctx.send(embed=embed(g.name, fields=[
            ("Members", str(g.member_count), True), ("Channels", str(len(g.text_channels)), True),
            ("Roles", str(len(g.roles)), True)]))

    @commands.command()
    @commands.guild_only()
    async def poll(self, ctx, *, spec: str):
        """`poll Best colour? | Red | Green | Blue` (up to 9 options)."""
        question, *options = (p.strip() for p in spec.split("|"))
        if not 2 <= len(options) <= 9 or not question:
            return await ctx.send(fail("A question and 2 to 9 options, separated by |."))
        msg = await ctx.send(embed=embed(f"📊 {question}", "\n".join(f"{NUMBERS[i]} {o}" for i, o in enumerate(options))))
        for i in range(len(options)):
            await msg.add_reaction(NUMBERS[i])

    @commands.command(aliases=["activity"])
    @commands.guild_only()
    async def analytics(self, ctx, days: int = 7):
        """Messages, joins and leaves per day, and the busiest channels."""
        days = min(max(days, 1), 30)
        rows = await self.activity.daily(str(ctx.guild.id), days)
        if not rows:
            return await ctx.send("No activity recorded yet.")
        top = await self.activity.top_channels(str(ctx.guild.id))
        busiest = []
        for r in top:
            ch = ctx.guild.get_channel(r["channel_id"])
            busiest.append(f"#{ch.name if ch else short(r['channel_id'])}: {r['m']}")
        peak = max(r["m"] or 0 for r in rows) or 1
        lines = [f"`{r['day']}` {'▇' * max(1, round(10 * (r['m'] or 0) / peak))} {r['m'] or 0} msgs "
                 f"(+{r['j'] or 0}/-{r['l'] or 0})" for r in reversed(rows)]
        await ctx.send(embed=embed(f"Activity: last {len(rows)} day(s)", "\n".join(lines),
                                   fields=[("Busiest channels", "\n".join(busiest) or "-", False)]))


async def setup(bot):
    await bot.add_cog(Utility(bot))

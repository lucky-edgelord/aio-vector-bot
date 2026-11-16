from __future__ import annotations

import time

from vector.ext import commands, tasks

from ..utils.durations import DurationError, format_duration, parse_duration
from ..utils.embeds import embed, fail, ok

JOIN = "🎉"


class Giveaways(commands.Cog, name="Giveaways"):
    """Timed giveaways: react 🎉 to enter, winners are drawn automatically."""

    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.config
        self.store = bot.stores.giveaways
        self.watch.start()

    async def cog_unload(self):
        self.watch.cancel()

    async def cog_check(self, ctx):
        if ctx.guild is None:
            raise commands.CheckFailure("Giveaways work inside a community.")
        return True

    @commands.group(invoke_without_command=True, aliases=["gw"])
    async def giveaway(self, ctx):
        await ctx.send("`giveaway start <time> <winners> <prize>` · `end <id>` · `reroll <id>` · `cancel <id>` · `list`")

    @giveaway.command(name="start")
    @commands.has_permissions(manage_messages=True)
    async def start(self, ctx, duration: str, winners: int, *, prize: str):
        """`giveaway start 1h 2 Nitro` (time: 30m, 2h, 1d)"""
        try:
            seconds = parse_duration(duration)
        except DurationError as exc:
            return await ctx.send(fail(str(exc)))
        if seconds < self.cfg.get("giveaways.min_minutes", 1) * 60:
            return await ctx.send(fail("That is too short."))
        winners = min(max(winners, 1), self.cfg.get("giveaways.max_winners", 10))
        ends = int(time.time()) + seconds
        g = await self.store.create(str(ctx.guild.id), str(ctx.channel.id), str(ctx.author.id), prize, winners, ends)
        msg = await ctx.send(embed=embed(f"🎁 {prize}", f"React with {JOIN} to enter!\n"
                                         f"Ends in **{format_duration(seconds)}** · {winners} winner(s)\n"
                                         f"Hosted by {ctx.author.mention}", footer=f"giveaway #{g.id}"))
        await self.store.set_message(g.id, str(msg.id))
        await msg.add_reaction(JOIN)
        self.bot.emit(ctx.guild, "giveaways", f"Giveaway #{g.id}", prize)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        await self._entry(payload, True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        await self._entry(payload, False)

    async def _entry(self, payload, joining: bool):
        if payload.emoji != JOIN or str(payload.user_id) == str(self.bot.user.id):
            return
        g = await self.store.by_message(str(payload.message_id))
        if g is None or g.ended:
            return
        await (self.store.enter(g.id, str(payload.user_id)) if joining else self.store.leave(g.id, str(payload.user_id)))

    async def _announce(self, g, winners: list[str]):
        guild = self.bot.get_guild(g.guild_id)
        ch = guild.get_channel(g.channel_id) if guild else None
        if ch is None:
            return
        if winners:
            text = f"🎉 Congratulations {' '.join(self._mention(guild, w) for w in winners)}! You won **{g.prize}**."
        else:
            text = f"😢 Nobody entered the **{g.prize}** giveaway."
        await ch.send(text)
        self.bot.emit(guild, "giveaways", f"Giveaway #{g.id} ended", g.prize)

    @staticmethod
    def _mention(guild, user_id: str) -> str:
        m = guild.get_member(user_id)
        return m.mention if m else user_id[:12]

    @tasks.loop(seconds=15)
    async def watch(self):
        for g in await self.store.due():
            await self._announce(g, await self.store.finish(g.id))

    @watch.before_loop
    async def _ready(self):
        await self.bot.wait_until_ready()

    @giveaway.command(name="end")
    @commands.has_permissions(manage_messages=True)
    async def end(self, ctx, giveaway_id: int):
        g = await self.store.get(giveaway_id)
        if g is None or g.guild_id != str(ctx.guild.id) or g.ended:
            return await ctx.send(fail("No running giveaway with that id."))
        await self._announce(g, await self.store.finish(g.id))

    @giveaway.command(name="reroll")
    @commands.has_permissions(manage_messages=True)
    async def reroll(self, ctx, giveaway_id: int):
        import random

        g = await self.store.get(giveaway_id)
        if g is None or g.guild_id != str(ctx.guild.id) or not g.ended:
            return await ctx.send(fail("That giveaway hasn't ended."))
        pool = await self.store.entries(g.id)
        if not pool:
            return await ctx.send(fail("Nobody entered."))
        await ctx.send(f"🎉 New winner: {self._mention(ctx.guild, random.choice(pool))}")

    @giveaway.command(name="cancel")
    @commands.has_permissions(manage_messages=True)
    async def cancel(self, ctx, giveaway_id: int):
        g = await self.store.get(giveaway_id)
        if g is None or g.guild_id != str(ctx.guild.id) or not await self.store.cancel(giveaway_id):
            return await ctx.send(fail("No running giveaway with that id."))
        await ctx.send(ok("Cancelled."))

    @giveaway.command(name="list")
    async def list_(self, ctx):
        rows = await self.store.active(str(ctx.guild.id))
        await ctx.send(embed=embed("Running giveaways", "\n".join(
            f"`#{g.id}` {g.prize} · ends in {format_duration(max(g.ends_at - time.time(), 0))}" for g in rows)
            or "None right now."))


async def setup(bot):
    await bot.add_cog(Giveaways(bot))

from __future__ import annotations

import vector
from vector.ext import commands

from ..utils.embeds import fail, name_of, ok


class Verification(commands.Cog, name="Verification"):
    """New members answer a quick question (or press a reaction) to get the member role."""

    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.config
        self.store = bot.stores.verification

    async def _grant(self, guild, member):
        role = await self.bot.ensure_role(guild, self.cfg.get("verification.role", "Verified"))
        await member.add_roles(role, reason="verified")
        self.bot.emit(guild, "joins", "Member verified", name_of(member))
        self.bot.dispatch("vectiq_verified", guild, member)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if not self.bot.serves(member.guild):
            return
        where = self.bot.find_channel(member.guild, self.cfg.get("verification.channel", "")) \
            or member.guild.system_channel
        if self.cfg.get("verification.mode") == "button":
            if where:
                msg = await where.send(f"{member.mention} react with ✅ to verify.")
                await msg.add_reaction("✅")
            return
        question = await self.store.start(str(member.guild.id), str(member.id))
        if where:
            await where.send(f"{member.mention} to join in, type `verify <answer>`: **{question}**")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if self.cfg.get("verification.mode") != "button" or payload.emoji != "✅":
            return
        if str(payload.user_id) == str(self.bot.user.id) or not payload.guild_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id) if guild else None
        ch = guild.get_channel(payload.channel_id) if guild else None
        if member and ch and ch == (self.bot.find_channel(guild, self.cfg.get("verification.channel", ""))
                                    or guild.system_channel):
            role = self.bot.find_role(guild, self.cfg.get("verification.role", "Verified"))
            if role is None or role not in member.roles:
                await self._grant(guild, member)

    @commands.command()
    @commands.guild_only()
    async def verify(self, ctx, *, answer: str = ""):
        """Answer your verification question."""
        gid, uid = str(ctx.guild.id), str(ctx.author.id)
        if not answer:
            pending = await self.store.pending(gid, uid)
            if pending is None:
                return await ctx.send(ok("You have nothing to verify."))
            return await ctx.send(f"**{pending['question']}** → `verify <answer>`")
        result = await self.store.attempt(gid, uid, answer, self.cfg.get("verification.max_attempts", 3))
        if result == "ok":
            await self._grant(ctx.guild, ctx.author)
            await ctx.send(ok(f"Welcome in, {name_of(ctx.author)}!"))
        elif result == "wrong":
            await ctx.send(fail("That's not it. Try again."))
        elif result == "locked":
            await ctx.send(fail("Too many wrong answers. Ask a moderator for help."))
        else:
            await ctx.send(ok("You have nothing to verify."))

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    async def forceverify(self, ctx, member: vector.Member):
        """Staff: verify someone by hand."""
        await self.store.clear(str(ctx.guild.id), str(member.id))
        await self._grant(ctx.guild, member)
        await ctx.send(ok(f"Verified {name_of(member)}."))


async def setup(bot):
    await bot.add_cog(Verification(bot))

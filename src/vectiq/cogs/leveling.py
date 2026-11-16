from __future__ import annotations

import asyncio
import io
import logging

import vector
from vector.ext import commands

from ..render import Entry, leaderboard_card, rank_card
from ..stores import xp_for_level
from ..utils.embeds import avatar_bytes, embed, fail, name_of, ok

log = logging.getLogger("vectiq.leveling")


def bar(done: int, total: int, width: int = 14) -> str:
    filled = 0 if total <= 0 else round(width * done / total)
    return "█" * filled + "░" * (width - filled)


class Leveling(commands.Cog, name="Leveling"):
    """XP for chatting, ranks, a leaderboard and role rewards."""

    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.config
        self.store = bot.stores.levels

    async def cog_check(self, ctx):
        if ctx.guild is None:
            raise commands.CheckFailure("Leveling works inside a community.")
        return True

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.guild is None or not self.bot.serves(message.guild):
            return
        if (message.content or "").startswith(self.cfg.prefix):
            return
        cid = str(message.channel.id)
        skip = {str(c).lstrip("#").lower() for c in self.cfg.get("leveling.no_xp_channels", [])}
        if cid in skip or getattr(message.channel, "name", "").lower() in skip:
            return
        lv = self.cfg["leveling"]
        result = await self.store.award(str(message.guild.id), str(message.author.id),
                                        xp_min=lv["xp_min"], xp_max=lv["xp_max"], cooldown=lv["cooldown_seconds"])
        if result is None:
            return
        rank, leveled = result
        if not leveled:
            return
        self.bot.emit(message.guild, "levels", "Level up", f"{name_of(message.author)} reached level {rank.level}")
        await self._grant_rewards(message.guild, message.author, rank.level)
        if lv["announce"]:
            target = self.bot.find_channel(message.guild, lv["announce_channel"]) or message.channel
            await target.send(f"🎉 {message.author.mention} reached **level {rank.level}**!")

    async def _grant_rewards(self, guild, member, level: int):
        """Roles come from the database (`!levelreward`) and from `leveling.rewards` in config.yaml."""
        wanted = {int(k): str(v) for k, v in (self.cfg.get("leveling.rewards") or {}).items()}
        wanted.update({lvl: rid for lvl, rid in (await self.store.rewards(str(guild.id))).items()})
        for lvl, ref in sorted(wanted.items()):
            if lvl > level:
                break
            role = self.bot.find_role(guild, ref)
            if role is None and ref and not ref.isalnum():
                continue
            try:
                role = role or await self.bot.ensure_role(guild, ref)
                if role not in member.roles:
                    await member.add_roles(role, reason=f"level {lvl} reward")
            except Exception:  # noqa: BLE001 - never lose the level-up over a role problem
                continue

    def _entry(self, rank, member, avatar=None) -> Entry:
        return Entry(position=rank.position, name=name_of(member) if member else rank.user_id[:12] + "…",
                     level=rank.level, xp=rank.xp, into=rank.into_level, span=rank.level_span,
                     messages=rank.messages, avatar=avatar, ident=rank.user_id)

    async def _send_card(self, ctx, build, filename: str, card: vector.Embed) -> bool:
        """Render in a worker thread and send it inside the embed; False means "fall back to text"."""
        if not self.cfg.get("leveling.cards", True):
            return False
        try:
            png = await asyncio.to_thread(build)
            card.set_image(url=f"attachment://{filename}")     # shown between the embed body and its footer
            await ctx.send(embed=card, file=vector.File(io.BytesIO(png), filename=filename))
            return True
        except Exception:  # noqa: BLE001
            log.exception("could not render %s", filename)
            return False

    @commands.command(aliases=["level", "xp"])
    async def rank(self, ctx, member: vector.Member = None):
        """Your level card: XP, rank and progress."""
        member = member or ctx.author
        r = await self.store.rank(str(ctx.guild.id), str(member.id))
        entry = self._entry(r, member, await avatar_bytes(member))
        card = embed(name_of(member), f"Level **{r.level}** · rank **#{r.position}** · {r.xp:,} XP",
                     footer=ctx.guild.name, timestamp=True)
        if await self._send_card(ctx, lambda: rank_card(entry, community=ctx.guild.name), "rank.png", card):
            return
        await ctx.send(embed=embed(
            f"{name_of(member)}: level {r.level}",
            f"`{bar(r.into_level, r.level_span)}` {r.into_level}/{r.level_span} XP",
            fields=[("Rank", f"#{r.position}", True), ("Total XP", str(r.xp), True),
                    ("Messages", str(r.messages), True)]))

    @commands.command(aliases=["lb", "top"])
    async def leaderboard(self, ctx, page: int = 1):
        """The most active members, as an image."""
        page = max(page, 1)
        rows = await self.store.leaderboard(str(ctx.guild.id), 8, (page - 1) * 8)
        if not rows:
            return await ctx.send("Nobody has any XP yet. Start chatting!")
        members = [ctx.guild.get_member(r.user_id) for r in rows]
        avatars = await asyncio.gather(*(avatar_bytes(m) if m else asyncio.sleep(0) for m in members))
        entries = [self._entry(r, m, a) for r, m, a in zip(rows, members, avatars, strict=True)]
        total = await self.bot.db.scalar("SELECT COUNT(*) FROM levels WHERE guild_id=?", (str(ctx.guild.id),), 0)
        more = f" · `{ctx.prefix}leaderboard {page + 1}` for more" if total > page * 8 else ""
        card = embed("🏆 Leaderboard", f"The most active members of **{ctx.guild.name}**, by XP.",
                     footer=f"Page {page}{more}", timestamp=True)
        if await self._send_card(ctx, lambda: leaderboard_card(entries, community=ctx.guild.name, page=page),
                                 "leaderboard.png", card):
            return
        lines = [f"`{e.position:>2}.` {e.name}: level {e.level} · {e.xp} XP" for e in entries]
        await ctx.send(embed=embed("Leaderboard", "\n".join(lines), footer=f"page {page}"))

    @commands.command()
    @commands.has_permissions(manage_roles=True)
    async def givexp(self, ctx, member: vector.Member, amount: int):
        """Add (or remove, with a negative number) XP."""
        r = await self.store.add_xp(str(ctx.guild.id), str(member.id), amount)
        await ctx.send(ok(f"{name_of(member)} now has {r.xp} XP (level {r.level})."))

    @commands.command()
    @commands.has_permissions(manage_roles=True)
    async def resetxp(self, ctx, member: vector.Member):
        """Wipe a member's XP."""
        await self.store.reset(str(ctx.guild.id), str(member.id))
        await ctx.send(ok(f"Reset {name_of(member)}."))

    @commands.group(invoke_without_command=True)
    async def levelreward(self, ctx):
        """Roles granted at a level."""
        rewards = await self.store.rewards(str(ctx.guild.id))
        lines = []
        for lvl, rid in rewards.items():
            role = ctx.guild.get_role(rid)
            lines.append(f"level {lvl}: {role.name if role else rid}")
        await ctx.send("\n".join(lines) or "No role rewards yet. `levelreward add <level> <role>`")

    @levelreward.command(name="add")
    @commands.has_permissions(manage_roles=True)
    async def reward_add(self, ctx, level: int, *, role: str):
        role_obj = await self.bot.ensure_role(ctx.guild, role)
        await self.store.set_reward(str(ctx.guild.id), level, str(role_obj.id))
        await ctx.send(ok(f"Level {level} now grants **{role_obj.name}**."))

    @levelreward.command(name="remove")
    @commands.has_permissions(manage_roles=True)
    async def reward_remove(self, ctx, level: int):
        done = await self.store.remove_reward(str(ctx.guild.id), level)
        await ctx.send(ok("Removed.") if done else fail("No reward at that level."))

    @commands.command()
    async def levelcurve(self, ctx):
        """XP needed for the next few levels."""
        await ctx.send("\n".join(f"level {n}: {xp_for_level(n)} XP" for n in (1, 5, 10, 20, 30, 50)))


async def setup(bot):
    await bot.add_cog(Leveling(bot))

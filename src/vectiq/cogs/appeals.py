"""Ban appeals. A banned person DMs `!appeal`, writes one message, and the moderators vote on it in a staff channel."""

from __future__ import annotations

import logging
import time
from types import SimpleNamespace

from vector.ext import commands

from ..utils.embeds import embed, fail, name_of, ok, short

log = logging.getLogger("vectiq.appeals")

YES, NO = "✅", "❌"
SEP = "\u241e"   # separates saved answers in a draft


def _who(uid: str):
    return SimpleNamespace(id=uid, display_name=short(uid))


class Appeals(commands.Cog, name="Appeals"):
    """Ban appeals: filled in by DM, decided by a moderator vote."""

    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.config
        self.store = bot.stores.appeals

    def v(self, key, default=None):
        return self.cfg.get(f"appeals.{key}", default)

    def _channel(self, guild):
        ref = self.v("channel", "") or self.cfg.get("moderation.log_channel", "")
        return self.bot.find_channel(guild, ref) if ref else None

    @staticmethod
    def _can_vote(member) -> bool:
        perms = getattr(member, "guild_permissions", None)
        return bool(perms and (getattr(perms, "ban_members", False) or getattr(perms, "administrator", False)))

    async def _banned_in(self, user_id: str) -> list:
        found = []
        for guild in list(self.bot.guilds):
            if not self.bot.serves(guild):
                continue
            try:
                await guild.fetch_ban(user_id)
                found.append(guild)
            except Exception:  # noqa: BLE001 - not banned there
                continue
        return found

    # -- the banned person's side (DM) ---------------------------------------------------------

    @commands.command()
    async def appeal(self, ctx, *, community: str = ""):
        """In a DM to the bot: appeal your ban. `!appeal cancel` stops a draft."""
        if ctx.guild is not None:
            return await ctx.send(fail("Send this to me in a private message, not in the community."))
        uid = str(ctx.author.id)
        if community.strip().lower() == "cancel":
            draft = await self.store.draft_of(uid)
            if draft:
                await self.store.cancel(draft.id)
            return await ctx.send(ok("Appeal cancelled."))
        guilds = await self._banned_in(uid)
        if community.strip():
            want = community.strip().lower()
            guilds = [g for g in guilds if str(g.id) == want or g.name.lower() == want]
        if not guilds:
            return await ctx.send(fail("I can't find a ban on you in a community I serve."
                                       + (" Check the name." if community.strip() else "")))
        if len(guilds) > 1:
            names = ", ".join(f"`{g.name}`" for g in guilds)
            return await ctx.send(f"You are banned in more than one community: {names}.\n"
                                  "Say which: `!appeal <community name>`")
        problem = await self._begin(guilds[0], uid, ctx.send)
        if problem:
            await ctx.send(fail(problem))

    async def _begin(self, guild, uid: str, send) -> str:
        """Open a draft and say how to fill it in through `send`. Returns why not, or an empty string."""
        gid = str(guild.id)
        if (open_ := await self.store.latest(gid, uid, "pending")):
            return f"Your appeal (#{open_.id}) is already with the moderators."
        denied = await self.store.latest(gid, uid, "denied")
        days = float(self.v("cooldown_days", 7) or 0)
        if denied and denied.decided_at and time.time() < denied.decided_at + days * 86400:
            left = int((denied.decided_at + days * 86400 - time.time()) // 86400) + 1
            return f"Your last appeal was denied. You can appeal again in {left} day(s)."
        if self._channel(guild) is None:
            return f"{guild.name} hasn't set up a place for appeals, so I can't pass one on."
        await self.store.start(gid, uid)
        await send(self._invite_text(guild))
        return ""

    def questions(self) -> list[str]:
        qs = [str(q).strip() for q in (self.v("questions", []) or []) if str(q).strip()]
        return qs or ["Why should the ban be lifted?"]

    def _invite_text(self, guild) -> str:
        qs = self.questions()
        return (f"**You were banned from {guild.name}.** If you think that was a mistake, you can appeal. "
                f"I'll ask {len(qs)} question{'s' if len(qs) != 1 else ''}, one at a time, and the moderators will "
                f"read your answers and vote. Send `!appeal cancel` to stop.\n\n**1/{len(qs)}** {qs[0]}")

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        """Someone was banned, by Vectiq or by hand: invite them to appeal without them having to ask."""
        uid = str(getattr(user, "id", user))
        if uid == str(self.bot.user.id) or not self.bot.serves(guild):
            return
        try:
            await self._begin(guild, uid, lambda text: user.send(text))
        except Exception as exc:  # noqa: BLE001 - closed DMs are normal; `!appeal` still works if they DM us
            log.debug("couldn't invite %s to appeal: %s", uid, exc)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild is not None or getattr(message.author, "bot", False):
            return
        text = str(message.content or "").strip()
        if not text or text.startswith(str(self.cfg.get("prefix", "!"))):
            return
        uid = str(message.author.id)
        draft = await self.store.draft_of(uid)
        if draft is None:
            return
        lo, hi = int(self.v("min_chars", 5)), int(self.v("max_chars", 1000))
        if len(text) < lo:
            return await message.channel.send(fail(f"Say a little more (at least {lo} characters)."))
        if len(text) > hi:
            return await message.channel.send(fail(f"That's {len(text) - hi} characters too long. Shorten it."))
        qs = self.questions()
        answers = (draft.text.split(SEP) if draft.text else []) + [text]
        if len(answers) < len(qs):
            await self.store.save_draft(draft.id, SEP.join(answers))
            return await message.channel.send(f"**{len(answers) + 1}/{len(qs)}** {qs[len(answers)]}")
        await self._submit(draft, message, qs, answers)

    async def _submit(self, draft, message, qs, answers) -> None:
        guild = self.bot.get_guild(draft.guild_id)
        channel = self._channel(guild) if guild else None
        if channel is None:
            await self.store.cancel(draft.id)
            return await message.channel.send(fail("That community can't receive appeals right now."))
        need = int(self.v("votes_needed", 2))
        card = embed(f"Ban appeal #{draft.id}", f"From {name_of(message.author)} (`{short(draft.user_id)}`)",
                     fields=[(q[:250], a[:1000], False) for q, a in zip(qs, answers, strict=False)]
                     + [("Votes needed", str(need), True)],
                     footer=f"React {YES} to lift the ban or {NO} to deny. Staff with Ban Members can vote.",
                     timestamp=True)
        sent = await channel.send(embed=card)
        for emoji in (YES, NO):
            try:
                await sent.add_reaction(emoji)
            except Exception as exc:  # noqa: BLE001
                log.debug("couldn't add %s: %s", emoji, exc)
        await self.store.submit(draft.id, "\n\n".join(f"{q}\n{a}" for q, a in zip(qs, answers, strict=False)),
                                str(channel.id), str(sent.id))
        await message.channel.send(ok(f"Sent. Appeal #{draft.id} is with the moderators. I'll message you when they decide."))

    # -- the moderators' side --------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        emoji = str(payload.emoji)
        if emoji not in (YES, NO) or not payload.guild_id:
            return
        if str(payload.user_id) == str(self.bot.user.id):
            return
        appeal = await self.store.by_message(str(payload.message_id))
        if appeal is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        voter = guild.get_member(payload.user_id) if guild else None
        if voter is None or not self._can_vote(voter):
            return
        await self._vote(guild, appeal, voter, emoji == YES)

    @commands.command()
    async def appealvote(self, ctx, appeal_id: int, choice: str):
        """Vote on an appeal without reactions: `!appealvote 3 yes` or `no`."""
        if ctx.guild is None:
            return await ctx.send(fail("Vote inside the community."))
        if not self._can_vote(ctx.author):
            return await ctx.send(fail("You need the Ban Members permission to vote on appeals."))
        appeal = await self.store.get(appeal_id)
        if appeal is None or appeal.guild_id != str(ctx.guild.id) or appeal.status != "pending":
            return await ctx.send(fail("No open appeal with that number."))
        if choice.lower() not in ("yes", "no", "approve", "deny"):
            return await ctx.send(fail("Say `yes` or `no`."))
        yes, no = await self._vote(ctx.guild, appeal, ctx.author, choice.lower() in ("yes", "approve"))
        await ctx.send(ok(f"Vote counted. Appeal #{appeal.id}: {yes} for, {no} against."))

    @commands.command()
    async def appeals(self, ctx):
        """Open appeals and their votes."""
        if ctx.guild is None or not self._can_vote(ctx.author):
            return await ctx.send(fail("Staff with Ban Members only."))
        rows = await self.store.pending(str(ctx.guild.id))
        if not rows:
            return await ctx.send(ok("No open appeals."))
        need = int(self.v("votes_needed", 2))
        lines = []
        for a in rows:
            yes, no = await self.store.tally(a.id)
            lines.append(f"`#{a.id}` {short(a.user_id)}: {yes} for, {no} against (need {need})")
        await ctx.send(embed=embed(f"Open appeals ({len(rows)})", "\n".join(lines)))

    async def _vote(self, guild, appeal, voter, approve: bool) -> tuple[int, int]:
        yes, no = await self.store.vote(appeal.id, str(voter.id), approve)
        need = int(self.v("votes_needed", 2))
        if yes >= need:
            await self._finish(guild, appeal, True, yes, no)
        elif no >= need:
            await self._finish(guild, appeal, False, yes, no)
        return yes, no

    async def _finish(self, guild, appeal, approved: bool, yes: int, no: int) -> None:
        if not await self.store.decide(appeal.id, "approved" if approved else "denied"):
            return   # someone else's vote already closed it
        note = ""
        if approved:
            try:
                mod = self.bot.get_cog("Moderation")
                if mod is not None:
                    await mod.lift_ban(guild, _who(appeal.user_id), self.bot.user, f"appeal #{appeal.id}")
                else:
                    await guild.unban(appeal.user_id, reason=f"appeal #{appeal.id}")
            except Exception as exc:  # noqa: BLE001
                note = f"\n⚠️ The vote passed but lifting the ban failed: {exc}"
        channel = guild.get_channel(appeal.channel_id) or self._channel(guild)
        verdict = "approved. The ban is lifted" if approved else "denied"
        if channel is not None:
            try:
                await channel.send(ok(f"Appeal #{appeal.id} {verdict} ({yes} for, {no} against).{note}"))
            except Exception as exc:  # noqa: BLE001
                log.debug("couldn't announce the result: %s", exc)
        user = self.bot.get_user(appeal.user_id)
        if user is not None:
            try:
                await user.send(f"Your appeal to {guild.name} was {'approved. You can join again.' if approved else 'denied.'}")
            except Exception as exc:  # noqa: BLE001 - closed DMs are normal
                log.debug("couldn't DM the result: %s", exc)


async def setup(bot):
    await bot.add_cog(Appeals(bot))

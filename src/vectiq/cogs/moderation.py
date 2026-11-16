from __future__ import annotations

import datetime as dt
import re
import time
from collections import defaultdict

import vector
from vector.ext import commands, tasks

from ..utils.durations import DurationError, format_duration, parse_duration
from ..utils.embeds import embed, fail, name_of, ok, short, table

LINK = re.compile(r"https?://|www\.", re.IGNORECASE)


class Moderation(commands.Cog, name="Moderation"):
    """Warnings, timeouts, kicks, bans, cleanup, slowmode and a light automod."""

    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.config
        self.store = bot.stores.moderation
        self._last_post: dict[tuple[str, str], float] = defaultdict(float)
        self.expire_loop.start()

    async def cog_unload(self):
        self.expire_loop.cancel()

    async def cog_check(self, ctx):
        if ctx.guild is None:
            raise commands.CheckFailure("Moderation commands only work inside a community.")
        return True

    # -- helpers ----------------------------------------------------------------------

    async def _record(self, ctx, user, action, reason, *, expires_at=None):
        case = await self.store.add(str(ctx.guild.id), str(user.id), str(ctx.author.id), action, reason,
                                    expires_at=expires_at)
        text = f"{name_of(user)} · {action} · {reason or 'no reason'}"
        self.bot.emit(ctx.guild, "mod", f"Case #{case.id}", text)
        log_ref = self.cfg.get("moderation.log_channel", "")
        if log_ref:
            await self.bot.log_to(ctx.guild, log_ref, f"Case #{case.id}: {action}",
                                  f"**User:** {name_of(user)}\n**Moderator:** {name_of(ctx.author)}\n"
                                  f"**Reason:** {reason or 'none'}")
        return case

    def _can_act_on(self, ctx, target) -> str | None:
        if str(target.id) == str(ctx.author.id):
            return "You can't do that to yourself."
        if str(target.id) == str(self.bot.user.id):
            return "Nice try."
        if str(target.id) == str(ctx.guild.owner_id):
            return "You can't do that to the community owner."
        return None

    # -- warnings ---------------------------------------------------------------------

    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def warn(self, ctx, member: vector.Member, *, reason: str = ""):
        """Warn a member. Enough warnings trigger the action set in config.yaml."""
        if (problem := self._can_act_on(ctx, member)):
            return await ctx.send(fail(problem))
        case = await self._record(ctx, member, "warn", reason)
        count = len(await self.store.warnings(str(ctx.guild.id), str(member.id)))
        await ctx.send(ok(f"Warned {name_of(member)} (case #{case.id}, warning {count})."))
        await self._maybe_escalate(ctx, member, count)

    async def _maybe_escalate(self, ctx, member, count):
        limit = self.cfg.get("moderation.warn_threshold", 3)
        action = self.cfg.get("moderation.warn_action", "none")
        if action == "none" or count < limit or count % limit:
            return
        minutes = self.cfg.get("moderation.warn_action_minutes", 60)
        try:
            if action == "timeout":
                await member.timeout(dt.timedelta(minutes=minutes), reason="warning threshold")
                await self._record(ctx, member, "timeout", f"{count} warnings",
                                   expires_at=int(time.time()) + minutes * 60)
            elif action == "kick":
                await member.kick(reason="warning threshold")
                await self._record(ctx, member, "kick", f"{count} warnings")
            elif action == "ban":
                await member.ban(reason="warning threshold")
                await self._record(ctx, member, "ban", f"{count} warnings")
            await ctx.send(f"⚠️ {name_of(member)} reached {count} warnings: {action}.")
        except Exception as exc:  # noqa: BLE001
            await ctx.send(fail(f"Could not {action} {name_of(member)}: {exc}"))

    @commands.command(aliases=["infractions"])
    @commands.has_permissions(moderate_members=True)
    async def warnings(self, ctx, member: vector.Member):
        """List a member's active warnings."""
        rows = await self.store.warnings(str(ctx.guild.id), str(member.id))
        if not rows:
            return await ctx.send(f"{name_of(member)} has no warnings.")
        body = "\n".join(f"`#{c.id}` {format_duration(time.time() - c.created_at)} ago · {c.reason or 'no reason'}"
                         for c in rows)
        await ctx.send(embed=embed(f"Warnings for {name_of(member)}", body, footer=f"{len(rows)} active"))

    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def delwarn(self, ctx, case_id: int):
        """Remove one warning by case number."""
        case = await self.store.get(str(ctx.guild.id), case_id)
        if case is None or case.action != "warn":
            return await ctx.send(fail("No warning with that case number."))
        await self.store.deactivate(str(ctx.guild.id), case_id)
        await ctx.send(ok(f"Removed warning #{case_id}."))

    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def clearwarns(self, ctx, member: vector.Member):
        """Clear all of a member's warnings."""
        n = await self.store.clear_warnings(str(ctx.guild.id), str(member.id))
        await ctx.send(ok(f"Cleared {n} warning(s) for {name_of(member)}."))

    # -- punishments ------------------------------------------------------------------

    @commands.command(aliases=["mute"])
    @commands.has_permissions(moderate_members=True)
    async def timeout(self, ctx, member: vector.Member, duration: str, *, reason: str = ""):
        """Time a member out: `timeout @user 30m spamming`."""
        if (problem := self._can_act_on(ctx, member)):
            return await ctx.send(fail(problem))
        try:
            seconds = parse_duration(duration)
        except DurationError as exc:
            return await ctx.send(fail(str(exc)))
        longest = self.cfg.get("moderation.mute_max_days", 28) * 86400
        if seconds > longest:
            return await ctx.send(fail(f"The longest timeout is {format_duration(longest)}."))
        await member.timeout(dt.timedelta(seconds=seconds), reason=reason or None)
        case = await self._record(ctx, member, "timeout", reason, expires_at=int(time.time()) + seconds)
        await ctx.send(ok(f"{name_of(member)} timed out for {format_duration(seconds)} (case #{case.id})."))

    @commands.command(aliases=["unmute"])
    @commands.has_permissions(moderate_members=True)
    async def untimeout(self, ctx, member: vector.Member):
        """Lift a timeout."""
        await member.timeout(None)
        for c in await self.store.for_user(str(ctx.guild.id), str(member.id), action="timeout", active_only=True):
            await self.store.deactivate(str(ctx.guild.id), c.id)
        await ctx.send(ok(f"Lifted the timeout on {name_of(member)}."))

    @commands.command()
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: vector.Member, *, reason: str = ""):
        """Remove a member (they can rejoin with an invite)."""
        if (problem := self._can_act_on(ctx, member)):
            return await ctx.send(fail(problem))
        await member.kick(reason=reason or None)
        case = await self._record(ctx, member, "kick", reason)
        await ctx.send(ok(f"Kicked {name_of(member)} (case #{case.id})."))

    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: vector.Member, *, reason: str = ""):
        """Ban a member."""
        if (problem := self._can_act_on(ctx, member)):
            return await ctx.send(fail(problem))
        await member.ban(reason=reason or None)
        case = await self._record(ctx, member, "ban", reason)
        await ctx.send(ok(f"Banned {name_of(member)} (case #{case.id})."))

    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def tempban(self, ctx, member: vector.Member, duration: str, *, reason: str = ""):
        """Ban for a while; Vectiq lifts it automatically."""
        if (problem := self._can_act_on(ctx, member)):
            return await ctx.send(fail(problem))
        try:
            seconds = parse_duration(duration)
        except DurationError as exc:
            return await ctx.send(fail(str(exc)))
        await member.ban(reason=reason or None)
        case = await self._record(ctx, member, "tempban", reason, expires_at=int(time.time()) + seconds)
        await ctx.send(ok(f"Banned {name_of(member)} for {format_duration(seconds)} (case #{case.id})."))

    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, user: vector.User, *, reason: str = ""):
        """Lift a ban."""
        await ctx.guild.unban(user, reason=reason or None)
        for action in ("ban", "tempban"):
            for c in await self.store.for_user(str(ctx.guild.id), str(user.id), action=action, active_only=True):
                await self.store.deactivate(str(ctx.guild.id), c.id)
        await self._record(ctx, user, "unban", reason)
        await ctx.send(ok(f"Unbanned {name_of(user)}."))

    @tasks.loop(seconds=30)
    async def expire_loop(self):
        """Lift temporary bans and close out finished timeouts."""
        for case in await self.store.due_expiries():
            guild = self.bot.get_guild(case.guild_id)
            try:
                if case.action == "tempban" and guild is not None:
                    await guild.unban(case.user_id, reason="tempban expired")
            except Exception as exc:  # noqa: BLE001
                self.bot.dispatch("vectiq_warning", f"tempban expiry failed for {short(case.user_id)}: {exc}")
            await self.store.deactivate(case.guild_id, case.id)

    @expire_loop.before_loop
    async def _wait(self):
        await self.bot.wait_until_ready()

    # -- records ----------------------------------------------------------------------

    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def case(self, ctx, case_id: int):
        """Show one case."""
        c = await self.store.get(str(ctx.guild.id), case_id)
        if c is None:
            return await ctx.send(fail("No such case."))
        await ctx.send(embed=embed(f"Case #{c.id}: {c.action}", c.reason or "no reason given", fields=[
            ("User", short(c.user_id), True), ("Moderator", short(c.moderator), True),
            ("Active", "yes" if c.active else "no", True)]))

    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def history(self, ctx, member: vector.Member):
        """Every case against a member."""
        rows = await self.store.for_user(str(ctx.guild.id), str(member.id))
        if not rows:
            return await ctx.send(f"{name_of(member)} has a clean record.")
        await ctx.send(embed=embed(f"History: {name_of(member)}", table(
            [(f"#{c.id}", c.action, (c.reason or "-")[:30]) for c in rows[:15]], ("case", "action", "reason"))))

    @commands.command()
    @commands.has_permissions(moderate_members=True)
    async def modlog(self, ctx, limit: int = 10):
        """The latest cases in this community."""
        rows = await self.store.recent(str(ctx.guild.id), min(max(limit, 1), 25))
        await ctx.send(embed=embed("Recent cases", table(
            [(f"#{c.id}", c.action, short(c.user_id)) for c in rows], ("case", "action", "user"))
            if rows else "Nothing yet."))

    # -- channel tools ----------------------------------------------------------------

    @commands.command(aliases=["clear"])
    @commands.has_permissions(manage_messages=True)
    async def purge(self, ctx, amount: int):
        """Delete the last N messages here (max 100)."""
        amount = min(max(amount, 1), 100)
        removed = await ctx.channel.purge(limit=amount + 1)
        await ctx.send(ok(f"Cleared {max(len(removed) - 1, 0)} message(s)."), delete_after=8)

    @commands.command()
    @commands.has_permissions(manage_channels=True)
    async def lock(self, ctx):
        """Stop everyone from sending messages in this channel."""
        await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)
        await ctx.send("🔒 Channel locked.")

    @commands.command()
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx):
        """Allow messages again."""
        await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=None)
        await ctx.send("🔓 Channel unlocked.")

    @commands.command()
    @commands.has_permissions(manage_channels=True)
    async def slowmode(self, ctx, seconds: int = 0):
        """Soft slowmode: Vectiq hides messages posted faster than this (0 turns it off)."""
        seconds = min(max(seconds, 0), 21600)
        if seconds:
            await self.bot.stores.settings.set(str(ctx.guild.id), f"slowmode:{ctx.channel.id}", seconds)
            await ctx.send(ok(f"Slowmode is {seconds}s in this channel."))
        else:
            await self.bot.stores.settings.unset(str(ctx.guild.id), f"slowmode:{ctx.channel.id}")
            await ctx.send(ok("Slowmode is off."))

    # -- listeners: slowmode + automod ------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.guild is None or not self.bot.serves(message.guild):
            return
        if message.author.guild_permissions.manage_messages:
            return
        gid, cid = str(message.guild.id), str(message.channel.id)
        delay = await self.bot.stores.settings.get(gid, f"slowmode:{cid}", 0)
        if delay:
            key, now = (cid, str(message.author.id)), time.monotonic()
            if now - self._last_post[key] < delay:
                return await self._hide(message)
            self._last_post[key] = now
        reason = self.automod_reason(message.content or "")
        if reason:
            await self._hide(message)
            if self.cfg.get("moderation.automod.action") == "warn":
                case = await self.store.add(gid, str(message.author.id), str(self.bot.user.id), "warn",
                                            f"automod: {reason}")
                await message.channel.send(f"⚠️ {name_of(message.author)}: {reason} (warning, case #{case.id})")
            else:
                await message.channel.send(f"🧹 {name_of(message.author)}: {reason}")

    async def _hide(self, message):
        try:
            await message.delete()
        except Exception:  # noqa: BLE001 - missing permission must not break other listeners
            pass

    def automod_reason(self, text: str) -> str | None:
        """Pure rule check (testable): the first rule the text breaks, or None."""
        a = self.cfg.get("moderation.automod", {})
        if not a.get("enabled"):
            return None
        if text.count("nostr:") + text.count("@") > a["max_mentions"]:
            return "too many mentions"
        letters = [c for c in text if c.isalpha()]
        if len(letters) >= a["caps_min_length"] and \
                100 * sum(c.isupper() for c in letters) / len(letters) >= a["max_caps_percent"]:
            return "too many capital letters"
        if a.get("block_links") and LINK.search(text):
            return "links are not allowed here"
        lowered = text.lower()
        for word in a.get("banned_words", []):
            if re.search(rf"\b{re.escape(str(word).lower())}\b", lowered):
                return "that word is not allowed"
        return None


async def setup(bot):
    await bot.add_cog(Moderation(bot))

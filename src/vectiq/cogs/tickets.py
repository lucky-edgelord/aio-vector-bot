from __future__ import annotations

import vector
from vector.ext import commands

from ..utils.embeds import embed, fail, name_of, ok


class Tickets(commands.Cog, name="Tickets"):
    """Private support channels with claim, close and a stored transcript."""

    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.config
        self.store = bot.stores.tickets

    async def cog_check(self, ctx):
        if ctx.guild is None:
            raise commands.CheckFailure("Tickets work inside a community.")
        return True

    def _is_staff(self, member) -> bool:
        if member.guild_permissions.manage_channels or member.guild_permissions.administrator:
            return True
        ref = self.cfg.get("tickets.support_role", "")
        role = self.bot.find_role(member.guild, ref) if ref else None
        return bool(role and role in member.roles)

    @commands.group(invoke_without_command=True, aliases=["ticket"])
    async def tickets(self, ctx):
        """Support tickets."""
        await ctx.send("`ticket open <subject>` · `ticket close` · `ticket claim` · `ticket list`")

    @tickets.command(name="open", aliases=["new", "create"])
    async def open_(self, ctx, *, subject: str = "Support"):
        """Open a private ticket channel."""
        gid, uid = str(ctx.guild.id), str(ctx.author.id)
        limit = self.cfg.get("tickets.max_open_per_user", 2)
        if await self.store.open_count(gid, uid) >= limit:
            return await ctx.send(fail(f"You already have {limit} open ticket(s)."))
        overwrites = {ctx.guild.default_role: vector.PermissionOverwrite(read_messages=False),
                      ctx.author: vector.PermissionOverwrite(read_messages=True, send_messages=True)}
        role = self.bot.find_role(ctx.guild, self.cfg.get("tickets.support_role", ""))
        if role:
            overwrites[role] = vector.PermissionOverwrite(read_messages=True, send_messages=True)
        category = None
        if (cat_name := self.cfg.get("tickets.category", "")):
            category = next((c for c in ctx.guild.categories if c.name.lower() == cat_name.lower()), None)
        ticket = await self.store.create(gid, uid, subject[:100])
        try:
            name = f"ticket-{ticket.id:04d}"
            try:
                channel = await ctx.guild.create_text_channel(name, category=category, topic=subject[:100],
                                                              private=True, overwrites=overwrites)
            except Exception as exc:  # noqa: BLE001
                if "legacy roster" not in str(exc):
                    raise
                # Communities on the legacy roster can't take per-channel overwrites: make the channel
                # private and grant access to the opener and the support role's members one by one.
                # The failed call may already have created the channel before it rejected the overwrites,
                # so reuse that one instead of making a duplicate.
                channel = next((c for c in reversed(ctx.guild.text_channels) if c.name == name), None)
                if channel is None:
                    channel = await ctx.guild.create_text_channel(name, category=category, topic=subject[:100],
                                                                  private=True)
                for who in [ctx.author, *(role.members if role else [])]:
                    try:
                        await channel.grant_access(who)
                    except Exception:  # noqa: BLE001 - best effort; admins still see it
                        pass
        except Exception as exc:  # noqa: BLE001 - usually a missing permission; don't leave a ghost ticket behind
            await self.store.close(ticket.id, str(self.bot.user.id))
            return await ctx.send(fail(f"I couldn't create the ticket channel ({exc}). "
                                       "Give me a role with Manage Channels."))
        await self.store.set_channel(ticket.id, str(channel.id))
        close_emoji = self.cfg.get("tickets.close_emoji", "🔒")
        hint = f"`ticket close` or react {close_emoji} ends it." if close_emoji else "`ticket close` ends it."
        welcome = await channel.send(embed=embed(f"Ticket #{ticket.id}", f"{ctx.author.mention} opened: **{subject}**\n"
                                                 f"Staff will be with you soon. {hint}", footer="staff: `ticket claim`"))
        if close_emoji:
            try:
                await welcome.add_reaction(close_emoji)
            except Exception:  # noqa: BLE001 - the command still works
                pass
        self.bot.emit(ctx.guild, "tickets", f"Ticket #{ticket.id} opened", f"{name_of(ctx.author)}: {subject}")
        await ctx.send(ok(f"Ticket #{ticket.id} created: #{channel.name}"))

    @tickets.command(name="claim")
    async def claim(self, ctx):
        """Staff: take this ticket."""
        t = await self.store.by_channel(str(ctx.channel.id))
        if t is None:
            return await ctx.send(fail("This isn't a ticket channel."))
        if not self._is_staff(ctx.author):
            return await ctx.send(fail("Only staff can claim tickets."))
        if not await self.store.claim(t.id, str(ctx.author.id)):
            return await ctx.send(fail("Already claimed or closed."))
        await ctx.send(ok(f"{name_of(ctx.author)} is handling this ticket."))

    @tickets.command(name="close")
    async def close(self, ctx, *, reason: str = ""):
        """Close the ticket (the opener or staff)."""
        await self._close(ctx.channel, ctx.guild, ctx.author, reason, reply=ctx.send)

    async def _close(self, channel, guild, closer, reason: str, reply) -> None:
        t = await self.store.by_channel(str(channel.id))
        if t is None:
            return await reply(fail("This isn't a ticket channel."))
        if str(closer.id) != t.user_id and not self._is_staff(closer):
            return await reply(fail("Only the opener or staff can close this."))
        if not await self.store.close(t.id, str(closer.id)):
            return await reply(fail("Already closed."))
        lines = await self.store.transcript(t.id)
        self.bot.emit(guild, "tickets", f"Ticket #{t.id} closed", f"{len(lines)} message(s). {reason}")
        await reply(ok(f"Ticket #{t.id} closed. {len(lines)} message(s) were saved."))
        try:
            await channel.delete()
        except Exception:  # noqa: BLE001 - leave the channel if we may not delete it
            pass

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """React with the close emoji (default 🔒) inside a ticket to close it."""
        emoji = self.cfg.get("tickets.close_emoji", "🔒")
        if not emoji or str(payload.emoji) != emoji or not payload.guild_id:
            return
        if str(payload.user_id) == str(self.bot.user.id):
            return
        guild = self.bot.get_guild(payload.guild_id)
        channel = guild.get_channel(payload.channel_id) if guild else None
        member = guild.get_member(payload.user_id) if guild else None
        if channel is None or member is None:
            return
        t = await self.store.by_channel(str(channel.id))
        if t is None:
            return  # not a ticket channel; ignore silently
        await self._close(channel, guild, member, "closed by reaction", reply=channel.send)

    @tickets.command(name="list")
    async def list_(self, ctx):
        """Open tickets."""
        if not self._is_staff(ctx.author):
            return await ctx.send(fail("Staff only."))
        rows = await self.store.open_tickets(str(ctx.guild.id))
        await ctx.send(embed=embed("Open tickets", "\n".join(
            f"`#{t.id}` {t.subject}" + (" · claimed" if t.claimed_by else "") for t in rows) or "None 🎉"))

    @tickets.command(name="transcript")
    async def transcript(self, ctx, ticket_id: int):
        """Staff: print a stored transcript."""
        if not self._is_staff(ctx.author):
            return await ctx.send(fail("Staff only."))
        t = await self.store.get(ticket_id)
        if t is None or t.guild_id != str(ctx.guild.id):
            return await ctx.send(fail("No such ticket."))
        rows = await self.store.transcript(ticket_id)
        text = "\n".join(f"{r['author_id'][:10]}: {r['content']}" for r in rows) or "(empty)"
        await ctx.send(f"**Ticket #{t.id}: {t.subject}**\n```\n{text[:1800]}\n```")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.guild is None or not self.cfg.get("tickets.transcripts", True):
            return
        t = await self.store.by_channel(str(message.channel.id))
        if t is not None and t.status == "open" and message.content:
            await self.store.log(t.id, str(message.author.id), message.content)


async def setup(bot):
    await bot.add_cog(Tickets(bot))

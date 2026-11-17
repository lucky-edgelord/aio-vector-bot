from __future__ import annotations

from vector.ext import commands

from ..utils.embeds import embed, fail, ok


class Roles(commands.Cog, name="Roles"):
    """Reaction role menus: react to a message to gain a role, un-react to drop it."""

    def __init__(self, bot):
        self.bot = bot
        self.store = bot.stores.role_menus

    async def cog_check(self, ctx):
        if ctx.guild is None:
            raise commands.CheckFailure("Role menus work inside a community.")
        return True

    @commands.group(invoke_without_command=True, aliases=["rolemenu"])
    async def rolemenus(self, ctx):
        """Reaction role menus."""
        await ctx.send("`rolemenu create <title> | 🎮=Gamer 🎨=Artist` · `rolemenu list` · `rolemenu delete <id>`")

    @rolemenus.command(name="create")
    @commands.has_permissions(manage_roles=True)
    async def create(self, ctx, *, spec: str):
        """`rolemenu create Pick your roles | 🎮=Gamer 🎨=Artist`"""
        title, _, pairs = (p.strip() for p in spec.partition("|"))
        options = []
        for pair in pairs.split():
            emoji, sep, role = pair.partition("=")
            if not sep or not emoji or not role:
                return await ctx.send(fail(f"Can't read `{pair}`. Use emoji=Role."))
            options.append((emoji, role.replace("_", " ")))
        if not title or not options:
            return await ctx.send(fail("Give a title and at least one emoji=Role pair."))
        menu = await self.build_menu(ctx.guild, ctx.channel, title, options)
        await ctx.send(ok(f"Menu #{menu.id} is live."), delete_after=10)

    async def build_menu(self, guild, channel, title: str, options: list[tuple[str, str]]):
        """Post a role menu: ``options`` is [(emoji, role name)]. Used by the command and the dashboard."""
        lines = [f"{emoji}  **{role}**" for emoji, role in options]
        msg = await channel.send(embed=embed(title, "React to get a role:\n" + "\n".join(lines)))
        menu = await self.store.create(str(guild.id), str(channel.id), str(msg.id), title)
        for emoji, role_name in options:
            role = await self.bot.ensure_role(guild, role_name)
            await self.store.add_option(menu.id, emoji, str(role.id), role_name)
            await msg.add_reaction(emoji)
        return menu

    @rolemenus.command(name="list")
    async def list_(self, ctx):
        menus = await self.store.menus(str(ctx.guild.id))
        await ctx.send("\n".join(f"`#{m.id}` {m.title}" for m in menus) or "No role menus.")

    @rolemenus.command(name="delete")
    @commands.has_permissions(manage_roles=True)
    async def delete(self, ctx, menu_id: int):
        await ctx.send(ok("Deleted (the message stays).") if await self.store.delete(str(ctx.guild.id), menu_id)
                       else fail("No such menu."))

    async def _toggle(self, payload, add: bool):
        if str(payload.user_id) == str(self.bot.user.id) or not payload.guild_id:
            return
        role_id = await self.store.role_for(str(payload.message_id), payload.emoji)
        if role_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id) if guild else None
        role = guild.get_role(role_id) if guild else None
        if member is None or role is None:
            return
        try:
            await (member.add_roles(role, reason="role menu") if add else member.remove_roles(role, reason="role menu"))
        except Exception:  # noqa: BLE001
            pass

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        await self._toggle(payload, True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        await self._toggle(payload, False)


async def setup(bot):
    await bot.add_cog(Roles(bot))

from __future__ import annotations

from vector.ext import commands

from ..utils.embeds import name_of


class Welcome(commands.Cog, name="Welcome"):
    """Greeting and goodbye messages, with join/leave counts for the analytics."""

    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.config
        self.activity = bot.stores.activity

    def render(self, template: str, guild, member) -> str:
        return (template.replace("{mention}", getattr(member, "mention", name_of(member)))
                .replace("{name}", name_of(member)).replace("{community}", guild.name)
                .replace("{server}", guild.name).replace("{count}", str(guild.member_count)))

    def _channel(self, guild):
        return self.bot.find_channel(guild, self.cfg.get("welcome.channel", "")) or guild.system_channel

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if not self.bot.serves(member.guild):
            return
        await self.activity.bump(str(member.guild.id), "", joins=1)
        self.bot.emit(member.guild, "joins", "Member joined", name_of(member))
        w = self.cfg["welcome"]
        if w["enabled"] and (ch := self._channel(member.guild)):
            await ch.send(self.render(w["message"], member.guild, member))
        if w["dm_message"]:
            try:
                await member.send(self.render(w["dm_message"], member.guild, member))
            except Exception:  # noqa: BLE001
                pass

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        if not self.bot.serves(member.guild):
            return
        await self.activity.bump(str(member.guild.id), "", leaves=1)
        self.bot.emit(member.guild, "leaves", "Member left", name_of(member))
        w = self.cfg["welcome"]
        if w["enabled"] and w["leave_message"] and (ch := self._channel(member.guild)):
            await ch.send(self.render(w["leave_message"], member.guild, member))

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def testwelcome(self, ctx):
        """Preview the welcome message."""
        await ctx.send(self.render(self.cfg.get("welcome.message"), ctx.guild, ctx.author))


async def setup(bot):
    await bot.add_cog(Welcome(bot))

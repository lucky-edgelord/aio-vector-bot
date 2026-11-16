"""New-member onboarding: welcome, verify, pick roles, done. Everything is configured in config.yaml.

The role menu is created from ``onboarding.role_menu`` (one ``emoji: Role`` pair each) and uses the same reaction
roles as ``!rolemenu``. Progress per member is stored in SQLite, and finishing posts an ``onboarding`` event
that webhooks can mirror.
"""

from __future__ import annotations

import asyncio
import logging

from vector.ext import commands

from ..utils.embeds import embed, name_of

log = logging.getLogger("vectiq.onboarding")


class Onboarding(commands.Cog, name="Onboarding"):
    """Guides new members through verification and a role menu."""

    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.config
        self.store = bot.stores.onboarding
        self.menus = bot.stores.role_menus
        self._menu_message: dict[str, str] = {}       # guild id -> role menu message id
        self._ensured = False

    # -- configuration helpers -------------------------------------------------------

    @property
    def steps(self) -> list[str]:
        steps = list(self.cfg.get("onboarding.steps", []))
        if "verify" in steps and not self.cfg.enabled("verification"):
            steps.remove("verify")                    # nothing to verify with: skip the step
        return steps

    def _channel(self, guild):
        return self.bot.find_channel(guild, self.cfg.get("onboarding.channel", "")) or guild.system_channel

    def _render(self, text: str, guild, member) -> str:
        return (text.replace("{mention}", getattr(member, "mention", name_of(member)))
                .replace("{name}", name_of(member)).replace("{community}", guild.name))

    # -- the role menu, made from YAML -----------------------------------------------

    async def ensure_menu(self, guild) -> str | None:
        """Create (or top up) the configured role menu. Safe to call as often as you like."""
        if "pick_roles" not in self.steps:
            return None
        pairs = {str(k): str(v) for k, v in (self.cfg.get("onboarding.role_menu") or {}).items()}
        channel = self._channel(guild)
        if channel is None or not pairs:
            return None
        title = self.cfg.get("onboarding.title", "Pick your interests")
        gid = str(guild.id)
        # Resolve every role first: if one can't be created (missing permission), nothing is posted half-built.
        roles = {emoji: await self.bot.ensure_role(guild, name) for emoji, name in pairs.items()}
        menu = next((m for m in await self.menus.menus(gid) if m.title == title), None)
        message = None
        if menu is None:
            lines = "\n".join(f"{emoji}  **{name}**" for emoji, name in pairs.items())
            message = await channel.send(embed=embed(title, f"{self.cfg.get('onboarding.prompt', '')}\n\n{lines}"))
            menu = await self.menus.create(gid, str(channel.id), str(message.id), title)
        have = {r["emoji"] for r in await self.menus.options(menu.id)}
        for emoji, name in pairs.items():
            if emoji in have:
                continue
            await self.menus.add_option(menu.id, emoji, str(roles[emoji].id), name)
            if message is None:
                ch = guild.get_channel(menu.channel_id)
                message = await ch.fetch_message(menu.message_id) if ch else None
            if message is not None:
                await message.add_reaction(emoji)
        self._menu_message[gid] = menu.message_id
        return menu.message_id

    async def _ensure_all(self):
        for guild in self.bot.guilds:
            if self.bot.serves(guild):
                try:
                    await self.ensure_menu(guild)
                except Exception as exc:  # noqa: BLE001 - a missing permission must not stop onboarding
                    log.warning("could not set up the role menu in %s: %s", guild.name, exc)

    async def cog_load(self):
        self.bot.add_listener(self._on_ready_once, "on_ready")

    async def _on_ready_once(self):
        if not self._ensured:
            self._ensured = True
            await self._ensure_all()

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await asyncio.sleep(5)
        try:
            await self.ensure_menu(guild)
        except Exception as exc:  # noqa: BLE001
            log.warning("role menu setup failed: %s", exc)

    # -- the flow ---------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.bot or not self.bot.serves(member.guild):
            return
        gid, uid = str(member.guild.id), str(member.id)
        await self.store.start(gid, uid)
        if "verify" not in self.steps:
            await self.store.mark(gid, uid, "verified_at")
            await self._after_verify(member.guild, member)

    @commands.Cog.listener()
    async def on_vectiq_verified(self, guild, member):
        if not self.bot.serves(guild):
            return
        if await self.store.get(str(guild.id), str(member.id)) is None:
            await self.store.start(str(guild.id), str(member.id))
        await self.store.mark(str(guild.id), str(member.id), "verified_at")
        await self._after_verify(guild, member)

    async def _after_verify(self, guild, member):
        if "pick_roles" not in self.steps:
            return await self._finish(guild, member)
        channel = self._channel(guild)
        if channel is not None:
            await channel.send(f"{member.mention} one more thing: "
                               f"{self.cfg.get('onboarding.prompt', 'pick your roles above.')} (react in #{channel.name})")
        if not self.cfg.get("onboarding.required", False):
            await self._finish(guild, member)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if not payload.guild_id or str(payload.user_id) == str(self.bot.user.id):
            return
        gid = str(payload.guild_id)
        if self._menu_message.get(gid) != str(payload.message_id):
            return
        if not await self.store.mark(gid, str(payload.user_id), "picked_at"):
            return
        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id) if guild else None
        row = await self.store.get(gid, str(payload.user_id))
        if member and row and row["verified_at"] is not None:
            await self._finish(guild, member)

    async def _finish(self, guild, member):
        if not await self.store.complete(str(guild.id), str(member.id)):
            return
        self.bot.emit(guild, "onboarding", "Onboarding complete", name_of(member))
        channel = self._channel(guild)
        if channel is not None and (text := self.cfg.get("onboarding.done_message", "")):
            await channel.send(self._render(text, guild, member))

    # -- commands ---------------------------------------------------------------------

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def onboarding(self, ctx):
        """Show onboarding progress and (re)post the role menu if needed."""
        await self.ensure_menu(ctx.guild)
        c = await self.store.counts(str(ctx.guild.id))
        await ctx.send(embed=embed("Onboarding", fields=[
            ("Steps", " → ".join(self.steps) or "none", False),
            ("Started", str(c["started"]), True), ("Completed", str(c["completed"]), True)]))


async def setup(bot):
    await bot.add_cog(Onboarding(bot))

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

RULES_KEY = "onboarding:rules_message"


class Onboarding(commands.Cog, name="Onboarding"):
    """Guides new members through verification and a role menu."""

    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.config
        self.store = bot.stores.onboarding
        self.menus = bot.stores.role_menus
        self._menu_message: dict[str, str] = {}       # guild id -> role menu message id
        self._ensured = False
        self._prompted: set[tuple[str, str]] = set()   # members already shown the role prompt

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

    async def cog_unload(self):
        self.bot.remove_listener(self._on_ready_once, "on_ready")

    async def cog_load(self):
        self.bot.when_ready(self._on_ready_once)

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
        self._prompted.discard((gid, uid))
        if "verify" not in self.steps:
            await self.store.mark(gid, uid, "verified_at")
        await self._advance(member.guild, member)

    @commands.Cog.listener()
    async def on_vectiq_verified(self, guild, member):
        if not self.bot.serves(guild):
            return
        if await self.store.get(str(guild.id), str(member.id)) is None:
            await self.store.start(str(guild.id), str(member.id))
        await self.store.mark(str(guild.id), str(member.id), "verified_at")
        await self._advance(guild, member)

    async def _advance(self, guild, member):
        """Do the next step this member hasn't done, in the configured order, and finish when none are left."""
        gid, uid = str(guild.id), str(member.id)
        row = await self.store.get(gid, uid)
        if row is None or row["completed_at"] is not None:
            return
        for step in self.steps:
            if step == "verify":
                if row["verified_at"] is None:
                    return                      # verification calls us again when they pass
            elif step == "rules":
                if row["rules_at"] is None:
                    return await self._ask_rules(guild, member)
            elif step == "pick_roles":
                if row["picked_at"] is None:
                    if (gid, uid) not in self._prompted:
                        self._prompted.add((gid, uid))
                        await self._ask_roles(guild, member)
                    if self.cfg.get("onboarding.required", False):
                        return
            elif step == "tutorial":
                if row["tutorial_at"] is None:
                    await self.store.mark(gid, uid, "tutorial_at")
                    await self.send_tutorial(guild, member)
        await self._finish(guild, member)

    async def _ask_roles(self, guild, member):
        channel = self._channel(guild)
        if channel is not None:
            await channel.send(f"{member.mention} one more thing: "
                               f"{self.cfg.get('onboarding.prompt', 'pick your roles above.')} (react in #{channel.name})")

    # -- rules ------------------------------------------------------------------------

    def _rules_channel(self, guild):
        return self.bot.find_channel(guild, self.cfg.get("onboarding.rules_channel", "")) or self._channel(guild)

    async def ensure_rules(self, guild) -> str | None:
        """Post the rules once (with the agree reaction) and remember where. Returns the message id."""
        gid = str(guild.id)
        if (known := await self.bot.stores.settings.get(gid, RULES_KEY, "")):
            return str(known)
        channel = self._rules_channel(guild)
        rules = [str(r) for r in self.cfg.get("onboarding.rules", []) if str(r).strip()]
        if channel is None or not rules:
            return None
        emoji = self.cfg.get("onboarding.rules_emoji", "✅")
        lines = "\n".join(f"**{i}.** {r}" for i, r in enumerate(rules, 1))
        message = await channel.send(embed=embed(self.cfg.get("onboarding.rules_title", "Community rules"),
                                                 f"{lines}\n\nReact with {emoji} (or type `{self.bot.config['prefix']}agree`) "
                                                 "to say you've read and accept them."))
        try:
            await message.add_reaction(emoji)
        except Exception as exc:  # noqa: BLE001 - `!agree` still works
            log.debug("couldn't add the agree reaction: %s", exc)
        await self.bot.stores.settings.set(gid, RULES_KEY, str(message.id))
        return str(message.id)

    async def _ask_rules(self, guild, member):
        if await self.ensure_rules(guild) is None:
            await self.store.mark(str(guild.id), str(member.id), "rules_at")     # nothing to accept: skip the step
            return await self._advance(guild, member)
        channel = self._rules_channel(guild)
        if channel is not None:
            emoji = self.cfg.get("onboarding.rules_emoji", "✅")
            await channel.send(f"{member.mention} please read the rules above and react {emoji} to accept them "
                               f"(or type `{self.bot.config['prefix']}agree`).")

    async def accept_rules(self, guild, member, ack=None) -> bool:
        """Record that they accepted; ``ack`` (a coroutine function) runs before the next step, so replies read in order."""
        if not await self.store.mark(str(guild.id), str(member.id), "rules_at"):
            return False
        if ack is not None:
            await ack()
        await self._advance(guild, member)
        return True

    # -- tutorial ---------------------------------------------------------------------

    async def send_tutorial(self, guild, member) -> None:
        """The welcome tour, one page per message, by DM (posted in the channel if their DMs are closed)."""
        pages = [str(p) for p in self.cfg.get("onboarding.tutorial", []) if str(p).strip()]
        if not pages:
            return
        title = self.cfg.get("onboarding.tutorial_title", "Welcome tour")
        cards = [embed(f"{title} ({i}/{len(pages)})", self._render(p, guild, member)) for i, p in enumerate(pages, 1)]
        try:
            for card in cards:
                await member.send(embed=card)
        except Exception as exc:  # noqa: BLE001 - closed DMs are normal
            log.debug("tutorial DM failed: %s", exc)
            channel = self._channel(guild)
            if channel is not None:
                await channel.send(f"{member.mention}", embed=embed(title, "\n".join(
                    f"**{i}.** {self._render(p, guild, member)}" for i, p in enumerate(pages, 1))))

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if not payload.guild_id or str(payload.user_id) == str(self.bot.user.id):
            return
        gid, uid = str(payload.guild_id), str(payload.user_id)
        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id) if guild else None
        if guild is None or member is None:
            return
        if str(payload.emoji) == self.cfg.get("onboarding.rules_emoji", "✅") and \
                str(payload.message_id) == str(await self.bot.stores.settings.get(gid, RULES_KEY, "")):
            await self.accept_rules(guild, member)
            return
        if self._menu_message.get(gid) != str(payload.message_id):
            return
        if await self.store.mark(gid, uid, "picked_at"):
            await self._advance(guild, member)

    async def _finish(self, guild, member):
        if not await self.store.complete(str(guild.id), str(member.id)):
            return
        self.bot.emit(guild, "onboarding", "Onboarding complete", name_of(member))
        if (ref := self.cfg.get("onboarding.log_channel", "")) and hasattr(self.bot, "log_to"):
            await self.bot.log_to(guild, ref, "Onboarding complete", name_of(member))
        channel = self._channel(guild)
        if channel is not None and (text := self.cfg.get("onboarding.done_message", "")):
            await channel.send(self._render(text, guild, member))

    # -- commands ---------------------------------------------------------------------

    @commands.command()
    @commands.guild_only()
    async def agree(self, ctx):
        """Accept the community rules."""
        if "rules" not in self.steps:
            return await ctx.send("There's nothing to accept here.")
        if await self.accept_rules(ctx.guild, ctx.author,
                                   ack=lambda: ctx.send(f"✅ Thanks {name_of(ctx.author)}, rules accepted.")):
            return
        await ctx.send("You've already accepted the rules, or you're not in onboarding.")

    @commands.command()
    @commands.guild_only()
    async def tutorial(self, ctx):
        """Send yourself the welcome tour again."""
        await self.send_tutorial(ctx.guild, ctx.author)

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

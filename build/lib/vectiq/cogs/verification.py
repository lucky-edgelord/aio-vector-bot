"""Member verification: a question, a reaction, or a CAPTCHA web page.

The CAPTCHA mode, the message gate, device checks, age checks, the invite gate and
softbans are ported from GateBot (https://gitworkshop.dev/henk.tech/Gatebot, MIT).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from urllib.parse import urlparse

import vector
from vector.ext import commands, tasks

from ..utils.embeds import embed, fail, name_of, ok
from ..utils.softban import is_staff, kick_on_sight, softban

log = logging.getLogger("vectiq.verification")

NOTICE_SECONDS = 60          # public notices delete themselves after this
INVITE_KICK_SECONDS = 60     # invite gate: time to accept the invite before leaving the lobby
SPAM_WINDOW = 15 * 60


class Verification(commands.Cog, name="Verification"):
    """New members prove they're human before they can talk: a question, a ✅ reaction, or a CAPTCHA page."""

    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.config
        self.store = bot.stores.verification
        self.gate = bot.stores.gate
        self._spam: dict[tuple[str, str], deque] = defaultdict(deque)
        self._server = None

    # -- settings ------------------------------------------------------------------------------

    def v(self, key, default=None):
        return self.cfg.get(f"verification.{key}", default)

    @property
    def mode(self) -> str:
        return self.v("mode", "question")

    def public_url(self) -> str:
        return str(self.v("public_url") or self.cfg.get("dashboard.base_url", "")).rstrip("/")

    def where(self, guild):
        return self.bot.find_channel(guild, self.v("channel", "")) or guild.system_channel

    def target(self, guild):
        """The community verified members are invited to (invite gate), or None."""
        ref = str(self.v("invite_to", "") or "").strip().lower()
        if not ref:
            return None
        for g in self.bot.guilds:
            if str(g.id).lower() == ref or str(g.name).lower() == ref:
                return g if g.id != guild.id else None
        return None

    def scope(self, guild):
        """The community a verification counts for: the invite target, or this one."""
        return self.target(guild) or guild

    async def log(self, guild, title: str, text: str = ""):
        """Staff log: verification.log_channel, else moderation.log_channel."""
        ref = self.v("log_channel", "") or self.cfg.get("moderation.log_channel", "")
        if ref and hasattr(self.bot, "log_to"):
            await self.bot.log_to(guild, ref, title, text)

    async def cog_load(self):
        self.prune_loop.start()
        if self.mode == "captcha" and not self.cfg.get("modules.dashboard"):
            self.bot.add_listener(self._serve_alone, "on_ready")

    async def cog_unload(self):
        self.prune_loop.cancel()
        if self._server is not None:
            self._server.should_exit = True

    async def _serve_alone(self):
        """Without the dashboard, run a small web server with only the verification page."""
        if self._server is not None:
            return
        try:
            import uvicorn
            from fastapi import FastAPI
        except ImportError:
            log.error("captcha verification needs FastAPI and uvicorn: pip install -e '.[dashboard]'")
            return
        from ..dashboard.verify_page import add_verify_routes

        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
        add_verify_routes(app, self.bot)
        d = self.cfg["dashboard"]
        self._server = uvicorn.Server(uvicorn.Config(app, host=str(d["host"]), port=int(d["port"]), log_level="warning",
                                                     proxy_headers=True, forwarded_allow_ips="127.0.0.1"))
        self._server.install_signal_handlers = lambda: None
        asyncio.ensure_future(self._server.serve())
        log.info("verification page on %s:%s (%s)", d["host"], d["port"], self.public_url())

    @tasks.loop(hours=6)
    async def prune_loop(self):
        await self.gate.prune(mark_days=int(self.v("device_check_days", 30)), link_minutes=int(self.v("link_minutes", 10)))

    # -- granting ------------------------------------------------------------------------------

    async def ensure_role(self, guild, member) -> bool:
        """Give a verified member the role if they lost it. Returns True when it was added."""
        role = self.bot.find_role(guild, self.v("role", "Verified"))
        if role is None:
            role = await self.bot.ensure_role(guild, self.v("role", "Verified"))
        if role in getattr(member, "roles", []):
            return False
        await member.add_roles(role, reason="verified")
        return True

    async def _grant(self, guild, member, method: str = "", is_adult: bool = False, recorded: bool = False):
        if not recorded:
            await self.gate.mark_verified(str(guild.id), str(member.id), method=method or self.mode, is_adult=is_adult)
        await self.ensure_role(guild, member)
        self.bot.emit(guild, "joins", "Member verified", name_of(member))
        await self.log(guild, "✅ Member verified", f"{name_of(member)} ({method or self.mode})")
        self.bot.dispatch("vectiq_verified", guild, member)

    async def is_verified(self, guild, member) -> bool:
        if is_staff(member):
            return True
        if await self.gate.is_verified(str(guild.id), str(member.id)):
            return True
        role = self.bot.find_role(guild, self.v("role", "Verified"))
        return role is not None and role in getattr(member, "roles", [])

    # -- notices -------------------------------------------------------------------------------

    async def notice(self, channel, text: str, seconds: int = NOTICE_SECONDS):
        """Post a public notice that deletes itself, so verification chatter doesn't pile up."""
        if channel is None:
            return None
        try:
            msg = await channel.send(text)
            asyncio.ensure_future(msg.delete(delay=seconds))
            return msg
        except Exception as exc:  # noqa: BLE001
            log.warning("verification notice failed: %s", exc)
            return None

    async def send_link(self, guild, member, channel=None) -> str:
        """DM a personal one-time link. The public notice only names the site, never the link,
        so nobody else can use it. If the DM fails, post the link publicly as a fallback."""
        token = await self.gate.new_link(str(guild.id), str(member.id), str(getattr(channel, "id", "") or ""))
        link = f"{self.public_url()}/verify/{token}"
        into = self.scope(guild).name
        mins = int(self.v("link_minutes", 10))
        channel = channel or self.where(guild)
        try:
            await member.send(f"🔐 To talk in **{into}**, verify here: {link}\n"
                              f"It works once, for {mins} minutes. It's your personal link, so don't share it.")
        except Exception as exc:  # noqa: BLE001
            log.info("couldn't DM a verification link to %s (%s); posting it instead", member.id, exc)
            await self.notice(channel, f"🔐 {member.mention} to talk here, verify first: {link}")
            return token
        domain = urlparse(link).netloc
        await self.notice(channel, f"🔐 {member.mention} to talk here, verify first. I've sent you a personal link "
                                   f"to **{domain}** by DM. A real verification page only asks for a CAPTCHA: "
                                   f"never your key, a sign-in or a download.")
        return token

    async def challenge(self, guild, member, channel=None):
        """Start (or repeat) verification for someone, in the configured mode."""
        channel = channel or self.where(guild)
        if self.mode == "captcha":
            await self.send_link(guild, member, channel)
        elif self.mode == "button":
            if channel:
                msg = await channel.send(f"{member.mention} react with ✅ to verify.")
                await msg.add_reaction("✅")
        else:
            question = await self.store.start(str(guild.id), str(member.id))
            if channel:
                prefix = self.bot.config["prefix"]
                await channel.send(f"{member.mention} to join in, type `{prefix}verify <answer>`: **{question}**")

    # -- invite gate ---------------------------------------------------------------------------

    async def invite_then_kick(self, lobby, target, member):
        """Invite a verified member to the real community, then remove them from the lobby."""
        try:
            await target.invite(member.npub if hasattr(member, "npub") else str(member.id))
        except Exception as exc:  # noqa: BLE001
            log.warning("invite to %s failed for %s: %s", target.id, member.id, exc)
            return   # keep them in the lobby so they can try again
        await asyncio.sleep(INVITE_KICK_SECONDS)
        try:
            await member.kick(reason="verified and invited")
        except Exception as exc:  # noqa: BLE001
            log.warning("couldn't remove %s from the lobby: %s", member.id, exc)

    async def _lobby(self, guild, member, channel) -> bool:
        """Handle someone in an invite-gate lobby. Returns True when nothing more should happen."""
        target = self.target(guild)
        if target is None:
            return False
        uid = str(member.id)
        if await self.gate.is_softbanned(str(target.id), uid):
            await kick_on_sight(self.bot, guild, member, count=False)
            return True
        if await self.gate.is_verified(str(target.id), uid):
            await self.notice(channel, f"{member.mention} you're verified. Your invite to **{target.name}** is on its way, "
                                       f"and you'll leave this lobby in a minute.")
            asyncio.ensure_future(self.invite_then_kick(guild, target, member))
            return True
        return False

    # -- listeners -----------------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild = member.guild
        if not self.bot.serves(guild) or str(member.id) == str(self.bot.user.id):
            return
        if await self.gate.is_softbanned(str(guild.id), str(member.id)):
            return   # moderation kicks them
        if await self._lobby(guild, member, self.where(guild)):
            return
        if await self.gate.is_verified(str(guild.id), str(member.id)):
            await self.ensure_role(guild, member)   # rejoined: give the role back, no new check
            return
        await self.challenge(guild, member)

    @commands.Cog.listener()
    async def on_message(self, message):
        guild, member = message.guild, message.author
        if guild is None or getattr(member, "bot", False) or not self.bot.serves(guild):
            return
        if str(member.id) == str(self.bot.user.id):
            return
        gid, uid = str(guild.id), str(member.id)
        if await self.gate.is_softbanned(gid, uid):
            return   # moderation handles it
        if await self.gate.is_verified(gid, uid):
            try:
                await self.ensure_role(guild, member)   # lost the role somehow: put it back
            except Exception as exc:  # noqa: BLE001
                log.debug("role restore failed: %s", exc)
            return
        gate = self.v("gate", "off")
        if gate == "off" or is_staff(member):
            return
        if gate == "channel" and message.channel != self.where(guild):
            return
        role = self.bot.find_role(guild, self.v("role", "Verified"))
        if role is not None and role in getattr(member, "roles", []):
            return
        if str(message.content or "").startswith(f"{self.bot.config['prefix']}verify"):
            return   # let them answer
        await self._gated(message)

    async def _gated(self, message):
        """An unverified member spoke behind the gate: hide it, count it, and point them at verification."""
        guild, member, channel = message.guild, message.author, message.channel
        try:
            await message.delete()
        except Exception as exc:  # noqa: BLE001
            log.debug("couldn't hide a gated message: %s", exc)
        if await self._lobby(guild, member, channel):
            return
        limit = int(self.v("spam_kick", 3) or 0)
        if limit:
            hits = self._spam[(str(guild.id), str(member.id))]
            now = time.monotonic()
            while hits and hits[0] < now - SPAM_WINDOW:
                hits.popleft()
            hits.append(now)
            if len(hits) >= limit:
                hits.clear()
                await softban(self.bot, guild, member, "kept posting without verifying")
                await self.log(guild, "⛔ Softbanned for posting without verifying", name_of(member))
                return
        await self.challenge(guild, member, channel)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if self.mode != "button" or payload.emoji != "✅":
            return
        if str(payload.user_id) == str(self.bot.user.id) or not payload.guild_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id) if guild else None
        ch = guild.get_channel(payload.channel_id) if guild else None
        if member and ch and ch == self.where(guild) and not await self.gate.is_verified(str(guild.id), str(member.id)):
            await self._grant(guild, member, "button")

    # -- the CAPTCHA page calls this --------------------------------------------------------

    async def check_captcha(self, token: str, ip: str | None) -> bool:
        c = self.v("captcha", {}) or {}
        secret = os.environ.get(str(c.get("secret_key_env") or "CAPTCHA_SECRET"), "")
        if not secret:
            log.error("no CAPTCHA secret: set the %s environment variable", c.get("secret_key_env"))
            return False
        form = {"secret": secret, "response": token}
        if ip:
            form["remoteip"] = ip
        data = urllib.parse.urlencode(form).encode()

        def post():
            req = urllib.request.Request(str(c["verify_url"]), data=data, method="POST")
            with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 - configured https endpoint
                return json.loads(r.read().decode())

        try:
            return bool((await asyncio.to_thread(post)).get("success"))
        except Exception as exc:  # noqa: BLE001
            log.warning("CAPTCHA check failed: %s", exc)
            return False

    def needs_age(self) -> bool:
        return int(self.v("min_age", 0) or 0) > 0 or bool(self.v("adult_role"))

    async def finish(self, token: str, *, captcha: str, age: int | None, ip: str | None,
                     cookie: str | None, fingerprint: str | None) -> tuple[int, str]:
        """Complete a web verification. Returns (HTTP status, message for the page)."""
        minutes = int(self.v("link_minutes", 10))
        link = await self.gate.link(token, minutes)
        if link is None:
            return 404, "This link has expired. Ask for a new one by typing !verify in the community."
        if link["used"]:
            return 400, "This link has already been used."
        guild = self.bot.get_guild(link["guild_id"])
        member = guild.get_member(link["user_id"]) if guild else None
        if guild is None or member is None:
            return 404, "You're no longer in the community. Join again to get a new link."
        if not await self.check_captcha(captcha, ip):
            return 400, "The CAPTCHA wasn't accepted. Please try again."
        scope = self.scope(guild)
        sid, uid = str(scope.id), str(member.id)

        min_age = int(self.v("min_age", 0) or 0)
        if min_age:
            if age is None:
                return 400, f"This community asks you to confirm you are at least {min_age}."
            if age < min_age:
                await self.gate.softban(sid, uid, f"under {min_age}")
                await kick_on_sight(self.bot, guild, member, count=False)
                self.bot.emit(guild, "mod", "Under the minimum age", name_of(member))
                await self.log(guild, "🔞 Under the minimum age", f"{name_of(member)} was softbanned and kicked.")
                return 403, "You don't meet the minimum age for this community."

        if not await self.gate.claim(token):
            return 400, "This link has already been used."
        is_adult = age is not None and age >= 18
        if self.v("device_check", True):
            hashes = await self.gate.device_hashes(sid, ip=ip, cookie=cookie, fingerprint=fingerprint)
            if not await self.gate.try_mark_device_verified(sid, uid, hashes, days=int(self.v("device_check_days", 30)),
                                                            is_adult=is_adult):
                action = self.v("on_duplicate", "refuse")
                self.bot.emit(guild, "mod", "Second account on one device", f"{name_of(member)} ({action})")
                await self.log(guild, "🖥️ Second account on one device", f"{name_of(member)}: {action}")
                if action == "softban":
                    await softban(self.bot, guild, member, "a second account on a device that already verified")
                elif action == "kick":
                    await member.kick(reason="a second account on a device that already verified")
                return 403, ("This device was already used to verify another account here. "
                             "Ask a moderator if you think that's a mistake.")
        else:
            await self.gate.mark_verified(sid, uid, method="captcha", is_adult=is_adult)

        channel = guild.get_channel(link["channel_id"]) if link["channel_id"] else self.where(guild)
        if scope is not guild:
            await self.notice(channel, f"{member.mention} you're verified. Your invite to **{scope.name}** is on its way, "
                                       f"and you'll leave this lobby in a minute.")
            try:
                await member.send(f"✅ You're verified and I've invited you to **{scope.name}**. "
                                  "If the invite doesn't show up, restart your app.")
            except Exception:  # noqa: BLE001
                pass
            asyncio.ensure_future(self.invite_then_kick(guild, scope, member))
            self.bot.emit(guild, "joins", "Member verified", name_of(member))
            await self.log(guild, "✅ Member verified", f"{name_of(member)}, invited to {scope.name}")
            return 200, f"You're verified. Look for your invite to {scope.name} in Vector."
        try:
            await self._grant(guild, member, "captcha", is_adult, recorded=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("verified %s but the role failed (%s); it's retried when they post", uid, exc)
        await self.notice(channel, f"✅ {member.mention} is now verified.")
        try:
            await member.send(f"✅ You're verified. You can now talk in **{guild.name}**.")
        except Exception:  # noqa: BLE001
            pass
        return 200, f"You're verified. Head back to {guild.name} in Vector."

    # -- commands ------------------------------------------------------------------------------

    @commands.command()
    @commands.guild_only()
    async def verify(self, ctx, *, answer: str = ""):
        """Verify yourself: answer your question, or get a fresh CAPTCHA link."""
        if await self.gate.is_verified(str(ctx.guild.id), str(ctx.author.id)):
            await self.ensure_role(ctx.guild, ctx.author)
            return await ctx.send(ok("You're already verified."))
        if self.mode == "captcha":
            await self.send_link(ctx.guild, ctx.author, ctx.channel)
            return
        if self.mode == "button":
            where = getattr(self.where(ctx.guild), "mention", "the verification channel")
            return await ctx.send(ok(f"React with ✅ on the message in {where}."))
        gid, uid = str(ctx.guild.id), str(ctx.author.id)
        if not answer:
            pending = await self.store.pending(gid, uid)
            if pending is None:
                question = await self.store.start(gid, uid)
                return await ctx.send(f"**{question}** → `verify <answer>`")
            return await ctx.send(f"**{pending['question']}** → `verify <answer>`")
        result = await self.store.attempt(gid, uid, answer, self.v("max_attempts", 3))
        if result == "ok":
            await self._grant(ctx.guild, ctx.author, "question")
            await ctx.send(ok(f"Welcome in, {name_of(ctx.author)}!"))
        elif result == "wrong":
            await ctx.send(fail("That's not it. Try again."))
        elif result == "locked":
            await ctx.send(fail("Too many wrong answers. Ask a moderator for help."))
        else:
            await ctx.send(ok("You have nothing to verify."))

    @commands.command(aliases=["verifyuser"])
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    async def forceverify(self, ctx, member: vector.Member):
        """Staff: verify someone by hand."""
        await self.store.clear(str(ctx.guild.id), str(member.id))
        await self._grant(ctx.guild, member, "staff")
        await ctx.send(ok(f"Verified {name_of(member)}."))

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    async def unverify(self, ctx, member: vector.Member):
        """Staff: take someone's verification and verified role away."""
        gid = str(ctx.guild.id)
        await self.gate.unverify(gid, str(member.id))
        roles = [r for r in (self.bot.find_role(ctx.guild, self.v("role", "Verified")),
                             self.bot.find_role(ctx.guild, self.v("adult_role", "") or "")) if r in member.roles]
        if roles:
            await member.remove_roles(*roles, reason=f"unverified by {ctx.author.id}")
        note = (" Their device stays marked, so they can't verify themselves again for a while; "
                "use `forceverify` to let them back.") if self.mode == "captcha" and self.v("device_check", True) else ""
        await ctx.send(ok(f"Unverified {name_of(member)}.{note}"))

    @commands.command()
    @commands.guild_only()
    async def adult(self, ctx):
        """Get the adults-only role, if you said you were 18 or over when you verified."""
        name = self.v("adult_role", "")
        if not name:
            return await ctx.send(fail("This community has no adults-only role."))
        if not await self.gate.is_adult(str(self.scope(ctx.guild).id), str(ctx.author.id)):
            return await ctx.send(fail("Only members who said they were 18 or over when they verified can have it."))
        role = await self.bot.ensure_role(ctx.guild, name)
        if role in ctx.author.roles:
            return await ctx.send(ok("You already have it."))
        await ctx.author.add_roles(role, reason="18+ at verification")
        await ctx.send(ok(f"Gave you **{role.name}**."))

    def warnings(self, guild) -> list[str]:
        """What would stop verification from working here."""
        out = []
        me = getattr(guild, "me", None)
        perms = getattr(me, "guild_permissions", None)
        admin = bool(me and (me.is_admin() or me.is_owner()))
        if not admin and perms is not None:
            if not perms.manage_roles:
                out.append("I need **Manage Roles** to give the verified role.")
            if not perms.kick_members:
                out.append("I need **Kick Members** for softbans, the spam limit and the invite gate.")
            if self.v("gate", "off") != "off" and not perms.manage_messages:
                out.append("I need **Manage Messages** to hide messages from unverified members.")
        role = self.bot.find_role(guild, self.v("role", "Verified"))
        if role is None:
            out.append(f"The role **{self.v('role')}** doesn't exist yet; I'll create it the first time someone verifies.")
        elif me is not None and not admin and getattr(me, "top_role", None) is not None and me.top_role <= role:
            out.append(f"My highest role must be above **{role.name}**, or I can't give it out.")
        if self.mode == "captcha":
            c = self.v("captcha", {}) or {}
            if not os.environ.get(str(c.get("secret_key_env") or "CAPTCHA_SECRET")):
                out.append(f"Set the CAPTCHA secret in the **{c.get('secret_key_env')}** environment variable.")
            if not self.public_url().startswith("https://"):
                out.append("Serve the verification page over **https** before you rely on it.")
        if self.v("invite_to") and self.target(guild) is None:
            out.append(f"I'm not in the invite-gate community **{self.v('invite_to')}**, or it is this one.")
        return out

    @commands.group(invoke_without_command=True)
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def verification(self, ctx):
        """How verification is set up here, and anything stopping it from working."""
        target = self.target(ctx.guild)
        lines = [f"**Mode:** {self.mode}", f"**Gate:** {self.v('gate')}",
                 f"**Role:** {self.v('role')}", f"**Verified members:** {await self.gate.count(str(self.scope(ctx.guild).id))}"]
        if self.v("min_age"):
            lines.append(f"**Minimum age:** {self.v('min_age')}")
        if target:
            lines.append(f"**Invite gate:** verified members are invited to {target.name}")
        problems = self.warnings(ctx.guild)
        lines.append("\n" + ("\n".join(f"⚠️ {p}" for p in problems) if problems else "✅ Everything I need is in place."))
        await ctx.send(embed=embed("Verification", "\n".join(lines)))

    @verification.command(name="reset")
    @commands.has_permissions(manage_guild=True)
    async def verification_reset(self, ctx):
        """Forget every verification here (roles members already have are left alone)."""
        await self.gate.reset(str(ctx.guild.id))
        await ctx.send(ok("Forgot every verification, link and device mark for this community."))


async def setup(bot):
    await bot.add_cog(Verification(bot))

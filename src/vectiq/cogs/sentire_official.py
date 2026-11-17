"""Sentire (official): invite the Sentire-001 bot VectorPrivacy already runs, instead of running one yourself."""

from __future__ import annotations

from vector.ext import commands

from ..sentire.roles import OFFICIAL_NPUB, apply_role, find_role, invite_and_grant, member_of, permissions
from ..utils.embeds import embed, fail, ok

DEFAULTS = {"role": "Sentire", "delete": True, "kick": False, "ban": False}


class SentireOfficial(commands.Cog, name="Sentire (official)"):
    """Brings the official Sentire-001 moderation bot into your communities and manages its role."""

    dashboard_page = {"label": "Sentire", "icon": "⛨", "scope": "community"}

    def __init__(self, bot):
        self.bot = bot

    @property
    def cfg(self) -> dict:
        return {**DEFAULTS, **(self.bot.config.get("sentire_official", {}) or {})}

    def perms(self):
        c = self.cfg
        return permissions(c["delete"], c["kick"], c["ban"])

    def state(self, guild) -> dict:
        member = member_of(guild, OFFICIAL_NPUB)
        role = find_role(guild, self.cfg["role"])
        has_role = bool(member and role and any(r.id == role.id for r in getattr(member, "roles", [])))
        c = self.cfg
        allowed = [w for w, on in (("delete", c["delete"]), ("kick", c["kick"]), ("ban", c["ban"])) if on]
        return {"joined": member is not None, "role": has_role, "allowed": allowed,
                "up_to_date": bool(role and int(role.permissions) == int(self.perms()))}

    async def invite(self, guild) -> str:
        if member_of(guild, OFFICIAL_NPUB) is not None:
            return await apply_role(guild, OFFICIAL_NPUB, self.cfg["role"], self.perms())
        await invite_and_grant(guild, OFFICIAL_NPUB, self.cfg["role"], self.perms())
        return "invited it"

    # -- commands --------------------------------------------------------------------------

    @commands.group(name="sentire", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def sentire(self, ctx):
        """Is the official Sentire here, and what may it do?"""
        st = self.state(ctx.guild)
        lines = [f"**Sentire-001:** {'here' if st['joined'] else 'not in this community'}",
                 f"**Vector ID:** `{OFFICIAL_NPUB}`",
                 f"**Its role:** {self.cfg['role']} " + ("✅" if st["role"] else "(not given yet)"),
                 f"**May:** {', '.join(st['allowed']) or 'only watch and report'}",
                 "", "Its rules are set with its own commands: `/help`, `/status`, `/words`, `/links`, `/ladder`.",
                 "`sentire invite` brings it here or updates its role."]
        await ctx.send(embed=embed("Sentire (official)", "\n".join(lines)))

    @sentire.command(name="invite", aliases=["role"])
    async def invite_cmd(self, ctx):
        """Invite the official Sentire, or update its role to match the settings."""
        try:
            what = await self.invite(ctx.guild)
        except Exception as exc:  # noqa: BLE001
            return await ctx.send(fail(str(exc)))
        if what == "invited it":
            return await ctx.send(ok(f"Invited Sentire-001. When it joins I'll give it the **{self.cfg['role']}** "
                                     "role."))
        await ctx.send(ok(f"Sentire is here; I {what}."))

    # -- dashboard -------------------------------------------------------------------------

    async def dashboard_panel(self, guild, viewer) -> dict:
        st = self.state(guild)
        items = [{"label": "Sentire-001", "value": "In this community" if st["joined"] else "Not invited",
                  "tone": "green" if st["joined"] else "yellow"},
                 {"label": "Its role", "value": self.cfg["role"] if st["role"] else "Not given",
                  "tone": "green" if st["role"] else "yellow"},
                 {"label": "May", "value": ", ".join(st["allowed"]) or "Only watch and report"},
                 {"label": "Vector ID", "value": OFFICIAL_NPUB, "mono": True}]
        actions = []
        if not st["joined"]:
            actions.append({"id": "invite", "label": "Invite Sentire here", "kind": "primary",
                            "confirm": "Sentire-001 is run by VectorPrivacy, not by you. It gets a role that lets it "
                                       "do what Settings → Sentire (official) allows."})
        elif not (st["role"] and st["up_to_date"]):
            actions.append({"id": "invite", "label": "Update its role", "kind": "primary"})
        return {"title": "Sentire (official)", "subtitle": "The Sentire-001 moderation bot, run by VectorPrivacy.",
                "refresh": 15, "sections": [
                    {"type": "status", "items": items},
                    {"type": "actions", "items": actions} if actions else {"type": "text", "text": "All set."},
                    {"type": "text", "title": "Its rules",
                     "text": "Sentire-001 keeps its own settings. In the community, try /help, /status, /words, "
                             "/links and /ladder. What it may do is set by its role: Settings → Sentire (official)."},
                ]}

    async def dashboard_action(self, action, guild, viewer, data) -> str:
        if action == "invite":
            what = await self.invite(guild)
            return "Invited. I'll give it its role when it joins." if what == "invited it" else f"Done: {what}."
        raise RuntimeError("unknown action")

    @commands.Cog.listener()
    async def on_vectiq_config_reload(self):
        """Settings changed: bring its role in every community up to date."""
        for g in self.bot.guilds:
            if self.bot.serves(g) and member_of(g, OFFICIAL_NPUB) is not None and find_role(g, self.cfg["role"]):
                try:
                    await apply_role(g, OFFICIAL_NPUB, self.cfg["role"], self.perms())
                except Exception:  # noqa: BLE001
                    pass


async def setup(bot):
    await bot.add_cog(SentireOfficial(bot))

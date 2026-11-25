"""Role-based command limits: only people with certain roles may use a command (or every command of a module)."""

from __future__ import annotations

import logging

from vector.ext import commands

from ..utils.embeds import embed, fail, ok

log = logging.getLogger("vectiq.limits")
KEY = "command_limits"
EXEMPT = {"limit", "limits"}      # managing the limits can never be limited away


def _names(command) -> list[str]:
    """Names a rule can use for this command, most specific first: `tickets list`, `tickets`, then its module."""
    out, parts = [], command.qualified_name.lower().split()
    while parts:
        out.append(" ".join(parts))
        parts.pop()
    if command.cog_name:
        out.append(command.cog_name.lower())
    return out


def rule_for(command, limits: dict) -> tuple[str, list[str]] | None:
    low = {k.lower(): v for k, v in limits.items()}
    for name in _names(command):
        if name in low:
            return name, [str(r) for r in low[name]]
    return None


def allowed(member, roles: list[str]) -> bool:
    mine = {str(getattr(r, "id", r)) for r in getattr(member, "roles", [])}
    return bool(mine & set(roles))


class Limits(commands.Cog, name="Limits"):
    """Who may use which commands."""

    def __init__(self, bot):
        self.bot = bot
        self.settings = bot.stores.settings
        bot.add_check(self.check)

    async def cog_unload(self):
        self.bot.remove_check(self.check)

    async def get(self, guild) -> dict[str, list[str]]:
        return dict(await self.settings.get(str(guild.id), KEY, {}) or {})

    async def check(self, ctx) -> bool:
        guild = ctx.guild
        if guild is None or ctx.command is None or (ctx.command.root_parent or ctx.command).name in EXEMPT:
            return True
        found = rule_for(ctx.command, await self.get(guild))
        if found is None:
            return True
        me = str(getattr(ctx.author, "npub", None) or ctx.author.id)
        if me in self.bot.config.owners or me == str(getattr(guild, "owner_id", "")):
            return True
        try:
            if ctx.author.is_admin() or ctx.author.is_owner():
                return True
        except Exception:  # noqa: BLE001
            pass
        if allowed(ctx.author, found[1]):
            return True
        names = [getattr(r, "name", r) for r in guild.roles if str(r.id) in found[1]] or ["a role you don't have"]
        raise commands.CheckFailure(f"`{found[0]}` is limited to: {', '.join(names)}.")

    # -- what can be limited ---------------------------------------------------------------------

    def targets(self) -> dict[str, list[str]]:
        cmds = sorted({c.qualified_name for c in self.bot.walk_commands()})
        return {"commands": [c for c in cmds if c.split()[0] not in EXEMPT],
                "modules": sorted(c for c in self.bot.cogs if c != "Limits")}

    def known(self, name: str) -> str | None:
        low = name.strip().lower()
        if low in EXEMPT or (low.split() or [""])[0] in EXEMPT:
            return None
        t = self.targets()
        for group in (t["commands"], t["modules"]):
            for x in group:
                if x.lower() == low:
                    return x
        cmd = self.bot.get_command(low)
        return cmd.qualified_name if cmd else None

    async def save(self, guild, name: str, role_ids: list[str]) -> None:
        limits = await self.get(guild)
        for k in [k for k in limits if k.lower() == name.lower()]:
            del limits[k]
        if role_ids:
            limits[name] = [str(r) for r in role_ids]
        await self.settings.set(str(guild.id), KEY, limits)

    def role_names(self, guild, ids) -> str:
        names = {str(r.id): r.name for r in guild.roles}
        return ", ".join(names.get(str(i), f"(deleted role {i})") for i in ids)

    # -- chat ------------------------------------------------------------------------------------

    @commands.group(name="limit", invoke_without_command=True)
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def limit(self, ctx, target: str = "", *, roles: str = ""):
        """Limit a command or module to roles: `!limit ban Moderator, Admin`. `!limit clear ban` removes it."""
        if not target or not roles.strip():
            return await ctx.send(fail(f"Say what and who: `{ctx.prefix}limit <command or module> <role>, <role>`. "
                                       f"`{ctx.prefix}limits` lists what is limited."))
        name = self.known(target)
        if name is None:
            return await ctx.send(fail(f"I don't know a command or module called `{target}`."))
        refs = [r.strip() for r in (roles.split(",") if "," in roles else roles.split()) if r.strip()]
        found, missing = [], []
        for ref in refs:
            role = self.bot.find_role(ctx.guild, ref)
            (found if role else missing).append(role or ref)
        if missing:
            return await ctx.send(fail(f"No role called {', '.join(f'`{m}`' for m in missing)}."))
        await self.save(ctx.guild, name, [str(r.id) for r in found])
        who = ", ".join(r.name for r in found)
        await ctx.send(ok(f"`{name}` is now limited to {who}. Admins and the owner can always use it."))

    @limit.command(name="clear", aliases=["remove", "off"])
    @commands.has_permissions(manage_guild=True)
    async def limit_clear(self, ctx, *, target: str):
        """Remove a limit."""
        limits = await self.get(ctx.guild)
        name = next((k for k in limits if k.lower() == target.strip().lower()), None)
        if name is None:
            return await ctx.send(fail(f"`{target}` isn't limited."))
        await self.save(ctx.guild, name, [])
        await ctx.send(ok(f"`{name}` is open to everyone again."))

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def limits(self, ctx):
        """Everything that is limited to roles."""
        limits = await self.get(ctx.guild)
        if not limits:
            return await ctx.send(ok("Nothing is limited. Use `!limit <command or module> <role>`."))
        await ctx.send(embed=embed(f"Command limits ({len(limits)})", "\n".join(
            f"`{k}`: {self.role_names(ctx.guild, v)}" for k, v in sorted(limits.items()))))


async def setup(bot):
    await bot.add_cog(Limits(bot))

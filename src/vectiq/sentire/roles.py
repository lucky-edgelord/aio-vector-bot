"""Bringing a Sentire bot into a community: the invite, and a role with exactly the powers it's allowed."""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("vectiq.sentire")

# The official Sentire-001, run by VectorPrivacy (github.com/VectorPrivacy/Sentire, "Getting Started").
OFFICIAL_NPUB = "npub1pc5sdve5w6wczjhhnzu4te7ayjujlprm2y4ndx044gzsqx0gq64qytz06y"


def permissions(delete: bool, kick: bool, ban: bool):
    """Sentire reads its powers from its role: Manage Messages lets it delete, Kick and Ban carry out its ladder."""
    import vector

    return vector.Permissions(manage_messages=bool(delete), kick_members=bool(kick), ban_members=bool(ban))


def member_of(guild, npub: str):
    return guild.get_member(npub) if hasattr(guild, "get_member") else None


def find_role(guild, name: str):
    return next((r for r in guild.roles if r.name == name), None)


async def apply_role(guild, npub: str, name: str, perms) -> str:
    """Create or update the role and make sure the member has it. Returns what happened."""
    member = member_of(guild, npub)
    if member is None:
        raise RuntimeError("it hasn't joined this community yet")
    role = find_role(guild, name)
    if role is None:
        role = await guild.create_role(name=name, permissions=perms)
        what = f"made the **{name}** role"
    else:
        if int(role.permissions) != int(perms):
            await role.edit(permissions=perms)
        what = f"updated the **{name}** role"
    if all(r.id != role.id for r in getattr(member, "roles", [])):
        await member.add_roles(role, reason="Sentire moderation bot (Vectiq)")
    return what


async def invite_and_grant(guild, npub: str, name: str, perms, *, wait: int = 600) -> None:
    """Invite ``npub``; once it has joined (checked every 10 s for ``wait`` seconds), give it the role."""
    if member_of(guild, npub) is None:
        await guild.invite(npub)

    async def later():
        for _ in range(max(1, wait // 10)):
            if member_of(guild, npub) is not None:
                try:
                    log.info("sentire: %s in %s", await apply_role(guild, npub, name, perms), guild.name)
                except Exception as exc:  # noqa: BLE001
                    log.warning("sentire: couldn't give it a role in %s: %s", guild.name, exc)
                return
            await asyncio.sleep(10)
        log.warning("sentire: it didn't join %s in time; give it the %s role by hand", guild.name, name)

    asyncio.get_running_loop().create_task(later())

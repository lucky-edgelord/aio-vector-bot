"""Kick-on-sight for softbanned members (an idea from GateBot).

A softban is kept in Vectiq's database rather than as a ban on the relay, so it costs
no key rotation. Whenever a softbanned member turns up (joins or posts), their roles
are taken and they are kicked again. After ``verification.softban_escalate`` kicks the
softban becomes a real ban (0 = never).
"""

from __future__ import annotations

import logging

log = logging.getLogger("vectiq.softban")


def is_staff(member) -> bool:
    try:
        if member.is_admin() or member.is_owner():
            return True
    except Exception:  # noqa: BLE001
        pass
    perms = getattr(member, "guild_permissions", None)
    return bool(perms and (getattr(perms, "manage_messages", False) or getattr(perms, "administrator", False)))


async def kick_on_sight(bot, guild, member, *, count: bool = True) -> str:
    """Strip roles, kick, and escalate to a real ban when the count is reached. Returns what happened."""
    gid, uid = str(guild.id), str(member.id)
    roles = [r for r in getattr(member, "roles", []) if r != getattr(guild, "default_role", None)]
    if roles:
        try:
            await member.remove_roles(*roles, reason="softbanned")
        except Exception as exc:  # noqa: BLE001
            log.warning("could not take roles from softbanned %s: %s", uid, exc)
    try:
        await member.kick(reason="softbanned")
    except Exception as exc:  # noqa: BLE001
        log.warning("could not kick softbanned %s: %s", uid, exc)
        return "failed"
    if not count:
        return "kicked"
    kicks = await bot.stores.gate.add_kick(gid, uid)
    limit = int(bot.config.get("verification.softban_escalate", 3) or 0)
    if limit and kicks >= limit:
        try:
            await member.ban(reason=f"softbanned and came back {kicks} times")
            text = f"{getattr(member, 'display_name', uid)} came back {kicks} times"
            bot.emit(guild, "mod", "Softban became a ban", text)
            if bot.config.get("moderation.log_channel") and hasattr(bot, "log_to"):
                await bot.log_to(guild, bot.config.get("moderation.log_channel"), "⛔ Softban became a ban", text)
            return "banned"
        except Exception as exc:  # noqa: BLE001
            log.warning("could not ban %s: %s", uid, exc)
    return "kicked"


async def softban(bot, guild, member, reason: str, by: str = "") -> str:
    """Record a softban and kick right away (the first kick doesn't count towards escalation)."""
    await bot.stores.gate.softban(str(guild.id), str(member.id), reason, by)
    bot.emit(guild, "mod", "Softbanned", f"{getattr(member, 'display_name', member.id)}: {reason}")
    return await kick_on_sight(bot, guild, member, count=False)

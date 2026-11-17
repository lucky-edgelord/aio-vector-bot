"""What happens when a safety module (link safety, image guard, plugins) catches a message.

Every module uses the same actions so they behave alike (plugins get this through vectiq.plugin.enforce):

* ``delete``: remove the message and say why in the channel (the notice disappears after a minute)
* ``warn``: also add a warning case (counts towards ``moderation.warn_threshold`` when Moderation is on)
* ``timeout``: also time the member out for ``timeout_minutes``
* ``log``: remove nothing, only tell the mod log (handy for trying a rule out first)
"""

from __future__ import annotations

import datetime as dt
import logging
import time

from .embeds import name_of

log = logging.getLogger("vectiq.enforce")

ACTIONS = ("delete", "warn", "timeout", "log")


def exempt(bot, message, cfg: dict) -> bool:
    """Staff (Manage Messages), bots, and the module's ``exempt_roles`` / ``exempt_channels`` are never checked."""
    author = message.author
    if getattr(author, "bot", False) or message.guild is None:
        return True
    perms = getattr(author, "guild_permissions", None)
    if perms is not None and getattr(perms, "manage_messages", False):
        return True
    for ref in cfg.get("exempt_channels") or []:
        ch = bot.find_channel(message.guild, ref)
        if ch is not None and str(ch.id) == str(message.channel.id):
            return True
    roles = {str(r.id) for r in getattr(author, "roles", [])} | {r.name.lower() for r in getattr(author, "roles", [])}
    return any(str(ref).lower().lstrip("@") in roles for ref in cfg.get("exempt_roles") or [])


async def enforce(bot, message, *, source: str, reason: str, action: str = "delete", timeout_minutes: int = 10,
                  detail: str = "", quote: bool = True) -> None:
    """Apply ``action`` to ``message``. Never raises: a missing permission must not break other listeners."""
    guild, member = message.guild, message.author
    who = name_of(member)
    if action != "log":
        try:
            await message.delete()
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: could not delete a message: %s", source, exc)
        try:
            await message.channel.send(f"🧹 {who}: {reason}", delete_after=60)
        except Exception:  # noqa: BLE001
            pass
    mod = bot.get_cog("Moderation")
    me = bot.user
    if action in ("warn", "timeout"):
        if mod is not None:
            await mod.record(guild, member, me, "warn", f"{source}: {reason}")
            count = len(await mod.store.warnings(str(guild.id), str(member.id)))
            await mod.escalate(guild, member, count, me, message.channel.send)
        else:
            await bot.stores.moderation.add(str(guild.id), str(member.id), str(me.id), "warn", f"{source}: {reason}")
    if action == "timeout":
        try:
            await member.timeout(dt.timedelta(minutes=timeout_minutes), reason=f"{source}: {reason}")
            if mod is not None:
                await mod.record(guild, member, me, "timeout", f"{source}: {reason}",
                                 expires_at=int(time.time()) + timeout_minutes * 60)
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: could not time out %s: %s", source, who, exc)
    if mod is None or action == "log" or action == "delete":
        # warn/timeout already reached the mod log through mod.record
        ref = bot.config.get("moderation.log_channel", "")
        if ref:
            text = f"**Member:** {who}\n**Channel:** #{getattr(message.channel, 'name', '?')}\n**Why:** {reason}"
            if detail:
                text += f"\n**Detail:** {detail}"
            if quote and message.content:
                text += f"\n**Message:** {message.content[:300]}"
            title = f"{source}: {'flagged' if action == 'log' else 'removed a message'}"
            try:
                await bot.log_to(guild, ref, title, text)
            except Exception:  # noqa: BLE001
                pass
    bot.emit(guild, "mod", source, f"{who} · {action} · {reason}")

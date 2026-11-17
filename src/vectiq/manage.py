"""Managing a community: channels, categories, roles, permissions, members, messages.

One place for every action, so the dashboard and the MCP server (and anything else) behave the same. Methods take
plain values (names or ids), return plain dicts, and raise :class:`ManageError` with a message a person can read.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from vector.permissions import _CANONICAL, VALID_FLAGS, PermissionOverwrite, Permissions

# Every permission, in the order people think about them, with plain labels.
PERMISSIONS: list[dict[str, str]] = [
    {"name": "view_channel", "label": "See channels", "group": "General"},
    {"name": "send_messages", "label": "Send messages", "group": "Text"},
    {"name": "send_messages_in_threads", "label": "Send in threads", "group": "Text"},
    {"name": "attach_files", "label": "Attach files", "group": "Text"},
    {"name": "add_reactions", "label": "Add reactions", "group": "Text"},
    {"name": "read_message_history", "label": "Read history", "group": "Text"},
    {"name": "mention_everyone", "label": "Mention @everyone", "group": "Text"},
    {"name": "pin_messages", "label": "Pin messages", "group": "Text"},
    {"name": "connect", "label": "Join voice", "group": "Voice"},
    {"name": "speak", "label": "Speak", "group": "Voice"},
    {"name": "stream", "label": "Video and screen share", "group": "Voice"},
    {"name": "priority_speaker", "label": "Priority speaker", "group": "Voice"},
    {"name": "mute_members", "label": "Mute members", "group": "Voice"},
    {"name": "deafen_members", "label": "Deafen members", "group": "Voice"},
    {"name": "move_members", "label": "Move members", "group": "Voice"},
    {"name": "create_instant_invite", "label": "Create invites", "group": "Members"},
    {"name": "change_nickname", "label": "Change own nickname", "group": "Members"},
    {"name": "manage_nicknames", "label": "Manage nicknames", "group": "Moderation"},
    {"name": "manage_messages", "label": "Manage messages", "group": "Moderation"},
    {"name": "moderate_members", "label": "Time out members", "group": "Moderation"},
    {"name": "kick_members", "label": "Kick", "group": "Moderation"},
    {"name": "ban_members", "label": "Ban", "group": "Moderation"},
    {"name": "view_audit_log", "label": "View audit log", "group": "Admin"},
    {"name": "manage_channels", "label": "Manage channels", "group": "Admin"},
    {"name": "manage_roles", "label": "Manage roles and permissions", "group": "Admin"},
    {"name": "manage_guild", "label": "Manage the community", "group": "Admin"},
]
PERM_NAMES = [p["name"] for p in PERMISSIONS]
assert set(PERM_NAMES) == set(_CANONICAL.values()), "a Vector permission is missing from PERMISSIONS"

KINDS = {"text": "chat", "chat": "chat", "voice": "voice", "forum": "forum"}


class ManageError(ValueError):
    """Something a person asked for can't be done; the message says why."""


def explain(exc: Exception) -> str:
    """Vector's own refusals, in words a community admin can act on."""
    text = str(exc)
    if "legacy roster" in text:
        return ("this community still uses Vector's legacy roster, which can't do this (per-channel permissions, "
                "deleting roles). Upgrading the community in Vector removes the limit")
    if "permission" in text.lower() and "denied" in text.lower():
        return f"the bot isn't allowed to do that here; give its role more permissions ({text})"
    return text


def perms_list(value: int | Permissions) -> list[str]:
    v = int(value)
    return [n for n in PERM_NAMES if v & VALID_FLAGS[n]]


def perms_value(names) -> Permissions:
    bad = [n for n in names or [] if n not in VALID_FLAGS]
    if bad:
        raise ManageError(f"unknown permission: {', '.join(bad)} (known: {', '.join(PERM_NAMES)})")
    return Permissions(**{n: True for n in names or []})


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def colour(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", s):
        raise ManageError("colour must look like #1abc9c")
    return int(s, 16)


class Manager:
    def __init__(self, bot):
        self.bot = bot

    # -- finding things ------------------------------------------------------------------------

    def communities(self) -> list[dict]:
        return [{"id": str(g.id), "name": g.name, "members": len(getattr(g, "members", []))}
                for g in self.bot.guilds if self.bot.serves(g)]

    def community(self, ref: str):
        ref = str(ref or "").strip()
        served = [g for g in self.bot.guilds if self.bot.serves(g)]
        if not ref and len(served) == 1:
            return served[0]
        for g in served:
            if str(g.id) == ref or g.name == ref:
                return g
        loose = [g for g in served if norm(ref) and norm(ref) in norm(g.name)]
        if len(loose) == 1:
            return loose[0]
        raise ManageError(f"no community called {ref!r}" if ref else
                          "several communities: say which (" + ", ".join(g.name for g in served) + ")")

    def channel(self, guild, ref: str):
        """A text, voice or forum channel by id, name, #name or a loose name ("mod-log" finds "🛡┊mod-log")."""
        ref = str(ref or "").strip().lstrip("#")
        chans = list(guild.channels)
        for ch in chans:
            if str(ch.id) == ref or ch.name == ref:
                return ch
        for ch in chans:
            if ch.name.lower() == ref.lower():
                return ch
        loose = [ch for ch in chans if norm(ref) and norm(ref) in norm(ch.name)]
        if len(loose) == 1:
            return loose[0]
        if len(loose) > 1:
            exact = [ch for ch in loose if norm(ch.name) == norm(ref)]
            if len(exact) == 1:
                return exact[0]
            raise ManageError(f"{len(loose)} channels match {ref!r}: " + ", ".join(ch.name for ch in loose[:6]))
        raise ManageError(f"no channel called {ref!r}")

    def category(self, guild, ref: str):
        ref = str(ref or "")
        for c in guild.categories:
            if str(c.id) == ref or c.name == ref:
                return c
        loose = [c for c in guild.categories if norm(ref) and norm(ref) == norm(c.name)]
        if loose:
            return loose[0]
        raise ManageError(f"no category called {ref!r}")

    def role(self, guild, ref: str):
        ref = str(ref or "").lstrip("@")
        if ref.lower() in ("everyone", "@everyone"):
            return guild.default_role
        for r in guild.roles:
            if str(r.id) == ref or r.name == ref:
                return r
        loose = [r for r in guild.roles if norm(ref) and norm(ref) == norm(r.name)]
        if loose:
            return loose[0]
        raise ManageError(f"no role called {ref!r}")

    def member(self, guild, ref: str):
        ref = str(ref or "").strip().removeprefix("nostr:")
        m = guild.get_member(ref) if hasattr(guild, "get_member") else None
        if m is not None:
            return m
        matches = [m for m in guild.members if norm(ref) and norm(ref) in (norm(getattr(m, "display_name", "")),
                                                                          norm(getattr(m, "name", "")))]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ManageError(f"{len(matches)} members match {ref!r}; use their npub")
        raise ManageError(f"no member called {ref!r}")

    def target(self, guild, ref: str):
        """An overwrite target: everyone, a role, or a member (npub)."""
        ref = str(ref or "").strip()
        if ref.lower() in ("everyone", "@everyone"):
            return guild.default_role
        if ref.startswith("npub1"):
            return self.member(guild, ref)
        return self.role(guild, ref)

    # -- reading -------------------------------------------------------------------------------

    def _overwrites(self, ch) -> list[dict]:
        out = []
        try:
            items = ch.overwrites.items()
        except Exception:  # noqa: BLE001 - legacy rosters have no overwrites
            return out
        for target, ow in items:
            allow, deny = ow.pair()
            if getattr(target, "is_default", lambda: False)():
                ref, name, kind = "everyone", "@everyone", "everyone"
            elif hasattr(target, "npub") and not hasattr(target, "permissions"):
                ref, name, kind = target.npub, getattr(target, "display_name", target.npub), "member"
            else:
                ref, name, kind = str(target.id), target.name, "role"
            out.append({"target": ref, "name": name, "kind": kind, "allow": perms_list(allow),
                        "deny": perms_list(deny)})
        return out

    def _channel(self, ch) -> dict:
        return {"id": str(ch.id), "name": ch.name, "kind": "text" if ch.view == "chat" else ch.view,
                "topic": ch.topic or "", "private": bool(ch.private), "read_only": bool(getattr(ch, "read_only", False)),
                "category": str(ch.category_id or ""), "overwrites": self._overwrites(ch)}

    def structure(self, guild) -> dict:
        chans = list(guild.channels)
        cats = []
        for c in guild.categories:
            cats.append({"id": str(c.id), "name": c.name, "overwrites": self._overwrites(c),
                         "channels": [self._channel(ch) for ch in chans if str(ch.category_id or "") == str(c.id)]})
        loose = [self._channel(ch) for ch in chans if not ch.category_id]
        roles = []
        for r in sorted(guild.roles, key=lambda r: -getattr(r, "position", 0)):
            if r.is_default():
                continue
            roles.append({"id": str(r.id), "name": r.name, "colour": f"#{int(r.colour):06x}" if int(r.colour) else "",
                          "permissions": perms_list(r.permissions), "hoist": bool(getattr(r, "hoist", False)),
                          "mentionable": bool(getattr(r, "mentionable", False)), "members": len(r.members),
                          "managed": bool(getattr(r, "is_bot_managed", lambda: False)())})
        return {"community": {"id": str(guild.id), "name": guild.name}, "categories": cats, "channels": loose,
                "roles": roles, "everyone": perms_list(guild.default_role.permissions), "permissions": PERMISSIONS}

    # -- channels and categories ---------------------------------------------------------------

    async def create_channel(self, guild, name: str, kind: str = "text", category: str = "", topic: str = "",
                             private: bool = False) -> dict:
        view = KINDS.get(str(kind or "text").lower())
        if view is None:
            raise ManageError("kind must be text, voice or forum")
        name = str(name or "").strip()
        if not name:
            raise ManageError("give the channel a name")
        cat = self.category(guild, category) if category else None
        if view == "voice":
            ch = await guild.create_voice_channel(name, category=cat, private=bool(private))
        elif view == "forum":
            ch = await guild.create_forum(name, category=cat, topic=topic or None, private=bool(private))
        else:
            ch = await guild.create_text_channel(name, category=cat, topic=topic or None, private=bool(private))
        return self._channel(ch)

    async def edit_channel(self, guild, ref: str, *, name: str | None = None, topic: str | None = None,
                           category: str | None = None, private: bool | None = None, read_only: bool | None = None,
                           position: int | None = None) -> dict:
        ch = self.channel(guild, ref)
        kw: dict[str, Any] = {}
        if name is not None and name.strip() and name.strip() != ch.name:
            kw["name"] = name.strip()
        if topic is not None and topic != (ch.topic or ""):
            kw["topic"] = topic
        if category is not None:
            kw["category"] = self.category(guild, category) if category else None
        if position is not None:
            kw["position"] = int(position)
        if private is not None and bool(private) != bool(ch.private):
            kw["private"] = bool(private)
        if read_only is not None and bool(read_only) != bool(getattr(ch, "read_only", False)):
            kw["read_only"] = bool(read_only)
        if kw:
            ch = await ch.edit(**kw)
        return self._channel(ch)

    async def delete_channel(self, guild, ref: str) -> str:
        ch = self.channel(guild, ref)
        await ch.delete()
        return ch.name

    async def create_category(self, guild, name: str) -> dict:
        name = str(name or "").strip()
        if not name:
            raise ManageError("give the category a name")
        c = await guild.create_category(name)
        return {"id": str(c.id), "name": c.name}

    async def rename_category(self, guild, ref: str, name: str) -> dict:
        c = self.category(guild, ref)
        c = await c.edit(name=str(name).strip())
        return {"id": str(c.id), "name": c.name}

    async def delete_category(self, guild, ref: str) -> str:
        c = self.category(guild, ref)
        await c.delete()
        return c.name

    async def set_overwrite(self, guild, where: str, target: str, allow=(), deny=()) -> dict:
        """Per-channel (or per-category) permissions for @everyone, a role or a member. Both empty clears it."""
        both = set(allow or []) & set(deny or [])
        if both:
            raise ManageError(f"can't both allow and deny: {', '.join(sorted(both))}")
        try:
            place = self.category(guild, where)
        except ManageError:
            place = self.channel(guild, where)
        who = self.target(guild, target)
        perms_value(list(allow or []) + list(deny or []))       # validates the names
        ow = PermissionOverwrite(**{n: True for n in allow or []}, **{n: False for n in deny or []})
        if not allow and not deny:
            await place.set_permissions(who, overwrite=None)
        else:
            await place.set_permissions(who, overwrite=ow)
        return {"where": place.name, "target": getattr(who, "name", target), "allow": sorted(allow or []),
                "deny": sorted(deny or [])}

    # -- roles ---------------------------------------------------------------------------------

    async def create_role(self, guild, name: str, *, permissions=(), colour_hex: str = "", hoist: bool = False,
                          mentionable: bool = False) -> dict:
        name = str(name or "").strip()
        if not name:
            raise ManageError("give the role a name")
        kw: dict[str, Any] = {"name": name, "permissions": perms_value(permissions), "hoist": bool(hoist),
                              "mentionable": bool(mentionable)}
        if (c := colour(colour_hex)) is not None:
            kw["colour"] = c
        r = await guild.create_role(**kw)
        return {"id": str(r.id), "name": r.name}

    async def edit_role(self, guild, ref: str, *, name: str | None = None, permissions=None,
                        colour_hex: str | None = None, hoist: bool | None = None,
                        mentionable: bool | None = None) -> dict:
        r = self.role(guild, ref)
        if r.is_default():
            raise ManageError("@everyone is changed with everyone_permissions")
        kw: dict[str, Any] = {}
        if name is not None and name.strip():
            kw["name"] = name.strip()
        if permissions is not None:
            kw["permissions"] = perms_value(permissions)
        if colour_hex is not None:
            kw["colour"] = colour(colour_hex) or 0
        if hoist is not None:
            kw["hoist"] = bool(hoist)
        if mentionable is not None:
            kw["mentionable"] = bool(mentionable)
        if kw:
            await r.edit(**kw)
        r = self.role(guild, str(r.id))
        return {"id": str(r.id), "name": r.name, "permissions": perms_list(r.permissions)}

    async def delete_role(self, guild, ref: str) -> str:
        r = self.role(guild, ref)
        if r.is_default():
            raise ManageError("@everyone can't be deleted")
        await r.delete()
        return r.name

    async def order_roles(self, guild, order: list[str]) -> list[str]:
        """Roles from highest to lowest."""
        roles = [self.role(guild, ref) for ref in order]
        top = len(roles)
        await guild.edit_role_positions({r: top - i for i, r in enumerate(roles)})
        return [r.name for r in roles]

    async def everyone_permissions(self, guild, permissions) -> list[str]:
        await guild.set_default_permissions(perms_value(permissions))
        return perms_list(guild.default_role.permissions)

    # -- members -------------------------------------------------------------------------------

    def members(self, guild, query: str = "", limit: int = 50) -> list[dict]:
        out = []
        for m in guild.members:
            name = str(getattr(m, "display_name", "") or getattr(m, "name", ""))
            if query and norm(query) not in norm(name) and query not in getattr(m, "npub", ""):
                continue
            out.append({"npub": getattr(m, "npub", str(m.id)), "name": name, "bot": bool(getattr(m, "bot", False)),
                        "roles": [r.name for r in getattr(m, "roles", []) if not r.is_default()]})
            if len(out) >= limit:
                break
        return out

    async def give_role(self, guild, member: str, role: str, give: bool = True) -> str:
        m, r = self.member(guild, member), self.role(guild, role)
        if give:
            await m.add_roles(r, reason="managed")
        else:
            await m.remove_roles(r, reason="managed")
        return f"{'gave' if give else 'took'} {r.name} {'to' if give else 'from'} {getattr(m, 'display_name', m)}"

    async def moderate(self, guild, member: str, action: str, *, reason: str = "", minutes: int = 0,
                       by: str = "") -> str:
        """kick, ban, unban, timeout or warn, recorded as a moderation case like the commands do."""
        action = action.lower()
        reason = reason or "no reason given"
        mod = self.bot.get_cog("Moderation")
        if action == "unban":
            await guild.unban(member.strip())
            return f"unbanned {member}"
        m = self.member(guild, member)
        if action == "kick":
            await m.kick(reason=reason)
        elif action == "ban":
            await m.ban(reason=reason)
        elif action == "timeout":
            if minutes <= 0:
                raise ManageError("timeout needs minutes")
            await m.timeout(dt.timedelta(minutes=minutes), reason=reason)
        elif action != "warn":
            raise ManageError("action must be warn, timeout, kick, ban or unban")
        if mod is not None:
            await mod.record(guild, m, self.bot.user, action, f"{reason} (by {by})" if by else reason)
        else:
            await self.bot.stores.moderation.add(str(guild.id), str(m.id), str(self.bot.user.id), action, reason)
        return f"{action}: {getattr(m, 'display_name', m)}"

    # -- messages ------------------------------------------------------------------------------

    async def send(self, guild, channel: str, text: str) -> dict:
        if not str(text or "").strip():
            raise ManageError("nothing to send")
        ch = self.channel(guild, channel)
        msg = await ch.send(str(text)[:4000])
        return {"channel": ch.name, "id": str(getattr(msg, "id", ""))}

    async def history(self, guild, channel: str, limit: int = 20) -> list[dict]:
        ch = self.channel(guild, channel)
        out = []
        async for m in ch.history(limit=max(1, min(int(limit), 100))):
            out.append({"id": str(m.id), "author": str(getattr(m.author, "display_name", "") or m.author),
                        "npub": getattr(m.author, "npub", ""), "text": m.content or "",
                        "at": m.created_at.isoformat() if getattr(m, "created_at", None) else "",
                        "files": [a.filename for a in getattr(m, "attachments", [])]})
        return list(reversed(out))

"""Who may sign in to the dashboard and what they may manage.

Everything is checked live against Vector on every request, so taking someone's admin role away
takes effect at once, even in a session that is already open.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

NPUB_CHARS = set("023456789acdefghjklmnpqrstuvwxyz")


def clean_npub(value: str) -> str | None:
    """Accept ``npub1…`` or ``nostr:npub1…``; return the bare npub or None."""
    v = (value or "").strip().lower().removeprefix("nostr:").removeprefix("@")
    if v.startswith("npub1") and 59 <= len(v) <= 70 and set(v[5:]) <= NPUB_CHARS:
        return v
    return None


@dataclass
class Actor:
    """The signed-in person, shaped enough like a Member for the cogs' helpers (record, launch...)."""

    npub: str
    display_name: str

    @property
    def id(self) -> str:
        return self.npub

    @property
    def mention(self) -> str:
        return f"nostr:{self.npub}"

    def __str__(self) -> str:
        return self.display_name


def member_of(guild: Any, npub: str):
    try:
        return guild.get_member(npub)
    except Exception:  # noqa: BLE001
        return None


def can_manage(guild: Any, member: Any) -> bool:
    """Community admins and people with Manage Community may use the dashboard for that community."""
    if member is None:
        return False
    if str(getattr(guild, "owner_id", "")) == str(member.npub):
        return True
    try:
        if member.is_admin():
            return True
    except Exception:  # noqa: BLE001
        pass
    perms = getattr(member, "guild_permissions", None)
    return bool(perms and (perms.administrator or perms.manage_guild))


class Access:
    def __init__(self, bot):
        self.bot = bot

    def communities(self) -> list:
        return [g for g in self.bot.guilds if self.bot.serves(g)]

    def is_owner(self, npub: str) -> bool:
        """Bot owners from config.yaml; with none set, the owner of any served community counts."""
        owners = [o.lower() for o in self.bot.config.owners]
        if owners:
            return npub.lower() in owners
        return any(str(g.owner_id).lower() == npub.lower() for g in self.communities())

    def manageable(self, npub: str) -> list:
        owner = self.is_owner(npub)
        return [g for g in self.communities() if owner or can_manage(g, member_of(g, npub))]

    def may_sign_in(self, npub: str) -> bool:
        return self.is_owner(npub) or bool(self.manageable(npub))

    def guild(self, npub: str, guild_id: str):
        """The community if ``npub`` may manage it, else None."""
        g = self.bot.get_guild(guild_id)
        if g is None or not self.bot.serves(g):
            return None
        if self.is_owner(npub) or can_manage(g, member_of(g, npub)):
            return g
        return None

    def actor(self, npub: str, guild: Any = None) -> Any:
        """A Member when the person is in ``guild``, otherwise a stand-in with the same few attributes."""
        m = member_of(guild, npub) if guild is not None else None
        if m is not None:
            return m
        for g in self.communities():
            m = member_of(g, npub)
            if m is not None:
                return Actor(npub, getattr(m, "display_name", None) or npub[:12] + "…")
        return Actor(npub, npub[:12] + "…")

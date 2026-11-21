"""Who may sign in to the dashboard and what they may see and change.

Bot owners and a community's owner can do everything. Community admins can too, unless the owner says otherwise.
On top of that, a community's owner (or a bot owner) can give Vector roles access to parts of the dashboard: for
each area, nothing, looking, or changing things (see AREAS and PRESETS).

Everything is checked live against Vector on every request, so taking someone's role away takes effect at once,
even in a session that is already open.
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


# Areas of a community's dashboard: id, label, what it covers.
AREAS: list[tuple[str, str, str]] = [
    ("overview", "Overview", "the community at a glance"),
    ("members", "Members", "the member list and profiles; giving and taking roles"),
    ("moderation", "Moderation", "cases and bans; warning, timing out, kicking and banning members"),
    ("tickets", "Tickets", "reading, claiming and closing tickets"),
    ("structure", "Channels & roles", "channels, categories, roles and their permissions"),
    ("rolemenus", "Role menus", "reaction role menus"),
    ("onboarding", "Onboarding", "who has finished onboarding; reposting the menu"),
    ("leveling", "Leveling", "levels, rewards, and members' XP"),
    ("economy", "Economy", "the shop and members' coins"),
    ("giveaways", "Giveaways", "starting, ending and rerolling giveaways"),
    ("games", "Games", "starting mini games"),
    ("securitycam", "Security cam", "the security cam settings"),
    ("announce", "Announce", "posting announcements as the bot"),
    ("modules", "Module pages", "pages that modules add, like Sentire's"),
    ("audit", "Audit log", "what was changed on the dashboard, and by whom"),
]
AREA_IDS = [a[0] for a in AREAS]
LEVELS = ("none", "view", "manage")
FULL = {a: "manage" for a in AREA_IDS}
PRESETS: dict[str, dict[str, str]] = {
    "full": FULL,
    "moderator": {"overview": "view", "members": "manage", "moderation": "manage", "tickets": "manage",
                  "onboarding": "view", "audit": "view"},
    "helper": {"overview": "view", "members": "view", "tickets": "manage"},
    "viewer": {a: "view" for a in AREA_IDS},
    "none": {},
}

# The first part of /api/c/<community>/<part>/... and the area it belongs to. Anything not listed needs full access.
ROUTE_AREAS = {
    "overview": "overview", "setup-check": "overview", "members": "members", "cases": "moderation",
    "bans": "moderation", "tickets": "tickets", "structure": "structure", "channels": "structure",
    "categories": "structure", "overwrites": "structure", "roles": "structure", "roles-order": "structure",
    "everyone": "structure", "rolemenus": "rolemenus", "onboarding": "onboarding", "leveling": "leveling",
    "leaderboard.png": "leveling", "rewards": "leveling", "economy": "economy", "shop": "economy",
    "giveaways": "giveaways", "games": "games", "securitycam": "securitycam", "announce": "announce",
    "audit": "audit",
}
# /members/<id>/<what> changes belong to the area that owns <what>
MEMBER_ACTIONS = {"action": "moderation", "xp": "leveling", "coins": "economy", "roles": "members"}


def clean_levels(raw: Any) -> dict[str, str]:
    """A role's areas as {area: "view"|"manage"}; unknown areas and levels are dropped."""
    if isinstance(raw, str):
        return dict(PRESETS.get(raw, {}))
    if not isinstance(raw, dict):
        return {}
    return {a: lv for a, lv in raw.items() if a in AREA_IDS and lv in ("view", "manage")}


def merge(*grants: dict[str, str]) -> dict[str, str]:
    """The most of each area that any of ``grants`` gives."""
    out: dict[str, str] = {}
    for g in grants:
        for a, lv in g.items():
            if LEVELS.index(lv) > LEVELS.index(out.get(a, "none")):
                out[a] = lv
    return out


def area_of(method: str, rest: list[str]) -> tuple[str | None, bool]:
    """(area, changes something) for a community API call; area None = only full access may do it."""
    write = method.upper() not in ("GET", "HEAD", "OPTIONS")
    if not rest:
        return None, write
    head = rest[0]
    if head == "channels" and not write:
        return "", False                      # the channel list feeds every page's pickers: any access will do
    if head == "members" and len(rest) >= 3 and write:
        return MEMBER_ACTIONS.get(rest[2]), True
    return ROUTE_AREAS.get(head), write


class Access:
    def __init__(self, bot):
        self.bot = bot
        self.rules: dict[str, dict] = {}       # community id -> {"admins": levels, "roles": [{role_id, name, areas}]}

    async def load(self, store) -> None:
        self.rules = {gid: self.clean_rules(r) for gid, r in (await store.access_rules()).items()}

    @staticmethod
    def clean_rules(raw: Any) -> dict:
        raw = raw if isinstance(raw, dict) else {}
        admins = raw.get("admins", "full")
        roles = []
        for r in raw.get("roles", []) if isinstance(raw.get("roles"), list) else []:
            if isinstance(r, dict) and str(r.get("role_id", "")).strip():
                areas = clean_levels(r.get("areas"))
                roles.append({"role_id": str(r["role_id"]), "name": str(r.get("name", ""))[:100], "areas": areas})
        return {"admins": clean_levels(admins), "roles": roles}

    def is_community_owner(self, guild: Any, npub: str) -> bool:
        return str(getattr(guild, "owner_id", "")).lower() == npub.lower()

    def can_configure(self, guild: Any, npub: str) -> bool:
        """Who sets the community's dashboard access: its owner and bot owners."""
        return self.is_owner(npub) or self.is_community_owner(guild, npub)

    def levels(self, guild: Any, npub: str) -> dict[str, str]:
        """What ``npub`` may do in ``guild``'s dashboard: {area: "view"|"manage"} ({} = nothing)."""
        if self.can_configure(guild, npub):
            return dict(FULL)
        member = member_of(guild, npub)
        if member is None:
            return {}
        rules = self.rules.get(str(guild.id)) or {"admins": dict(FULL), "roles": []}
        grants = []
        if can_manage(guild, member):
            grants.append(rules["admins"])
        have = {str(getattr(r, "id", "")) for r in getattr(member, "roles", []) or []}
        grants += [r["areas"] for r in rules["roles"] if r["role_id"] in have]
        return merge(*grants)

    def allows(self, guild: Any, npub: str, area: str | None, write: bool) -> bool:
        lv = self.levels(guild, npub)
        if area is None:
            return lv == FULL
        if area == "":
            return bool(lv)
        return lv.get(area) == "manage" or (not write and lv.get(area) == "view")

    def communities(self) -> list:
        return [g for g in self.bot.guilds if self.bot.serves(g)]

    def is_owner(self, npub: str) -> bool:
        """Bot owners from config.yaml; with none set, the owner of any served community counts."""
        owners = [o.lower() for o in self.bot.config.owners]
        if owners:
            return npub.lower() in owners
        return any(str(g.owner_id).lower() == npub.lower() for g in self.communities())

    def manageable(self, npub: str) -> list:
        """Communities whose dashboard ``npub`` may open (any access at all)."""
        return [g for g in self.communities() if self.levels(g, npub)]

    def may_sign_in(self, npub: str) -> bool:
        return self.is_owner(npub) or bool(self.manageable(npub))

    def guild(self, npub: str, guild_id: str):
        """The community if ``npub`` may manage it, else None."""
        g = self.bot.get_guild(guild_id)
        if g is None or not self.bot.serves(g):
            return None
        return g if self.levels(g, npub) else None

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

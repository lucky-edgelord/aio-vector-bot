"""The settings the dashboard can edit, grouped as they appear on the Settings page.

Each field is a dotted path into config.yaml. Saved values are stored as overrides in the database and
layered on top of config.yaml, so the file (and its comments) is never rewritten.
"""

from __future__ import annotations

from typing import Any

from ..config import MODULES

# type: bool | int | text | longtext | enum | list | emoji_map
F = dict[str, Any]


def field(path: str, label: str, kind: str, help: str = "", *, options: tuple = (), restart: bool = False,
          minimum: int | None = None, maximum: int | None = None) -> F:
    return {"path": path, "label": label, "type": kind, "help": help, "options": list(options), "restart": restart,
            "min": minimum, "max": maximum}


MODULE_HELP = {
    "moderation": "Warnings, timeouts, kicks, bans, purge, lock, slowmode, automod",
    "leveling": "XP for chatting, levels, rank cards, role rewards",
    "economy": "Coins, daily and work rewards, shop",
    "tickets": "Private support channels",
    "verification": "Make new members answer a question before they get in",
    "roles": "Reaction role menus",
    "giveaways": "Timed giveaways with reactions",
    "games": "WebXDC mini games refereed by the bot",
    "welcome": "Join and leave messages",
    "onboarding": "Welcome → verify → pick roles",
    "utility": "Polls, reminders, analytics and other tools",
    "webhooks": "Webhooks declared in config.yaml",
    "dashboard": "This web dashboard",
}

GROUPS: list[dict[str, Any]] = [
    {"id": "general", "title": "General", "fields": [
        field("prefix", "Command prefix", "text", "What commands start with, e.g. !help"),
        field("communities", "Communities served", "list", "Community names or ids, one per line. Empty = every "
              "community the bot is in."),
        field("owners", "Bot owners", "list", "npubs, one per line. Owners can use owner commands, change these "
              "settings and manage webhooks."),
    ]},
    {"id": "modules", "title": "Modules", "fields": [
        field(f"modules.{m}", m.capitalize(), "bool", MODULE_HELP.get(m, ""), restart=True) for m in MODULES
    ]},
    {"id": "moderation", "title": "Moderation", "fields": [
        field("moderation.log_channel", "Mod log channel", "text", "Channel name or id (blank = none)"),
        field("moderation.warn_threshold", "Warnings before action", "int", minimum=1, maximum=50),
        field("moderation.warn_action", "Action at threshold", "enum", options=("timeout", "kick", "ban", "none")),
        field("moderation.warn_action_minutes", "Timeout length (minutes)", "int", minimum=1, maximum=40320),
        field("moderation.mute_max_days", "Longest timeout (days)", "int", minimum=1, maximum=28),
    ]},
    {"id": "automod", "title": "Automod", "fields": [
        field("moderation.automod.enabled", "Automod on", "bool"),
        field("moderation.automod.action", "What to do", "enum", options=("delete", "warn")),
        field("moderation.automod.banned_words", "Banned words", "list", "One per line"),
        field("moderation.automod.block_links", "Block links", "bool"),
        field("moderation.automod.max_mentions", "Most mentions per message", "int", minimum=1, maximum=100),
        field("moderation.automod.max_caps_percent", "Most capital letters (%)", "int", minimum=1, maximum=100),
        field("moderation.automod.caps_min_length", "Check caps from length", "int", minimum=1, maximum=2000),
    ]},
    {"id": "leveling", "title": "Leveling", "fields": [
        field("leveling.cards", "Image rank cards", "bool"),
        field("leveling.xp_min", "XP per message (min)", "int", minimum=0, maximum=1000),
        field("leveling.xp_max", "XP per message (max)", "int", minimum=0, maximum=1000),
        field("leveling.cooldown_seconds", "XP cooldown (seconds)", "int", minimum=0, maximum=3600),
        field("leveling.announce", "Announce level-ups", "bool"),
        field("leveling.announce_channel", "Level-up channel", "text", "Blank = where the member was chatting"),
        field("leveling.no_xp_channels", "No-XP channels", "list", "Channel names or ids, one per line"),
    ]},
    {"id": "economy", "title": "Economy", "fields": [
        field("economy.currency_name", "Currency name", "text"),
        field("economy.currency_symbol", "Currency symbol", "text"),
        field("economy.start_balance", "Starting balance", "int", minimum=0),
        field("economy.daily_amount", "Daily reward", "int", minimum=0),
        field("economy.daily_streak_bonus", "Streak bonus per day", "int", minimum=0),
        field("economy.daily_streak_cap", "Streak cap (days)", "int", minimum=0),
        field("economy.work_min", "Work pays (min)", "int", minimum=0),
        field("economy.work_max", "Work pays (max)", "int", minimum=0),
        field("economy.work_cooldown_minutes", "Work cooldown (minutes)", "int", minimum=0),
        field("economy.message_reward", "Coins per message", "int", minimum=0),
    ]},
    {"id": "tickets", "title": "Tickets", "fields": [
        field("tickets.category", "Ticket category", "text", "Category name for new ticket channels (blank = none)"),
        field("tickets.support_role", "Support role", "text", "Role that can see every ticket"),
        field("tickets.max_open_per_user", "Open tickets per member", "int", minimum=1, maximum=20),
        field("tickets.close_emoji", "Close emoji", "text", "React with this in a ticket to close it (blank = off)"),
        field("tickets.transcripts", "Keep transcripts", "bool"),
    ]},
    {"id": "verification", "title": "Verification", "fields": [
        field("verification.mode", "Mode", "enum", "question = answer a captcha, button = react ✅",
              options=("question", "button")),
        field("verification.role", "Verified role", "text"),
        field("verification.max_attempts", "Attempts", "int", minimum=1, maximum=20),
        field("verification.channel", "Verification channel", "text", "Blank = the system channel"),
    ]},
    {"id": "welcome", "title": "Welcome", "fields": [
        field("welcome.enabled", "Welcome messages", "bool"),
        field("welcome.channel", "Channel", "text", "Blank = the community's system channel"),
        field("welcome.message", "Join message", "longtext", "{mention} {name} {community} {count}"),
        field("welcome.leave_message", "Leave message", "longtext", "Blank = none"),
        field("welcome.dm_message", "DM to new members", "longtext", "Blank = none"),
    ]},
    {"id": "onboarding", "title": "Onboarding", "fields": [
        field("onboarding.steps", "Steps", "list", "verify and/or pick_roles, in order"),
        field("onboarding.channel", "Role menu channel", "text", "Blank = the system channel"),
        field("onboarding.required", "Required", "bool", "Members must finish before they can chat"),
        field("onboarding.title", "Role menu title", "text"),
        field("onboarding.prompt", "Prompt", "longtext"),
        field("onboarding.done_message", "Done message", "longtext", "{mention} {community}"),
        field("onboarding.role_menu", "Roles to offer", "emoji_map", "One emoji and one role per row"),
    ]},
    {"id": "giveaways", "title": "Giveaways", "fields": [
        field("giveaways.max_winners", "Most winners", "int", minimum=1, maximum=100),
        field("giveaways.min_minutes", "Shortest giveaway (minutes)", "int", minimum=1),
    ]},
    {"id": "games", "title": "Games", "fields": [
        field("games.winner_coins", "Coins for a win", "int", minimum=0),
        field("games.draw_coins", "Coins for a draw", "int", minimum=0),
        field("games.trivia_coins_per_point", "Trivia coins per point", "int", minimum=0),
        field("games.slots_max_bet", "Slots: biggest bet", "int", minimum=1),
        field("games.idle_timeout_seconds", "Close idle games after (seconds)", "int", minimum=30),
        field("games.join_when", "Referee joins when", "enum", options=("opened", "shared"), restart=True),
    ]},
    {"id": "dashboard", "title": "Dashboard", "fields": [
        field("dashboard.base_url", "Public address", "text", "The address people open, used in sign-in links",
              restart=True),
        field("dashboard.host", "Listen on", "text", "127.0.0.1 = this computer only", restart=True),
        field("dashboard.port", "Port", "int", minimum=1, maximum=65535, restart=True),
        field("dashboard.vector_code_login", "Sign in with a Vector code", "bool",
              "Lets admins without a password (or who forgot it) get a one-time code by Vector DM"),
        field("dashboard.session_days", "Stay signed in (days)", "int", minimum=1, maximum=90),
        field("dashboard.code_minutes", "Sign-in codes last (minutes)", "int", minimum=2, maximum=60),
    ]},
]

FIELDS: dict[str, F] = {f["path"]: f for g in GROUPS for f in g["fields"]}


class FieldError(ValueError):
    pass


def coerce(path: str, value: Any) -> Any:
    """Turn what the browser sent into the type config.yaml uses. Raises FieldError."""
    f = FIELDS.get(path)
    if f is None:
        raise FieldError(f"{path}: not an editable setting")
    kind, label = f["type"], f["label"]
    if kind == "bool":
        if not isinstance(value, bool):
            raise FieldError(f"{label}: must be on or off")
        return value
    if kind == "int":
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise FieldError(f"{label}: must be a whole number") from None
        if f["min"] is not None and n < f["min"]:
            raise FieldError(f"{label}: at least {f['min']}")
        if f["max"] is not None and n > f["max"]:
            raise FieldError(f"{label}: at most {f['max']}")
        return n
    if kind in ("text", "longtext"):
        if not isinstance(value, str):
            raise FieldError(f"{label}: must be text")
        return value if kind == "longtext" else value.strip()
    if kind == "enum":
        if value not in f["options"]:
            raise FieldError(f"{label}: pick one of {', '.join(f['options'])}")
        return value
    if kind == "list":
        items = value.splitlines() if isinstance(value, str) else value
        if not isinstance(items, list):
            raise FieldError(f"{label}: must be a list")
        return [str(x).strip() for x in items if str(x).strip()]
    if kind == "emoji_map":
        if not isinstance(value, dict):
            raise FieldError(f"{label}: must be emoji → role pairs")
        out = {str(k).strip(): str(v).strip() for k, v in value.items() if str(k).strip() and str(v).strip()}
        return out
    raise FieldError(f"{label}: unknown type {kind}")

"""The settings the dashboard can edit, grouped as they appear on the Settings page.

Each field is a dotted path into config.yaml. Saved values are stored as overrides in the database and
layered on top of config.yaml, so the file (and its comments) is never rewritten.
"""

from __future__ import annotations

from typing import Any

from ..config import MODULES

# type: bool | int | text | channel | longtext | enum | list | emoji_map
# (channel is text, matched loosely; the dashboard offers the community's channels to pick from)
F = dict[str, Any]


def field(path: str, label: str, kind: str, help: str = "", *, options: tuple = (), restart: bool = False,
          minimum: int | None = None, maximum: int | None = None) -> F:
    return {"path": path, "label": label, "type": kind, "help": help, "options": list(options), "restart": restart,
            "min": minimum, "max": maximum}


MODULE_LABEL = {"roles": "Role menus", "securitycam": "Security cam", "games": "Mini games", "events": "Event calendar"}

MODULE_HELP = {
    "moderation": "Warnings, timeouts, kicks, bans, purge, lock, slowmode, automod",
    "leveling": "XP for chatting, levels, rank cards, role rewards",
    "economy": "Coins, daily and work rewards, shop",
    "tickets": "Private support channels",
    "verification": "New members pass a question, a reaction or a CAPTCHA before they can talk",
    "roles": "Reaction role menus",
    "giveaways": "Timed giveaways with reactions",
    "games": "WebXDC mini games refereed by the bot",
    "welcome": "Join and leave messages",
    "onboarding": "Welcome → verify → pick roles",
    "utility": "Polls, reminders, analytics and other tools",
    "webhooks": "Webhooks declared in config.yaml",
    "events": "Event calendar with RSVPs, reminders and repeats",
    "securitycam": "Echo every message from every channel into one staff channel",
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
        field(f"modules.{m}", MODULE_LABEL.get(m, m.capitalize()), "bool", MODULE_HELP.get(m, ""), restart=True)
        for m in MODULES
    ]},
    {"id": "moderation", "title": "Moderation", "fields": [
        field("moderation.log_channel", "Mod log channel", "channel", "Channel name or id (blank = none)"),
        field("verification.softban_escalate", "Softban returns before a real ban", "int", "0 = never",
              minimum=0, maximum=50),
        field("moderation.warn_threshold", "Warnings before action", "int", minimum=1, maximum=50),
        field("moderation.warn_action", "Action at threshold", "enum", options=("timeout", "kick", "ban", "none")),
        field("moderation.warn_action_minutes", "Timeout length (minutes)", "int", minimum=1, maximum=40320),
        field("moderation.mute_max_days", "Longest timeout (days)", "int", minimum=1, maximum=28),
    ]},
    {"id": "backup", "title": "Restore points", "fields": [
        field("backup.every_hours", "Make one every (hours)", "int", "0 = only before risky changes and by hand",
              minimum=0, maximum=720),
        field("backup.keep_automatic", "Scheduled and automatic points to keep", "int", minimum=1, maximum=500),
        field("backup.keep_manual", "Points you make to keep", "int", minimum=1, maximum=500),
        field("backup.dir", "Folder", "text", "Blank = data/restore-points. Another disk is safer.", restart=True),
        field("backup.include_pictures", "Include event pictures", "bool"),
    ]},
    {"id": "events", "title": "Events", "fields": [
        field("events.timezone", "Default time zone", "text", "e.g. America/New_York. Each community can override it "
              "with !event timezone or on the Events page."),
        field("events.channel", "Event channel", "channel", "Where event posts go. A name or id; \"announcements\" finds "
              "\"📣┊Announcements\". Blank = where the command was used."),
        field("events.banner_image", "Banner picture on each event", "bool", "A picture attached to the command wins"),
        field("events.default_minutes", "Default length (minutes)", "int", minimum=1, maximum=20160),
        field("events.reminders", "Reminders (minutes before)", "list", "One number per line, e.g. 60 and 15"),
        field("events.dm_reminders", "DM reminders to people going", "bool"),
        field("events.who_can_create", "Who can create events", "enum", options=("staff", "everyone")),
        field("events.attendee_roles", "Give attendees a role", "bool", "A temporary role per event, for pings"),
        field("events.calendar_image", "Calendar as an image", "bool"),
        field("events.week_starts", "Week starts on", "enum", options=("monday", "sunday")),
    ]},
    {"id": "securitycam", "title": "Security cam", "fields": [
        field("securitycam.channel", "Camera channel", "channel", "Channel name or id that receives every echoed "
              "message. Blank = use the one set with !securitycam set. Keep it private."),
        field("securitycam.include_bots", "Include other bots", "bool"),
        field("securitycam.ignore_channels", "Channels to skip", "list", "Names or ids, one per line"),
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
        field("leveling.announce_channel", "Level-up channel", "channel", "Blank = where the member was chatting"),
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
        field("tickets.log_channel", "Ticket log channel", "channel", "Opened and closed tickets are noted here (blank = none)"),
        field("tickets.support_role", "Support role", "text", "Role that can see every ticket"),
        field("tickets.max_open_per_user", "Open tickets per member", "int", minimum=1, maximum=20),
        field("tickets.close_emoji", "Close emoji", "text", "React with this in a ticket to close it (blank = off)"),
        field("tickets.transcripts", "Keep transcripts", "bool"),
    ]},
    {"id": "verification", "title": "Verification", "fields": [
        field("verification.mode", "Mode", "enum",
              "question = answer a sum, button = react ✅, captcha = a CAPTCHA web page",
              options=("question", "button", "captcha"), restart=True),
        field("verification.role", "Verified role", "text"),
        field("verification.max_attempts", "Attempts", "int", minimum=1, maximum=20),
        field("verification.channel", "Verification channel", "channel", "Blank = the system channel"),
        field("verification.log_channel", "Verification log channel", "channel",
              "Verifications, refusals and softbans (blank = the mod log)"),
        field("verification.gate", "Hide unverified messages", "enum", "channel = only the verification channel",
              options=("off", "channel", "all")),
        field("verification.spam_kick", "Softban after gated messages", "int", "Within 15 minutes, 0 = never",
              minimum=0, maximum=50),
        field("verification.public_url", "Verification page address", "text",
              "https address members open; blank = the dashboard address", restart=True),
        field("verification.link_minutes", "Link lasts (minutes)", "int", minimum=1, maximum=1440),
        field("verification.captcha.provider", "CAPTCHA provider name", "text", "Shown on the page"),
        field("verification.captcha.site_key", "CAPTCHA site key", "text", "The public key from your provider"),
        field("verification.captcha.secret_key_env", "Secret key variable", "text",
              "Environment variable holding the secret. The secret itself never goes in the dashboard."),
        field("verification.captcha.verify_url", "CAPTCHA check URL", "text"),
        field("verification.captcha.script_url", "CAPTCHA script URL", "text"),
        field("verification.device_check", "One verification per device", "bool"),
        field("verification.device_check_days", "Remember devices (days)", "int", minimum=1, maximum=365),
        field("verification.on_duplicate", "Second account on a device", "enum", options=("refuse", "kick", "softban")),
        field("verification.min_age", "Minimum age", "int", "0 = don't ask", minimum=0, maximum=120),
        field("verification.adult_role", "Adults-only role", "text", "Claimed with !adult. Blank = none"),
        field("verification.invite_to", "Invite gate target", "text", "Community verified members are invited to"),
    ]},
    {"id": "welcome", "title": "Welcome", "fields": [
        field("welcome.enabled", "Welcome messages", "bool"),
        field("welcome.channel", "Welcome channel", "channel", "Blank = the community's system channel"),
        field("welcome.message", "Join message", "longtext", "{mention} {name} {community} {count}"),
        field("welcome.leave_message", "Leave message", "longtext", "Blank = none"),
        field("welcome.leave_channel", "Leave channel", "channel", "Blank = the welcome channel"),
        field("welcome.dm_message", "DM to new members", "longtext", "Blank = none"),
    ]},
    {"id": "onboarding", "title": "Onboarding", "fields": [
        field("onboarding.steps", "Steps", "list", "verify and/or pick_roles, in order"),
        field("onboarding.channel", "Role menu channel", "channel", "Blank = the system channel"),
        field("onboarding.required", "Required", "bool", "Members must finish before they can chat"),
        field("onboarding.log_channel", "Onboarding log channel", "channel", "Notes who finished (blank = none)"),
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

# The setup wizard (dashboard and `vectiq --setup`) walks through these steps in order, one
# question per screen, with the bot doing the talking. "say" opens the step; "when" shows a
# step only if a setting has one of the given values (as answered earlier in the wizard).
WIZARD: list[dict[str, Any]] = [
    {"id": "basics", "title": "The basics", "say": "First, the basics: how people talk to me, and who's in charge.",
     "paths": ["prefix", "owners", "communities"]},
    {"id": "features", "title": "Features", "say": "Pick what I should do. Tick as many as you like; you can change "
     "your mind later.", "paths": [f"modules.{m}" for m in MODULES]},
    {"id": "channels", "title": "Channels", "say": "Now, where should I post things? Pick a channel or leave it on "
     "the default. Names match loosely, so \"mod-log\" finds \"🛡┊mod-log\".",
     "paths": ["moderation.log_channel", "verification.channel", "verification.log_channel", "welcome.channel",
               "welcome.leave_channel", "onboarding.channel", "onboarding.log_channel", "events.channel",
               "leveling.announce_channel", "tickets.log_channel", "securitycam.channel"]},
    {"id": "verification", "title": "Verification", "say": "Let's keep the bots out. I'll check new members are "
     "human before they can join in.", "when": {"modules.verification": [True]},
     "paths": ["verification.mode", "verification.role", "verification.gate", "verification.spam_kick",
               "verification.min_age", "verification.adult_role", "verification.invite_to"]},
    {"id": "captcha", "title": "CAPTCHA", "say": "For CAPTCHA checks I need a key from Cloudflare Turnstile, hCaptcha "
     "or reCAPTCHA. They're free. Keep the secret key out of here: it goes in your .env file.",
     "when": {"modules.verification": [True], "verification.mode": ["captcha"]},
     "paths": ["verification.captcha.provider", "verification.captcha.site_key", "verification.captcha.secret_key_env",
               "verification.captcha.verify_url", "verification.captcha.script_url", "verification.public_url",
               "verification.device_check", "verification.on_duplicate"]},
    {"id": "moderation", "title": "Moderation", "say": "When someone breaks the rules, how firm should I be?",
     "when": {"modules.moderation": [True]},
     "paths": ["moderation.warn_threshold", "moderation.warn_action", "verification.softban_escalate",
               "moderation.automod.enabled", "moderation.automod.block_links"]},
    {"id": "welcome", "title": "New members", "say": "Last one: what should new members see when they arrive?",
     "when": {"modules.welcome": [True]},
     "paths": ["welcome.message", "welcome.leave_message", "onboarding.steps", "onboarding.required"]},
]

# What the bot asks on each screen. Anything not listed falls back to the setting's label.
WIZARD_ASK: dict[str, str] = {
    "prefix": "What should my commands start with? Most communities use !",
    "owners": "Who owns me? Add your npub, and anyone else who should control the bot everywhere.",
    "communities": "Which communities should I look after? Leave it empty and I'll serve every one I'm in.",
    "moderation.log_channel": "Where should I write down warnings, kicks and bans?",
    "verification.channel": "Where should I greet new members and ask them to verify?",
    "verification.log_channel": "Where should I note who verified, and who I turned away?",
    "welcome.channel": "Where should I say hello to new members?",
    "welcome.leave_channel": "And where should I mention when someone leaves?",
    "onboarding.channel": "Where should the pick-your-roles menu live?",
    "onboarding.log_channel": "Where should I note who finished onboarding?",
    "events.channel": "Where should I post events?",
    "leveling.announce_channel": "Where should I announce level-ups?",
    "tickets.log_channel": "Where should I note opened and closed tickets?",
    "securitycam.channel": "Which channel gets a copy of every message? Keep it staff-only.",
    "verification.mode": "How should new members prove they're human?",
    "verification.role": "What should the role for verified members be called? I'll create it if needed.",
    "verification.gate": "Should I hide messages from people who haven't verified yet?",
    "verification.spam_kick": "If someone keeps posting without verifying, after how many messages should I "
                              "show them the door? (0 means never)",
    "verification.min_age": "Is there a minimum age? (0 means I won't ask)",
    "verification.adult_role": "Want an adults-only role that members aged 18+ can claim? Name it, or leave it empty.",
    "verification.invite_to": "Using a lobby? Name the real community I should invite verified members to. "
                              "Leave it empty if not.",
    "verification.captcha.provider": "Which CAPTCHA service are you using?",
    "verification.captcha.site_key": "What's your site key? It's the public one.",
    "verification.captcha.secret_key_env": "Which environment variable holds the secret key?",
    "verification.captcha.verify_url": "Where do I check answers? The default is Cloudflare Turnstile's.",
    "verification.captcha.script_url": "And where does the CAPTCHA script load from?",
    "verification.public_url": "What web address will members open? Use https. Empty means the dashboard's address.",
    "verification.device_check": "Should I stop one device from verifying lots of accounts?",
    "verification.on_duplicate": "If a second account tries from the same device, what should I do?",
    "moderation.warn_threshold": "How many warnings before I step in?",
    "moderation.warn_action": "And then what should I do?",
    "verification.softban_escalate": "If a softbanned member keeps coming back, after how many returns should it "
                                     "become a real ban? (0 means never)",
    "moderation.automod.enabled": "Should I watch for spam, mass mentions and shouting on my own?",
    "moderation.automod.block_links": "Should I remove links from members who aren't staff?",
    "welcome.message": "What should I say when someone joins? You can use {mention}, {name}, {community} and {count}.",
    "welcome.leave_message": "And when someone leaves? Leave it empty to say nothing.",
    "onboarding.steps": "What should new members go through, in order? verify, pick_roles, or both.",
    "onboarding.required": "Do members have to pick a role before they're done?",
}

WIZARD_HELLO = ("Hi! I'm Vectiq. I'll ask you a few questions and set myself up for your community. "
                "It takes about five minutes. You can go back any time, and nothing changes until you say so.")
WIZARD_READY = "That's everything. Here's what I'll change. Look it over, then I'll save it."
WIZARD_DONE = "All set! Thanks for having me."

# A question in the wizard is only asked when it applies (same rule shape as a step's "when").
WIZARD_WHEN: dict[str, dict[str, list]] = {
    "moderation.log_channel": {"modules.moderation": [True]},
    "verification.channel": {"modules.verification": [True]},
    "verification.log_channel": {"modules.verification": [True]},
    "welcome.channel": {"modules.welcome": [True]},
    "welcome.leave_channel": {"modules.welcome": [True]},
    "onboarding.channel": {"modules.onboarding": [True]},
    "onboarding.log_channel": {"modules.onboarding": [True]},
    "onboarding.steps": {"modules.onboarding": [True]},
    "onboarding.required": {"modules.onboarding": [True]},
    "events.channel": {"modules.events": [True]},
    "leveling.announce_channel": {"modules.leveling": [True]},
    "tickets.log_channel": {"modules.tickets": [True]},
    "securitycam.channel": {"modules.securitycam": [True]},
    "verification.spam_kick": {"verification.gate": ["channel", "all"]},
    "verification.on_duplicate": {"verification.device_check": [True]},
    "moderation.automod.block_links": {"moderation.automod.enabled": [True]},
}

# Plain explanations for each choice, shown next to the options in both wizards.
OPTION_HELP: dict[str, dict[str, str]] = {
    "verification.mode": {
        "question": "Answer a quick sum in chat. Nothing else to set up.",
        "button": "React ✅ on a message. Easiest for people, easiest for bots too.",
        "captcha": "Open a personal link and pass a CAPTCHA. Stops bots best; needs a web address and a CAPTCHA key.",
    },
    "verification.gate": {
        "off": "Unverified members can talk, they just don't get the role.",
        "channel": "Messages in the verification channel are hidden until they verify.",
        "all": "Messages anywhere are hidden until they verify.",
    },
    "verification.on_duplicate": {
        "refuse": "Say no and let staff decide. Safest: families and shared Wi-Fi look like one device.",
        "kick": "Remove the second account. It can rejoin.",
        "softban": "Remove it and keep removing it if it comes back.",
    },
    "moderation.warn_action": {
        "timeout": "Mute them for a while.", "kick": "Remove them; they can rejoin.",
        "ban": "Remove them for good.", "none": "Just count the warnings.",
    },
}


def applies(path_or_step: Any, value) -> bool:
    """Is this wizard step (a dict with "when") or question (a path) relevant, given value(path)?"""
    when = path_or_step.get("when") if isinstance(path_or_step, dict) else WIZARD_WHEN.get(path_or_step)
    return all(value(p) in ok for p, ok in (when or {}).items())


assert all(p in FIELDS for step in WIZARD for p in step["paths"]), "wizard path missing from GROUPS"
assert all(p in FIELDS for p in WIZARD_WHEN) and all(p in FIELDS for p in OPTION_HELP)
assert all(p in FIELDS for p in WIZARD_ASK)


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
    if kind in ("text", "longtext", "channel"):
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

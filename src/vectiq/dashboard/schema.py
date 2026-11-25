"""The settings the dashboard can edit, grouped as they appear on the Settings page.

Each field is a dotted path into config.yaml. Saved values are stored as overrides in the database and
layered on top of config.yaml, so the file (and its comments) is never rewritten.
"""

from __future__ import annotations

from typing import Any

from .. import modules

# type: bool | int | number | text | channel | longtext | enum | list | emoji_map
# (channel is text, matched loosely; the dashboard offers the community's channels to pick from)
F = dict[str, Any]


def field(path: str, label: str, kind: str, help: str = "", *, options: tuple = (), restart: bool = False,
          minimum: int | None = None, maximum: int | None = None) -> F:
    return {"path": path, "label": label, "type": kind, "help": help, "options": list(options), "restart": restart,
            "min": minimum, "max": maximum}


MODULE_LABEL: dict[str, str] = {}
MODULE_HELP: dict[str, str] = {}
ACTIONS = ("delete", "warn", "timeout", "log")

GROUPS: list[dict[str, Any]] = [
    {"id": "general", "title": "General", "fields": [
        field("prefix", "Command prefix", "text", "What commands start with, e.g. !help"),
        field("communities", "Communities served", "list", "Community names or ids, one per line. Empty = every "
              "community the bot is in."),
        field("owners", "Bot owners", "list", "npubs, one per line. Owners can use owner commands, change these "
              "settings and manage webhooks."),
    ]},
    {"id": "profile", "title": "Bot profile", "fields": [
        field("profile.name", "Name", "text", "The bot's name in Vector. Empty leaves it as it is."),
        field("profile.about", "About", "longtext", "The text on its profile. Empty leaves it as it is."),
        field("profile.avatar", "Picture", "text", "A picture file on the bot's computer (a path, relative to "
              "config.yaml) or a web address. Set again whenever the file changes."),
    ]},
    {"id": "modules", "title": "Modules", "fields": []},          # filled by refresh(): every module, plugins too
    {"id": "mcp", "title": "MCP server", "fields": [
        field("mcp.read_only", "Read-only", "bool", "Assistants can look but not change anything"),
        field("mcp.host", "Listen on", "text", "127.0.0.1 keeps it on this computer"),
        field("mcp.port", "Port", "int", minimum=1, maximum=65535),
    ]},
    {"id": "plugins", "title": "Plugins", "fields": [
        field("plugins.dirs", "Plugin folders", "list", "Folders with plugin modules, relative to config.yaml",
              restart=True),
        field("plugins.allow_install", "Owners may install plugins from chat", "bool",
              "`!module install <package>` runs pip on the bot's computer. Only turn on if you trust every owner."),
    ]},
    {"id": "marketplace", "title": "Marketplace", "fields": [
        field("marketplace.repo", "Marketplace", "text", "The GitHub repository modules are browsed from (owner/name)"),
        field("marketplace.branch", "Branch", "text"),
        field("marketplace.allow_code", "Allow modules with code", "bool",
              "Some JSON modules carry Python that runs on this computer with the bot's access. Leave off unless "
              "you've read the module or trust its author. Modules without code are always allowed."),
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
    {"id": "updates", "title": "Updates", "fields": [
        field("updates.check", "Check for updates", "bool", "One small request to GitHub every few hours"),
        field("updates.every_hours", "Check every (hours)", "int", minimum=1, maximum=168),
        field("updates.notify", "DM the owners when one is ready", "bool"),
        field("updates.auto_install", "Install updates automatically", "bool",
              "Makes a restore point, installs and restarts by itself. Only works on a git install."),
        field("updates.restart", "Restart after updating", "bool"),
    ]},
    {"id": "securitycam", "title": "Security cam", "fields": [
        field("securitycam.channel", "Camera channel", "channel", "Channel name or id that receives every echoed "
              "message. Blank = use the one set with !securitycam set. Keep it private."),
        field("securitycam.include_bots", "Include other bots", "bool"),
        field("securitycam.dashboard_feed", "Live feed on the dashboard", "bool",
              "Shows messages as they arrive on the Security cam page. Kept in memory only."),
        field("securitycam.feed_size", "Messages the live feed keeps", "int", minimum=20, maximum=2000),
        field("securitycam.ignore_channels", "Channels to skip", "list", "Names or ids, one per line"),
    ]},
    {"id": "sentire", "title": "Sentire", "fields": [
        field("sentire.arm.warn", "Armed: warn", "bool", "Unarmed actions are rehearsed and reported, never done"),
        field("sentire.arm.delete", "Armed: delete messages", "bool"),
        field("sentire.arm.kick", "Armed: kick", "bool"),
        field("sentire.arm.ban", "Armed: ban", "bool"),
        field("sentire.arm.raid", "Armed: contain raids", "bool"),
        field("sentire.raid.response", "Raid response", "enum", options=("report", "kick", "ban")),
        field("sentire.banned_words", "Banned words", "list", "Whole words; *word* also matches inside words"),
        field("sentire.word_gravity", "How serious a banned word is", "enum",
              options=("note", "minor", "serious", "grave")),
        field("sentire.blocked_links", "Blocked sites", "list", "Domains, one per line"),
        field("sentire.rate.enabled", "Too many messages too fast", "bool"),
        field("sentire.rate.messages", "…more than this many messages", "int", minimum=2, maximum=1000),
        field("sentire.rate.per_secs", "…in this many seconds", "int", minimum=1, maximum=3600),
        field("sentire.repetition.enabled", "The same line again and again", "bool"),
        field("sentire.mass_tagging.enabled", "Tagging a crowd", "bool"),
        field("sentire.ladder.warn_at", "Warn at strike total", "int", minimum=1, maximum=1000000),
        field("sentire.ladder.kick_at", "Kick at strike total", "int", minimum=2, maximum=1000000),
        field("sentire.ladder.ban_at", "Ban at strike total", "int", minimum=3, maximum=1000000),
        field("sentire.ladder.decay_half_life_hours", "Strikes halve every (hours)", "int", minimum=1, maximum=8760),
        field("sentire.vision.enabled", "Check pictures and video", "bool", "Sends attachments to the model below"),
        field("sentire.vision.base_url", "Vision model address", "text", "Any OpenAI-compatible /v1 address"),
        field("sentire.vision.model", "Vision model", "text"),
        field("sentire.vision.api_key_env", "Vision API key variable", "text", "Name of the .env variable"),
        field("sentire.vision.allow_remote", "Allow a model on another computer", "bool",
              "Attachments leave this computer to reach it"),
        field("sentire.communities", "Communities to watch", "list", "Blank = every community Vectiq serves"),
        field("sentire.mod_channel", "Sentence announcements channel", "channel", "Blank = the mod log"),
        field("sentire.name", "Its name", "text"),
        field("sentire.binary", "Sentire program", "text", "Blank = the one `vectiq --install-sentire` built"),
        field("sentire.config_file", "Use my own sentinel.toml", "text", "Leave blank to let Vectiq write it"),
    ]},
    {"id": "sentire_official", "title": "Sentire (official)", "fields": [
        field("sentire_official.delete", "May delete messages", "bool", "Manage Messages on its role"),
        field("sentire_official.kick", "May kick", "bool", "Kick on its role: its ladder and raid containment"),
        field("sentire_official.ban", "May ban", "bool", "Ban on its role"),
        field("sentire_official.role", "Its role's name", "text"),
    ]},
    {"id": "linksafety", "title": "Link safety", "fields": [
        field("linksafety.lists", "Blocklists", "list", "Links to domain lists, one per line. The default oisd "
              "big list covers scams, malware, phishing, ads and tracking."),
        field("linksafety.nsfw", "Also block adult sites", "bool", "Adds the oisd NSFW list"),
        field("linksafety.allow", "Always allow", "list", "Domains, one per line"),
        field("linksafety.block", "Always block", "list", "Domains, one per line"),
        field("linksafety.action", "What to do", "enum", options=ACTIONS),
        field("linksafety.refresh_hours", "Download lists every (hours)", "int", minimum=1, maximum=720),
        field("linksafety.safe_browsing_key_env", "Google Safe Browsing key variable", "text",
              "Optional: name of the .env variable with an API key"),
        field("linksafety.exempt_roles", "Roles that are skipped", "list"),
        field("linksafety.exempt_channels", "Channels that are skipped", "list"),
    ]},
    {"id": "imageguard", "title": "Image guard", "fields": [
        field("imageguard.detector", "Nudity detector", "enum", "off = only the blocklist of known pictures",
              options=("off", "nudenet", "nsfw-detector", "sightengine", "http")),
        field("imageguard.threshold", "Remove at score", "number", "0 to 1. Lower is stricter.", minimum=0, maximum=1),
        field("imageguard.action", "What to do", "enum", options=ACTIONS),
        field("imageguard.blocklist", "Blocklist of known pictures", "bool"),
        field("imageguard.match_distance", "How close counts as the same picture", "int", "0 = identical only; "
              "6 catches resized and re-saved copies", minimum=0, maximum=20),
        field("imageguard.remember", "Remember pictures the detector removed", "bool"),
        field("imageguard.allow_channels", "Channels where anything goes", "list", "e.g. an adults-only channel"),
        field("imageguard.nsfw_detector.model_path", "nsfw-detector model file", "text", "Path to the downloaded "
              ".h5 model"),
        field("imageguard.http.url", "Web API address", "text", "For the http detector"),
        field("imageguard.http.score_field", "Score field in the answer", "text", "e.g. score or result.nsfw"),
        field("imageguard.exempt_roles", "Roles that are skipped", "list"),
    ]},
    {"id": "music", "title": "Music", "fields": [
        field("music.dj_role", "DJ role", "text", "Who controls the player. Blank = everyone."),
        field("music.default_volume", "Starting volume (%)", "int", minimum=0, maximum=200),
        field("music.max_volume", "Highest volume (%)", "int", minimum=1, maximum=200),
        field("music.vote_skip_ratio", "Share of listeners to vote-skip", "number", minimum=0.05, maximum=1),
        field("music.max_queue", "Longest queue", "int", minimum=1, maximum=5000),
        field("music.max_track_minutes", "Longest song (minutes)", "int", "0 = no limit", minimum=0, maximum=1440),
        field("music.search", "Search on", "enum", options=("ytsearch", "ytmsearch", "scsearch")),
        field("music.allow_playlists", "Allow playlists", "bool"),
        field("music.max_playlist", "Most songs from a playlist", "int", minimum=1, maximum=1000),
        field("music.leave_when_alone_seconds", "Leave when alone after (seconds)", "int", minimum=5, maximum=86400),
        field("music.leave_when_idle_seconds", "Leave when idle after (seconds)", "int", minimum=5, maximum=86400),
        field("music.stay_247", "24/7 by default", "bool"),
        field("music.announce", "Post \"Now playing\"", "bool"),
        field("music.cards", "Picture cards", "bool", "Now playing and the queue as images with cover art"),
        field("music.controls", "Reaction buttons", "bool", "⏯ ⏭ ⏹ 🔁 🔀 📜 under Now playing"),
    ]},
    {"id": "notifications", "title": "Stream & video alerts", "fields": [
        field("notifications.channel", "Default channel", "channel", "Where alerts go unless a feed says otherwise"),
        field("notifications.check_minutes", "Check every (minutes)", "int", minimum=2, maximum=1440),
        field("notifications.max_per_check", "Most posts per feed per check", "int", minimum=1, maximum=20),
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
        field("onboarding.steps", "Steps", "list", "Any of verify, rules, pick_roles, tutorial, in order"),
        field("onboarding.rules", "Rules to accept", "list", "One rule per line. Used by the rules step"),
        field("onboarding.rules_emoji", "Agree reaction", "text", "New members react with this to accept"),
        field("onboarding.tutorial", "Tutorial pages", "list", "One page per line. Used by the tutorial step"),
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
     "your mind later.", "paths": []},                            # filled by refresh()
    {"id": "channels", "title": "Channels", "say": "Now, where should I post things? Pick a channel or leave it on "
     "the default. Names match loosely, so \"mod-log\" finds \"🛡┊mod-log\".",
     "paths": ["moderation.log_channel", "verification.channel", "verification.log_channel", "welcome.channel",
               "welcome.leave_channel", "onboarding.channel", "onboarding.log_channel", "events.channel",
               "leveling.announce_channel", "tickets.log_channel", "securitycam.channel", "notifications.channel"]},
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
     "paths": ["moderation.warn_threshold", "moderation.warn_action", "verification.softban_escalate"]},
    {"id": "sentire", "title": "Sentire", "say": "Sentire will moderate beside me. It starts by only watching and "
     "reporting; arm what it may do.", "when": {"modules.sentire": [True]},
     "paths": ["sentire.arm.delete", "sentire.arm.warn", "sentire.arm.kick", "sentire.arm.ban", "sentire.arm.raid",
               "sentire.raid.response", "sentire.banned_words", "sentire.vision.enabled", "sentire.vision.base_url",
               "sentire.vision.model"]},
    {"id": "sentire_official", "title": "Sentire (official)", "say": "The official Sentire-001 will moderate here. "
     "What may it do? (Its rules are set with its own /words and /ladder commands.)",
     "when": {"modules.sentire_official": [True]},
     "paths": ["sentire_official.delete", "sentire_official.kick", "sentire_official.ban"]},
    {"id": "linksafety", "title": "Link safety", "say": "I'll check links against big public blocklists and remove "
     "the dangerous ones.", "when": {"modules.linksafety": [True]},
     "paths": ["linksafety.nsfw", "linksafety.action", "linksafety.allow"]},
    {"id": "imageguard", "title": "Image guard", "say": "Now pictures. I can remove pictures you've blocked, and "
     "with a detector I can spot nudity too.", "when": {"modules.imageguard": [True]},
     "paths": ["imageguard.detector", "imageguard.threshold", "imageguard.nsfw_detector.model_path",
               "imageguard.http.url", "imageguard.action", "imageguard.allow_channels"]},
    {"id": "music", "title": "Music", "say": "Music! Who gets to control the player?",
     "when": {"modules.music": [True]},
     "paths": ["music.dj_role", "music.default_volume", "music.search", "music.stay_247"]},
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
    "notifications.channel": "Where should YouTube, Twitch and RSS alerts go?",
    "sentire.arm.delete": "May Sentire delete messages that break the rules?",
    "sentire.arm.warn": "May it warn members?",
    "sentire.arm.kick": "May it kick members who keep at it?",
    "sentire.arm.ban": "May it ban members who reach the top of its ladder?",
    "sentire.arm.raid": "May it contain raids (a wave of new accounts) on its own?",
    "sentire.raid.response": "What should it do to raiders?",
    "sentire.banned_words": "Any words Sentire should treat as serious? Separate them with commas.",
    "sentire.vision.enabled": "Should Sentire check pictures and video with a vision model?",
    "sentire.vision.base_url": "Where is that model? (an OpenAI-compatible address)",
    "sentire.vision.model": "Which model?",
    "music.dj_role": "Which role can skip, loop and change the volume without a vote? Leave it empty to let everyone.",
    "music.default_volume": "How loud should I start, in percent?",
    "music.search": "Where should I search when someone types a song name?",
    "music.stay_247": "Should I stay in the voice channel even when nobody's listening?",
    "linksafety.nsfw": "Should I also block adult sites?",
    "linksafety.action": "When someone posts a dangerous link, what should I do?",
    "linksafety.allow": "Any sites I should always allow, even if a list says otherwise?",
    "imageguard.detector": "Should I look for nudity in pictures? Pick a detector, or off.",
    "imageguard.threshold": "How sure should I be before removing a picture? 0.7 is a good start; lower is stricter.",
    "imageguard.nsfw_detector.model_path": "Where is the nsfw-detector model file you downloaded?",
    "imageguard.http.url": "What's the address of your image-checking API?",
    "imageguard.action": "When I remove a picture, what else should I do?",
    "imageguard.allow_channels": "Any channels where pictures shouldn't be checked (like an adults-only one)?",
    "welcome.message": "What should I say when someone joins? You can use {mention}, {name}, {community} and {count}.",
    "welcome.leave_message": "And when someone leaves? Leave it empty to say nothing.",
    "onboarding.steps": "What should new members go through, in order? verify, rules, pick_roles, tutorial.",
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
    "notifications.channel": {"modules.notifications": [True]},
    "sentire.raid.response": {"sentire.arm.raid": [True]},
    "sentire.vision.base_url": {"sentire.vision.enabled": [True]},
    "sentire.vision.model": {"sentire.vision.enabled": [True]},
    "imageguard.threshold": {"imageguard.detector": ["nudenet", "nsfw-detector", "sightengine", "http"]},
    "imageguard.nsfw_detector.model_path": {"imageguard.detector": ["nsfw-detector"]},
    "imageguard.http.url": {"imageguard.detector": ["http"]},
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
    "linksafety.action": {
        "delete": "Remove it and say why.", "warn": "Remove it and add a warning.",
        "timeout": "Remove it, warn and mute them for a while.", "log": "Leave it, just tell the mod log.",
    },
    "imageguard.action": {
        "delete": "Remove it and say why.", "warn": "Remove it and add a warning.",
        "timeout": "Remove it, warn and mute them for a while.", "log": "Leave it, just tell the mod log.",
    },
    "sentire.raid.response": {"report": "Only tell the mod channel.", "kick": "Remove them; they could come back.",
                              "ban": "Remove them and close the door they came through."},
    "music.search": {"ytsearch": "YouTube.", "ytmsearch": "YouTube Music: better for songs.",
                     "scsearch": "SoundCloud."},
    "imageguard.detector": {
        "off": "Only pictures you've blocked with !imageguard block. Nothing to install.",
        "nudenet": "NudeNet, on this computer. Private and free; pip install \"vectiq[nudenet]\".",
        "nsfw-detector": "GantMan's model on this computer. Needs TensorFlow and a model download.",
        "sightengine": "Sightengine's web API. Accurate; needs an account and keys in .env.",
        "http": "Your own web API that answers with a score.",
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


def refresh() -> None:
    """Rebuild everything that lists modules, after plugins were found. Lists are changed in place."""
    MODULE_LABEL.clear()
    MODULE_HELP.clear()
    for m in modules.REGISTRY:
        MODULE_LABEL[m.name] = m.label
        hint = m.install_hint() if m.imports else ""
        who = "" if m.builtin else f" (plugin{', ' + m.version if m.version else ''})"
        MODULE_HELP[m.name] = m.help + who + (f" (needs {hint})" if hint else "")
    next(g for g in GROUPS if g["id"] == "modules")["fields"][:] = [
        field(f"modules.{m.name}", m.label, "bool", MODULE_HELP[m.name]) | {"group": m.group, "slot": m.slot}
        for m in modules.REGISTRY]
    GROUPS[:] = [g for g in GROUPS if not g.get("plugin")]
    WIZARD[:] = [st for st in WIZARD if not st.get("plugin")]
    at = next(i for i, st in enumerate(WIZARD) if st["id"] == "welcome")
    for m in modules.plugins():
        fields = [f for f in m.settings if isinstance(f, dict) and str(f.get("path", "")).startswith(m.name + ".")]
        if not fields:
            continue
        GROUPS.append({"id": f"plugin-{m.name}", "title": m.label, "fields": fields, "plugin": True})
        WIZARD.insert(at, {"id": f"plugin-{m.name}", "title": m.label, "plugin": True,
                           "say": m.wizard or f"Now {m.label}.", "when": {f"modules.{m.name}": [True]},
                           "paths": [f["path"] for f in fields]})
        at += 1
    FIELDS.clear()
    FIELDS.update({f["path"]: f for g in GROUPS for f in g["fields"]})
    next(st for st in WIZARD if st["id"] == "features")["paths"][:] = [f"modules.{n}" for n in modules.NAMES]


refresh()
modules.on_change(refresh)

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
    if kind == "number":
        try:
            x = float(value)
        except (TypeError, ValueError):
            raise FieldError(f"{label}: must be a number") from None
        if f["min"] is not None and x < f["min"]:
            raise FieldError(f"{label}: at least {f['min']}")
        if f["max"] is not None and x > f["max"]:
            raise FieldError(f"{label}: at most {f['max']}")
        return x
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

"""Every feature Vectiq has, in one list.

Each feature is a module you can switch on or off in config.yaml (``modules:``), the setup wizard, the dashboard
or with ``!module``. A module's code is only imported when it is on, and switching one on or off takes effect
straight away, without a restart. Modules that need extra Python packages say which ``pip install`` extra
provides them; the bot keeps running without them and says what is missing.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Module:
    name: str
    label: str
    help: str
    group: str
    cogs: tuple[str, ...]
    default: bool = True
    extra: str = ""                                  # pip extra that provides `imports`, e.g. "dashboard"
    imports: tuple[str, ...] = ()                    # top-level packages the module needs beyond the basics
    works_with: tuple[str, ...] = field(default=())  # other modules it can use when they are on (never required)

    def missing(self) -> list[str]:
        """Packages this module needs that aren't installed."""
        return [p for p in self.imports if importlib.util.find_spec(p) is None]

    def install_hint(self) -> str:
        return f'pip install "vectiq[{self.extra}]"' if self.extra else ""


GROUPS = ("Safety", "Members", "Community", "Fun", "Integrations")

REGISTRY: tuple[Module, ...] = (
    # -- Safety
    Module("moderation", "Moderation", "Warnings, timeouts, kicks, bans, softbans, purge, lock and slowmode",
           "Safety", ("vectiq.cogs.moderation",)),
    Module("automod", "Automod", "Removes spam, mass mentions, shouting, banned words, invites, floods and risky "
           "files, each rule on its own switch", "Safety", ("vectiq.cogs.automod",), default=False,
           works_with=("moderation",)),
    Module("linksafety", "Link safety", "Checks links against big blocklists (oisd.nl) and removes scam, malware "
           "and adult sites", "Safety", ("vectiq.cogs.linksafety",), default=False, works_with=("moderation",)),
    Module("imageguard", "Image guard", "Polices pictures: a blocklist of known images, and optional nudity "
           "detection on this computer", "Safety", ("vectiq.cogs.imageguard",), default=False,
           works_with=("moderation",)),
    Module("verification", "Verification", "New members prove they're human before they can join in",
           "Safety", ("vectiq.cogs.verification",)),
    Module("securitycam", "Security cam", "Copies every message into one staff channel", "Safety",
           ("vectiq.cogs.securitycam",), default=False),
    # -- Members
    Module("welcome", "Welcome", "Welcome and goodbye messages, optional welcome DM", "Members",
           ("vectiq.cogs.welcome",)),
    Module("onboarding", "Onboarding", "Welcome, verify, pick roles; tracked per member", "Members",
           ("vectiq.cogs.onboarding",), works_with=("verification", "roles")),
    Module("roles", "Role menus", "Reaction role menus members can pick from", "Members", ("vectiq.cogs.roles",)),
    Module("tickets", "Tickets", "Private support channels with transcripts", "Members", ("vectiq.cogs.tickets",)),
    # -- Community
    Module("events", "Event calendar", "Events with RSVPs, reminders and calendar pictures", "Community",
           ("vectiq.cogs.events",)),
    Module("notifications", "Stream & video alerts", "Posts when a YouTube channel uploads, a Twitch channel goes "
           "live or any RSS feed has something new", "Community", ("vectiq.cogs.notifications",), default=False),
    Module("utility", "Utility", "Polls, reminders, user and community info", "Community", ("vectiq.cogs.utility",)),
    # -- Fun
    Module("leveling", "Leveling", "XP for chatting, levels, rank cards, role rewards", "Fun",
           ("vectiq.cogs.leveling",)),
    Module("economy", "Economy", "Coins, daily and work rewards, shop", "Fun", ("vectiq.cogs.economy",)),
    Module("giveaways", "Giveaways", "Timed giveaways with reaction entry", "Fun", ("vectiq.cogs.giveaways",)),
    Module("music", "Music", "Plays music in voice channels: search or links, a queue, loops, filters, vote-skips "
           "and a DJ role", "Fun", ("vectiq.cogs.music",), default=False, extra="music", imports=("yt_dlp",)),
    Module("games", "Mini games", "WebXDC mini games refereed by the bot", "Fun", ("vectiq.cogs.games",),
           works_with=("economy",)),
    # -- Integrations
    Module("webhooks", "Webhooks", "Let outside tools (GitHub, Grafana...) post into channels, declared in YAML",
           "Integrations", ("vectiq.cogs.webhooks",), extra="webhooks"),
    Module("dashboard", "Web dashboard", "Manage everything from a browser", "Integrations",
           ("vectiq.cogs.dashboard",), default=False, extra="dashboard", imports=("fastapi", "uvicorn")),
)

CORE_COGS = ("vectiq.cogs.core", "vectiq.cogs.restorepoints")
BY_NAME = {m.name: m for m in REGISTRY}
NAMES = tuple(m.name for m in REGISTRY)


def get(name: str) -> Module | None:
    return BY_NAME.get(name)


def wanted(enabled) -> list[Module]:
    """The modules to run, given ``enabled(name) -> bool``."""
    return [m for m in REGISTRY if enabled(m.name)]

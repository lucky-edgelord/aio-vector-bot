"""Every feature Vectiq has, as modules: the built-in ones and any plugins you install.

Each module can be switched on or off in config.yaml (``modules:``), the setup wizard, the dashboard or with
``!module``. Its code is only imported while it is on, and switching takes effect straight away, without a restart.

Plugins are modules that don't ship with Vectiq. They come from two places:

* a pip package that declares an entry point in the ``vectiq.modules`` group pointing at a :class:`Module`
* a folder: ``modules/<name>/__init__.py`` (next to config.yaml, or in the data folder) that defines ``MODULE``
  and ``async def setup(bot)``

A plugin can add something new, or take the place of a built-in: every module fills a *slot* (``provides``,
its own name unless it says otherwise). Only one module per slot runs, so an AI automod that ``provides="automod"``
swaps with the built-in automod. See docs/writing-modules.md.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import logging
import sys
import types
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("vectiq.modules")

PLUGIN_PACKAGE = "vectiq_plugins"          # folder plugins are imported as vectiq_plugins.<folder>
ENTRY_POINT_GROUP = "vectiq.modules"


@dataclass(frozen=True)
class Module:
    name: str
    label: str
    help: str
    group: str
    cogs: tuple[str, ...] = ()
    default: bool = True
    extra: str = ""                                  # pip extra that provides `imports`, e.g. "dashboard"
    imports: tuple[str, ...] = ()                    # top-level packages the module needs beyond the basics
    works_with: tuple[str, ...] = field(default=())  # other modules it can use when they are on (never required)
    provides: str = ""                               # the slot it fills; blank = its own name
    defaults: dict = field(default_factory=dict, hash=False, compare=False)   # its config.yaml section: name:
    settings: tuple = field(default=(), hash=False, compare=False)           # dashboard/wizard fields (field())
    wizard: str = ""                                 # what the setup wizard says before its settings
    install: str = ""                                # how to install what `imports` needs, for plugins
    version: str = ""
    author: str = ""
    source: str = "built-in"                         # built-in | package <dist> | folder <path>

    @property
    def slot(self) -> str:
        return self.provides or self.name

    @property
    def builtin(self) -> bool:
        return self.source == "built-in"

    def missing(self) -> list[str]:
        """Packages this module needs that aren't installed."""
        return [p for p in self.imports if importlib.util.find_spec(p) is None]

    def install_hint(self) -> str:
        if self.install:
            return self.install
        return f'pip install "vectiq[{self.extra}]"' if self.extra else ""


GROUPS = ["Safety", "Members", "Community", "Fun", "Integrations"]

BUILTIN: tuple[Module, ...] = (
    # -- Safety
    Module("moderation", "Moderation", "Warnings, timeouts, kicks, bans, softbans, purge, lock and slowmode",
           "Safety", ("vectiq.cogs.moderation",)),
    Module("linksafety", "Link safety", "Checks links against big blocklists (oisd.nl) and removes scam, malware "
           "and adult sites", "Safety", ("vectiq.cogs.linksafety",), default=False, works_with=("moderation",)),
    Module("imageguard", "Image guard", "Polices pictures: a blocklist of known images, and optional nudity "
           "detection on this computer", "Safety", ("vectiq.cogs.imageguard",), default=False,
           works_with=("moderation",)),
    Module("sentire", "Sentire", "Automod by Sentire (VectorPrivacy), run by you: screens messages, strikes that "
           "decay, raid containment and media checks", "Safety", ("vectiq.cogs.sentire",), default=False,
           provides="automod", works_with=("moderation",)),
    Module("sentire_official", "Sentire (official)", "Automod by the official Sentire-001 bot that VectorPrivacy runs: "
           "Vectiq invites it and manages its role; nothing to build", "Safety", ("vectiq.cogs.sentire_official",),
           default=False, provides="automod"),
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
    Module("mcp", "MCP server", "Lets Claude or any MCP client manage your communities: channels, roles, "
           "members, messages, modules and settings", "Integrations", ("vectiq.cogs.mcp",), default=False,
           extra="mcp", imports=("fastmcp", "uvicorn")),
    Module("dashboard", "Web dashboard", "Manage everything from a browser", "Integrations",
           ("vectiq.cogs.dashboard",), default=False, extra="dashboard", imports=("fastapi", "uvicorn")),
)

CORE_COGS = ("vectiq.cogs.core", "vectiq.cogs.restorepoints")

# Live views of every module known right now. They are updated in place when plugins are found, so code that
# imported them keeps seeing the current list.
REGISTRY: list[Module] = list(BUILTIN)
BY_NAME: dict[str, Module] = {m.name: m for m in REGISTRY}
NAMES: list[str] = [m.name for m in REGISTRY]
PROBLEMS: dict[str, str] = {}                     # plugin name or path -> why it couldn't be loaded
_listeners: list[Callable[[], None]] = []
_scanned: set[str] = set()


def get(name: str) -> Module | None:
    return BY_NAME.get(name)


def wanted(enabled) -> list[Module]:
    """The modules to run, given ``enabled(name) -> bool``."""
    return [m for m in REGISTRY if enabled(m.name)]


def plugins() -> list[Module]:
    return [m for m in REGISTRY if not m.builtin]


def prime(ext: str) -> None:
    """Before a folder plugin's code is (re)loaded, import its package from its own folder again."""
    m = next((x for x in REGISTRY if ext in x.cogs), None)
    if m is None or not m.source.startswith("folder "):
        return
    root = ".".join(ext.split(".")[:2])
    if root not in sys.modules:
        _import_plugin(root, Path(m.source.split(" ", 1)[1]))


def drop_bytecode(name: str) -> None:
    """Forget compiled copies of a folder plugin, so a reload always runs the file as it is now."""
    m = BY_NAME.get(name)
    if m is None or not m.source.startswith("folder "):
        return
    path = Path(m.source.split(" ", 1)[1])
    for pyc in (path if path.is_dir() else path.parent).rglob("__pycache__/*.pyc"):
        try:
            pyc.unlink()
        except OSError:
            pass


def owner_of(ext: str) -> str:
    """The module an extension (cog import path) belongs to."""
    return next((m.name for m in REGISTRY if ext in m.cogs), ext.rsplit(".", 1)[-1])


def same_slot(name: str) -> list[Module]:
    """Other modules that fill the same slot as ``name`` (switching one on switches these off)."""
    m = BY_NAME.get(name)
    return [] if m is None else [x for x in REGISTRY if x.slot == m.slot and x.name != name]


def on_change(fn: Callable[[], None]) -> None:
    """Call ``fn`` whenever the list of modules changes (the dashboard schema rebuilds itself)."""
    _listeners.append(fn)


def _publish() -> None:
    BY_NAME.clear()
    BY_NAME.update({m.name: m for m in REGISTRY})
    NAMES[:] = [m.name for m in REGISTRY]
    for g in {m.group for m in REGISTRY}:
        if g not in GROUPS:
            GROUPS.append(g)
    for fn in list(_listeners):
        fn()


def register(module: Module) -> Module:
    """Add (or replace) a plugin module. Built-in names can't be taken over: use ``provides`` instead."""
    if not isinstance(module, Module):
        raise TypeError("a plugin must be a vectiq.plugin.Module")
    if not module.name.replace("_", "").replace("-", "").isalnum() or module.name != module.name.lower():
        raise ValueError(f"module name {module.name!r}: use lowercase letters, digits, - and _")
    old = BY_NAME.get(module.name)
    if old is not None and old.builtin:
        raise ValueError(f"{module.name!r} is a built-in module; pick another name and set provides={module.name!r} "
                         "to take its place")
    if old is not None:
        REGISTRY[REGISTRY.index(old)] = module
    else:
        REGISTRY.append(module)
    _publish()
    return module


def forget(name: str) -> None:
    """Drop a plugin from the list (after it was uninstalled)."""
    m = BY_NAME.get(name)
    if m is not None and not m.builtin:
        REGISTRY.remove(m)
        _publish()


# -- discovery ------------------------------------------------------------------------------------------


def _plugin_package(dirs: list[Path]) -> types.ModuleType:
    """The ``vectiq_plugins`` package whose __path__ is every plugin folder, so plugins import (and reload) normally."""
    pkg = sys.modules.get(PLUGIN_PACKAGE)
    if pkg is None:
        pkg = types.ModuleType(PLUGIN_PACKAGE)
        pkg.__path__ = []                          # type: ignore[attr-defined]
        pkg.__doc__ = "Vectiq folder plugins"
        sys.modules[PLUGIN_PACKAGE] = pkg
    for d in dirs:
        if str(d) not in pkg.__path__:            # type: ignore[attr-defined]
            pkg.__path__.append(str(d))            # type: ignore[attr-defined]
    return pkg


def _import_plugin(qual: str, entry: Path) -> types.ModuleType:
    """Import a folder plugin from exactly this path (not whichever plugin folder happens to come first)."""
    for key in [k for k in sys.modules if k == qual or k.startswith(qual + ".")]:
        del sys.modules[key]
    if entry.is_dir():
        spec = importlib.util.spec_from_file_location(qual, entry / "__init__.py",
                                                      submodule_search_locations=[str(entry)])
    else:
        spec = importlib.util.spec_from_file_location(qual, entry)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[qual] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        del sys.modules[qual]
        raise
    return mod


def _from_folder(folder: Path) -> list[Module]:
    found = []
    if not folder.is_dir():
        return found
    _plugin_package([folder])
    for entry in sorted(folder.iterdir()):
        if entry.name.startswith((".", "_")):
            continue
        if entry.is_dir() and (entry / "__init__.py").exists():
            modname = entry.name
        elif entry.suffix == ".py":
            modname = entry.stem
        else:
            continue
        if not modname.isidentifier():
            PROBLEMS[str(entry)] = "the folder or file name must be a Python name (letters, digits, _)"
            continue
        qual = f"{PLUGIN_PACKAGE}.{modname}"
        try:
            importlib.invalidate_caches()
            mod = sys.modules.get(qual)
            here = entry / "__init__.py" if entry.is_dir() else entry
            if mod is not None and Path(getattr(mod, "__file__", "") or "").resolve() != here.resolve():
                if BY_NAME.get(modname) and not BY_NAME[modname].source.endswith(str(entry)):
                    PROBLEMS[str(entry)] = f"another plugin folder already has a module called {modname}"
                    continue
                mod = None
            if mod is None:
                mod = _import_plugin(qual, entry)
            m = getattr(mod, "MODULE", None)
            if not isinstance(m, Module):
                PROBLEMS[str(entry)] = "it doesn't define MODULE = Module(...)"
                continue
            # cogs default to the plugin itself; ".cog" means a module inside the plugin's folder
            cogs = tuple(f"{qual}{c}" if c.startswith(".") else c for c in (m.cogs or (qual,)))
            found.append(_with(m, cogs=cogs, source=f"folder {entry}"))
        except Exception as exc:  # noqa: BLE001 - one broken plugin must not stop the bot
            PROBLEMS[str(entry)] = f"{type(exc).__name__}: {exc}"
            log.warning("plugin %s couldn't be read: %s", entry, exc)
    return found


def _from_packages() -> list[Module]:
    found = []
    try:
        eps = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
    except Exception:  # noqa: BLE001
        return found
    for ep in eps:
        try:
            m = ep.load()
            if callable(m) and not isinstance(m, Module):
                m = m()
            if not isinstance(m, Module):
                raise TypeError("the entry point must point at a vectiq.plugin.Module")
            dist = getattr(ep, "dist", None)
            version = m.version or (dist.version if dist else "")
            found.append(_with(m, source=f"package {dist.name if dist else ep.value}", version=version))
        except Exception as exc:  # noqa: BLE001
            PROBLEMS[f"package {ep.name}"] = f"{type(exc).__name__}: {exc}"
            log.warning("plugin %s couldn't be read: %s", ep.name, exc)
    return found


def _with(m: Module, **changes: Any) -> Module:
    from dataclasses import replace

    return replace(m, **changes)


def discover(dirs: list[str | Path] = (), *, force: bool = False) -> list[Module]:
    """Find plugins in ``dirs`` and in installed packages, and add them. Returns the plugins found this time."""
    key = "|".join(sorted(str(Path(d).resolve()) for d in dirs))
    if key in _scanned and not force:
        return []
    _scanned.add(key)
    found = _from_packages()
    for d in dirs:
        found += _from_folder(Path(d).expanduser().resolve())
    added = []
    for m in found:
        try:
            register(_with(m, default=False))      # a plugin never switches itself on
            added.append(m)
        except Exception as exc:  # noqa: BLE001
            PROBLEMS[m.name] = str(exc)
            log.warning("plugin %s couldn't be added: %s", m.name, exc)
    return added

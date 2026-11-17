"""Typed access to ``config.yaml`` plus the few settings that come from the environment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import modules as _modules
from .modules import NAMES as MODULES  # a live list: plugins found later appear in it too
from .modules import REGISTRY

SAFETY_ACTIONS = ("delete", "warn", "timeout", "log")
DETECTORS = ("off", "nudenet", "nsfw-detector", "sightengine", "http")


def _merge(base: dict, over: Mapping) -> dict:
    out = dict(base)
    for key, value in (over or {}).items():
        if isinstance(value, Mapping) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


DEFAULTS: dict[str, Any] = {
    "prefix": "!",
    "communities": [],
    "owners": [],
    "modules": {m.name: m.default for m in REGISTRY},
    "moderation": {"mute_max_days": 28, "warn_threshold": 3, "warn_action": "timeout",
                   "warn_action_minutes": 60, "log_channel": ""},
    "automod": {"action": "delete", "timeout_minutes": 10, "exempt_roles": [], "exempt_channels": [],
                "mentions": {"enabled": True, "max": 6},
                "caps": {"enabled": True, "percent": 80, "min_length": 12},
                "words": {"enabled": False, "list": [], "partial": False},
                "links": {"enabled": False, "allow": []},
                "invites": {"enabled": True, "allow": [], "extra": []},
                "flood": {"enabled": True, "messages": 6, "seconds": 8},
                "duplicates": {"enabled": True, "repeats": 3, "seconds": 60},
                "files": {"enabled": True, "block": ["exe", "scr", "bat", "cmd", "com", "msi", "vbs", "js", "jar",
                                                      "ps1", "lnk", "apk", "dll", "hta", "reg"]},
                "zalgo": {"enabled": False, "max_marks": 10}},
    "linksafety": {"lists": ["https://big.oisd.nl/domainswild2"], "nsfw": False, "refresh_hours": 24,
                   "allow": [], "block": [], "action": "delete", "timeout_minutes": 10,
                   "exempt_roles": [], "exempt_channels": [], "safe_browsing_key_env": ""},
    "imageguard": {"detector": "off", "threshold": 0.7, "action": "delete", "timeout_minutes": 10,
                   "blocklist": True, "match_distance": 6, "remember": True, "max_mb": 15,
                   "allow_channels": [], "exempt_roles": [], "exempt_channels": [],
                   "nsfw_detector": {"model_path": "", "count_sexy": False},
                   "sightengine": {"user_env": "SIGHTENGINE_USER", "secret_env": "SIGHTENGINE_SECRET",
                                   "models": "nudity-2.1", "strict": False},
                   "http": {"url": "", "score_field": "score", "header": "", "header_env": ""}},
    "music": {"dj_role": "DJ", "default_volume": 80, "max_volume": 150, "max_queue": 500, "max_track_minutes": 0,
              "vote_skip_ratio": 0.5, "leave_when_alone_seconds": 60, "leave_when_idle_seconds": 300,
              "stay_247": False, "announce": True, "cards": True, "controls": True, "search": "ytsearch", "allow_playlists": True,
              "max_playlist": 100, "ffmpeg": "ffmpeg", "cookies_file": ""},
    "notifications": {"channel": "announcements", "check_minutes": 5, "max_per_check": 3, "messages": {},
                      "feeds": [], "twitch": {"client_id_env": "TWITCH_CLIENT_ID",
                                              "client_secret_env": "TWITCH_CLIENT_SECRET"}},
    "leveling": {"cards": True, "xp_min": 15, "xp_max": 25, "cooldown_seconds": 60, "announce": True,
                 "announce_channel": "", "no_xp_channels": [], "rewards": {}},
    "economy": {"currency_name": "coins", "currency_symbol": "🪙", "daily_amount": 200,
                "daily_streak_bonus": 25, "daily_streak_cap": 10, "work_min": 40, "work_max": 120,
                "work_cooldown_minutes": 30, "start_balance": 100, "message_reward": 0},
    "tickets": {"category": "", "log_channel": "",
                "support_role": "", "max_open_per_user": 2, "close_emoji": "🔒", "transcripts": True},
    "verification": {"mode": "question", "role": "Verified", "max_attempts": 3, "channel": "",
                     "gate": "off", "spam_kick": 3, "public_url": "", "link_minutes": 10,
                     "captcha": {"provider": "Cloudflare Turnstile", "site_key": "", "secret_key_env": "CAPTCHA_SECRET",
                                 "verify_url": "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                                 "script_url": "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"},
                     "device_check": True, "device_check_days": 30, "on_duplicate": "refuse",
                     "min_age": 0, "adult_role": "", "invite_to": "", "softban_escalate": 3, "log_channel": ""},
    "welcome": {"enabled": True, "channel": "",
                "message": "Welcome to {community}, {mention}! You are member #{count}.",
                "leave_message": "{name} has left {community}.", "leave_channel": "", "dm_message": ""},
    "onboarding": {"steps": ["verify", "pick_roles"], "channel": "", "log_channel": "", "required": False,
                   "title": "Pick your interests", "prompt": "Welcome! Pick your roles below, then say hi.",
                   "done_message": "{mention} you're all set. Enjoy {community}!",
                   "role_menu": {"🎮": "Gamer", "🎨": "Artist", "💻": "Dev"}},
    "giveaways": {"max_winners": 10, "min_minutes": 1},
    "games": {"join_when": "opened", "allow_unverified": False, "winner_coins": 50, "draw_coins": 10,
              "trivia_coins_per_point": 10, "slots_max_bet": 1000, "idle_timeout_seconds": 300},
    "webhooks": {"server": {"enabled": False, "host": "0.0.0.0", "port": 8080,
                            "base_url": "http://localhost:8080", "admin_key_env": "WEBHOOKS_ADMIN_KEY"},
                 "hooks": []},
    "plugins": {"dirs": ["modules"], "allow_install": False},
    "backup": {"every_hours": 24, "keep_automatic": 14, "keep_manual": 20, "dir": "", "include_pictures": True},
    "events": {"timezone": "UTC", "channel": "announcements", "banner_image": True,
               "default_minutes": 60, "reminders": [60, 15], "dm_reminders": True,
               "who_can_create": "staff", "attendee_roles": False, "calendar_image": True, "week_starts": "monday",
               "max_per_community": 200},
    "securitycam": {"channel": "", "include_bots": False, "ignore_channels": []},
    "dashboard": {"host": "127.0.0.1", "port": 8090, "base_url": "http://localhost:8090",
                  "session_days": 7, "code_minutes": 10, "vector_code_login": True},
}


def defaults() -> dict[str, Any]:
    """DEFAULTS plus every known module's switch and the settings sections plugins bring."""
    out = dict(DEFAULTS)
    out["modules"] = {m.name: m.default for m in REGISTRY}
    for m in REGISTRY:
        if m.defaults and m.name not in DEFAULTS:
            out[m.name] = _merge(m.defaults, {})
    return out


def plugin_dirs(raw: Mapping, config_path: Path, data_dir: str) -> list[Path]:
    """Where folder plugins live: plugins.dirs (relative to config.yaml) and <data dir>/modules."""
    dirs = ((raw.get("plugins") or {}) if isinstance(raw.get("plugins"), Mapping) else {}).get("dirs", ["modules"])
    out = [(config_path.parent / str(d)).resolve() for d in (dirs or [])]
    out.append((Path(data_dir) / "modules").resolve())
    return out


def unflatten(flat: Mapping[str, Any]) -> dict:
    """{"a.b": 1} -> {"a": {"b": 1}}"""
    out: dict = {}
    for dotted, value in flat.items():
        node = out
        *parents, last = dotted.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        node[last] = value
    return out


class ConfigError(ValueError):
    pass


def upgrade_legacy(raw: Mapping) -> Mapping:
    """Older config.yaml files kept automod under ``moderation.automod``; read them as the automod module."""
    old = (raw.get("moderation") or {}).get("automod") if isinstance(raw.get("moderation"), Mapping) else None
    if not isinstance(old, Mapping):
        return raw
    raw = dict(raw)
    raw["moderation"] = {k: v for k, v in raw["moderation"].items() if k != "automod"}
    if "automod" not in raw:
        words = list(old.get("banned_words") or [])
        raw["automod"] = {"action": old.get("action", "delete"),
                          "mentions": {"enabled": True, "max": old.get("max_mentions", 6)},
                          "caps": {"enabled": True, "percent": old.get("max_caps_percent", 80),
                                   "min_length": old.get("caps_min_length", 12)},
                          "words": {"enabled": bool(words), "list": words},
                          "links": {"enabled": bool(old.get("block_links"))}}
    mods = dict(raw.get("modules") or {})
    mods.setdefault("automod", bool(old.get("enabled")))
    raw["modules"] = mods
    return raw


def load_dotenv(path: str | Path = ".env", env: dict | None = None) -> int:
    """Read ``KEY=VALUE`` lines into the environment without overriding what is already set. Returns how many."""
    target = os.environ if env is None else env
    p = Path(path)
    if not p.is_file():
        return 0
    added = 0
    for raw in p.read_text("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip().removeprefix("export "), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in target:
            target[key] = value
            added += 1
    return added


@dataclass
class Config:
    data: dict[str, Any]
    nsec: str = ""
    db_path: str = "data/vectiq.db"
    data_dir: str = "data"
    path: Path | None = None
    invite_urls: list[str] = field(default_factory=list)
    file_data: dict[str, Any] = field(default_factory=dict)      # config.yaml merged over DEFAULTS
    overrides: dict[str, Any] = field(default_factory=dict)      # dotted path -> value, set in the dashboard

    # -- loading ----------------------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path | None = None, env: Mapping[str, str] | None = None) -> Config:
        env = os.environ if env is None else env
        path = Path(path or env.get("VECTIQ_CONFIG", "config.yaml"))
        raw: Mapping = {}
        if path.exists():
            try:
                raw = yaml.safe_load(path.read_text("utf-8")) or {}
            except yaml.YAMLError as exc:
                raise ConfigError(f"{path}: not valid YAML ({exc})") from exc
            if not isinstance(raw, Mapping):
                raise ConfigError(f"{path}: the top level must be a mapping")
        raw = upgrade_legacy(raw)
        _modules.discover(plugin_dirs(raw, path.resolve(), env.get("VECTIQ_DATA_DIR", "data")), force=True)
        data = _merge(defaults(), raw)
        if env.get("VECTIQ_DASHBOARD_HOST"):          # lets a container listen on 0.0.0.0 without editing config.yaml
            data["dashboard"] = {**data["dashboard"], "host": env["VECTIQ_DASHBOARD_HOST"]}
        cfg = cls(
            data=data,
            nsec=env.get("VECTOR_NSEC", ""),
            data_dir=env.get("VECTIQ_DATA_DIR", "data"),
            db_path=env.get("VECTIQ_DB", str(Path(env.get("VECTIQ_DATA_DIR", "data")) / "vectiq.db")),
            path=path,
            invite_urls=[u for u in env.get("VECTIQ_INVITE_URLS", "").split() if u],
            file_data=data,
        )
        cfg.validate()
        return cfg

    def apply_overrides(self, overrides: Mapping[str, Any]) -> None:
        """Layer dashboard-edited settings over config.yaml. Raises ConfigError (and changes nothing) if invalid."""
        before = self.data, self.overrides
        self.overrides = dict(overrides)
        self.data = _merge(self.file_data, unflatten(self.overrides))
        try:
            self.validate()
        except ConfigError:
            self.data, self.overrides = before
            raise

    def reload(self) -> None:
        """Re-read config.yaml, keeping dashboard overrides on top."""
        fresh = Config.load(self.path)
        self.file_data = fresh.file_data
        self.apply_overrides(self.overrides)

    def from_file(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.file_data
        for part in dotted.split("."):
            if not isinstance(node, Mapping) or part not in node:
                return default
            node = node[part]
        return node

    def validate(self) -> None:
        d = self.data
        if not str(d["prefix"]):
            raise ConfigError("prefix must not be empty")
        for name in d["modules"]:
            if name not in MODULES:
                hint = " Is the plugin installed? `vectiq --modules` lists what was found." if name else ""
                raise ConfigError(f"modules.{name}: unknown module (known: {', '.join(MODULES)}).{hint}")
        slots: dict[str, list[str]] = {}
        for m in REGISTRY:
            if d["modules"].get(m.name):
                slots.setdefault(m.slot, []).append(m.name)
        for slot, names in slots.items():
            if len(names) > 1:
                raise ConfigError(f"modules: {' and '.join(names)} both do {slot}; switch all but one off "
                                  f"(or use `module on {names[-1]}`, which swaps them)")
        if d["moderation"]["warn_action"] not in ("timeout", "kick", "ban", "none"):
            raise ConfigError("moderation.warn_action must be timeout, kick, ban or none")
        vf = d["verification"]
        if vf["mode"] not in ("question", "button", "captcha"):
            raise ConfigError("verification.mode must be question, button or captcha")
        if vf["gate"] not in ("off", "channel", "all"):
            raise ConfigError("verification.gate must be off, channel or all")
        if vf["on_duplicate"] not in ("refuse", "kick", "softban"):
            raise ConfigError("verification.on_duplicate must be refuse, kick or softban")
        if not isinstance(vf["min_age"], int) or not 0 <= vf["min_age"] <= 120:
            raise ConfigError("verification.min_age must be 0 (off) to 120")
        if vf["mode"] == "captcha" and d["modules"].get("verification"):
            if not str(vf["captcha"]["site_key"]).strip():
                raise ConfigError("verification.captcha.site_key is needed for mode: captcha")
            if not str(vf["public_url"] or d["dashboard"]["base_url"]).strip():
                raise ConfigError("verification.public_url is needed for mode: captcha")
        for section in ("automod", "linksafety", "imageguard"):
            if d[section]["action"] not in SAFETY_ACTIONS:
                raise ConfigError(f"{section}.action must be one of {', '.join(SAFETY_ACTIONS)}")
        for rule, r in d["automod"].items():
            if isinstance(r, Mapping) and r.get("action") and r["action"] not in SAFETY_ACTIONS:
                raise ConfigError(f"automod.{rule}.action must be one of {', '.join(SAFETY_ACTIONS)}")
        ig = d["imageguard"]
        if ig["detector"] not in DETECTORS:
            raise ConfigError(f"imageguard.detector must be one of {', '.join(DETECTORS)}")
        if not isinstance(ig["threshold"], (int, float)) or not 0 < float(ig["threshold"]) <= 1:
            raise ConfigError("imageguard.threshold must be between 0 and 1, e.g. 0.7")
        if not isinstance(d["linksafety"]["lists"], list):
            raise ConfigError("linksafety.lists must be a list of blocklist links")
        mu = d["music"]
        if mu["search"] not in ("ytsearch", "scsearch", "ytmsearch"):
            raise ConfigError("music.search must be ytsearch (YouTube), ytmsearch (YouTube Music) or scsearch (SoundCloud)")
        if not 0 < float(mu["vote_skip_ratio"]) <= 1:
            raise ConfigError("music.vote_skip_ratio must be more than 0 and at most 1, e.g. 0.5")
        if not 0 <= int(mu["default_volume"]) <= int(mu["max_volume"]):
            raise ConfigError("music.default_volume must be between 0 and max_volume")
        feeds = d["notifications"]["feeds"]
        if not isinstance(feeds, list):
            raise ConfigError("notifications.feeds must be a list")
        for i, f in enumerate(feeds):
            if not isinstance(f, Mapping) or f.get("type") not in ("youtube", "twitch", "rss") or not f.get("source"):
                raise ConfigError(f"notifications.feeds[{i}]: needs type (youtube, twitch or rss) and source")
        port = d["dashboard"]["port"]
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise ConfigError("dashboard.port must be a port number")
        if d["games"]["join_when"] not in ("opened", "shared"):
            raise ConfigError("games.join_when must be opened or shared")
        ev = d["events"]
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(str(ev["timezone"]))
        except Exception:  # noqa: BLE001
            raise ConfigError(f"events.timezone: unknown time zone {ev['timezone']!r} (e.g. America/New_York)") from None
        if ev["who_can_create"] not in ("staff", "everyone"):
            raise ConfigError("events.who_can_create must be staff or everyone")
        if any(not str(m).strip().isdigit() for m in ev["reminders"]):
            raise ConfigError("events.reminders: minutes before the start, e.g. [60, 15]")
        lv = d["leveling"]
        if lv["xp_min"] > lv["xp_max"]:
            raise ConfigError("leveling.xp_min must not exceed xp_max")
        ob = d["onboarding"]
        bad = [x for x in ob["steps"] if x not in ("verify", "pick_roles")]
        if bad:
            raise ConfigError(f"onboarding.steps: unknown step {bad[0]!r} (use verify, pick_roles)")
        if "pick_roles" in ob["steps"] and d["modules"].get("onboarding") and not ob["role_menu"]:
            raise ConfigError("onboarding.role_menu needs at least one emoji: Role pair when pick_roles is a step")
        hooks = d["webhooks"]["hooks"]
        if not isinstance(hooks, list):
            raise ConfigError("webhooks.hooks must be a list")
        seen = set()
        for i, hook in enumerate(hooks):
            if not isinstance(hook, Mapping) or not hook.get("name") or not hook.get("channel"):
                raise ConfigError(f"webhooks.hooks[{i}]: needs a name and a channel")
            if hook["name"] in seen:
                raise ConfigError(f"webhooks.hooks[{i}]: duplicate name {hook['name']!r}")
            seen.add(hook["name"])

    # -- access -----------------------------------------------------------------------

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, Mapping) or part not in node:
                return default
            node = node[part]
        return node

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def enabled(self, module: str) -> bool:
        return bool(self.data["modules"].get(module, False))

    @property
    def prefix(self) -> str:
        return str(self.data["prefix"])

    @property
    def owners(self) -> list[str]:
        return [str(o) for o in self.data["owners"]]

    @property
    def hooks(self) -> list[dict]:
        return [dict(h) for h in self.data["webhooks"]["hooks"]]

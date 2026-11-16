"""Typed access to ``config.yaml`` plus the few settings that come from the environment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

MODULES = ("moderation", "leveling", "economy", "tickets", "verification", "roles",
           "giveaways", "games", "welcome", "onboarding", "utility", "webhooks")


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
    "modules": {name: True for name in MODULES},
    "moderation": {"mute_max_days": 28, "warn_threshold": 3, "warn_action": "timeout",
                   "warn_action_minutes": 60, "log_channel": "",
                   "automod": {"enabled": False, "max_mentions": 6, "max_caps_percent": 80, "caps_min_length": 12,
                               "block_links": False, "banned_words": [], "action": "delete"}},
    "leveling": {"cards": True, "xp_min": 15, "xp_max": 25, "cooldown_seconds": 60, "announce": True,
                 "announce_channel": "", "no_xp_channels": [], "rewards": {}},
    "economy": {"currency_name": "coins", "currency_symbol": "🪙", "daily_amount": 200,
                "daily_streak_bonus": 25, "daily_streak_cap": 10, "work_min": 40, "work_max": 120,
                "work_cooldown_minutes": 30, "start_balance": 100, "message_reward": 0},
    "tickets": {"category": "", "support_role": "", "max_open_per_user": 2, "close_emoji": "🔒", "transcripts": True},
    "verification": {"mode": "question", "role": "Verified", "max_attempts": 3, "channel": ""},
    "welcome": {"enabled": True, "channel": "",
                "message": "Welcome to {community}, {mention}! You are member #{count}.",
                "leave_message": "{name} has left {community}.", "dm_message": ""},
    "onboarding": {"steps": ["verify", "pick_roles"], "channel": "", "required": False,
                   "title": "Pick your interests", "prompt": "Welcome! Pick your roles below, then say hi.",
                   "done_message": "{mention} you're all set. Enjoy {community}!",
                   "role_menu": {"🎮": "Gamer", "🎨": "Artist", "💻": "Dev"}},
    "giveaways": {"max_winners": 10, "min_minutes": 1},
    "games": {"join_when": "opened", "allow_unverified": False, "winner_coins": 50, "draw_coins": 10,
              "trivia_coins_per_point": 10, "slots_max_bet": 1000, "idle_timeout_seconds": 300},
    "webhooks": {"server": {"enabled": False, "host": "0.0.0.0", "port": 8080,
                            "base_url": "http://localhost:8080", "admin_key_env": "WEBHOOKS_ADMIN_KEY"},
                 "hooks": []},
}


class ConfigError(ValueError):
    pass


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
        data = _merge(DEFAULTS, raw)
        cfg = cls(
            data=data,
            nsec=env.get("VECTOR_NSEC", ""),
            data_dir=env.get("VECTIQ_DATA_DIR", "data"),
            db_path=env.get("VECTIQ_DB", str(Path(env.get("VECTIQ_DATA_DIR", "data")) / "vectiq.db")),
            path=path,
            invite_urls=[u for u in env.get("VECTIQ_INVITE_URLS", "").split() if u],
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        d = self.data
        if not str(d["prefix"]):
            raise ConfigError("prefix must not be empty")
        for name in d["modules"]:
            if name not in MODULES:
                raise ConfigError(f"modules.{name}: unknown module (known: {', '.join(MODULES)})")
        if d["moderation"]["warn_action"] not in ("timeout", "kick", "ban", "none"):
            raise ConfigError("moderation.warn_action must be timeout, kick, ban or none")
        if d["verification"]["mode"] not in ("question", "button"):
            raise ConfigError("verification.mode must be question or button")
        if d["games"]["join_when"] not in ("opened", "shared"):
            raise ConfigError("games.join_when must be opened or shared")
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

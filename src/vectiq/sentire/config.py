"""Sentire's sentinel.toml, written from Vectiq's ``sentire:`` settings."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .toml import dumps

NSEC_ENV = "SENTINEL_NSEC"

DEFAULTS: dict[str, Any] = {
    "binary": "",                 # blank = data/sentire/bin/sentinel, then `sentinel` on PATH
    "name": "Sentire",            # its Vector profile name
    "communities": [],            # community ids or names; blank = every community Vectiq serves
    "mod_channel": "",            # where it announces sentences; blank = moderation.log_channel
    "poll_secs": 120,
    "arm": {"warn": False, "delete": False, "kick": False, "ban": False, "raid": False},
    "banned_words": [],
    "word_gravity": "grave",
    "blocked_links": [],
    "link_gravity": "serious",
    "rate": {"enabled": True, "per_secs": 60, "messages": 10, "gravity": "minor"},
    "repetition": {"enabled": True, "times": 4, "gravity": "minor"},
    "mass_tagging": {"enabled": True, "times": 15, "gravity": "serious"},
    "ladder": {"warn_at": 1, "kick_at": 36, "ban_at": 48, "decay_half_life_hours": 168},
    "raid": {"response": "kick", "min_confidence": 75, "tripwire_accounts": 5, "tripwire_secs": 30},
    "vision": {"enabled": False, "provider": "openai", "base_url": "http://127.0.0.1:8080/v1", "model": "llava",
               "api_key_env": "", "allow_remote": False, "video": True},
    "extra": {},                  # any other sentinel.toml settings, merged in as written
    "config_file": "",            # use your own sentinel.toml instead of the one Vectiq writes
    "log_lines": 300,             # lines of its output kept for !sentire log and the dashboard
}

GRAVITIES = ("note", "minor", "serious", "grave")
RAID_RESPONSES = ("report", "kick", "ban")


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def build(cfg: dict, *, communities: list[str], mod_channel: str = "") -> dict:
    """The sentinel.toml contents as a dict."""
    c = deep_merge(DEFAULTS, cfg)
    rules: dict[str, Any] = {"window_hours": 168, "window_messages": 4000}
    if c["banned_words"]:
        rules["words"] = [{"id": "vectiq-words", "patterns": [str(w) for w in c["banned_words"]],
                           "gravity": c["word_gravity"]}]
    if c["blocked_links"]:
        rules["links"] = [{"id": "vectiq-links", "domains": [str(d).lower().lstrip("*.") for d in c["blocked_links"]],
                           "gravity": c["link_gravity"]}]
    for rule in ("rate", "repetition", "mass_tagging"):
        if c[rule].get("enabled"):
            rules[rule] = dict(c[rule])
    lad = c["ladder"]
    steps = [{"at": int(lad["warn_at"]), "response": "warn"}, {"at": int(lad["kick_at"]), "response": "kick"},
             {"at": int(lad["ban_at"]), "response": "ban"}]
    v = c["vision"]
    out = {
        "bot": {"nsec_env": NSEC_ENV, "communities": communities or ["*"], "poll_secs": max(90, int(c["poll_secs"])),
                "profile": {"name": c["name"]}},
        "arm": {k: bool(c["arm"].get(k)) for k in ("warn", "delete", "kick", "ban", "raid")},
        "rules": rules,
        "ladder": {"decay_half_life_hours": int(lad["decay_half_life_hours"]), "steps": steps},
        "raid": dict(c["raid"]),
        "vision": {"enabled": bool(v["enabled"]), "provider": v["provider"], "base_url": v["base_url"],
                   "model": v["model"], "api_key_env": v["api_key_env"], "allow_remote": bool(v["allow_remote"]),
                   "communities": communities if communities and communities != ["*"] else [],
                   "video": {"enabled": bool(v.get("video", True))}},
    }
    if mod_channel:
        out["bot"]["mod_channel"] = mod_channel
    if not v["enabled"]:
        out["vision"] = {"enabled": False}
    return deep_merge(out, c.get("extra") or {})


def write(path: Path, data: dict) -> bool:
    """Write the file if it changed. Returns True when it did."""
    text = "# Written by Vectiq from its `sentire:` settings. Edit those (or the dashboard), not this file.\n\n" \
           + dumps(data)
    if path.exists() and path.read_text("utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, "utf-8")
    tmp.replace(path)
    return True


def problems(cfg: dict) -> list[str]:
    """Settings Sentire would refuse at start, explained the Vectiq way."""
    c = deep_merge(DEFAULTS, cfg)
    out = []
    lad = c["ladder"]
    if not 0 < int(lad["warn_at"]) < int(lad["kick_at"]) < int(lad["ban_at"]):
        out.append("sentire.ladder: warn_at < kick_at < ban_at, all above 0")
    if c["raid"]["response"] not in RAID_RESPONSES:
        out.append(f"sentire.raid.response must be one of {', '.join(RAID_RESPONSES)}")
    for k in ("word_gravity", "link_gravity"):
        if c[k] not in GRAVITIES:
            out.append(f"sentire.{k} must be one of {', '.join(GRAVITIES)}")
    if c["vision"]["provider"] not in ("openai", "tee"):
        out.append("sentire.vision.provider must be openai or tee")
    return out

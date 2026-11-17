"""Export and import settings as YAML, from the dashboard or with ``vectiq --export-config`` /
``--import-config``.

An export is config.yaml with any dashboard changes applied. Keys (the bot's nsec) live in
.env and are never part of it. An import is checked first: you see every change, and anything
that isn't a valid setting is reported instead of applied.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import yaml

from .config import DEFAULTS

# Maps whose keys are yours to choose (emoji → role, level → role): imported as one value.
OPEN_MAPS = {"leveling.rewards", "onboarding.role_menu"}
MAX_BYTES = 256 * 1024


class ImportError_(ValueError):
    """The file can't be read as settings at all."""


@dataclass
class Plan:
    changes: dict[str, Any] = field(default_factory=dict)      # path -> new value
    unchanged: int = 0
    skipped: list[str] = field(default_factory=list)            # paths we won't apply, with why
    errors: list[str] = field(default_factory=list)


def export_yaml(cfg) -> str:
    text = yaml.safe_dump(json.loads(json.dumps(cfg.data)), sort_keys=False, allow_unicode=True)
    return ("# Vectiq settings, exported with any dashboard changes applied.\n"
            "# Import it on the dashboard (Settings > Import) or with: vectiq --import-config this-file.yaml\n"
            "# The bot's key is not included; it stays in .env.\n" + text)


def parse(text: str) -> dict:
    if len(text.encode()) > MAX_BYTES:
        raise ImportError_("That file is too big to be a settings file.")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ImportError_(f"That isn't valid YAML: {str(exc).splitlines()[0]}") from None
    if not isinstance(data, dict):
        raise ImportError_("That file doesn't contain settings.")
    return data


def _known(path: str) -> bool:
    node: Any = DEFAULTS
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return path.startswith("modules.") and path.count(".") == 1   # modules.* are added from the list
        node = node[part]
    return True


def leaves(data: dict, prefix: str = "") -> dict[str, Any]:
    """Flatten to dotted paths. Lists and open maps stay whole."""
    out: dict[str, Any] = {}
    for key, value in data.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and path not in OPEN_MAPS and value:
            out.update(leaves(value, path + "."))
        else:
            out[path] = value
    return out


def plan(cfg, data: dict, *, editable: dict | None = None, coerce=None) -> Plan:
    """Work out what importing ``data`` would change.

    With ``editable`` (the dashboard's fields) only those can change, values are checked with
    ``coerce``, and everything else is listed as skipped. Without it (the terminal), any known
    setting can change.
    """
    p = Plan()
    for path, value in leaves(data).items():
        if not _known(path):
            p.skipped.append(f"{path}: not a Vectiq setting")
            continue
        if editable is not None and path not in editable:
            p.skipped.append(f"{path}: change it in config.yaml or with vectiq --import-config")
            continue
        if coerce is not None:
            try:
                value = coerce(path, value)
            except ValueError as exc:
                p.errors.append(str(exc))
                continue
        current = cfg.get(path)
        if coerce is not None:
            try:
                current = coerce(path, current)   # compare like with like (e.g. [60, 15] and ["60", "15"])
            except ValueError:
                pass
        if value == current:
            p.unchanged += 1
        else:
            p.changes[path] = value
    return p

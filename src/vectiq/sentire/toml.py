"""A small TOML writer (Python only ships a reader), enough for Sentire's config."""

from __future__ import annotations

import json
import re
from typing import Any

BARE = re.compile(r"^[A-Za-z0-9_-]+$")


def _key(k: str) -> str:
    return k if BARE.match(k) else json.dumps(k)


def _value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{_key(k)} = {_value(x)}" for k, x in v.items()) + " }"
    raise TypeError(f"can't write {type(v).__name__} to TOML")


def _is_table_list(v: Any) -> bool:
    return isinstance(v, (list, tuple)) and bool(v) and all(isinstance(x, dict) for x in v)


def dumps(data: dict, _prefix: str = "") -> str:
    """Scalars first, then sub-tables, then arrays of tables, as TOML wants."""
    lines: list[str] = []
    for k, v in data.items():
        if v is None or isinstance(v, dict) or _is_table_list(v):
            continue
        lines.append(f"{_key(k)} = {_value(v)}")
    out = "\n".join(lines) + ("\n" if lines else "")
    for k, v in data.items():
        name = f"{_prefix}.{_key(k)}" if _prefix else _key(k)
        if isinstance(v, dict):
            body = dumps(v, name)
            has_scalars = any(not (isinstance(x, dict) or _is_table_list(x)) and x is not None for x in v.values())
            out += f"\n[{name}]\n" + body if has_scalars or not v else body
        elif _is_table_list(v):
            for item in v:
                out += f"\n[[{name}]]\n" + dumps(item, name)
    return out

"""Reads the bot's source and config.yaml to produce the command and configuration references.

Only the standard library and PyYAML are used (nothing imports vectiq), so the docs build in seconds
without compiling the Vector SDK.
"""

from __future__ import annotations

import ast
import html
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
COGS = ROOT / "src" / "vectiq" / "cogs"

# cog class name -> (page title, order). Cogs not listed are skipped (the dashboard cog has one command).
AREAS = {
    "Core": "Bot and owner", "Moderation": "Moderation", "Leveling": "Leveling", "Economy": "Economy",
    "Tickets": "Tickets", "Verification": "Verification", "RoleMenus": "Role menus", "Roles": "Role menus",
    "Giveaways": "Giveaways", "Games": "Games", "Welcome": "Welcome", "Onboarding": "Onboarding",
    "Utility": "Utility", "Webhooks": "Webhooks", "Events": "Events", "SecurityCam": "Security cam",
    "Dashboard": "Dashboard", "Restore points": "Restore points", "LinkSafety": "Link safety",
    "ImageGuard": "Image guard", "Sentire": "Sentire", "Sentire (official)": "Sentire (official)", "MCP": "MCP server", "Notifications": "Stream & video alerts", "Music": "Music",
}
PERMS = {
    "manage_messages": "Manage Messages", "manage_guild": "Manage Community", "manage_roles": "Manage Roles",
    "manage_channels": "Manage Channels", "moderate_members": "Moderate Members", "kick_members": "Kick Members",
    "ban_members": "Ban Members", "administrator": "Administrator",
}


def _name(node) -> str:
    if isinstance(node, ast.Attribute):
        return f"{_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _const(node):
    return node.value if isinstance(node, ast.Constant) else None


def _signature(fn: ast.AsyncFunctionDef) -> str:
    a = fn.args
    args = a.args[2:] if a.args and a.args[0].arg == "self" else a.args[1:]       # drop (self,) ctx
    defaults = [None] * (len(args) - len(a.defaults)) + list(a.defaults)
    parts = []
    for arg, default in zip(args, defaults, strict=True):
        if arg.arg == "ctx":
            continue
        label = arg.arg.replace("_", " ")
        parts.append(f"[{label}]" if default is not None else f"<{label}>")
    for arg, default in zip(a.kwonlyargs, a.kw_defaults, strict=True):
        label = arg.arg.replace("_", " ")
        parts.append(f"[{label}…]" if default is not None else f"<{label}…>")
    return " ".join(parts)


def _decorators(fn):
    """-> (kind, group var or None, name, aliases, hidden, permissions)"""
    kind = group_of = None
    name, aliases, hidden, perms = fn.name, [], False, []
    for dec in fn.decorator_list:
        call = dec if isinstance(dec, ast.Call) else None
        target = _name(call.func) if call else _name(dec)
        if target.endswith(".command") or target.endswith(".group"):
            owner = target.rsplit(".", 1)[0]
            kind = "group" if target.endswith(".group") else "command"
            group_of = None if owner == "commands" else owner
            for kw in (call.keywords if call else []):
                if kw.arg == "name" and _const(kw.value):
                    name = _const(kw.value)
                elif kw.arg == "aliases" and isinstance(kw.value, ast.List):
                    aliases = [_const(e) for e in kw.value.elts if _const(e)]
                elif kw.arg == "hidden" and _const(kw.value) is True:
                    hidden = True
        elif target.endswith("has_permissions") and call:
            perms += [PERMS.get(kw.arg, kw.arg.replace("_", " ").title()) for kw in call.keywords if _const(kw.value)]
        elif target.endswith("is_owner") or target.endswith("owner_only"):
            perms.append("Bot owner")
    return kind, group_of, name, aliases, hidden, perms


def commands() -> dict[str, list[dict]]:
    """Every public command, grouped by the area it belongs to, in source order."""
    out: dict[str, list[dict]] = {}
    for path in sorted(COGS.glob("*.py")):
        tree = ast.parse(path.read_text())
        for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            if not any("Cog" in _name(b) for b in cls.bases):
                continue
            cog = next((_const(k.value) for d in cls.keywords for k in [d] if k.arg == "name"), cls.name)
            area = AREAS.get(cog, AREAS.get(cls.name))
            if area is None:
                continue
            groups: dict[str, str] = {}             # python function name -> command name of the group
            rows = []
            for fn in (n for n in cls.body if isinstance(n, ast.AsyncFunctionDef)):
                kind, owner, name, aliases, hidden, perms = _decorators(fn)
                if kind is None or hidden:
                    continue
                if kind == "group":
                    groups[fn.name] = name
                parent = groups.get(owner) if owner else None
                if owner and parent is None:
                    continue
                doc = ast.get_docstring(fn) or ""
                first = re.split(r"\n\s*\n", doc.strip())[0].replace("\n", " ") if doc else ""
                rows.append({"name": name, "parent": parent, "aliases": aliases, "sig": _signature(fn),
                             "doc": first, "perms": perms, "group": kind == "group"})
            out.setdefault(area, []).extend(rows)
    return out


def inline(text: str) -> str:
    """Escape, then turn `code` spans into <code>."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(text, quote=False))


def commands_markdown(area: str | None = None, prefix: str = "!") -> str:
    data = commands()
    areas = [area] if area else list(data)
    chunks = []
    for a in areas:
        rows = data.get(a, [])
        if not rows:
            continue
        body = []
        for r in rows:
            full = f"{r['parent']} {r['name']}" if r["parent"] else r["name"]
            usage = f"{prefix}{full}{(' ' + r['sig']) if r['sig'] else ''}"
            alias = ""
            if r["aliases"]:
                alias = "<small>also " + ", ".join(f"<code>{html.escape(prefix + x)}</code>" for x in r["aliases"]) + "</small>"
            needs = ", ".join(r["perms"])
            body.append(f"<tr><td><code>{html.escape(usage)}</code>{alias}</td><td>{inline(r['doc'])}</td>"
                        f"<td>{html.escape(needs)}</td></tr>")
        table = ('<div class="table"><table><thead><tr><th>Command</th><th>What it does</th><th>Needs</th></tr></thead>'
                 "<tbody>" + "".join(body) + "</tbody></table></div>")
        chunks.append((f"### {a}\n\n" if not area else "") + table)
    return "\n\n".join(chunks)


# -- config.yaml reference -------------------------------------------------------------------------

_LINE = re.compile(r"^(?P<indent> *)(?P<key>[A-Za-z_][\w-]*):(?P<rest>.*)$")


FALLBACK = {
    "general.prefix": "what commands start with, for example `!help`",
    "general.communities": "names or ids of the communities to serve; empty means every community the bot is in",
    "leveling.xp_max": "see `xp_min`", "economy.currency_symbol": "shown next to amounts",
    "economy.work_max": "see `work_min`", "webhooks.server.port": "port the endpoint listens on",
}


def module_help() -> dict[str, str]:
    """One-line module descriptions, from the module registry (the same words the Settings page uses)."""
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from vectiq import modules

    return {m.name: m.help + (f" (needs `{m.install_hint()}`)" if m.imports else "") for m in modules.REGISTRY}


def config_reference() -> dict[str, list[dict]]:
    """{section: [{key, default, note}]} from config.yaml's values and its trailing comments."""
    text = (ROOT / "config.yaml").read_text()
    data = yaml.safe_load(text)
    sections: dict[str, list[dict]] = {}
    stack: list[tuple[int, str]] = []
    last: dict | None = None
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            # a comment aligned far to the right continues the note of the setting just above it
            if last is not None and stripped.startswith("#") and len(raw) - len(raw.lstrip()) >= 20 and last["note"]:
                last["note"] += " " + stripped.lstrip("# ").strip()
            continue
        m = _LINE.match(raw)
        if m is None:
            continue
        indent, key, rest = len(m["indent"]), m["key"], m["rest"]
        while stack and stack[-1][0] >= indent:
            stack.pop()
        path = [k for _, k in stack] + [key]
        note = ""
        if "#" in rest:
            head, _, note = rest.partition("  #")
            if not _ and "# " in rest:
                head, _, note = rest.partition("# ")
            note = note.strip().lstrip("#").strip()
        else:
            head = rest
        has_children = head.strip() == ""
        if has_children:
            stack.append((indent, key))
        if len(path) == 1 and not has_children:
            sections.setdefault("general", []).append({"key": key, "default": _show(data.get(key)), "note": note})
            last = sections["general"][-1]
        elif len(path) >= 2 and not has_children:
            val = data
            for k in path:
                val = val.get(k) if isinstance(val, dict) else None
            sections.setdefault(path[0], []).append({"key": ".".join(path[1:]), "default": _show(val), "note": note})
            last = sections[path[0]][-1]
        elif has_children and len(path) > 1 and note:
            sections.setdefault(path[0], []).append({"key": ".".join(path[1:]), "default": "", "note": note})
    help_ = module_help()
    for sec, rows in sections.items():
        for row in rows:
            if not row["note"]:
                row["note"] = (help_.get(row["key"], "") if sec == "modules" else "") or \
                    FALLBACK.get(f"{sec}.{row['key']}", "")
    return sections


def _show(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "`true`" if v else "`false`"
    if v == "" or v == [] or v == {}:
        return "*(empty)*"
    if isinstance(v, list):
        return "`[" + ", ".join(str(x) for x in v) + "]`"
    if isinstance(v, dict):
        return "`{" + ", ".join(f"{k}: {x}" for k, x in v.items()) + "}`"
    return f"`{v}`"


def config_markdown(section: str) -> str:
    rows = config_reference().get(section, [])
    if not rows:
        return ""
    body = []
    for r in rows:
        key = f"{section}.{r['key']}" if section != "general" else r["key"]
        default = r["default"]
        shown = inline(default) if default.startswith("`") else f"<em>{html.escape(default.strip('*()'))}</em>"
        body.append(f"<tr><td><code>{html.escape(key)}</code></td><td>{shown}</td><td>{inline(r['note'])}</td></tr>")
    return ('<div class="table"><table><thead><tr><th>Setting</th><th>Default</th><th>What it does</th></tr></thead>'
            "<tbody>" + "".join(body) + "</tbody></table></div>")

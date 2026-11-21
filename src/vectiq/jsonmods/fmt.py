"""The JSON module format: reading, checking and describing ``*.module.json`` files.

Like a Lilith Learning Lab course, a module file is plain JSON that people (or an AI) can write by hand, and the
checker is forgiving: a broken command is skipped with a note instead of rejecting the whole file. Only problems
that make the module unusable are errors.

This file uses the standard library only and imports nothing from Vectiq, so other tools (the marketplace's catalog
builder) can copy it as it is.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

FORMAT = "vectiq-module"
VERSION = 1
CATALOG_FORMAT = "vectiq-catalog"
SUFFIX = ".module.json"

MAX_FILE_BYTES = 1_000_000
MAX_CODE_BYTES = 500_000
MAX_CODE_FILES = 40
LIMITS = {"commands": 50, "autoresponders": 50, "timers": 10, "settings": 30}
MAX_TEXT = 2000
MAX_CHOICES = 50

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")
SETTING_TYPES = ("text", "longtext", "int", "number", "bool", "channel", "enum", "list")
MATCHES = ("contains", "word", "exact", "startswith", "endswith")
CODE_SUFFIXES = (".py", ".json", ".txt", ".md", ".toml", ".yaml", ".yml", ".csv")
PRIVATE_HINTS = ("token", "secret", "password", "apikey", "api_key", "nsec", "cookie", "webhook")


@dataclass
class Result:
    """What :func:`validate` found. ``module`` is the cleaned module (or None when there are errors)."""

    ok: bool
    module: dict | None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dumps(module: dict) -> str:
    """How a module file is written: two-space indent, UTF-8, a newline at the end."""
    return json.dumps(module, ensure_ascii=False, indent=2) + "\n"


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
    s = s if s[:1].isalpha() else f"m_{s}"
    return s[:32].rstrip("_")


def private(key: str, setting: dict | None = None) -> bool:
    """Settings that are never put in an export: marked private, or named like a secret."""
    return bool(setting and setting.get("private")) or any(h in key.lower() for h in PRIVATE_HINTS)


# -- checking -----------------------------------------------------------------------------------------------


class _Ctx:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def text(self, where: str, v: Any, limit: int = MAX_TEXT) -> str:
        if v is None:
            return ""
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            v = str(v)
        if not isinstance(v, str):
            self.warnings.append(f"{where} should be text; ignored")
            return ""
        if len(v) > limit:
            self.warnings.append(f"{where} is longer than {limit} characters; cut short")
            v = v[:limit]
        return v

    def texts(self, where: str, v: Any, limit: int = MAX_CHOICES, each: int = MAX_TEXT) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, list):
            self.warnings.append(f"{where} should be a list of text; ignored")
            return []
        out = [self.text(f"{where}[{i}]", x, each) for i, x in enumerate(v)]
        out = [x for x in out if x.strip()]
        if len(out) > limit:
            self.warnings.append(f"{where} has more than {limit} items; the rest were dropped")
            out = out[:limit]
        return out

    def number(self, where: str, v: Any, low: float, high: float, default: float) -> float:
        if v is None:
            return default
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            self.warnings.append(f"{where} should be a number; using {default:g}")
            return default
        if not low <= v <= high:
            fixed = min(max(v, low), high)
            self.warnings.append(f"{where} must be between {low:g} and {high:g}; using {fixed:g}")
            return fixed
        return v


def _say(c: _Ctx, where: str, d: dict) -> dict | None:
    """The reply part shared by commands, autoresponders and timers: reply/replies, card, react."""
    out: dict[str, Any] = {}
    replies = c.texts(f"{where}.replies", d.get("replies"))
    reply = c.text(f"{where}.reply", d.get("reply"))
    if reply.strip():
        replies = [reply, *replies] if replies else [reply]
    if replies:
        out["replies"] = replies
    card = d.get("card")
    if isinstance(card, dict):
        title = c.text(f"{where}.card.title", card.get("title"), 256)
        color = c.text(f"{where}.card.color", card.get("color"), 7)
        out["card"] = {"title": title}
        if color:
            if COLOR_RE.match(color):
                out["card"]["color"] = color.lower()
            else:
                c.warnings.append(f"{where}.card.color should look like #59fcb3; ignored")
    elif card is not None:
        c.warnings.append(f"{where}.card should be an object with a title; ignored")
    react = c.texts(f"{where}.react", d.get("react"), 5, 32)
    if react:
        out["react"] = react
    return out if (replies or react) else None


def _commands(c: _Ctx, raw: Any, taken: set[str]) -> list[dict]:
    out = []
    for i, d in enumerate(_list(c, "commands", raw)):
        where = f"commands[{i}]"
        if not isinstance(d, dict):
            c.warnings.append(f"{where} isn't an object; skipped")
            continue
        name = c.text(f"{where}.name", d.get("name"), 32).strip().lower().lstrip("!")
        if not NAME_RE.match(name):
            c.warnings.append(f"{where}: the name {name!r} should be letters, digits, - or _ ; skipped")
            continue
        where = f"command {name!r}"
        say = _say(c, where, d)
        if say is None:
            c.warnings.append(f"{where} has no reply; skipped")
            continue
        aliases = [a.lower().lstrip("!") for a in c.texts(f"{where}.aliases", d.get("aliases"), 8, 32)]
        aliases = [a for a in aliases if NAME_RE.match(a) and a != name]
        clash = [n for n in [name, *aliases] if n in taken]
        if clash:
            c.warnings.append(f"{where}: {', '.join(clash)} is already used by another command in this module; skipped")
            continue
        taken.update([name, *aliases])
        item: dict[str, Any] = {"name": name, "help": c.text(f"{where}.help", d.get("help"), 200).strip(), **say}
        if not item["help"]:
            item["help"] = f"The {name} command"
            c.warnings.append(f"{where} has no help text; !help will say \"{item['help']}\"")
        if aliases:
            item["aliases"] = aliases
        for key, low, high, default in (("cooldown", 0, 86400, 3),):
            item[key] = c.number(f"{where}.{key}", d.get(key), low, high, default)
        for key in ("roles", "channels"):
            vals = c.texts(f"{where}.{key}", d.get(key), 20, 100)
            if vals:
                item[key] = vals
        for key in ("dm", "delete_trigger"):
            if d.get(key) is True:
                item[key] = True
        out.append(item)
    return out


def _autoresponders(c: _Ctx, raw: Any) -> list[dict]:
    out = []
    for i, d in enumerate(_list(c, "autoresponders", raw)):
        where = f"autoresponders[{i}]"
        if not isinstance(d, dict):
            c.warnings.append(f"{where} isn't an object; skipped")
            continue
        phrases = c.texts(f"{where}.phrases", d.get("phrases"), 40, 200)
        if not phrases:
            c.warnings.append(f"{where} has no phrases to listen for; skipped")
            continue
        say = _say(c, where, d)
        if say is None:
            c.warnings.append(f"{where} has no reply or reaction; skipped")
            continue
        match = d.get("match", "contains")
        if match not in MATCHES:
            c.warnings.append(f"{where}.match should be one of {', '.join(MATCHES)}; using contains")
            match = "contains"
        item = {"match": match, "phrases": phrases, **say,
                "cooldown": c.number(f"{where}.cooldown", d.get("cooldown"), 0, 86400, 60)}
        for key in ("roles", "channels"):
            vals = c.texts(f"{where}.{key}", d.get(key), 20, 100)
            if vals:
                item[key] = vals
        out.append(item)
    return out


def _timers(c: _Ctx, raw: Any, settings: dict[str, dict]) -> list[dict]:
    out = []
    for i, d in enumerate(_list(c, "timers", raw)):
        where = f"timers[{i}]"
        if not isinstance(d, dict):
            c.warnings.append(f"{where} isn't an object; skipped")
            continue
        channel = c.text(f"{where}.channel", d.get("channel"), 100).strip()
        if not channel:
            c.warnings.append(f"{where} has no channel; skipped")
            continue
        say = _say(c, where, d)
        if say is None or "replies" not in say:
            c.warnings.append(f"{where} has nothing to post; skipped")
            continue
        item: dict[str, Any] = {"channel": channel, **say}
        if d.get("every_minutes") is not None:
            item["every_minutes"] = c.number(f"{where}.every_minutes", d.get("every_minutes"), 5, 43200, 60)
        elif d.get("at") is not None:
            at = c.text(f"{where}.at", d.get("at"), 40).strip()
            ref = _setting_ref(at)
            if not (TIME_RE.match(at) or (ref and ref in settings)):
                c.warnings.append(f"{where}.at is {at!r}; it should be a time like 18:30 (or {{settings.name}}); skipped")
                continue
            item["at"] = at
            tz = c.text(f"{where}.timezone", d.get("timezone"), 64).strip()
            if tz:
                item["timezone"] = tz
        else:
            c.warnings.append(f"{where} needs every_minutes or at; skipped")
            continue
        if d.get("order") in ("random", "in_turn"):
            item["order"] = d["order"]
        out.append(item)
    return out


def _setting_ref(text: str) -> str | None:
    m = re.fullmatch(r"\{settings\.([a-z][a-z0-9_]*)\}", text or "")
    return m.group(1) if m else None


def _settings(c: _Ctx, raw: Any) -> list[dict]:
    out, seen = [], set()
    for i, d in enumerate(_list(c, "settings", raw)):
        where = f"settings[{i}]"
        if not isinstance(d, dict):
            c.warnings.append(f"{where} isn't an object; skipped")
            continue
        key = c.text(f"{where}.key", d.get("key"), 40).strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key) or key in seen:
            c.warnings.append(f"{where}: the key {key!r} should be lowercase letters, digits and _ , and unique; skipped")
            continue
        seen.add(key)
        kind = d.get("type", "text")
        if kind not in SETTING_TYPES:
            c.warnings.append(f"setting {key!r}: type should be one of {', '.join(SETTING_TYPES)}; using text")
            kind = "text"
        item: dict[str, Any] = {"key": key, "label": c.text(f"{where}.label", d.get("label"), 80).strip() or key,
                                "type": kind}
        help_ = c.text(f"{where}.help", d.get("help"), 300).strip()
        if help_:
            item["help"] = help_
        if kind == "enum":
            opts = c.texts(f"setting {key!r}.options", d.get("options"), 30, 80)
            if not opts:
                c.warnings.append(f"setting {key!r} is a choice but has no options; skipped")
                continue
            item["options"] = opts
        for bound in ("min", "max"):
            if isinstance(d.get(bound), (int, float)) and not isinstance(d.get(bound), bool):
                item[bound] = d[bound]
        item["default"] = _default(c, key, kind, d.get("default"), item)
        if d.get("private") is True or private(key):
            item["private"] = True
        out.append(item)
    return out


def _default(c: _Ctx, key: str, kind: str, v: Any, item: dict) -> Any:
    blank = {"bool": False, "int": 0, "number": 0, "list": []}.get(kind, "")
    if kind == "enum":
        blank = item["options"][0]
    if v is None:
        return blank
    ok = {
        "bool": isinstance(v, bool),
        "int": isinstance(v, int) and not isinstance(v, bool),
        "number": isinstance(v, (int, float)) and not isinstance(v, bool),
        "list": isinstance(v, list) and all(isinstance(x, str) for x in v),
        "enum": v in item.get("options", ()),
    }.get(kind, isinstance(v, str))
    if not ok:
        c.warnings.append(f"setting {key!r}: the default doesn't fit its type ({kind}); using {blank!r}")
        return blank
    return v


def _list(c: _Ctx, key: str, raw: Any) -> list:
    if raw is None:
        return []
    if not isinstance(raw, list):
        c.warnings.append(f"{key} should be a list; ignored")
        return []
    limit = LIMITS.get(key)
    if limit and len(raw) > limit:
        c.warnings.append(f"{key} has more than {limit}; the rest were dropped")
        raw = raw[:limit]
    return raw


def _code(c: _Ctx, raw: Any) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("files"), dict) or not raw["files"]:
        c.errors.append('"code" needs "files": an object of file name → file text')
        return None
    files, total = {}, 0
    for name, body in raw["files"].items():
        p = PurePosixPath(str(name))
        bad = (p.is_absolute() or not p.parts or ".." in p.parts or "\\" in str(name)
               or any(not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", part) for part in p.parts))
        if bad:
            c.errors.append(f"code file {name!r}: use a plain relative path (letters, digits, _ - .)")
            continue
        if p.suffix not in CODE_SUFFIXES:
            c.errors.append(f"code file {name!r}: only {' '.join(CODE_SUFFIXES)} files")
            continue
        if not isinstance(body, str):
            c.errors.append(f"code file {name!r} must be text")
            continue
        total += len(body.encode("utf-8"))
        files[p.as_posix()] = body
    if len(files) > MAX_CODE_FILES:
        c.errors.append(f'"code" has {len(files)} files; at most {MAX_CODE_FILES}')
    if total > MAX_CODE_BYTES:
        c.errors.append(f'"code" is {total // 1000} KB; at most {MAX_CODE_BYTES // 1000} KB')
    entry = c.text("code.entry", raw.get("entry"), 100).strip() or "__init__"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*", entry):
        c.errors.append('"code.entry" should be a module name inside the files, like "cog" or "__init__"')
    elif f"{entry.replace('.', '/')}.py" not in files and f"{entry.replace('.', '/')}/__init__.py" not in files:
        c.errors.append(f'"code.entry" is {entry!r}, but there is no {entry.replace(".", "/")}.py in the files')
    if "__init__.py" not in files:
        files["__init__.py"] = ""
    if not re.search(r"^\s*(async\s+)?def\s+setup\s*\(", "\n".join(files.values()), re.M):
        c.warnings.append("no setup(bot) function was found in the code; the module won't add anything when on")
    packages = {}
    pip_spec = re.compile(r"[A-Za-z0-9_.\-\[\],<>=!~ ]+")
    for k, v in (raw.get("packages") or {}).items() if isinstance(raw.get("packages"), dict) else []:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(k)) and isinstance(v, str) and pip_spec.fullmatch(v):
            packages[str(k)] = v
        else:
            c.warnings.append(f"code.packages: {k!r} → {v!r} should map an import name to a pip requirement; ignored")
    out = {"entry": entry, "files": files}
    if packages:
        out["packages"] = packages
    return out


def validate(raw: Any, *, reserved: tuple[str, ...] = ()) -> Result:
    """Check a module (parsed JSON, or its text). ``reserved`` are ids that may not be used (built-in modules)."""
    c = _Ctx()
    if isinstance(raw, (bytes, str)):
        data = raw.encode("utf-8") if isinstance(raw, str) else raw
        if len(data) > MAX_FILE_BYTES:
            return Result(False, None, [f"the file is {len(data) // 1000} KB; at most {MAX_FILE_BYTES // 1000} KB"])
        try:
            raw = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return Result(False, None, [f"this isn't valid JSON: {exc}"])
    if not isinstance(raw, dict):
        return Result(False, None, ["a module file is a JSON object: { \"format\": \"vectiq-module\", ... }"])
    if raw.get("format") not in (None, FORMAT):
        c.errors.append(f'"format" should be "{FORMAT}" (found {raw.get("format")!r})')
    ver = raw.get("version", VERSION)
    if not isinstance(ver, int) or ver > VERSION:
        c.errors.append(f"this module needs a newer Vectiq (it's format version {ver}; this Vectiq reads {VERSION})")
    name = c.text("name", raw.get("name"), 60).strip()
    if not name:
        c.errors.append('"name" is required (what the module is called)')
    mid = c.text("id", raw.get("id"), 40).strip() or (slug(name) if name else "")
    if mid and not raw.get("id"):
        c.warnings.append(f'no "id"; using "{mid}"')
    if mid and not ID_RE.match(mid):
        c.errors.append(f'"id" {mid!r} should be 2-32 lowercase letters, digits and _, starting with a letter')
    if mid in reserved:
        c.errors.append(f'"id" {mid!r} is the name of a built-in module; choose another')
    release = c.text("release", raw.get("release"), 20).strip() or "1.0.0"
    if not SEMVER_RE.match(release):
        c.warnings.append(f'"release" should look like 1.2.0 (found {release!r}); using 1.0.0')
        release = "1.0.0"
    mod: dict[str, Any] = {"format": FORMAT, "version": VERSION, "id": mid, "name": name,
                           "summary": c.text("summary", raw.get("summary"), 200).strip(),
                           "group": c.text("group", raw.get("group"), 24).strip() or "Community",
                           "release": release}
    if not mod["summary"]:
        c.warnings.append('no "summary"; add one line saying what the module does')
    for key, limit in (("description", 4000), ("author", 80), ("license", 40), ("homepage", 300), ("provides", 32)):
        v = c.text(key, raw.get(key), limit).strip()
        if v:
            mod[key] = v
    if mod.get("homepage") and not mod["homepage"].startswith(("https://", "http://")):
        c.warnings.append('"homepage" should be a web address; ignored')
        del mod["homepage"]
    tags = [t.lower() for t in c.texts("tags", raw.get("tags"), 10, 30)]
    if tags:
        mod["tags"] = tags
    settings = _settings(c, raw.get("settings"))
    if settings:
        mod["settings"] = settings
    by_key = {s["key"]: s for s in settings}
    for key, items in (("commands", _commands(c, raw.get("commands"), set())),
                       ("autoresponders", _autoresponders(c, raw.get("autoresponders"))),
                       ("timers", _timers(c, raw.get("timers"), by_key))):
        if items:
            mod[key] = items
    code = _code(c, raw.get("code"))
    if code:
        mod["code"] = code
    for ref in sorted(set(re.findall(r"\{settings\.([a-z0-9_]+)\}", json.dumps({k: mod.get(k) for k in
                                                                                ("commands", "autoresponders", "timers")})))):
        if ref not in by_key:
            c.warnings.append(f"{{settings.{ref}}} is used but there is no setting {ref!r}; it will show as written")
    if not c.errors and not any(mod.get(k) for k in ("commands", "autoresponders", "timers", "code")):
        c.errors.append("the module does nothing: give it commands, autoresponders, timers or code")
    if c.errors:
        return Result(False, None, c.errors, c.warnings)
    return Result(True, mod, [], c.warnings)


# -- describing --------------------------------------------------------------------------------------------


def kind(module: dict) -> str:
    """``code`` if it runs Python, else ``data`` (commands, autoresponders and timers only)."""
    return "code" if module.get("code") else "data"


def summary(module: dict) -> dict:
    """The facts people see before installing, and the catalog lists."""
    return {
        "id": module["id"], "name": module["name"], "summary": module.get("summary", ""),
        "description": module.get("description", ""), "group": module["group"], "release": module["release"],
        "author": module.get("author", ""), "license": module.get("license", ""), "homepage": module.get("homepage", ""),
        "tags": module.get("tags", []), "kind": kind(module), "provides": module.get("provides", ""),
        "commands": [c["name"] for c in module.get("commands", [])],
        "autoresponders": len(module.get("autoresponders", [])), "timers": len(module.get("timers", [])),
        "settings": [s["label"] for s in module.get("settings", [])],
        "files": sorted(module.get("code", {}).get("files", {})),
        "packages": sorted(module.get("code", {}).get("packages", {}).values()),
    }


def template() -> dict:
    """A small complete module that shows every part except code. Give it to an AI as an example."""
    return validate(_TEMPLATE).module


_TEMPLATE = {
        "format": FORMAT, "version": VERSION, "id": "hello_world", "name": "Hello world",
        "summary": "Greets people and answers a question.", "group": "Fun", "release": "1.0.0", "author": "you",
        "license": "MIT", "tags": ["example"],
        "settings": [
            {"key": "greeting", "label": "Greeting", "type": "text", "default": "Hello, {user}!",
             "help": "What the hello command says"},
            {"key": "channel", "label": "Daily post channel", "type": "channel", "default": "general"},
            {"key": "time", "label": "Daily post time", "type": "text", "default": "09:00", "help": "24-hour, like 09:00"},
        ],
        "commands": [
            {"name": "hello", "aliases": ["hi"], "help": "Say hello", "reply": "{settings.greeting}", "cooldown": 5},
            {"name": "flip", "help": "Flip a coin", "replies": ["Heads", "Tails"]},
            {"name": "about", "help": "About this community", "card": {"title": "{community}", "color": "#59fcb3"},
             "reply": "{community} has {members} members. Ask away, {mention}."},
        ],
        "autoresponders": [
            {"match": "word", "phrases": ["good morning", "gm"], "react": ["☀️"], "cooldown": 30},
            {"match": "contains", "phrases": ["how do i join"], "reply": "Ask a moderator, {user}!", "cooldown": 120},
        ],
        "timers": [
            {"channel": "{settings.channel}", "at": "{settings.time}", "timezone": "UTC", "order": "random",
             "replies": ["Good morning, {community}!", "A new day: what are you working on?"]},
        ],
    }


# The prompt is one long instruction per line on purpose: it is pasted into a chat with an AI.
PROMPT = """Write a Vectiq module as one JSON file. Vectiq is a bot for Vector messenger communities.

Use exactly this shape (no comments, no trailing commas, nothing before or after the JSON):
{"format":"vectiq-module","version":1,"id":"lowercase_id","name":"Name","summary":"One line","group":"Community|Fun|Members|Safety|Integrations","release":"1.0.0","author":"","license":"MIT","tags":["..."],
 "settings":[{"key":"name","label":"Label","type":"text|longtext|int|number|bool|channel|enum|list","default":...,"help":"","options":["for enum"]}],
 "commands":[{"name":"cmd","aliases":[],"help":"what it does","reply":"text" OR "replies":["one is picked at random"],"card":{"title":"optional: show as a card","color":"#59fcb3"},"react":["emoji"],"cooldown":3,"roles":["only these roles"],"channels":["only these channels"],"dm":false,"delete_trigger":false}],
 "autoresponders":[{"match":"contains|word|exact|startswith|endswith","phrases":["..."],"reply":"..." OR "replies":[...],"react":["emoji"],"cooldown":60,"channels":[]}],
 "timers":[{"channel":"channel name or {settings.key}","every_minutes":60 OR "at":"18:30","timezone":"Europe/London","order":"random|in_turn","replies":["..."],"card":{"title":"..."}}]}

In any text you may use {user} {mention} {args} (what followed the command) {channel} {community} {members} {prefix} and {settings.key}.
Put anything a community would want to change (texts, links, channel names, times) in "settings" and refer to it with {settings.key}.
Keep replies short and friendly. Commands are lowercase. Do not include "code".
The module I want:
"""  # noqa: E501

"""What the dashboard, the command line and MCP do with JSON modules, against the running bot: check, install, update,
remove, export, and browse a marketplace."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .. import modules
from . import fmt
from .library import Library, LibraryError, entry_for, is_json, reserved
from .market import RAW, MarketError, Marketplace, valid_source
from .runtime import STATE

log = logging.getLogger("vectiq.jsonmods")


class JsonModules:
    def __init__(self, bot):
        self.bot = bot
        self._market: Marketplace | None = None

    @property
    def cfg(self):
        return self.bot.config

    @property
    def library(self) -> Library:
        return Library(self.cfg.data_dir)

    @property
    def allow_code(self) -> bool:
        return bool(self.cfg.get("marketplace.allow_code", False))

    def marketplace(self) -> Marketplace:
        repo, branch = str(self.cfg.get("marketplace.repo", "")), str(self.cfg.get("marketplace.branch", "main"))
        if self._market is None or (self._market.repo, self._market.branch) != (repo, branch):
            self._market = Marketplace(repo, branch)
        return self._market

    # -- looking ----------------------------------------------------------------------------------------

    def check(self, text: str | bytes) -> dict:
        """Everything the "Add a module" screen shows before installing: errors, notes, what's in it, what happens."""
        result = fmt.validate(text, reserved=reserved())
        out: dict[str, Any] = {"ok": result.ok, "errors": result.errors, "warnings": result.warnings}
        if result.ok:
            m = result.module
            out["module"] = fmt.summary(m)
            out.update(self._fit(m))
        return out

    def _fit(self, m: dict) -> dict:
        current = modules.get(m["id"])
        blocked = ""
        if current is not None and not is_json(current):
            blocked = f"There is already a module called {m['id']} ({current.source}). Change the id to install this one."
        elif fmt.kind(m) == "code" and not self.allow_code:
            blocked = ("This module runs Python on the bot's computer. To install it, an owner has to turn on "
                       "Settings → Marketplace → Allow modules with code.")
        installed = self.library.read(m["id"])
        rivals = [x.label for x in modules.REGISTRY if m.get("provides") and x.slot == m["provides"] and x.name != m["id"]]
        return {"blocked": blocked, "installed_release": installed["release"] if installed else "",
                "replaces": rivals}

    def installed(self) -> list[dict]:
        lib = self.library
        out = []
        for mid in lib.ids():
            data, src = lib.read(mid), lib.source(mid)
            m = modules.get(mid)
            out.append({
                "id": mid, "name": data["name"] if data else mid, "summary": data.get("summary", "") if data else "",
                "release": data["release"] if data else "", "kind": fmt.kind(data) if data else "",
                "source": src.get("source", ""), "sha256": src.get("sha256", ""), "installed_at": src.get("installed_at", 0),
                "on": bool(m and is_json(m) and self.cfg.enabled(mid)),
                "loaded": f"vectiq_json.{mid}" in getattr(self.bot, "extensions", {}),
                "problem": "" if data else lib.problem(mid),
                "skipped": STATE.get(mid, {}).get("skipped", []),
                "commands": [c["name"] for c in data.get("commands", [])] if data else [],
                "settings": bool(data and data.get("settings")),
                "icon": data.get("icon", "") if data else "", "media": self.media_for(src.get("source", ""))})
        return out

    def media_for(self, source: str) -> str:
        """Where an installed module's pictures are: the modules/ folder of the marketplace it came from."""
        repo = source.split(" ", 1)[1] if source.startswith("marketplace ") else ""
        branch = (self.cfg.get("marketplace.branch") or "main") if repo == self.cfg.get("marketplace.repo") else "main"
        return f"{RAW}/{repo}/{branch}/modules/" if repo and valid_source(repo, branch) else ""

    def exportable(self) -> list[dict]:
        """Modules that can be saved as a JSON file: installed JSON modules and plugins from a folder."""
        return [{"id": m.name, "name": m.label, "from": "json" if is_json(m) else "folder",
                 "settings": bool(m.settings)}
                for m in modules.plugins() if is_json(m) or m.source.startswith("folder ")]

    async def browse(self, *, fresh: bool = False) -> dict:
        mine = {x["id"]: x for x in self.installed()}
        out: dict[str, Any] = {"repo": self.cfg.get("marketplace.repo"), "branch": self.cfg.get("marketplace.branch"),
                               "allow_code": self.allow_code, "modules": [], "groups": [], "error": "", "media": ""}
        try:
            cat = await self.marketplace().catalog(fresh=fresh)
        except MarketError as exc:
            out["error"] = str(exc)
            return out
        out["media"] = cat.get("media", "")
        for e in cat["modules"]:
            have = mine.get(e["id"])
            other = modules.get(e["id"])
            out["modules"].append({**e, "installed_release": have["release"] if have else "",
                                   "update": bool(have and have["sha256"] != e["sha256"]),
                                   "blocked": (e.get("kind") == "code" and not self.allow_code)
                                   or bool(other is not None and not is_json(other))})
        out["groups"] = sorted({str(e.get("group", "Other")) for e in out["modules"]})
        return out

    # -- changing ---------------------------------------------------------------------------------------

    async def install(self, m: dict, *, source: str, sha256: str = "", on: bool | None = None, by: str) -> dict:
        """Install or update a checked module and load it. Returns {"id", "name", "message"}."""
        fit = self._fit(m)
        if fit["blocked"]:
            raise LibraryError(fit["blocked"])
        mid = m["id"]
        was_on = bool(is_json(modules.get(mid)) and self.cfg.enabled(mid))
        path = self.library.save(m, source=source, sha256=sha256)
        entry = entry_for(m, path)
        modules.register(entry)
        for tree in (self.cfg.data, self.cfg.file_data):            # new settings get their defaults
            section = tree.setdefault(mid, {})
            if isinstance(section, dict):
                for k, v in entry.defaults.items():
                    section.setdefault(k, v)
            tree.setdefault("modules", {}).setdefault(mid, False)
        if on is None:
            on = fmt.kind(m) == "data"                                # code never switches itself on
        verb = "Updated" if fit["installed_release"] else "Installed"
        if was_on:
            await self.bot.reload_module(mid)
            note = f"{verb} {m['name']} {m['release']} and reloaded it."
        elif on:
            result = await self.bot.set_module(mid, True, by)
            problem = next((p for p in result.get("problems", []) if mid in p), "")
            note = f"{verb} {m['name']} {m['release']} and switched it on." + (f" But: {problem}" if problem else "")
        else:
            note = f"{verb} {m['name']} {m['release']}. It's off: switch it on when you're ready."
        if entry.missing():
            note += f" It needs {', '.join(entry.missing())}: {entry.install_hint()}"
        skipped = STATE.get(mid, {}).get("skipped", [])
        if skipped:
            note += f" Skipped: {'; '.join(skipped)}."
        log.info("%s %s (%s) by %s", verb.lower(), mid, source, by)
        return {"id": mid, "name": m["name"], "release": m["release"], "message": note}

    async def install_text(self, text: str | bytes, *, source: str, on: bool | None = None, by: str) -> dict:
        result = fmt.validate(text, reserved=reserved())
        if not result.ok:
            raise LibraryError("That isn't a module Vectiq can use: " + "; ".join(result.errors))
        return await self.install(result.module, source=source, on=on, by=by)

    async def install_from_market(self, mid: str, *, on: bool | None = None, by: str) -> dict:
        m, raw, _entry = await self.marketplace().download(mid)
        return await self.install(m, source=f"marketplace {self.marketplace().repo}", sha256=fmt.digest(raw), on=on, by=by)

    async def remove(self, mid: str, *, by: str) -> str:
        m = modules.get(mid)
        if self.library.read(mid) is None and not self.library.file(mid).exists():
            raise LibraryError(f"No JSON module called {mid} is installed.")
        if m is not None and is_json(m) and self.cfg.enabled(mid):
            await self.bot.set_module(mid, False, by)
        self.library.remove(mid)
        if is_json(m):
            modules.forget(mid)
            await self._drop_switch(mid)
        STATE.pop(mid, None)
        log.info("removed %s by %s", mid, by)
        return f"Removed {m.label if m else mid}. Its settings are kept in case you add it again."

    async def _drop_switch(self, mid: str) -> None:
        """Forget the module's on/off switch everywhere, or the config would name a module that no longer exists.
        Its own settings stay, so adding it again brings them back."""
        cfg, path = self.cfg, f"modules.{mid}"
        for tree in (cfg.file_data, cfg.data):
            if isinstance(tree.get("modules"), dict):
                tree["modules"].pop(mid, None)
        overrides = {k: v for k, v in cfg.overrides.items() if k != path}
        cfg.apply_overrides(overrides)
        stores = getattr(self.bot, "stores", None)
        if stores is not None:
            await stores.dashboard.clear_override(path)

    # -- exporting --------------------------------------------------------------------------------------

    def export(self, name: str, *, with_settings: bool = False) -> dict:
        """A module as a JSON module file. ``with_settings`` makes your current values the defaults (secrets are
        never included)."""
        m = modules.get(name)
        if m is None:
            raise LibraryError(f"There's no module called {name}.")
        if m.builtin:
            raise LibraryError(f"{m.label} is built into Vectiq, so there's nothing to export.")
        if is_json(m):
            data = self.library.read(name)
            if data is None:
                raise LibraryError(f"{name}'s file can't be read: {self.library.problem(name)}")
        elif m.source.startswith("folder "):
            data = from_folder(m)
        else:
            raise LibraryError(f"{m.label} was installed with pip ({m.source}); share the package name instead.")
        if with_settings:
            current = self.cfg.get(name, {}) or {}
            for s in data.get("settings", []):
                if s["key"] in current and not s.get("private"):
                    s["default"] = current[s["key"]]
        result = fmt.validate(data, reserved=reserved())
        if not result.ok:
            raise LibraryError(f"{m.label} can't be exported as it is: {'; '.join(result.errors)}")
        return result.module


def from_folder(m: modules.Module) -> dict:
    """A folder plugin, files and all, as a JSON module with code."""
    path = Path(m.source.split(" ", 1)[1])
    root = path if path.is_dir() else path.parent
    if path.is_dir():
        files = {}
        for f in sorted(root.rglob("*")):
            rel = f.relative_to(root)
            if f.is_file() and "__pycache__" not in rel.parts and not any(p.startswith(".") for p in rel.parts) \
                    and f.suffix in fmt.CODE_SUFFIXES:
                files[rel.as_posix()] = f.read_text("utf-8")
    else:
        files = {"__init__.py": path.read_text("utf-8")}
    package = f"{modules.PLUGIN_PACKAGE}.{root.name if path.is_dir() else path.stem}"
    entries = [c[len(package) + 1:] if c.startswith(package + ".") else "__init__" for c in m.cogs]
    if len(entries) != 1:
        raise LibraryError(f"{m.label} loads {len(entries)} cogs; a JSON module has one entry. Give it one setup().")
    settings = []
    for f in m.settings:
        if isinstance(f, dict) and str(f.get("path", "")).startswith(m.name + "."):
            key = f["path"][len(m.name) + 1:]
            if "." in key or f["type"] not in fmt.SETTING_TYPES:
                continue
            s = {"key": key, "label": f["label"], "type": f["type"], "default": m.defaults.get(key)}
            if f.get("help"):
                s["help"] = f["help"]
            if f.get("options"):
                s["options"] = list(f["options"])
            for b in ("min", "max"):
                if f.get(b) is not None:
                    s[b] = f[b]
            settings.append(s)
    out = {"format": fmt.FORMAT, "version": fmt.VERSION, "id": m.name, "name": m.label, "summary": m.help,
           "group": m.group, "release": m.version if fmt.SEMVER_RE.match(m.version or "") else "1.0.0",
           "settings": settings, "code": {"entry": entries[0], "files": files}}
    if m.author:
        out["author"] = m.author
    if m.provides:
        out["provides"] = m.provides
    if m.imports:
        out["code"]["packages"] = {i: i for i in m.imports}
    return out

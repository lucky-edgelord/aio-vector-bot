"""Installed JSON modules: where they are kept, how Python imports them, and how they join the module list.

Each installed module is its own file, ``<data>/json-modules/<id>.module.json``, the same file you'd export or share
(like a course in Lilith Learning Lab's library). Next to it, ``<id>.source.json`` says where it came from.

When a module is switched on, Vectiq loads the extension ``vectiq_json.<id>``. An import hook builds that from the
file: a cog for its commands, autoresponders and timers, plus its Python if it has a ``code`` part. Python files are
unpacked under ``.code/<id>/<checksum>/`` so tracebacks point at real files.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import inspect
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

from .. import modules
from ..modules import Module
from . import fmt

log = logging.getLogger("vectiq.jsonmods")

PACKAGE = "vectiq_json"
FOLDER = "json-modules"


class LibraryError(RuntimeError):
    """Something a person can fix, said in plain words."""


def reserved() -> tuple[str, ...]:
    return tuple(m.name for m in modules.BUILTIN)


class Library:
    def __init__(self, data_dir: str | Path):
        self.dir = Path(data_dir).expanduser().resolve() / FOLDER

    def file(self, mid: str) -> Path:
        return self.dir / f"{mid}{fmt.SUFFIX}"

    def ids(self) -> list[str]:
        if not self.dir.is_dir():
            return []
        return sorted(p.name[: -len(fmt.SUFFIX)] for p in self.dir.glob(f"*{fmt.SUFFIX}"))

    def read(self, mid: str) -> dict | None:
        try:
            result = fmt.validate(self.file(mid).read_bytes(), reserved=reserved())
        except OSError:
            return None
        return result.module if result.ok and result.module["id"] == mid else None

    def problem(self, mid: str) -> str:
        """Why an installed file can't be used (it was edited by hand, or Vectiq got stricter)."""
        try:
            result = fmt.validate(self.file(mid).read_bytes(), reserved=reserved())
        except OSError as exc:
            return str(exc)
        if not result.ok:
            return "; ".join(result.errors)
        return "" if result.module["id"] == mid else f"the file says its id is {result.module['id']}"

    def source(self, mid: str) -> dict:
        try:
            return json.loads((self.dir / f"{mid}.source.json").read_text("utf-8"))
        except (OSError, ValueError):
            return {}

    def save(self, module: dict, *, source: str, sha256: str = "") -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.file(module["id"])
        text = fmt.dumps(module)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, "utf-8")
        os.replace(tmp, path)
        (self.dir / f"{module['id']}.source.json").write_text(json.dumps({
            "source": source, "sha256": sha256 or fmt.digest(text.encode()), "release": module["release"],
            "installed_at": int(time.time())}, indent=2) + "\n", "utf-8")
        return path

    def remove(self, mid: str) -> None:
        for p in (self.file(mid), self.dir / f"{mid}.source.json"):
            p.unlink(missing_ok=True)
        shutil.rmtree(self.dir / ".code" / mid, ignore_errors=True)

    def code_dir(self, module: dict) -> Path:
        """The module's Python files on disk, written once per version of the file."""
        files = module["code"]["files"]
        stamp = fmt.digest(json.dumps(files, sort_keys=True).encode())[:12]
        base = self.dir / ".code" / module["id"]
        target = base / stamp
        if not (target / ".complete").exists():
            shutil.rmtree(target, ignore_errors=True)
            for name, body in files.items():
                p = (target / name).resolve()
                if target.resolve() not in p.parents:          # fmt already refuses such paths; belt and braces
                    raise LibraryError(f"{name}: outside the module's folder")
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(body, "utf-8")
            (target / ".complete").write_text("")
        for old in base.iterdir():
            if old.name != stamp:
                shutil.rmtree(old, ignore_errors=True)
        return target


# -- the import hook ------------------------------------------------------------------------------------


class _Package(importlib.abc.Loader):
    def create_module(self, spec):
        return None

    def exec_module(self, module):
        module.__path__ = []
        module.__doc__ = "Vectiq JSON modules"


class _ModuleLoader(importlib.abc.Loader):
    def __init__(self, library: Library, module: dict):
        self.library, self.data = library, module

    def create_module(self, spec):
        return None

    def exec_module(self, mod):
        data, name = self.data, mod.__name__
        mod.MODULE_JSON = data
        code_setup = None
        if data.get("code"):
            folder = self.library.code_dir(data)
            mod.__path__ = [str(folder)]
            mod.__file__ = str(folder / "__init__.py")
            source = (folder / "__init__.py").read_text("utf-8")
            exec(compile(source, mod.__file__, "exec"), mod.__dict__)  # noqa: S102 - only with marketplace.allow_code
            entry = data["code"]["entry"]
            code_setup = mod.__dict__.get("setup") if entry == "__init__" else None
        else:
            mod.__path__ = []

        async def setup(bot):
            from .runtime import build

            if any(data.get(k) for k in ("commands", "autoresponders", "timers")):
                await bot.add_cog(build(bot, data, name))
            if data.get("code"):
                fn = code_setup
                if data["code"]["entry"] != "__init__":
                    fn = getattr(importlib.import_module(f"{name}.{data['code']['entry']}"), "setup", None)
                if fn is not None:
                    result = fn(bot)
                    if inspect.isawaitable(result):
                        await result

        mod.setup = setup


class _Finder(importlib.abc.MetaPathFinder):
    library: Library | None = None

    def find_spec(self, fullname, path=None, target=None):
        if fullname == PACKAGE:
            spec = importlib.machinery.ModuleSpec(PACKAGE, _Package(), is_package=True)
            spec.submodule_search_locations = []
            return spec
        if self.library is None or not fullname.startswith(PACKAGE + ".") or fullname.count(".") != 1:
            return None
        mid = fullname.split(".", 1)[1]
        data = self.library.read(mid)
        if data is None:
            return None
        spec = importlib.machinery.ModuleSpec(fullname, _ModuleLoader(self.library, data),
                                              origin=str(self.library.file(mid)), is_package=True)
        spec.submodule_search_locations = []
        return spec


_FINDER = _Finder()


def use(library: Library) -> None:
    _FINDER.library = library
    if _FINDER not in sys.meta_path:
        sys.meta_path.insert(0, _FINDER)


# -- the module list ------------------------------------------------------------------------------------


def entry_for(module: dict, path: Path) -> Module:
    """How an installed JSON module appears in the module list, the dashboard and the wizard."""
    from ..dashboard.schema import field

    mid = module["id"]
    packages = module.get("code", {}).get("packages", {})
    return Module(
        name=mid, label=module["name"], help=module.get("summary") or module["name"], group=module["group"],
        cogs=(f"{PACKAGE}.{mid}",), default=False, provides=module.get("provides", ""),
        defaults={s["key"]: s["default"] for s in module.get("settings", [])},
        settings=tuple(field(f"{mid}.{s['key']}", s["label"], s["type"], s.get("help", ""),
                             options=tuple(s.get("options", ())), minimum=s.get("min"), maximum=s.get("max"))
                       for s in module.get("settings", [])),
        imports=tuple(packages), install=("pip install " + " ".join(f'"{v}"' for v in packages.values())) if packages else "",
        version=module["release"], author=module.get("author", ""), source=f"json {path}")


def is_json(m: Module | None) -> bool:
    return m is not None and m.source.startswith("json ")


def discover(data_dir: str | Path) -> list[str]:
    """Add every installed JSON module to the module list (and drop ones that were removed). Returns their names."""
    library = Library(data_dir)
    use(library)
    found = []
    for mid in library.ids():
        data = library.read(mid)
        if data is None:
            modules.PROBLEMS[str(library.file(mid))] = library.problem(mid)
            continue
        current = modules.get(mid)
        if current is not None and not is_json(current):
            modules.PROBLEMS[str(library.file(mid))] = f"a {current.source} module is already called {mid}"
            continue
        modules.PROBLEMS.pop(str(library.file(mid)), None)
        modules.register(entry_for(data, library.file(mid)))
        found.append(mid)
    for m in [m for m in modules.plugins() if is_json(m) and m.name not in found]:
        modules.forget(m.name)
    return found

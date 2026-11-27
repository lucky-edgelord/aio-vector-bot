"""Finding out whether a newer Vectiq exists, and installing it. No bot or Vector involved, so it is easy to test."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from importlib import metadata
from pathlib import Path

import tomllib

from . import __version__

ROOT = Path(__file__).resolve().parents[2]       # the checkout, when Vectiq was installed by get.sh / git clone


@dataclass
class UpdateInfo:
    kind: str = "package"           # git | docker | package
    current: str = __version__
    latest: str = ""                # a version (package) or the newest commit (git)
    behind: int = 0                 # commits (git) or 1 when a newer release exists
    changes: list[str] = field(default_factory=list)
    url: str = ""
    checked_at: float = 0.0
    error: str = ""
    dirty: bool = False             # your own edits to the code would be in the way of a git update
    can_update: bool = False
    how: str = ""                   # what to do by hand when the bot can't update itself

    def as_dict(self) -> dict:
        return asdict(self) | {"available": self.behind > 0}


def version_key(text: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", text.split("-")[0])[:4])


def changed_files(status: str) -> list[str]:
    """Paths in `git status --porcelain` output (the output may have lost its first leading space)."""
    return [line.split(maxsplit=1)[-1].strip() for line in status.splitlines() if line.strip()]


def install_kind(root: Path = ROOT) -> str:
    if (root / ".git").exists() and (root / "pyproject.toml").exists():
        return "git"
    return "docker" if Path("/.dockerenv").exists() else "package"


async def sh(*args: str, cwd: Path | None = None, timeout: float = 120) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(*args, cwd=cwd, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "timed out"
    return proc.returncode or 0, out.decode("utf-8", "replace").strip()


async def _latest_release(repo: str) -> tuple[str, str]:
    """(version, page) of the newest GitHub release, or its newest tag when there are no releases."""
    def get(path: str):
        req = urllib.request.Request(f"https://api.github.com/repos/{repo}/{path}",
                                     headers={"User-Agent": "vectiq-update-check", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 - fixed https host
            return json.load(r)

    try:
        rel = await asyncio.to_thread(get, "releases/latest")
        return str(rel["tag_name"]).lstrip("v"), rel.get("html_url", "")
    except Exception:  # noqa: BLE001 - no release yet: try tags
        tags = await asyncio.to_thread(get, "tags?per_page=1")
        if not tags:
            raise
        return str(tags[0]["name"]).lstrip("v"), f"https://github.com/{repo}/releases"


async def check(repo: str = "lucky-edgelord/aio-vector-bot", root: Path = ROOT, kind: str | None = None) -> UpdateInfo:
    kind = kind or install_kind(root)
    info = UpdateInfo(kind=kind, checked_at=time.time(), url=f"https://github.com/{repo}")
    try:
        if kind == "git":
            rc, out = await sh("git", "fetch", "--quiet", "origin", cwd=root, timeout=60)
            if rc:
                raise RuntimeError(out or "git fetch failed")
            _, branch = await sh("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=root)
            up = f"origin/{branch}"
            rc, count = await sh("git", "rev-list", "--count", f"HEAD..{up}", cwd=root)
            if rc:
                raise RuntimeError(f"no {up} to compare with")
            info.behind = int(count or 0)
            _, log = await sh("git", "log", "--format=%s", "-n", "12", f"HEAD..{up}", cwd=root)
            info.changes = [line for line in log.splitlines() if line.strip()]
            _, info.latest = await sh("git", "rev-parse", "--short", up, cwd=root)
            _, status = await sh("git", "status", "--porcelain", "--untracked-files=no", cwd=root)
            info.dirty = any(f != "config.yaml" for f in changed_files(status))
            info.can_update = not info.dirty
            if info.dirty:
                info.how = "You've edited Vectiq's own files. Commit or undo those edits, then update."
        else:
            info.latest, info.url = await _latest_release(repo)
            info.behind = 1 if version_key(info.latest) > version_key(info.current) else 0
            info.how = ("Pull the new image and restart: docker compose pull && docker compose up -d"
                        if kind == "docker" else "Upgrade the package you installed from, then restart Vectiq.")
    except Exception as exc:  # noqa: BLE001 - offline or rate limited: say so, don't crash
        info.error = str(exc)[:300] or exc.__class__.__name__
    return info


async def apply(root: Path = ROOT, *, pip: bool = True) -> tuple[bool, str]:
    """Update a git checkout: pull (keeping your config.yaml, like get.sh does), then refresh the packages."""
    if install_kind(root) != "git":
        return False, "This copy of Vectiq wasn't installed with git, so it can't update itself."
    _, status = await sh("git", "status", "--porcelain", "--untracked-files=no", cwd=root)
    files = changed_files(status)
    if any(f != "config.yaml" for f in files):
        return False, "You've edited Vectiq's own files; update by hand or undo those edits first."
    cfg, aside = root / "config.yaml", root / ".config.yaml.yours"
    kept = False
    if "config.yaml" in files:
        shutil.copy2(cfg, aside)
        await sh("git", "checkout", "-q", "--", "config.yaml", cwd=root)
        kept = True
    rc, out = await sh("git", "pull", "--ff-only", "-q", cwd=root, timeout=180)
    if kept:
        shutil.move(str(aside), str(cfg))
    if rc:
        return False, f"git pull failed: {out[-300:]}"
    if pip:
        extras = kept_extras(root)
        target = f"{root}[{','.join(extras)}]" if extras else str(root)
        rc, out = await sh(sys.executable, "-m", "pip", "install", "-q", "-e", target, cwd=root, timeout=900)
        if rc:
            return False, f"The new code is in place but installing its packages failed: {out[-300:]}"
    return True, "Updated."


def _req_name(req: str) -> str:
    return re.split(r"[\s\[<>=!~;@]", req.strip(), maxsplit=1)[0].lower().replace("_", "-")


def _installed(name: str) -> bool:
    try:
        metadata.distribution(name)
        return True
    except metadata.PackageNotFoundError:
        return False


def kept_extras(root: Path = ROOT, installed=_installed) -> list[str]:
    """The optional extras this install already has, read from the (new) pyproject.toml.

    An extra counts as installed when a package only it brings is there. That way an update that adds a package to
    an extra you use (say, media) installs it, and extras you never chose stay out."""
    try:
        extras = tomllib.loads((root / "pyproject.toml").read_text())["project"]["optional-dependencies"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return []
    extras = {k: [_req_name(r) for r in v] for k, v in extras.items() if k not in ("all", "dev")}
    keep = []
    for name, reqs in extras.items():
        others = {r for k, v in extras.items() if k != name for r in v}
        own = [r for r in reqs if r not in others and r != "vectiq"] or reqs
        if any(installed(r) for r in own):
            keep.append(name)
    return sorted(keep)


def restart() -> None:
    """Replace this process with a fresh one (same arguments). A service manager sees nothing happen."""
    os.execv(sys.executable, [sys.executable, *sys.orig_argv[1:]])

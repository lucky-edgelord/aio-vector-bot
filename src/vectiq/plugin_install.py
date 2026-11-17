"""Installing and removing plugin packages with pip, for ``vectiq --install-module`` and ``!module install``."""

from __future__ import annotations

import importlib
import re
import subprocess
import sys

from . import modules

SPEC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-\[\],<>=!~ ]*$|^(git\+)?https://[^\s;|&`$]+$")


class InstallError(RuntimeError):
    pass


def _pip(*args: str, timeout: int = 900) -> str:
    cmd = [sys.executable, "-m", "pip", *args, "--disable-pip-version-check", "--no-input"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = (p.stdout + p.stderr).strip()
    if p.returncode != 0:
        if "externally-managed-environment" in out:
            raise InstallError("this Python is managed by the system; run Vectiq from its virtual environment "
                               "(.venv) or install the plugin with pipx inject vectiq <package>")
        raise InstallError(out[-800:] or f"pip exited with {p.returncode}")
    importlib.invalidate_caches()
    return out


def install(spec: str) -> str:
    """Blocking. ``pip install --upgrade <spec>``: a package name, name==version, or a git+https / https link."""
    spec = spec.strip()
    if not SPEC.match(spec) or spec.startswith("-"):
        raise InstallError("give a package name (vectiq-ai-automod), name==version, or a git+https:// link")
    return _pip("install", "--upgrade", spec)


def uninstall(name: str) -> str:
    """Blocking. Remove the package a plugin module came from."""
    m = modules.get(name)
    if m is None:
        raise InstallError(f"no module called {name}")
    if not m.source.startswith("package "):
        raise InstallError(f"{name} isn't from a package ({m.source}); delete its folder instead")
    out = _pip("uninstall", "-y", m.source.split(" ", 1)[1])
    modules.forget(name)
    return out

"""Find or build the Sentire binary, and keep its identity."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO = "https://github.com/VectorPrivacy/Sentire"


def home(data_dir: str) -> Path:
    return Path(data_dir).resolve() / "sentire"


def find_binary(configured: str, data_dir: str) -> Path | None:
    for cand in (configured, str(home(data_dir) / "bin" / "sentinel")):
        if cand and Path(cand).expanduser().is_file() and os.access(Path(cand).expanduser(), os.X_OK):
            return Path(cand).expanduser().resolve()
    for name in ("sentinel", "sentire"):
        if (found := shutil.which(name)):
            return Path(found)
    return None


def identity(data_dir: str) -> str:
    """Sentire's own key, made once and kept in data/sentire/identity.env (readable by this user only)."""
    path = home(data_dir) / "identity.env"
    if path.exists():
        for line in path.read_text("utf-8").splitlines():
            if line.startswith("SENTINEL_NSEC="):
                return line.split("=", 1)[1].strip()
    from vector import generate_nsec

    nsec = generate_nsec()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("# Sentire's Vector identity, made by Vectiq. Back it up: it is the bot's account.\n"
                f"SENTINEL_NSEC={nsec}\n")
    return nsec


def build(data_dir: str, *, tee: bool = False, ref: str = "", log=print) -> Path:
    """Blocking, minutes. Clone (or update) Sentire and build it with cargo. Returns the binary's path."""
    if shutil.which("cargo") is None:
        raise RuntimeError("building Sentire needs Rust: install it from https://rustup.rs (the Vectiq installers "
                           "already did), or download a Sentire binary and set sentire.binary")
    h = home(data_dir)
    src = h / "src"
    if (src / ".git").exists():
        log("updating Sentire's source…")
        subprocess.run(["git", "-C", str(src), "fetch", "--depth", "1", "origin", ref or "HEAD"], check=True)
        subprocess.run(["git", "-C", str(src), "reset", "--hard", "FETCH_HEAD"], check=True)
    else:
        log("downloading Sentire's source…")
        h.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth", "1", *(["--branch", ref] if ref else []), REPO, str(src)],
                       check=True)
    log("building Sentire (this takes a few minutes the first time)…")
    cmd = ["cargo", "build", "--release"] + ([] if tee else ["--no-default-features"])
    subprocess.run(cmd, cwd=src, check=True)
    out = h / "bin" / "sentinel"
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src / "target" / "release" / "sentinel", out)
    return out

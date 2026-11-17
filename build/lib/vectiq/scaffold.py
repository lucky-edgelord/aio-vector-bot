"""Start-up files for a pip install: ``vectiq --init`` writes config.yaml and .env into a folder."""
from __future__ import annotations

import os
from importlib import resources
from pathlib import Path


def example(name: str) -> str:
    """The text of a bundled example file (``config.example.yaml`` or ``env.example``)."""
    return resources.files("vectiq").joinpath(name).read_text("utf-8")


def init(folder: str | Path = ".") -> list[tuple[Path, bool]]:
    """Create config.yaml and .env in ``folder`` unless they exist. Returns (path, created) for each."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for fname, src, mode in (("config.yaml", "config.example.yaml", 0o644), (".env", "env.example", 0o600)):
        dest = folder / fname
        created = not dest.exists()
        if created:
            dest.write_text(example(src), "utf-8")
            os.chmod(dest, mode)
        out.append((dest, created))
    return out

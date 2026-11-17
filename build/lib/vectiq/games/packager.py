"""Build ``.xdc`` files (zip archives) from games/apps/<name>/ plus the shared front-end files."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

APPS = Path(__file__).parent / "apps"
SHARED = APPS / "_shared"

# Fixed timestamp so the same sources always make byte-identical archives (stable content hash).
_EPOCH = (2026, 1, 1, 0, 0, 0)


def source_files(name: str) -> list[tuple[str, Path]]:
    app = APPS / name
    if not (app / "index.html").exists():
        raise FileNotFoundError(f"no game app named {name!r}")
    files = {p.relative_to(app).as_posix(): p for p in app.rglob("*") if p.is_file()}
    for p in SHARED.glob("*"):
        files.setdefault(p.name, p)
    return sorted(files.items())


def build(name: str, out_dir: str | Path) -> Path:
    """Write ``<out_dir>/vectiq-<name>.xdc`` and return its path."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"vectiq-{name}.xdc"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, path in source_files(name):
            info = zipfile.ZipInfo(arc, _EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, path.read_bytes())
    return target


def digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]

"""Reading a marketplace: a GitHub repository with ``modules/catalog.json`` and the module files next to it.

As in Lilith Learning Lab, only raw.githubusercontent.com is contacted. Every file is checked against the checksum the
catalog gives for it before it is read, so a catalog and its files can't drift apart unnoticed.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable

from . import fmt

RAW = "https://raw.githubusercontent.com"
REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,38}/[A-Za-z0-9_.-]{1,100}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,99}$")
FILE_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}\.module\.json$")
CACHE_SECONDS = 300


class MarketError(RuntimeError):
    pass


def http_get(url: str, limit: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Vectiq (+https://github.com/lucky-edgelord/aio-vector-bot)"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 - the address is always RAW/... (see Marketplace)
            data = r.read(limit + 1)
    except urllib.error.HTTPError as exc:
        raise MarketError("not found" if exc.code == 404 else f"GitHub answered {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise MarketError(f"couldn't reach GitHub ({getattr(exc, 'reason', exc)})") from None
    if len(data) > limit:
        raise MarketError("the file is too big")
    return data


def valid_source(repo: str, branch: str) -> bool:
    return bool(REPO_RE.match(repo or "")) and bool(BRANCH_RE.match(branch or "")) and ".." not in (branch or "")


class Marketplace:
    def __init__(self, repo: str, branch: str = "main", *, get: Callable[[str, int], bytes] = http_get):
        if not valid_source(repo, branch):
            raise MarketError(f"{repo!r} on {branch!r} isn't a GitHub repository and branch (use owner/name and main)")
        self.repo, self.branch, self._get = repo, branch, get
        self._cached: tuple[float, dict] | None = None

    def url(self, file: str) -> str:
        return f"{RAW}/{self.repo}/{self.branch}/modules/{file}"

    @staticmethod
    def clean_media(e: dict) -> dict:
        """Keep only pictures that live in the marketplace itself (``media/...``); the dashboard loads them from it."""
        icon = e.get("icon", "")
        images = [i for i in e.get("images", []) if isinstance(i, dict) and fmt.media_path(i.get("src"))] \
            if isinstance(e.get("images"), list) else []
        return {**e, "icon": icon if fmt.media_path(icon) or fmt.emoji_icon(icon) else "",
                "images": [{"src": i["src"], "caption": str(i.get("caption", ""))[:160]} for i in images[:fmt.MAX_IMAGES]]}

    async def catalog(self, *, fresh: bool = False) -> dict:
        if self._cached and not fresh and time.monotonic() - self._cached[0] < CACHE_SECONDS:
            return self._cached[1]
        try:
            raw = await asyncio.to_thread(self._get, self.url("catalog.json"), 5_000_000)
        except MarketError as exc:
            raise MarketError(f"{self.repo} has no module catalog ({exc})" if "not found" in str(exc) else str(exc)) from None
        try:
            cat = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError):
            raise MarketError(f"{self.repo}'s modules/catalog.json isn't valid JSON") from None
        if not isinstance(cat, dict) or cat.get("format") != fmt.CATALOG_FORMAT or not isinstance(cat.get("modules"), list):
            raise MarketError(f"{self.repo} has no module catalog (modules/catalog.json with format {fmt.CATALOG_FORMAT})")
        entries = []
        for e in cat["modules"]:
            if isinstance(e, dict) and fmt.ID_RE.match(str(e.get("id", ""))) and FILE_RE.match(str(e.get("file", ""))) \
                    and re.fullmatch(r"[0-9a-f]{64}", str(e.get("sha256", ""))):
                entries.append(self.clean_media(e))
        cat = {**cat, "modules": entries, "media": self.url("")}
        self._cached = (time.monotonic(), cat)
        return cat

    async def download(self, mid: str) -> tuple[dict, bytes, dict]:
        """The module (checked), its exact bytes, and its catalog entry."""
        cat = await self.catalog()
        entry = next((e for e in cat["modules"] if e["id"] == mid), None)
        if entry is None:
            raise MarketError(f"{self.repo} has no module {mid}")
        raw = await asyncio.to_thread(self._get, self.url(entry["file"]), fmt.MAX_FILE_BYTES)
        if fmt.digest(raw) != entry["sha256"]:
            self._cached = None
            raise MarketError(f"{entry.get('name', mid)} doesn't match the catalog's checksum, so it wasn't used. "
                              "The marketplace may be mid-update; try again in a minute.")
        from .library import reserved

        result = fmt.validate(raw, reserved=reserved())
        if not result.ok:
            raise MarketError(f"{mid} isn't a valid module: {'; '.join(result.errors)}")
        if result.module["id"] != mid:
            raise MarketError(f"the file listed as {mid} is really {result.module['id']}")
        return result.module, raw, entry

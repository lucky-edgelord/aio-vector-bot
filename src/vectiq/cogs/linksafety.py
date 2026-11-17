"""Link safety: removes links to scam, malware, tracking or adult sites using public blocklists (oisd.nl by
default) and, optionally, Google Safe Browsing."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import urllib.request
from pathlib import Path

from vector.ext import commands, tasks

from ..utils.embeds import embed, fail, ok
from ..utils.enforce import enforce, exempt

log = logging.getLogger("vectiq.linksafety")

OISD_BIG = "https://big.oisd.nl/domainswild2"
OISD_NSFW = "https://nsfw.oisd.nl/domainswild2"
SAFE_BROWSING = "https://safebrowsing.googleapis.com/v4/threatMatches:find?key={key}"
DOMAIN = re.compile(r"(?:https?://)?(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}(?=[/:?#\s)\]>'\",;!.]|$)",
                    re.IGNORECASE)
URL = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)


def domains_in(text: str) -> list[str]:
    """Every domain mentioned, with or without http(s)://, lower-cased, without www."""
    out = []
    for m in DOMAIN.finditer(text or ""):
        d = re.sub(r"^https?://", "", m.group(0).lower()).removeprefix("www.").rstrip(".")
        if d not in out:
            out.append(d)
    return out


def parse_list(text: str) -> set[str]:
    """A blocklist: one domain per line; ``#`` comments, hosts-file lines and ``*.`` / ``||...^`` forms are accepted."""
    out = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip().lower()
        if not line or line.startswith("!"):
            continue
        parts = line.split()
        if len(parts) == 2 and parts[0] in ("0.0.0.0", "127.0.0.1", "::"):
            line = parts[1]
        line = line.removeprefix("||").removesuffix("^").removeprefix("*.").removeprefix("www.")
        if "." in line and " " not in line:
            out.add(line)
    return out


def listed(domain: str, blocked: set[str]) -> str | None:
    """The blocklist entry matching ``domain`` or one of its parents (lists include subdomains), or None."""
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        d = ".".join(parts[i:])
        if d in blocked:
            return d
    return None


class Blocklists:
    """Downloaded lists, cached on disk so the bot starts with them even when offline."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.domains: set[str] = set()
        self.sources: dict[str, int] = {}     # url -> entries
        self.updated = 0.0

    def path(self, url: str) -> Path:
        return self.folder / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".txt")

    def load(self, urls, *, download: bool, max_age: float) -> None:
        """Blocking: read each list from cache, downloading it first when missing or older than ``max_age``."""
        self.folder.mkdir(parents=True, exist_ok=True)
        merged: set[str] = set()
        sources = {}
        for url in urls:
            p = self.path(url)
            stale = not p.exists() or time.time() - p.stat().st_mtime > max_age
            if download and stale:
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Vectiq link safety"})
                    with urllib.request.urlopen(req, timeout=60) as r:
                        data = r.read(64 * 1024 * 1024)
                    tmp = p.with_suffix(".part")
                    tmp.write_bytes(data)
                    os.replace(tmp, p)
                    log.info("downloaded %s", url)
                except Exception as exc:  # noqa: BLE001 - keep the cached copy
                    log.warning("could not download %s: %s", url, exc)
            if p.exists():
                found = parse_list(p.read_text("utf-8", "replace"))
                sources[url] = len(found)
                merged |= found
        self.domains, self.sources, self.updated = merged, sources, time.time()


async def safe_browsing(key: str, urls: list[str]) -> bool:
    """True if Google Safe Browsing knows any of ``urls`` as malware, phishing or unwanted software."""
    body = {"client": {"clientId": "vectiq", "clientVersion": "1"},
            "threatInfo": {"threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE",
                                           "POTENTIALLY_HARMFUL_APPLICATION"],
                           "platformTypes": ["ANY_PLATFORM"], "threatEntryTypes": ["URL"],
                           "threatEntries": [{"url": u} for u in urls[:50]]}}

    def call():
        req = urllib.request.Request(SAFE_BROWSING.format(key=key), data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read() or b"{}")

    try:
        return bool((await asyncio.to_thread(call)).get("matches"))
    except Exception as exc:  # noqa: BLE001
        log.warning("Safe Browsing check failed: %s", exc)
        return False


class LinkSafety(commands.Cog, name="LinkSafety"):
    """Removes links to known scam, malware, tracking or adult sites."""

    def __init__(self, bot):
        self.bot = bot
        self.lists = Blocklists(Path(bot.config.data_dir) / "linksafety")
        self.refresh.start()

    async def cog_unload(self):
        self.refresh.cancel()

    @property
    def cfg(self) -> dict:
        return self.bot.config.get("linksafety", {})

    def urls(self) -> list[str]:
        urls = [str(u) for u in self.cfg.get("lists") or []]
        if self.cfg.get("nsfw") and OISD_NSFW not in urls:
            urls.append(OISD_NSFW)
        return urls

    async def reload(self, *, force: bool = False) -> None:
        hours = float(self.cfg.get("refresh_hours", 24) or 24)
        await asyncio.to_thread(self.lists.load, self.urls(), download=True, max_age=0 if force else hours * 3600)
        log.info("link safety: %d blocked domains from %d lists", len(self.lists.domains), len(self.lists.sources))

    @tasks.loop(hours=1)
    async def refresh(self):
        hours = float(self.cfg.get("refresh_hours", 24) or 24)
        if not self.lists.domains or time.time() - self.lists.updated >= hours * 3600 or \
                set(self.lists.sources) != set(self.urls()):
            await self.reload()

    def verdict(self, domain: str) -> str | None:
        """Why ``domain`` is blocked, or None. ``allow`` beats everything; ``block`` beats the lists."""
        cfg = self.cfg
        allow = {str(d).lower().lstrip("*.") for d in cfg.get("allow") or []}
        if listed(domain, allow):
            return None
        if (hit := listed(domain, {str(d).lower().lstrip("*.") for d in cfg.get("block") or []})):
            return f"{hit} is blocked here"
        if (hit := listed(domain, self.lists.domains)):
            return f"{hit} is on a blocklist"
        return None

    async def check(self, text: str) -> str | None:
        for d in domains_in(text):
            if (why := self.verdict(d)):
                return why
        key_env = self.cfg.get("safe_browsing_key_env") or ""
        key = os.environ.get(key_env, "") if key_env else ""
        urls = URL.findall(text or "")
        if key and urls and await safe_browsing(key, urls):
            return "Google Safe Browsing flags that link as dangerous"
        return None

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild is None or not self.bot.serves(message.guild) or exempt(self.bot, message, self.cfg):
            return
        why = await self.check(message.content or "")
        if why:
            await enforce(self.bot, message, source="link safety", reason="that link isn't safe", detail=why,
                          action=self.cfg.get("action", "delete"),
                          timeout_minutes=int(self.cfg.get("timeout_minutes", 10)))

    @commands.group(name="linksafety", invoke_without_command=True)
    @commands.has_permissions(manage_messages=True)
    async def linksafety(self, ctx):
        """Show the blocklists and how many sites they cover."""
        lines = [f"• {url} ({n:,} sites)" for url, n in self.lists.sources.items()] or ["No lists loaded yet."]
        age = f"{(time.time() - self.lists.updated) / 3600:.1f} h ago" if self.lists.updated else "never"
        lines.append(f"\n{len(self.lists.domains):,} blocked sites in total, updated {age}. "
                     "`!linksafety check <link>` · `!linksafety update`")
        await ctx.send(embed=embed("Link safety", "\n".join(lines)))

    @linksafety.command(name="check")
    async def check_cmd(self, ctx, *, link: str):
        """Would this link be removed?"""
        why = await self.check(link)
        await ctx.send(fail(f"Blocked: {why}.") if why else ok("That link is allowed."))

    @linksafety.command(name="update")
    @commands.has_permissions(manage_guild=True)
    async def update(self, ctx):
        """Download the blocklists again now."""
        await ctx.send("Downloading the blocklists…")
        await self.reload(force=True)
        await ctx.send(ok(f"{len(self.lists.domains):,} blocked sites loaded."))


async def setup(bot):
    await bot.add_cog(LinkSafety(bot))

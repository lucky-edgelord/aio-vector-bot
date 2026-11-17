"""Stream & video alerts: post when a YouTube channel uploads, a Twitch channel goes live, or an RSS/Atom feed has
something new. Feeds come from config.yaml (``notifications.feeds``) and from ``!notify add``."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from vector.ext import commands, tasks

from ..utils.embeds import embed, fail, ok, table

log = logging.getLogger("vectiq.notifications")

KINDS = ("youtube", "twitch", "rss")
DEFAULT_MESSAGE = {
    "youtube": "📺 **{author}** posted a new video: {title}\n{url}",
    "twitch": "🔴 **{author}** is live on Twitch: {title}\n{url}",
    "rss": "📰 **{author}**: {title}\n{url}",
}
YT_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={id}"
YT_ID = re.compile(r"\b(UC[\w-]{22})\b")
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/"}


@dataclass
class Item:
    id: str
    title: str
    url: str
    author: str = ""


@dataclass
class Feed:
    kind: str
    source: str
    channel_ref: str
    guild_id: str
    message: str = ""
    role: str = ""
    db_id: int | None = None

    @property
    def key(self) -> str:
        return f"{self.guild_id}:{self.kind}:{self.source.lower()}:{self.channel_ref}"


def fetch(url: str, *, headers: dict | None = None, data: bytes | None = None, limit: int = 5 * 1024 * 1024) -> bytes:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Vectiq notifications", **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read(limit)


def parse_feed(xml: bytes) -> list[Item]:
    """Items of an RSS 2.0 or Atom feed (YouTube's included), newest first as the feed lists them."""
    root = ET.fromstring(xml)
    items: list[Item] = []
    if root.tag.endswith("rss") or root.find("channel") is not None:
        ch = root.find("channel")
        author = (ch.findtext("title") or "").strip() if ch is not None else ""
        for it in (ch.findall("item") if ch is not None else []):
            link = (it.findtext("link") or "").strip()
            items.append(Item((it.findtext("guid") or link or it.findtext("title") or "").strip(),
                              (it.findtext("title") or "").strip(), link, author))
        return items
    author = (root.findtext("a:author/a:name", namespaces=NS) or root.findtext("a:title", namespaces=NS) or "").strip()
    for e in root.findall("a:entry", NS):
        link_el = e.find("a:link[@rel='alternate']", NS)
        if link_el is None:
            link_el = e.find("a:link", NS)
        link = link_el.get("href", "") if link_el is not None else ""
        vid = e.findtext("yt:videoId", namespaces=NS)
        items.append(Item((vid or e.findtext("a:id", namespaces=NS) or link).strip(),
                          (e.findtext("a:title", namespaces=NS) or "").strip(), link,
                          (e.findtext("a:author/a:name", namespaces=NS) or author).strip()))
    return items


def youtube_channel_id(source: str) -> str | None:
    """A channel id from an id, a /channel/ URL, or (by reading the page) an @handle or channel URL."""
    if (m := YT_ID.search(source)):
        return m.group(1)
    s = source.strip()
    if s.startswith("@"):
        s = f"https://www.youtube.com/{s}"
    elif not s.startswith("http"):
        s = f"https://www.youtube.com/@{s}"
    try:
        page = fetch(s, headers={"Accept-Language": "en"}).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r'"(?:channelId|externalId)":"(UC[\w-]{22})"', page) or \
        re.search(r'youtube\.com/channel/(UC[\w-]{22})', page)
    return m.group(1) if m else None


class Twitch:
    """Twitch Helix with an app access token (TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET)."""

    def __init__(self):
        self.token = ""
        self.expires = 0.0

    def creds(self, cfg: dict) -> tuple[str, str]:
        t = cfg.get("twitch") or {}
        return (os.environ.get(t.get("client_id_env", "TWITCH_CLIENT_ID"), ""),
                os.environ.get(t.get("client_secret_env", "TWITCH_CLIENT_SECRET"), ""))

    def live(self, cfg: dict, logins: list[str]) -> dict[str, Item]:
        cid, secret = self.creds(cfg)
        if not cid or not secret:
            raise RuntimeError("Twitch alerts need TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET in .env")
        if not self.token or time.time() > self.expires - 60:
            q = urllib.parse.urlencode({"client_id": cid, "client_secret": secret, "grant_type": "client_credentials"})
            tok = json.loads(fetch("https://id.twitch.tv/oauth2/token", data=q.encode()))
            self.token, self.expires = tok["access_token"], time.time() + float(tok.get("expires_in", 3600))
        out: dict[str, Item] = {}
        for i in range(0, len(logins), 100):
            q = urllib.parse.urlencode([("user_login", u) for u in logins[i:i + 100]])
            data = json.loads(fetch(f"https://api.twitch.tv/helix/streams?{q}",
                                    headers={"Client-Id": cid, "Authorization": f"Bearer {self.token}"}))
            for s in data.get("data", []):
                login = s.get("user_login", "").lower()
                out[login] = Item(str(s.get("id")), s.get("title", ""), f"https://twitch.tv/{login}",
                                  s.get("user_name", login))
        return out


class Notifications(commands.Cog, name="Notifications"):
    """YouTube uploads, Twitch go-lives and RSS posts, announced in a channel."""

    def __init__(self, bot):
        self.bot = bot
        self.store = bot.stores.notify
        self.twitch = Twitch()
        self._last = 0.0
        self._yt_ids: dict[str, str] = {}
        self.loop.start()

    async def cog_unload(self):
        self.loop.cancel()

    @property
    def cfg(self) -> dict:
        return self.bot.config.get("notifications", {})

    async def feeds(self) -> list[Feed]:
        out = []
        for f in self.cfg.get("feeds") or []:
            kind = str(f.get("type", "")).lower()
            if kind not in KINDS or not f.get("source"):
                continue
            for guild in self.bot.guilds:
                if not self.bot.serves(guild):
                    continue
                want = str(f.get("community", "")).lower()
                if want and want not in (str(guild.id).lower(), str(guild.name).lower()):
                    continue
                out.append(Feed(kind, str(f["source"]), str(f.get("channel", "")), str(guild.id),
                                str(f.get("message", "")), str(f.get("role", ""))))
        for r in await self.store.feeds():
            out.append(Feed(r["kind"], r["source"], r["channel_id"], r["guild_id"], r["message"], r["role"], r["id"]))
        return out

    async def items(self, feed: Feed, twitch_live: dict[str, Item]) -> list[Item]:
        if feed.kind == "twitch":
            it = twitch_live.get(feed.source.lower().lstrip("@"))
            return [it] if it else []
        if feed.kind == "youtube":
            cid = self._yt_ids.get(feed.source) or await asyncio.to_thread(youtube_channel_id, feed.source)
            if not cid:
                raise RuntimeError(f"couldn't find the YouTube channel {feed.source}")
            self._yt_ids[feed.source] = cid
            url = YT_FEED.format(id=cid)
        else:
            url = feed.source
        return parse_feed(await asyncio.to_thread(fetch, url))

    async def check(self, *, only: list[Feed] | None = None) -> int:
        """Look at every feed once and post what is new. Returns how many posts were made."""
        feeds = only if only is not None else await self.feeds()
        logins = sorted({f.source.lower().lstrip("@") for f in feeds if f.kind == "twitch"})
        live: dict[str, Item] = {}
        if logins:
            try:
                live = await asyncio.to_thread(self.twitch.live, self.cfg, logins)
            except Exception as exc:  # noqa: BLE001
                log.warning("twitch: %s", exc)
        posted = 0
        for feed in feeds:
            try:
                items = await self.items(feed, live)
            except Exception as exc:  # noqa: BLE001 - one broken feed must not stop the others
                log.warning("%s %s: %s", feed.kind, feed.source, exc)
                continue
            seen = await self.store.seen(feed.key)
            fresh = [i for i in items if i.id and i.id not in seen]
            if not seen and feed.kind != "twitch":
                await self.store.mark(feed.key, [i.id for i in items] or ["-"])   # first look: remember, don't post
                continue
            for item in reversed(fresh[: int(self.cfg.get("max_per_check", 3))]):
                if await self.post(feed, item):
                    posted += 1
            await self.store.mark(feed.key, [i.id for i in fresh] or (["-"] if not seen else []))
        return posted

    async def post(self, feed: Feed, item: Item) -> bool:
        guild = self.bot.get_guild(feed.guild_id) if hasattr(self.bot, "get_guild") else None
        guild = guild or next((g for g in self.bot.guilds if str(g.id) == feed.guild_id), None)
        if guild is None:
            return False
        ch = self.bot.find_channel(guild, feed.channel_ref or self.cfg.get("channel", "announcements"))
        if ch is None:
            log.warning("notifications: no channel %r in %s", feed.channel_ref, guild.name)
            return False
        template = feed.message or (self.cfg.get("messages") or {}).get(feed.kind) or DEFAULT_MESSAGE[feed.kind]
        text = template.format_map({"title": item.title, "url": item.url, "author": item.author or feed.source,
                                    "kind": feed.kind})
        role = self.bot.find_role(guild, feed.role) if feed.role else None
        if role is not None:
            text = f"{getattr(role, 'mention', '@' + role.name)} {text}"
        await ch.send(text)
        self.bot.emit(guild, "notifications", f"{feed.kind}: {item.author}", item.title)
        return True

    @tasks.loop(minutes=1)
    async def loop(self):
        every = max(2.0, float(self.cfg.get("check_minutes", 5) or 5)) * 60
        if time.time() - self._last < every:
            return
        self._last = time.time()
        await self.check()
        await self.store.prune()

    @loop.before_loop
    async def _wait(self):
        await self.bot.wait_until_ready()

    # -- commands -------------------------------------------------------------------------

    @commands.group(name="notify", aliases=["alerts"], invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def notify(self, ctx):
        """List the alerts in this community."""
        feeds = [f for f in await self.feeds() if f.guild_id == str(ctx.guild.id)]
        if not feeds:
            return await ctx.send("No alerts yet. `!notify add youtube <channel link or @handle> [#channel]`, "
                                  "`!notify add twitch <name> [#channel]`, `!notify add rss <feed link> [#channel]`.")
        rows = [(str(f.db_id or "yaml"), f.kind, f.source[:40], f.channel_ref or "default") for f in feeds]
        await ctx.send(embed=embed("Alerts", table(rows, header=("#", "type", "source", "channel"))
                                   + "\n`!notify remove <#>` · `!notify check`"))

    @notify.command(name="add")
    async def add(self, ctx, kind: str, source: str, channel: str = "", *, role: str = ""):
        """Add an alert: `!notify add youtube @handle #videos`, `!notify add twitch name #live @Viewers`."""
        kind = kind.lower()
        if kind not in KINDS:
            return await ctx.send(fail(f"Pick one of: {', '.join(KINDS)}."))
        ch = self.bot.find_channel(ctx.guild, channel) if channel else ctx.channel
        if ch is None:
            return await ctx.send(fail(f"I can't find a channel called {channel}."))
        if kind == "youtube" and not await asyncio.to_thread(youtube_channel_id, source):
            return await ctx.send(fail("I couldn't find that YouTube channel. Try its link or @handle."))
        feed_id = await self.store.add(str(ctx.guild.id), kind, source.strip("<>"), str(ch.id), role=role.lstrip("@"),
                                       by_id=str(ctx.author.id))
        feed = next(f for f in await self.feeds() if f.db_id == feed_id)
        await self.check(only=[feed])          # remember what's already there so it isn't posted
        await ctx.send(ok(f"Alert #{feed_id} added. New {kind} posts will go to #{ch.name}."))

    @notify.command(name="remove")
    async def remove(self, ctx, feed_id: int):
        """Remove an alert."""
        done = await self.store.remove(str(ctx.guild.id), feed_id)
        await ctx.send(ok(f"Alert #{feed_id} removed.") if done else fail(f"No alert #{feed_id} here."))

    @notify.command(name="check")
    async def check_now(self, ctx):
        """Check every alert now."""
        n = await self.check(only=[f for f in await self.feeds() if f.guild_id == str(ctx.guild.id)])
        await ctx.send(ok(f"Checked. {n} new post(s)."))


async def setup(bot):
    await bot.add_cog(Notifications(bot))

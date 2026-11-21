"""Runs what a JSON module describes: its commands, autoresponders and timers.

Nothing in the file is executed. Each part is data this cog knows how to act on, and text is filled in from a fixed
set of placeholders, so a module from a stranger can only say things, react, and post on a schedule.
"""

from __future__ import annotations

import datetime
import logging
import random
import re
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from vector.ext import commands, tasks

from ..utils.embeds import embed, name_of

log = logging.getLogger("vectiq.jsonmods")

# module id -> what the dashboard shows about the running module
STATE: dict[str, dict] = {}
_PLACEHOLDER = re.compile(r"\{(settings\.[a-z][a-z0-9_]*|user|mention|args|channel|community|members|prefix)\}")


def fill(text: str, values: dict[str, str], settings: dict) -> str:
    """Replace the known placeholders. Anything else in braces stays exactly as written."""

    def one(m: re.Match) -> str:
        key = m.group(1)
        if key.startswith("settings."):
            v = settings.get(key[9:])
            if v is None:
                return m.group(0)
            return ", ".join(map(str, v)) if isinstance(v, list) else str(v)
        return values.get(key, m.group(0))

    return _PLACEHOLDER.sub(one, text)


def heard(match: str, phrases: list[str], content: str) -> bool:
    text = " ".join(content.lower().split())
    for p in phrases:
        p = " ".join(p.lower().split())
        if not p:
            continue
        if (match == "contains" and p in text) or (match == "exact" and text == p) \
                or (match == "startswith" and text.startswith(p)) or (match == "endswith" and text.endswith(p)) \
                or (match == "word" and re.search(rf"(?<![\w]){re.escape(p)}(?![\w])", text)):
            return True
    return False


class DataModule(commands.Cog):
    """Shared behaviour. :func:`build` makes a subclass per module with its commands attached."""

    module: dict = {}

    def __init__(self, bot):
        self.bot = bot
        self.mid = self.module["id"]
        self._cool: dict[tuple, float] = {}
        self._next: dict[int, float] = {}
        self._done_day: dict[int, tuple[str, tuple]] = {}
        self._turn: dict[int, int] = {}
        if self.module.get("timers"):
            self.clock.start()

    async def cog_unload(self):
        if self.module.get("timers"):
            self.clock.cancel()

    # -- shared helpers ----------------------------------------------------------------------------------

    def settings(self) -> dict:
        value = self.bot.config.get(self.mid, {})
        return value if isinstance(value, dict) else {}

    def values(self, guild, channel, author, args: str = "") -> dict[str, str]:
        return {"user": name_of(author), "mention": str(getattr(author, "mention", "") or name_of(author)),
                "args": args.strip(), "channel": str(getattr(channel, "name", "") or ""),
                "community": str(getattr(guild, "name", "") or ""),
                "members": str(getattr(guild, "member_count", "") or ""), "prefix": str(self.bot.config.prefix)}

    def waiting(self, key: tuple, seconds: float) -> bool:
        """True if ``key`` is still cooling down; otherwise starts its cooldown."""
        if seconds <= 0:
            return False
        now = time.monotonic()
        if self._cool.get(key, 0) > now:
            return True
        self._cool[key] = now + seconds
        if len(self._cool) > 5000:
            self._cool = {k: t for k, t in self._cool.items() if t > now}
        return False

    @staticmethod
    def allowed(item: dict, member, channel) -> bool:
        roles = {r.lower() for r in item.get("roles", [])}
        if roles and not roles & {str(getattr(r, "name", "")).lower() for r in getattr(member, "roles", []) or []}:
            return False
        chans = {c.lower().lstrip("#") for c in item.get("channels", [])}
        if chans:
            name = str(getattr(channel, "name", "")).lower()
            loose = "".join(ch for ch in name if ch.isalnum())
            if name not in chans and str(getattr(channel, "id", "")) not in chans and \
                    not any("".join(ch for ch in c if ch.isalnum()) == loose for c in chans):
                return False
        return True

    def choose(self, item: dict, index: int | None = None) -> str:
        replies = item.get("replies") or []
        if not replies:
            return ""
        if index is not None and item.get("order") == "in_turn":
            turn = self._turn.get(index, 0)
            self._turn[index] = turn + 1
            return replies[turn % len(replies)]
        return random.choice(replies)

    async def say(self, target, item: dict, values: dict, index: int | None = None) -> None:
        settings = self.settings()
        text = fill(self.choose(item, index), values, settings)[:4000]
        if not text.strip():
            return
        card = item.get("card")
        if card:
            e = embed(fill(card.get("title", ""), values, settings)[:256] or self.module["name"], text)
            if card.get("color"):
                try:
                    e.color = int(card["color"].lstrip("#"), 16)
                except (AttributeError, TypeError, ValueError):
                    pass
            await target.send(embed=e)
        else:
            await target.send(text)

    @staticmethod
    async def react(message, item: dict) -> None:
        for emoji in item.get("react", []):
            try:
                await message.add_reaction(emoji)
            except Exception:  # noqa: BLE001 - a reaction that can't be added isn't worth an error
                pass

    # -- commands ----------------------------------------------------------------------------------------

    async def run_command(self, item: dict, ctx, args: str) -> None:
        if ctx.guild is not None and not self.bot.serves(ctx.guild):
            return
        if not self.allowed(item, ctx.author, ctx.channel):
            await ctx.send("❌ You can't use that here.")
            return
        if self.waiting((str(ctx.author.id), item["name"]), item.get("cooldown", 0)):
            return
        values = self.values(ctx.guild, ctx.channel, ctx.author, args)
        await self.react(ctx.message, item)
        if item.get("delete_trigger"):
            try:
                await ctx.message.delete()
            except Exception:  # noqa: BLE001 - missing permission or already gone
                pass
        if item.get("replies"):
            await self.say(ctx.author if item.get("dm") else ctx, item, values)

    # -- autoresponders ----------------------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message):
        items = self.module.get("autoresponders")
        if not items or getattr(message.author, "bot", False) or message.guild is None:
            return
        content = message.content or ""
        if not content.strip() or content.startswith(self.bot.config.prefix) or not self.bot.serves(message.guild):
            return
        for i, item in enumerate(items):
            if not heard(item["match"], item["phrases"], content) or not self.allowed(item, message.author, message.channel):
                continue
            if self.waiting((str(message.channel.id), i), item.get("cooldown", 60)):
                return
            await self.react(message, item)
            if item.get("replies"):
                await self.say(message.channel, item, self.values(message.guild, message.channel, message.author))
            return

    # -- timers --------------------------------------------------------------------------------------------

    def due(self, i: int, item: dict, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        if "every_minutes" in item:
            nxt = self._next.setdefault(i, now + item["every_minutes"] * 60)
            if now < nxt:
                return False
            self._next[i] = now + item["every_minutes"] * 60
            return True
        settings = self.settings()
        at = fill(item["at"], {}, settings).strip()
        m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", at)
        if not m:
            return False
        try:
            zone = ZoneInfo(fill(item.get("timezone", "UTC"), {}, settings).strip() or "UTC")
        except (ZoneInfoNotFoundError, ValueError):
            zone = datetime.timezone.utc
        local = datetime.datetime.now(zone)
        today = local.date().isoformat()
        late = local.hour * 60 + local.minute - (int(m[1]) * 60 + int(m[2]))
        when = (at, str(zone))
        if self._done_day.get(i, ("", None))[1] != when:
            # First look since loading, or the time was just changed: a time that passed more than two minutes ago
            # waits for tomorrow instead of posting late.
            self._done_day[i] = (today if late > 2 else "", when)
        if late >= 0 and self._done_day[i][0] != today:
            self._done_day[i] = (today, when)
            return True
        return False

    async def post(self, i: int, item: dict) -> int:
        """Post one timer's message in every served community that has its channel."""
        ref = fill(item["channel"], {}, self.settings()).strip()
        text_item = {**item, "replies": [self.choose(item, i)]}
        sent = 0
        for guild in list(self.bot.guilds):
            if not self.bot.serves(guild):
                continue
            channel = self.bot.find_channel(guild, ref) if ref else None
            if channel is None:
                continue
            try:
                await self.say(channel, text_item, self.values(guild, channel, self.bot.user))
                sent += 1
            except Exception as exc:  # noqa: BLE001 - one channel failing must not stop the others
                log.warning("%s: couldn't post in %s: %s", self.mid, getattr(channel, "name", "?"), exc)
        STATE.setdefault(self.mid, {}).setdefault("posted", {})[i] = int(time.time())
        return sent

    @tasks.loop(seconds=30)
    async def clock(self):
        for i, item in enumerate(self.module.get("timers", [])):
            if self.due(i, item):
                await self.post(i, item)

    @clock.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()


def build(bot, module: dict, extension: str) -> commands.Cog:
    """A cog for this module. Its class and commands say they come from ``extension``, so switching the module off
    (unloading the extension) removes all of them."""
    ns: dict = {"module": module, "__module__": extension}
    skipped = []
    for i, item in enumerate(module.get("commands", [])):
        clash = next((n for n in [item["name"], *item.get("aliases", [])] if bot.get_command(n) is not None), None)
        if clash:
            skipped.append(f"{item['name']}: !{clash} already belongs to another module")
            continue

        def make(item=item):
            async def callback(self, ctx, *, args: str = ""):
                await self.run_command(item, ctx, args)

            callback.__module__ = extension
            callback.__name__ = callback.__qualname__ = f"command_{item['name'].replace('-', '_')}"
            return commands.command(name=item["name"], aliases=item.get("aliases", []), help=item["help"])(callback)

        ns[f"command_{i}"] = make()
    label = module["name"]
    if bot.get_cog(label) is not None:
        label = f"{label} ({module['id']})"
    STATE[module["id"]] = {"skipped": skipped, "posted": {}}
    cls = type(commands.Cog)(f"JsonModule_{module['id']}", (DataModule,), ns, name=label)
    return cls(bot)

"""Automod: rules that remove spam and trouble as it is posted. Every rule has its own switch."""

from __future__ import annotations

import re
import time
import unicodedata
from collections import defaultdict, deque

from vector.ext import commands

from ..utils.embeds import embed
from ..utils.enforce import enforce, exempt

URL = re.compile(r"(?:https?://|www\.)[^\s<>()]+", re.IGNORECASE)
INVITES = (r"vectorapp\.io/invite/", r"discord(?:app)?\.(?:gg|com/invite)/", r"t\.me/(?:\+|joinchat/)",
           r"chat\.whatsapp\.com/", r"signal\.group/", r"matrix\.to/#/[#!]")

RULES = ("mentions", "caps", "words", "links", "invites", "flood", "duplicates", "files", "zalgo")


def host(url: str) -> str:
    url = re.sub(r"^(?:https?://)?(?:www\.)?", "", url.lower())
    return re.split(r"[/:?#]", url, maxsplit=1)[0]


def domain_allowed(domain: str, allow) -> bool:
    return any(domain == a or domain.endswith("." + a) for a in (str(x).lower().lstrip("*.") for x in allow))


class Rules:
    """The checks themselves, with the per-member memory flood and duplicate checks need. Pure and testable."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._recent: dict[tuple[str, str], deque] = defaultdict(lambda: deque(maxlen=50))

    def on(self, rule: str) -> dict | None:
        r = self.cfg.get(rule) or {}
        return r if r.get("enabled") else None

    def check(self, text: str, *, key: tuple[str, str] = ("", ""), filenames=(), now: float | None = None) \
            -> tuple[str, str] | None:
        """The first rule broken as (rule, reason), or None."""
        now = time.monotonic() if now is None else now
        lowered = text.lower()
        if (r := self.on("mentions")) and text.count("nostr:npub") + text.count("@") > int(r.get("max", 6)):
            return "mentions", "too many mentions"
        if (r := self.on("caps")):
            letters = [c for c in text if c.isalpha()]
            if len(letters) >= int(r.get("min_length", 12)) and \
                    100 * sum(c.isupper() for c in letters) / len(letters) >= int(r.get("percent", 80)):
                return "caps", "too many capital letters"
        if (r := self.on("words")):
            for word in r.get("list") or []:
                w = re.escape(str(word).lower())
                if re.search(w if r.get("partial") else rf"\b{w}\b", lowered):
                    return "words", "that word isn't allowed here"
        if (r := self.on("invites")):
            for pat in list(INVITES) + [re.escape(str(p)) for p in r.get("extra") or []]:
                if re.search(pat, lowered) and not any(str(a).lower() in lowered for a in r.get("allow") or []):
                    return "invites", "invite links aren't allowed here"
        if (r := self.on("links")):
            for url in URL.findall(text):
                if not domain_allowed(host(url), r.get("allow") or []):
                    return "links", "links aren't allowed here"
        if (r := self.on("zalgo")):
            marks = sum(unicodedata.category(c) == "Mn" for c in text)
            if marks >= int(r.get("max_marks", 10)) and marks > len(text) / 3:
                return "zalgo", "that text is too glitchy"
        if (r := self.on("files")):
            blocked = {str(e).lower().lstrip(".") for e in r.get("block") or []}
            for name in filenames:
                if "." in name and name.rsplit(".", 1)[1].lower() in blocked:
                    return "files", f".{name.rsplit('.', 1)[1].lower()} files aren't allowed here"
        recent = self._recent[key]
        recent.append((now, lowered.strip()))
        if (r := self.on("flood")):
            window = float(r.get("seconds", 8))
            if sum(1 for t, _ in recent if now - t <= window) > int(r.get("messages", 6)):
                return "flood", "slow down a little"
        if (r := self.on("duplicates")) and lowered.strip():
            window = float(r.get("seconds", 60))
            same = sum(1 for t, m in recent if now - t <= window and m == lowered.strip())
            if same > int(r.get("repeats", 3)):
                return "duplicates", "please don't repeat the same message"
        return None


class Automod(commands.Cog, name="Automod"):
    """Removes spam, mass mentions, shouting, banned words, invites, floods and risky files."""

    def __init__(self, bot):
        self.bot = bot
        self.rules = Rules(bot.config.get("automod", {}))

    @commands.Cog.listener()
    async def on_vectiq_config_reload(self):
        self.rules.cfg = self.bot.config.get("automod", {})

    @commands.Cog.listener()
    async def on_message(self, message):
        cfg = self.bot.config.get("automod", {})
        self.rules.cfg = cfg
        if message.guild is None or not self.bot.serves(message.guild) or exempt(self.bot, message, cfg):
            return
        hit = self.rules.check(message.content or "", key=(str(message.guild.id), str(message.author.id)),
                               filenames=[a.filename or "" for a in getattr(message, "attachments", [])])
        if hit:
            rule, reason = hit
            r = cfg.get(rule) or {}
            await enforce(self.bot, message, source="automod", reason=reason,
                          action=r.get("action") or cfg.get("action", "delete"),
                          timeout_minutes=int(cfg.get("timeout_minutes", 10)))

    @commands.command(name="automod")
    @commands.has_permissions(manage_messages=True)
    async def automod_(self, ctx):
        """Show which automod rules are on."""
        cfg = self.bot.config.get("automod", {})
        lines = [f"{'🟢' if (cfg.get(r) or {}).get('enabled') else '⚪'} `{r}`" for r in RULES]
        lines.append(f"\nAction: **{cfg.get('action', 'delete')}**. Change rules in config.yaml, the dashboard or "
                     "`vectiq --setup`.")
        await ctx.send(embed=embed("Automod", "\n".join(lines)))


async def setup(bot):
    await bot.add_cog(Automod(bot))

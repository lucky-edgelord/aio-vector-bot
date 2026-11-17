"""AI automod: an LLM judges each message against the community's rules."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import urllib.request
from collections import deque

from vector.ext import commands

from vectiq.plugin import embed, enforce, exempt

log = logging.getLogger("vectiq.ai_automod")

PROMPT = """You moderate a chat community. Its rules:
{rules}

Decide whether the message below breaks a rule. Answer with JSON only, like
{{"flag": false, "rule": "", "reason": ""}}
Set "flag" to true only for a clear break. Jokes, disagreement and swearing that isn't aimed at someone are fine."""


def ask_model(cfg: dict, text: str) -> dict:
    """Blocking. Ask the model about one message. Returns {"flag": bool, "rule": str, "reason": str}."""
    key = os.environ.get(cfg.get("api_key_env") or "", "")
    body = {"model": cfg["model"], "temperature": 0,
            "messages": [{"role": "system", "content": PROMPT.format(rules=cfg["rules"])},
                         {"role": "user", "content": text[:2000]}]}
    req = urllib.request.Request(cfg["base_url"].rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {key}"} if key else {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        reply = json.loads(r.read())["choices"][0]["message"]["content"]
    return parse(reply)


def parse(reply: str) -> dict:
    m = re.search(r"\{.*\}", reply or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        data = {}
    return {"flag": bool(data.get("flag")), "rule": str(data.get("rule") or ""), "reason": str(data.get("reason") or "")}


class AIAutomod(commands.Cog, name="AI automod"):
    def __init__(self, bot):
        self.bot = bot
        self.calls: deque[float] = deque()

    @property
    def cfg(self) -> dict:
        return self.bot.config.get("ai_automod", {})

    def budget(self) -> bool:
        now = time.monotonic()
        while self.calls and now - self.calls[0] > 60:
            self.calls.popleft()
        if len(self.calls) >= int(self.cfg.get("max_per_minute", 30)):
            return False
        self.calls.append(now)
        return True

    @commands.Cog.listener()
    async def on_message(self, message):
        cfg = self.cfg
        if message.guild is None or not self.bot.serves(message.guild) or exempt(self.bot, message, cfg):
            return
        text = message.content or ""
        if len(text.strip()) < int(cfg.get("min_chars", 12)) or not self.budget():
            return
        try:
            verdict = await asyncio.to_thread(ask_model, cfg, text)
        except Exception as exc:  # noqa: BLE001 - the model being down must never remove messages
            log.warning("AI automod: the model didn't answer: %s", exc)
            return
        if verdict["flag"]:
            await enforce(self.bot, message, source="AI automod", reason=verdict["rule"] or "that breaks a rule",
                          detail=verdict["reason"], action=cfg.get("action", "delete"),
                          timeout_minutes=int(cfg.get("timeout_minutes", 10)))

    @commands.command(name="aicheck")
    @commands.has_permissions(manage_messages=True)
    async def aicheck(self, ctx, *, text: str):
        """Ask the AI about a message without removing anything."""
        try:
            v = await asyncio.to_thread(ask_model, self.cfg, text)
        except Exception as exc:  # noqa: BLE001
            return await ctx.send(f"❌ The model didn't answer: {exc}")
        await ctx.send(embed=embed("AI automod", ("🚫 Would remove" if v["flag"] else "✅ Fine")
                                   + (f"\n**Rule:** {v['rule']}" if v["rule"] else "")
                                   + (f"\n**Why:** {v['reason']}" if v["reason"] else "")))


async def setup(bot):
    await bot.add_cog(AIAutomod(bot))

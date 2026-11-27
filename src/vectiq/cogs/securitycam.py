from __future__ import annotations

import datetime
import logging
from collections import deque

import vector
from vector.ext import commands

from ..utils.embeds import fail, name_of, ok

log = logging.getLogger("vectiq.securitycam")

KEY = "securitycam:channel"
IGNORE_KEY = "securitycam:ignore"
MAX_FILES = 8
MAX_FILE_BYTES = 8_000_000


def avatar_url(user) -> str | None:
    try:
        url = getattr(getattr(user, "display_avatar", None), "url", None)
        return url if isinstance(url, str) and url.startswith(("https://", "http://")) else None
    except Exception:  # noqa: BLE001 - an avatar is decoration
        return None


class SecurityCam(commands.Cog, name="SecurityCam"):
    """Echoes every message from every channel into one channel, so staff can see it all in one place."""

    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.config
        self.settings = bot.stores.settings
        self.stats: dict[str, dict] = {}      # guild id -> {"echoed": n, "last": datetime}; since the bot started
        self.feed: dict[str, deque] = {}      # guild id -> the latest messages, for the dashboard's live feed (memory only)
        self._seq: dict[str, int] = {}

    # -- where to echo ------------------------------------------------------------------

    async def camera(self, guild):
        """The channel set with ``!securitycam set`` (or ``securitycam.channel`` in config.yaml)."""
        ref = await self.settings.get(str(guild.id), KEY, "") or self.cfg.get("securitycam.channel", "")
        return self.bot.find_channel(guild, ref) if ref else None

    async def ignored_channels(self, guild) -> list[str]:
        """Channel ids skipped by this community (dashboard) plus names/ids from config.yaml."""
        return list(await self.settings.get(str(guild.id), IGNORE_KEY, []) or []) + \
            [str(c) for c in self.cfg.get("securitycam.ignore_channels", [])]

    def _ignored(self, message, cam, ignore=()) -> bool:
        if cam is not None and str(message.channel.id) == str(cam.id):
            return True      # never echo the camera's own channel: that would loop forever
        if str(message.author.id) == str(self.bot.user.id):
            return True      # our own messages (Vector doesn't always flag them as a bot's)
        if message.author.bot and not self.cfg.get("securitycam.include_bots", False):
            return True
        ignore = {str(c).lstrip("#").lower() for c in ignore}
        return bool(ignore & {str(message.channel.id).lower(), str(message.channel.name).lower()})

    # -- the dashboard feed -------------------------------------------------------------

    def remember(self, guild, message) -> None:
        """Keep the message in memory so the web dashboard can show it live. Nothing is written to disk."""
        gid = str(guild.id)
        size = max(int(self.cfg.get("securitycam.feed_size", 300) or 300), 20)
        buf = self.feed.get(gid)
        if buf is None or buf.maxlen != size:
            buf = self.feed[gid] = deque(buf or (), maxlen=size)
        self._seq[gid] = seq = self._seq.get(gid, 0) + 1
        at = getattr(message, "created_at", None) or datetime.datetime.now(datetime.timezone.utc)
        buf.append({"seq": seq, "at": at.timestamp(), "channel_id": str(message.channel.id),
                    "channel": str(getattr(message.channel, "name", "")), "author_id": str(message.author.id),
                    "author": name_of(message.author), "avatar": avatar_url(message.author),
                    "text": (message.content or "")[:2000],
                    "attachments": [str(getattr(a, "filename", "file")) for a in message.attachments[:8]]})

    def recent(self, guild_id: str, after: int = 0, limit: int = 100) -> tuple[list[dict], int]:
        """Messages newer than ``after`` (the last 100 on a first load) and the newest sequence number."""
        rows = [e for e in self.feed.get(str(guild_id), ()) if e["seq"] > after]
        return rows[-max(limit, 1):], self._seq.get(str(guild_id), 0)

    # -- the echo -----------------------------------------------------------------------

    async def echo(self, message, cam) -> None:
        text = message.content or ""
        e = vector.Embed(description=text[:4000] or None)
        e.set_author(name=name_of(message.author), icon_url=avatar_url(message.author))
        e.set_footer(text=f"#{message.channel.name}")
        e.timestamp = getattr(message, "created_at", None) or datetime.datetime.now(datetime.timezone.utc)
        files, extra = [], []
        for att in message.attachments[:MAX_FILES]:
            try:
                if getattr(att, "size", 0) and att.size > MAX_FILE_BYTES:
                    raise ValueError("too big")
                files.append(await att.to_file())
            except Exception:  # noqa: BLE001 - fall back to a link rather than lose the record
                extra.append(f"📎 {att.filename} ({getattr(att, 'url', '') or 'unavailable'})")
        if len(message.attachments) > MAX_FILES:
            extra.append(f"…and {len(message.attachments) - MAX_FILES} more attachments")
        if not text and not message.attachments:
            e.description = "*(empty message)*"
        if extra:
            e.add_field(name="Attachments", value="\n".join(extra), inline=False)
        elif files and not text:
            e.description = f"📎 {len(files)} attachment{'s' if len(files) != 1 else ''}"
        if files and getattr(files[0], "filename", None):
            # pointing the embed at a file makes the SDK post: body, then the files, then the footer
            e.set_image(url=f"attachment://{files[0].filename}")
        await cam.send(embed=e, files=files or None)

    @commands.Cog.listener()
    async def on_message(self, message):
        guild = message.guild
        if guild is None or not self.bot.serves(guild):
            return
        try:
            cam = await self.camera(guild)
            skip = self._ignored(message, cam, await self.ignored_channels(guild))
            if not skip and self.cfg.get("securitycam.dashboard_feed", True):
                self.remember(guild, message)
            if cam is None or skip:
                return
            await self.echo(message, cam)
            st = self.stats.setdefault(str(guild.id), {"echoed": 0, "last": None})
            st["echoed"] += 1
            st["last"] = datetime.datetime.now(datetime.timezone.utc)
        except Exception as exc:  # noqa: BLE001 - the camera must never break other listeners
            log.warning("could not echo a message: %s", exc)

    # -- setup commands -----------------------------------------------------------------

    @commands.group(name="securitycam", aliases=["seccam", "cam"], invoke_without_command=True)
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def securitycam(self, ctx):
        """Show where messages are being echoed."""
        cam = await self.camera(ctx.guild)
        if cam is None:
            return await ctx.send(f"📹 The security cam is off. Turn it on with `{ctx.prefix}securitycam set #channel`.")
        await ctx.send(f"📹 Every message from every channel is echoed to #{cam.name}.")

    @securitycam.command(name="set")
    @commands.has_permissions(manage_guild=True)
    async def cam_set(self, ctx, *, channel: str = ""):
        """Pick the channel that receives the echoes (default: this channel)."""
        target = self.bot.find_channel(ctx.guild, channel) if channel else ctx.channel
        if target is None:
            return await ctx.send(fail(f"I can't find a channel called {channel!r}."))
        await self.settings.set(str(ctx.guild.id), KEY, str(target.id))
        await ctx.send(ok(f"Security cam on. Everything said in this community is echoed to #{target.name}. "
                          "Keep that channel private to staff."))

    @securitycam.command(name="off")
    @commands.has_permissions(manage_guild=True)
    async def cam_off(self, ctx):
        """Stop echoing messages."""
        await self.settings.set(str(ctx.guild.id), KEY, "")
        await ctx.send(ok("Security cam off."))


async def setup(bot):
    await bot.add_cog(SecurityCam(bot))

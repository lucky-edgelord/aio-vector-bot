"""Image guard: polices pictures. A blocklist of known pictures always works; nudity detection is optional."""

from __future__ import annotations

import logging

from vector.ext import commands

from ..imagecheck import Detector, DetectorUnavailable, dhash, open_image
from ..utils.embeds import embed, fail, ok, table
from ..utils.enforce import enforce, exempt

log = logging.getLogger("vectiq.imageguard")

PICTURE = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "heic", "avif"}


def is_picture(att) -> bool:
    ext = (getattr(att, "extension", "") or (att.filename or "").rsplit(".", 1)[-1]).lower().lstrip(".")
    try:
        if att.is_image():
            return True
    except Exception:  # noqa: BLE001
        pass
    return ext in PICTURE


class ImageGuard(commands.Cog, name="ImageGuard"):
    """Removes known bad pictures and, with a detector switched on, nudity."""

    def __init__(self, bot):
        self.bot = bot
        self.store = bot.stores.image_blocks
        self._detector: Detector | None = None
        self._warned: set[str] = set()

    @property
    def cfg(self) -> dict:
        return self.bot.config.get("imageguard", {})

    def detector(self) -> Detector:
        """The configured detector; rebuilt (and its model dropped) when the settings change."""
        key = {k: self.cfg.get(k) for k in ("detector", "nsfw_detector", "sightengine", "http")}
        if self._detector is None or self._detector.cfg_key != key:
            self._detector = Detector(self.cfg)
            self._detector.cfg_key = key
        return self._detector

    async def inspect(self, guild_id: str, data: bytes) -> tuple[str, str] | None:
        """(reason, detail) when the picture must go, else None. Raises nothing for a broken picture."""
        cfg = self.cfg
        if len(data) > float(cfg.get("max_mb", 15)) * 1024 * 1024:
            return None
        try:
            img = open_image(data)
        except Exception:  # noqa: BLE001 - not a picture Pillow can read
            return None
        h = dhash(img)
        if cfg.get("blocklist", True):
            hit = await self.store.match(guild_id, h, int(cfg.get("match_distance", 6)))
            if hit:
                return "that picture isn't allowed here", f"matches blocked picture #{hit['id']} {hit['note']}".strip()
        det = self.detector()
        if det.name == "off":
            return None
        try:
            score, label = await det.score(img)
        except DetectorUnavailable as exc:
            if det.name not in self._warned:
                self._warned.add(det.name)
                log.error("image guard: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001 - a flaky API must not remove pictures
            log.warning("image guard: the %s detector failed: %s", det.name, exc)
            return None
        if score >= float(cfg.get("threshold", 0.7)):
            if cfg.get("remember", True):
                await self.store.add(guild_id, h, f"auto: {label} {score:.2f}", str(self.bot.user.id))
            return "that picture isn't allowed here", f"{det.name}: {label} {score:.2f}"
        return None

    @commands.Cog.listener()
    async def on_message(self, message):
        cfg = self.cfg
        if message.guild is None or not self.bot.serves(message.guild) or not getattr(message, "attachments", None):
            return
        merged = dict(cfg, exempt_channels=list(cfg.get("exempt_channels") or []) + list(cfg.get("allow_channels") or []))
        if exempt(self.bot, message, merged):
            return
        for att in message.attachments:
            if not is_picture(att):
                continue
            try:
                data = await att.read()
            except Exception as exc:  # noqa: BLE001
                log.warning("image guard: couldn't download a picture: %s", exc)
                continue
            hit = await self.inspect(str(message.guild.id), data)
            if hit:
                reason, detail = hit
                await enforce(self.bot, message, source="image guard", reason=reason, detail=detail,
                              action=cfg.get("action", "delete"), timeout_minutes=int(cfg.get("timeout_minutes", 10)))
                return

    # -- commands -------------------------------------------------------------------------

    async def _pictures(self, ctx) -> list[bytes]:
        """Pictures attached to the command, or to the message it replies to."""
        msgs = [ctx.message]
        ref = getattr(ctx.message, "reference", None)
        if ref is not None:
            target = getattr(ref, "resolved", None)
            if target is None and getattr(ref, "message_id", None):
                try:
                    target = await ctx.channel.fetch_message(ref.message_id)
                except Exception:  # noqa: BLE001
                    target = None
            if target is not None:
                msgs.append(target)
        out = []
        for m in msgs:
            for att in getattr(m, "attachments", []) or []:
                if is_picture(att):
                    out.append(await att.read())
        return out

    @commands.group(name="imageguard", aliases=["ig"], invoke_without_command=True)
    @commands.has_permissions(manage_messages=True)
    async def imageguard(self, ctx):
        """Show the image guard's settings."""
        cfg = self.cfg
        n = len(await self.store.list(str(ctx.guild.id)))
        det = cfg.get("detector", "off")
        level = f" (removes at {float(cfg.get('threshold', 0.7)):.2f} and above)" if det != "off" else ""
        text = (f"Detector: **{det}**{level}"
                + f"\nBlocked pictures: **{n}**\nAction: **{cfg.get('action', 'delete')}**\n\n"
                "Reply to a picture with `!imageguard block [note]` to block it, `!imageguard list`, "
                "`!imageguard unblock <id>`, `!imageguard test` (attach or reply to a picture).")
        await ctx.send(embed=embed("Image guard", text))

    @imageguard.command(name="block")
    async def block(self, ctx, *, note: str = ""):
        """Block a picture: attach it, or reply to the message that has it."""
        pics = await self._pictures(ctx)
        if not pics:
            return await ctx.send(fail("Attach a picture or reply to a message that has one."))
        ids = []
        for data in pics:
            try:
                ids.append(await self.store.add(str(ctx.guild.id), dhash(data), note, str(ctx.author.id)))
            except Exception:  # noqa: BLE001
                continue
        await ctx.send(ok(f"Blocked {len(ids)} picture(s): " + ", ".join(f"#{i}" for i in ids)))
        try:
            ref = getattr(ctx.message, "reference", None)
            if ref is not None and getattr(ref, "resolved", None) is not None:
                await ref.resolved.delete()
        except Exception:  # noqa: BLE001
            pass

    @imageguard.command(name="unblock")
    async def unblock(self, ctx, block_id: int):
        """Allow a blocked picture again."""
        done = await self.store.remove(str(ctx.guild.id), block_id)
        await ctx.send(ok(f"Picture #{block_id} is allowed again.") if done else fail(f"No blocked picture #{block_id}."))

    @imageguard.command(name="list")
    async def list_(self, ctx):
        """The blocked pictures."""
        rows = await self.store.list(str(ctx.guild.id))
        if not rows:
            return await ctx.send("No blocked pictures yet.")
        await ctx.send(embed=embed("Blocked pictures", table([(str(r["id"]), r["note"] or "-") for r in rows[:25]],
                                                                 header=("#", "note"))))

    @imageguard.command(name="test")
    async def test(self, ctx):
        """Check a picture without removing anything."""
        pics = await self._pictures(ctx)
        if not pics:
            return await ctx.send(fail("Attach a picture or reply to a message that has one."))
        det = self.detector()
        lines = []
        for data in pics:
            hit = await self.store.match(str(ctx.guild.id), dhash(data), int(self.cfg.get("match_distance", 6)))
            line = f"blocklist: {'#' + str(hit['id']) if hit else 'no match'}"
            if det.name != "off":
                try:
                    score, label = await det.score(open_image(data))
                    line += f" · {det.name}: {label} {score:.2f}"
                except Exception as exc:  # noqa: BLE001
                    line += f" · {det.name}: {exc}"
            lines.append(line)
        await ctx.send("\n".join(lines))


async def setup(bot):
    await bot.add_cog(ImageGuard(bot))

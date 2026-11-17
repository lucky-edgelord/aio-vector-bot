"""One player per community: the voice connection, the queue and what's playing."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .queue import Queue, Track, clock
from .sources import FFmpegStream, ffmpeg_args, stream_url

log = logging.getLogger("vectiq.music")


def bar(position: float, duration: float, width: int = 18) -> str:
    if not duration:
        return "▬" * width
    done = min(width - 1, int(width * position / duration))
    return "▬" * done + "🔘" + "▬" * (width - done - 1)


class Player:
    def __init__(self, cog: Any, guild: Any, vc: Any, text_channel: Any):
        self.cog = cog
        self.guild = guild
        self.vc = vc
        self.text_channel = text_channel
        cfg = cog.cfg
        self.queue = Queue(max_size=int(cfg.get("max_queue", 500)))
        self.volume = int(cfg.get("default_volume", 80))
        self.filter = ""
        self.stay = bool(cfg.get("stay_247", False))
        self.stream: FFmpegStream | None = None
        self.votes: set[str] = set()
        self.idle_since = time.monotonic()
        self.alone_since: float | None = None
        self._gen = 0
        self._lock = asyncio.Lock()

    # -- state -------------------------------------------------------------------------------

    @property
    def current(self) -> Track | None:
        return self.queue.current

    @property
    def position(self) -> float:
        return self.stream.position if self.stream else 0.0

    def playing(self) -> bool:
        return self.current is not None and self.vc is not None and (self.vc.is_playing() or self.vc.is_paused())

    def now_text(self) -> str:
        t = self.current
        if t is None:
            return "Nothing is playing."
        state = "⏸️" if self.vc.is_paused() else "▶️"
        pos = f"{clock(self.position)} / {t.length()}"
        extras = [f"🔊 {self.volume}%"]
        if self.queue.loop != "off":
            extras.append(f"🔁 {self.queue.loop}")
        if self.filter:
            extras.append(f"🎛️ {self.filter}")
        who = f" · added by {t.requester_name}" if t.requester_name else ""
        return (f"{state} **{t.title}**\n{t.url}\n{bar(self.position, t.duration)} `{pos}`\n"
                f"{' · '.join(extras)}{who}")

    # -- playback ----------------------------------------------------------------------------

    async def play_next(self, *, skipped: bool = False) -> Track | None:
        async with self._lock:
            self.votes.clear()
            track = self.queue.advance(skipped=skipped)
            while track is not None:
                try:
                    await self._start(track)
                    return track
                except Exception as exc:  # noqa: BLE001 - skip tracks that won't play
                    log.warning("music: couldn't play %s: %s", track.url, exc)
                    await self._say(f"⚠️ Couldn't play **{track.title}**, skipping it.")
                    track = self.queue.advance(skipped=True)
            self.idle_since = time.monotonic()
            if self.cog.cfg.get("announce", True) and self.queue.history:
                await self._say("✅ The queue is finished. Add more with `play`.")
            return None

    async def _start(self, track: Track, at: float = 0.0) -> None:
        url, headers = await asyncio.to_thread(stream_url, track)
        cfg = self.cog.cfg
        stream = FFmpegStream(ffmpeg_args(url, headers=headers, start=at, filter_name=self.filter,
                                          ffmpeg=str(cfg.get("ffmpeg", "ffmpeg"))), start=at)
        stream.volume = self.volume / 100
        self._gen += 1
        gen = self._gen
        if self.vc.is_playing() or self.vc.is_paused():
            self.vc.stop()
            await asyncio.sleep(0.05)
        self.stream = stream

        async def after(error):
            if error:
                log.warning("music: playback error: %s", error)
            if gen == self._gen:             # not replaced by a seek, a filter change or a skip
                await self.play_next()

        self.vc.play(stream, after=after)
        if at == 0 and cfg.get("announce", True):
            await self._say(f"🎶 Now playing **{track.title}** `{track.length()}`"
                            + (f" · added by {track.requester_name}" if track.requester_name else ""))

    async def skip(self) -> Track | None:
        self._gen += 1                       # the old track's after-callback must not advance again
        return await self.play_next(skipped=True)

    async def restart_at(self, seconds: float) -> None:
        """Play the current track again from ``seconds`` (seek, replay, filters)."""
        if self.current is None:
            return
        async with self._lock:
            await self._start(self.current, at=max(0.0, seconds))

    def set_volume(self, percent: int) -> None:
        self.volume = percent
        if self.stream is not None:
            self.stream.volume = percent / 100

    async def stop(self) -> None:
        self._gen += 1
        self.queue.clear()
        self.queue.current = None
        if self.vc is not None:
            self.vc.stop()
        self.idle_since = time.monotonic()

    async def leave(self) -> None:
        await self.stop()
        if self.vc is not None:
            try:
                await self.vc.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self.vc = None

    async def _say(self, text: str) -> None:
        try:
            await self.text_channel.send(text)
        except Exception:  # noqa: BLE001
            pass

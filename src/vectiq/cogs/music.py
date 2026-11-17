"""Music in voice channels, with the commands people know from the big Discord music bots."""

from __future__ import annotations

import asyncio
import io
import logging
import math
import time

import vector
from vector.ext import commands, tasks

from ..music.player import CONTROLS, Player
from ..music.queue import LOOP_MODES, clock, parse_time
from ..music.sources import FILTERS, MusicUnavailable, search
from ..render.music import queue_card
from ..utils.embeds import embed, fail, name_of, ok

log = logging.getLogger("vectiq.music")


def voice_channel_of(guild, member):
    """The voice channel ``member`` is in, or None."""
    who = str(member.id)
    for ch in getattr(guild, "voice_channels", []):
        try:
            if who in ch.voice_states:
                return ch
        except Exception:  # noqa: BLE001
            continue
    return None


def listeners(vc, bot_id: str) -> list[str]:
    try:
        return [n for n in vc.channel.voice_states if n != bot_id]
    except Exception:  # noqa: BLE001
        return []


class Music(commands.Cog, name="Music"):
    """Play music in voice channels: search or links, a queue, loops, filters and vote-skips."""

    def __init__(self, bot):
        self.bot = bot
        self.players: dict[str, Player] = {}
        self.watch.start()

    async def cog_unload(self):
        self.watch.cancel()
        for p in list(self.players.values()):
            await p.leave()
        self.players.clear()

    async def cog_check(self, ctx):
        if ctx.guild is None:
            raise commands.CheckFailure("Music only works inside a community.")
        return True

    @property
    def cfg(self) -> dict:
        return self.bot.config.get("music", {})

    # -- helpers ---------------------------------------------------------------------------

    def player(self, ctx) -> Player | None:
        p = self.players.get(str(ctx.guild.id))
        return p if p is not None and p.vc is not None else None

    def is_dj(self, ctx, p: Player | None = None) -> bool:
        return self.member_is_dj(ctx.author, p)

    def member_is_dj(self, a, p: Player | None = None) -> bool:
        perms = getattr(a, "guild_permissions", None)
        if perms is not None and (getattr(perms, "manage_channels", False) or getattr(perms, "manage_guild", False)):
            return True
        role = str(self.cfg.get("dj_role", "") or "")
        if not role:
            return True
        if any(r.name.lower() == role.lower() or str(r.id) == role for r in getattr(a, "roles", [])):
            return True
        if p is not None and len(listeners(p.vc, str(self.bot.user.id))) <= 1:
            return True                      # alone with the bot
        return False

    async def need_player(self, ctx, *, dj: bool = False) -> Player | None:
        p = self.player(ctx)
        if p is None:
            await ctx.send(fail("I'm not playing anything. Start with `play <song or link>`."))
            return None
        if voice_channel_of(ctx.guild, ctx.author) is None or \
                str(voice_channel_of(ctx.guild, ctx.author).id) != str(p.vc.channel.id):
            await ctx.send(fail(f"Join #{p.vc.channel.name} first."))
            return None
        if dj and not self.is_dj(ctx, p):
            await ctx.send(fail(f"Only DJs can do that (the **{self.cfg.get('dj_role')}** role, or staff)."))
            return None
        return p

    async def connect(self, ctx) -> Player | None:
        ch = voice_channel_of(ctx.guild, ctx.author)
        if ch is None:
            await ctx.send(fail("Join a voice channel first."))
            return None
        p = self.player(ctx)
        if p is not None:
            if str(p.vc.channel.id) != str(ch.id):
                if p.playing() and not self.is_dj(ctx, p):
                    await ctx.send(fail(f"I'm already playing in #{p.vc.channel.name}."))
                    return None
                await p.vc.move_to(ch)
            p.text_channel = ctx.channel
            return p
        try:
            vc = await ch.connect()
        except Exception as exc:  # noqa: BLE001
            await ctx.send(fail(f"I couldn't join #{ch.name}: {exc}"))
            return None
        p = Player(self, ctx.guild, vc, ctx.channel)
        self.players[str(ctx.guild.id)] = p
        return p

    async def find(self, ctx, query: str, *, limit: int = 1):
        cfg = self.cfg
        try:
            tracks = await asyncio.to_thread(
                search, query.strip("<>"), limit=limit, playlist=bool(cfg.get("allow_playlists", True)),
                max_playlist=int(cfg.get("max_playlist", 100)), site=str(cfg.get("search", "ytsearch")),
                requester=str(ctx.author.id), requester_name=name_of(ctx.author),
                cookies=str(cfg.get("cookies_file", "") or ""))
        except MusicUnavailable as exc:
            await ctx.send(fail(str(exc)))
            return None
        except Exception as exc:  # noqa: BLE001
            await ctx.send(fail(f"I couldn't find that: {str(exc)[:200]}"))
            return None
        limit_s = int(cfg.get("max_track_minutes", 0) or 0) * 60
        if limit_s:
            tracks = [t for t in tracks if t.live or not t.duration or t.duration <= limit_s]
        if not tracks:
            await ctx.send(fail("Nothing found."))
            return None
        return tracks

    async def enqueue(self, ctx, query: str, *, front: bool = False):
        p = await self.connect(ctx)
        if p is None:
            return
        tracks = await self.find(ctx, query)
        if not tracks:
            return
        added = p.queue.add(tracks, front=front)
        if added == 0:
            return await ctx.send(fail(f"The queue is full ({p.queue.max_size} tracks)."))
        if p.current is None:
            await p.play_next()
        elif added == 1:
            where = "next" if front else f"#{len(p.queue) if not front else 1}"
            await ctx.send(ok(f"Queued **{tracks[0].title}** `{tracks[0].length()}` ({where})."))
        if added > 1:
            await ctx.send(ok(f"Queued {added} tracks" + (f" (the queue is full, {len(tracks) - added} left out)"
                                                         if added < len(tracks) else "") + "."))

    # -- playing ---------------------------------------------------------------------------

    @commands.command(aliases=["p"])
    async def play(self, ctx, *, query: str = ""):
        """Play a song: search words, or a YouTube, SoundCloud, Bandcamp or audio link (playlists too)."""
        if not query:
            return await ctx.send("What should I play? `play <song name or link>`. Mini games are `game <name>`.")
        await self.enqueue(ctx, query)

    @commands.command(aliases=["pn", "playtop"])
    async def playnext(self, ctx, *, query: str):
        """Put a song at the front of the queue."""
        if self.player(ctx) is not None and not self.is_dj(ctx, self.player(ctx)):
            return await ctx.send(fail("Only DJs can jump the queue."))
        await self.enqueue(ctx, query, front=True)

    @commands.command(name="search", aliases=["find"])
    async def search_(self, ctx, *, query: str):
        """Show the top results and pick one by typing its number."""
        tracks = await self.find(ctx, query, limit=5)
        if not tracks:
            return
        lines = [f"`{i}.` **{t.title}** `{t.length()}` · {t.uploader}" for i, t in enumerate(tracks, 1)]
        await ctx.send(embed=embed("Pick a track", "\n".join(lines) + "\n\nType a number, or `cancel`."))

        def check(m):
            return str(m.author.id) == str(ctx.author.id) and str(m.channel.id) == str(ctx.channel.id)

        try:
            reply = await self.bot.wait_for("message", check=check, timeout=30)
        except asyncio.TimeoutError:
            return await ctx.send("Search closed.")
        pick = (reply.content or "").strip()
        if not pick.isdigit() or not 1 <= int(pick) <= len(tracks):
            return await ctx.send("Search closed.")
        p = await self.connect(ctx)
        if p is None:
            return
        p.queue.add([tracks[int(pick) - 1]])
        if p.current is None:
            await p.play_next()
        else:
            await ctx.send(ok(f"Queued **{tracks[int(pick) - 1].title}**."))

    @commands.command()
    async def join(self, ctx):
        """Join your voice channel."""
        p = await self.connect(ctx)
        if p is not None:
            await ctx.send(ok(f"Joined #{p.vc.channel.name}."))

    @commands.command(aliases=["dc", "disconnect", "stop"])
    async def leave(self, ctx):
        """Stop, clear the queue and leave the voice channel."""
        p = await self.need_player(ctx, dj=True)
        if p is None:
            return
        await p.leave()
        self.players.pop(str(ctx.guild.id), None)
        await ctx.send("👋 Bye!")

    @commands.command()
    async def pause(self, ctx):
        """Pause."""
        p = await self.need_player(ctx, dj=True)
        if p is not None and p.vc.is_playing():
            p.vc.pause()
            await ctx.send("⏸️ Paused. `resume` to carry on.")

    @commands.command(aliases=["unpause"])
    async def resume(self, ctx):
        """Carry on after pause."""
        p = await self.need_player(ctx, dj=True)
        if p is not None and p.vc.is_paused():
            p.vc.resume()
            await ctx.send("▶️ Playing.")

    @commands.command(aliases=["s", "next"])
    async def skip(self, ctx):
        """Skip the song. DJs and whoever added it skip at once; others vote."""
        p = await self.need_player(ctx)
        if p is None or p.current is None:
            return
        if self.is_dj(ctx, p) or str(ctx.author.id) == p.current.requester:
            title = p.current.title
            await p.skip()
            return await ctx.send(f"⏭️ Skipped **{title}**.")
        p.votes.add(str(ctx.author.id))
        need = max(1, math.ceil(len(listeners(p.vc, str(self.bot.user.id))) * float(self.cfg.get("vote_skip_ratio", 0.5))))
        if len(p.votes) >= need:
            title = p.current.title
            await p.skip()
            return await ctx.send(f"⏭️ Vote passed, skipped **{title}**.")
        await ctx.send(f"🗳️ Skip vote {len(p.votes)}/{need}.")

    @commands.command(aliases=["fs"])
    async def forceskip(self, ctx):
        """Skip without a vote (DJs)."""
        p = await self.need_player(ctx, dj=True)
        if p is not None and p.current is not None:
            title = p.current.title
            await p.skip()
            await ctx.send(f"⏭️ Skipped **{title}**.")

    @commands.command(aliases=["st", "jump"])
    async def skipto(self, ctx, position: int):
        """Jump to a song in the queue."""
        p = await self.need_player(ctx, dj=True)
        if p is None:
            return
        try:
            p.queue.skip_to(position)
        except IndexError:
            return await ctx.send(fail(f"The queue has {len(p.queue)} songs."))
        await p.skip()

    @commands.command(aliases=["previous", "prev"])
    async def back(self, ctx):
        """Play the previous song again."""
        p = await self.need_player(ctx, dj=True)
        if p is None:
            return
        if p.queue.back() is None:
            return await ctx.send(fail("There's no previous song."))
        await p.skip()

    @commands.command(aliases=["restart"])
    async def replay(self, ctx):
        """Start the song from the beginning."""
        p = await self.need_player(ctx, dj=True)
        if p is not None:
            await p.restart_at(0)
            await ctx.send("⏮️ From the top.")

    @commands.command()
    async def seek(self, ctx, to: str):
        """Jump to a time: `seek 1:30`, `seek 90`, `seek +30`, `seek -10`."""
        p = await self.need_player(ctx, dj=True)
        if p is None or p.current is None:
            return
        if p.current.live:
            return await ctx.send(fail("You can't seek in a live stream."))
        try:
            rel = to[0] in "+-"
            secs = parse_time(to.lstrip("+-"))
            target = p.position + (secs if to[0] == "+" else -secs) if rel else secs
        except (ValueError, IndexError):
            return await ctx.send(fail("Give a time like 1:30, 90 or +30."))
        if p.current.duration and target >= p.current.duration:
            return await ctx.send(fail(f"The song is only {p.current.length()} long."))
        await p.restart_at(target)
        await ctx.send(f"⏩ {clock(target)}")

    # -- the queue -------------------------------------------------------------------------

    @commands.command(aliases=["np", "current"])
    async def nowplaying(self, ctx):
        """What's playing: a card with the cover, a progress bar and control buttons."""
        p = self.player(ctx)
        if p is None or p.current is None:
            return await ctx.send("Nothing is playing.")
        await p.announce(ctx.channel)

    async def send_queue(self, channel, p: Player, page: int = 1) -> None:
        pages = max(1, math.ceil(len(p.queue) / 10))
        page = min(max(1, page), pages)
        rows = p.queue.page(page)
        if self.cfg.get("cards", True):
            try:
                cards = await asyncio.gather(*(p.card_track(t) for _, t in rows))
                current = await p.card_track(p.current) if p.current else None
                png = await asyncio.to_thread(queue_card, current, p.state(), list(zip([n for n, _ in rows], cards, strict=True)),
                                              page=page, pages=pages, community=getattr(p.guild, "name", ""))
                more = f" `queue {page + 1}` for more." if page < pages else ""
                await channel.send(f"📜 Queue: {len(p.queue)} songs · {clock(p.queue.total_seconds())}.{more}",
                                   file=vector.File(io.BytesIO(png), filename="queue.png"))
                return
            except Exception:  # noqa: BLE001 - fall back to text
                log.exception("music: couldn't draw the queue card")
        lines = [f"`{i}.` **{t.title}** `{t.length()}` · {t.requester_name}" for i, t in rows]
        head = f"**Now:** {p.current.title} `{clock(p.position)}/{p.current.length()}`\n\n" if p.current else ""
        foot = (f"\n\n{len(p.queue)} songs · {clock(p.queue.total_seconds())} · loop {p.queue.loop}"
                + (f" · page {page}/{pages}" if pages > 1 else ""))
        await channel.send(embed=embed("Queue", head + ("\n".join(lines) or "Nothing up next.") + foot))

    @commands.command(aliases=["q"])
    async def queue(self, ctx, page: int = 1):
        """The queue as a card, ten songs per page."""
        p = self.player(ctx)
        if p is None or (p.current is None and not len(p.queue)):
            return await ctx.send("The queue is empty.")
        await self.send_queue(ctx.channel, p, page)

    @commands.command(aliases=["rm"])
    async def remove(self, ctx, position: int):
        """Take a song out of the queue."""
        p = await self.need_player(ctx)
        if p is None:
            return
        try:
            t = p.queue.tracks[position - 1]
        except IndexError:
            return await ctx.send(fail(f"The queue has {len(p.queue)} songs."))
        if not self.is_dj(ctx, p) and t.requester != str(ctx.author.id):
            return await ctx.send(fail("You can only remove songs you added."))
        p.queue.remove(position)
        await ctx.send(ok(f"Removed **{t.title}**."))

    @commands.command(aliases=["mv"])
    async def move(self, ctx, src: int, dest: int):
        """Move a song in the queue: `move 5 1`."""
        p = await self.need_player(ctx, dj=True)
        if p is None:
            return
        try:
            t = p.queue.move(src, dest)
        except IndexError:
            return await ctx.send(fail(f"The queue has {len(p.queue)} songs."))
        await ctx.send(ok(f"Moved **{t.title}** to #{dest}."))

    @commands.command()
    async def shuffle(self, ctx):
        """Shuffle the queue."""
        p = await self.need_player(ctx, dj=True)
        if p is not None:
            p.queue.shuffle()
            await ctx.send("🔀 Shuffled.")

    @commands.command(name="clearqueue", aliases=["cq"])
    async def clearqueue(self, ctx):
        """Empty the queue (the current song keeps playing)."""
        p = await self.need_player(ctx, dj=True)
        if p is not None:
            await ctx.send(ok(f"Cleared {p.queue.clear()} songs."))

    @commands.command(aliases=["dedupe"])
    async def removedupes(self, ctx):
        """Remove songs that are in the queue twice."""
        p = await self.need_player(ctx, dj=True)
        if p is not None:
            await ctx.send(ok(f"Removed {p.queue.dedupe()} duplicates."))

    @commands.command()
    async def leavecleanup(self, ctx):
        """Remove songs added by people who left the voice channel."""
        p = await self.need_player(ctx, dj=True)
        if p is None:
            return
        here = set(listeners(p.vc, str(self.bot.user.id)))
        n = sum(p.queue.remove_by(r) for r in {t.requester for t in p.queue.tracks} if r and r not in here)
        await ctx.send(ok(f"Removed {n} songs."))

    @commands.command(aliases=["repeat", "l"])
    async def loop(self, ctx, mode: str = ""):
        """Loop: `loop track`, `loop queue` or `loop off` (no word: cycle through them)."""
        p = await self.need_player(ctx, dj=True)
        if p is None:
            return
        mode = mode.lower() or LOOP_MODES[(LOOP_MODES.index(p.queue.loop) + 1) % len(LOOP_MODES)]
        if mode in ("song", "one", "single"):
            mode = "track"
        if mode in ("all",):
            mode = "queue"
        if mode not in LOOP_MODES:
            return await ctx.send(fail("Use `loop off`, `loop track` or `loop queue`."))
        p.queue.loop = mode
        await ctx.send(f"🔁 Loop: **{mode}**")

    @commands.command(aliases=["vol", "v"])
    async def volume(self, ctx, percent: int | None = None):
        """Set the volume: `volume 60`."""
        p = await self.need_player(ctx, dj=percent is not None)
        if p is None:
            return
        if percent is None:
            return await ctx.send(f"🔊 {p.volume}%")
        top = int(self.cfg.get("max_volume", 150))
        if not 0 <= percent <= top:
            return await ctx.send(fail(f"Pick 0 to {top}."))
        p.set_volume(percent)
        await ctx.send(f"🔊 {percent}%")

    @commands.command(aliases=["fx", "effect"])
    async def filter(self, ctx, name: str = ""):
        """Audio filters: `filter bassboost`, `filter nightcore`, `filter off`. No name lists them."""
        if not name:
            return await ctx.send("Filters: " + ", ".join(f"`{f}`" for f in FILTERS) + ", `off`")
        p = await self.need_player(ctx, dj=True)
        if p is None:
            return
        name = name.lower()
        if name not in FILTERS and name not in ("off", "none", "clear"):
            return await ctx.send(fail("Unknown filter. Try: " + ", ".join(FILTERS)))
        p.filter = "" if name in ("off", "none", "clear") else name
        if p.current is not None and not p.current.live:
            await p.restart_at(p.position)
        await ctx.send(f"🎛️ Filter: **{p.filter or 'off'}**")

    @commands.command(name="247", aliases=["stay", "24/7"])
    async def stay(self, ctx):
        """Stay in the voice channel even when it's empty or the queue ends."""
        p = await self.need_player(ctx, dj=True)
        if p is not None:
            p.stay = not p.stay
            await ctx.send(f"🌙 24/7 mode is **{'on' if p.stay else 'off'}**.")

    # -- control buttons -------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        await self.press(payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        await self.press(payload)       # reactions toggle, so taking one back presses the button again

    async def press(self, payload) -> None:
        if not payload.guild_id or str(payload.user_id) == str(self.bot.user.id):
            return
        p = self.players.get(str(payload.guild_id))
        if p is None or p.vc is None or p.np_message is None or str(p.np_message.id) != str(payload.message_id):
            return
        action = CONTROLS.get(str(payload.emoji).replace("\ufe0f", ""))
        if action is None:
            return
        member = payload.member or (p.guild.get_member(str(payload.user_id)) if hasattr(p.guild, "get_member") else None)
        if member is None:
            return
        here = voice_channel_of(p.guild, member)
        if here is None or str(here.id) != str(p.vc.channel.id):
            return
        who = name_of(member)
        if action == "queue":
            return await self.send_queue(p.text_channel, p)
        if action == "skip":
            if p.current is None:
                return
            if self.member_is_dj(member, p) or str(member.id) == p.current.requester:
                title = p.current.title
                await p.skip()
                return await p._say(f"⏭️ {who} skipped **{title}**.")
            p.votes.add(str(member.id))
            need = max(1, math.ceil(len(listeners(p.vc, str(self.bot.user.id)))
                                    * float(self.cfg.get("vote_skip_ratio", 0.5))))
            if len(p.votes) >= need:
                await p.skip()
                return await p._say("⏭️ Vote passed, skipped.")
            return await p._say(f"🗳️ Skip vote {len(p.votes)}/{need}.")
        if not self.member_is_dj(member, p):
            return
        if action == "pause":
            if p.vc.is_paused():
                p.vc.resume()
                await p._say(f"▶️ {who} resumed.")
            elif p.vc.is_playing():
                p.vc.pause()
                await p._say(f"⏸️ {who} paused.")
        elif action == "stop":
            await p.leave()
            self.players.pop(str(payload.guild_id), None)
            await p._say(f"⏹️ {who} stopped the music. Bye!")
        elif action == "loop":
            p.queue.loop = LOOP_MODES[(LOOP_MODES.index(p.queue.loop) + 1) % len(LOOP_MODES)]
            await p._say(f"🔁 Loop: **{p.queue.loop}**")
        elif action == "shuffle":
            p.queue.shuffle()
            await p._say(f"🔀 {who} shuffled the queue.")

    # -- leaving on its own ----------------------------------------------------------------

    @tasks.loop(seconds=15)
    async def watch(self):
        now = time.monotonic()
        cfg = self.cfg
        for gid, p in list(self.players.items()):
            if p.vc is None or not p.vc.is_connected():
                self.players.pop(gid, None)
                continue
            if p.stay:
                continue
            alone = not listeners(p.vc, str(self.bot.user.id))
            p.alone_since = (p.alone_since or now) if alone else None
            idle = p.current is None
            if alone and now - p.alone_since >= float(cfg.get("leave_when_alone_seconds", 60)):
                await p._say("👋 Everyone left, so I did too.")
            elif idle and now - p.idle_since >= float(cfg.get("leave_when_idle_seconds", 300)):
                await p._say("👋 Nothing to play, so I'm heading out.")
            else:
                continue
            await p.leave()
            self.players.pop(gid, None)


async def setup(bot):
    await bot.add_cog(Music(bot))

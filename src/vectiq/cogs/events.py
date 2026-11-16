"""The event calendar: scheduled events with RSVPs, reminders, repeats, attendee roles and calendar files."""

from __future__ import annotations

import asyncio
import calendar as pycal
import datetime as dt
import io
import logging
import re
import time
from pathlib import Path

import vector
from vector.ext import commands, tasks

from ..render import Slot, calendar_card, event_card
from ..stores.events import Attendees, Event
from ..utils.embeds import embed, fail, name_of, ok
from ..utils.ics import calendar_file
from ..utils.when import REPEATS, UTC, WhenError, fmt_relative, fmt_span, fmt_when, next_occurrence, parse_span, parse_when, zone

log = logging.getLogger("vectiq.events")

GOING, MAYBE, NO = "✅", "🤔", "❌"
EMOJI = {GOING: "going", MAYBE: "maybe", NO: "no"}
TZ_KEY = "events:timezone"
SHOW_NAMES = 15
IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}
MAX_IMAGE = 8_000_000
BANNER_FIELDS = ("title", "when", "length", "location", "repeat", "image")   # changing these redraws the banner
FIELDS = ("title", "when", "length", "description", "location", "repeat", "remind", "capacity", "channel", "image")


class EventError(ValueError):
    pass


def parse_remind(text: str) -> list[int]:
    """``1h, 15m`` -> [60, 15] (minutes before the start). ``none`` -> []."""
    text = text.strip().lower()
    if text in ("", "none", "off", "no"):
        return []
    out = []
    for part in re.split(r"[,\s]+", text):
        if part:
            try:
                out.append(max(1, parse_span(part) // 60))
            except WhenError as exc:
                raise EventError(str(exc)) from None
    if any(m > 60 * 24 * 14 for m in out):
        raise EventError("reminders can be at most 14 days before")
    return sorted(set(out), reverse=True)


def occurrences(event: Event, start: int, end: int, tz, limit: int = 100) -> list[tuple[int, int]]:
    """Every (start, end) of ``event`` that touches [start, end). Repeating events are expanded forward."""
    length = event.ends_at - event.starts_at
    out, s = [], event.start
    for _ in range(limit if event.repeat != "none" else 1):
        st = int(s.timestamp())
        if st >= end:
            break
        if st + length > start:
            out.append((st, st + length))
        if event.repeat == "none":
            break
        s = next_occurrence(s, event.repeat, tz)
    return out


class Events(commands.Cog, name="Events"):
    """A community event calendar: RSVPs, reminders, repeats, a month view and calendar files."""

    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.config
        self.store = bot.stores.events
        self._pending: dict[int, asyncio.Task] = {}
        self.watch.start()

    async def cog_unload(self):
        self.watch.cancel()
        for t in self._pending.values():
            t.cancel()

    async def cog_check(self, ctx):
        if ctx.guild is None:
            raise commands.CheckFailure("Events work inside a community.")
        return True

    # -- settings ---------------------------------------------------------------------------

    async def tz_name(self, guild) -> str:
        return await self.bot.stores.settings.get(str(guild.id), TZ_KEY, "") or self.cfg.get("events.timezone", "UTC")

    async def tz(self, guild):
        try:
            return zone(await self.tz_name(guild))
        except WhenError:
            return zone("UTC")

    def may_manage(self, member) -> bool:
        perms = getattr(member, "guild_permissions", None)
        return bool(perms and (perms.manage_messages or perms.manage_guild or perms.administrator))

    def may_create(self, member) -> bool:
        return self.cfg.get("events.who_can_create", "staff") == "everyone" or self.may_manage(member)

    def may_edit(self, member, event: Event) -> bool:
        return self.may_manage(member) or str(member.id) == event.creator_id

    # -- the event post ---------------------------------------------------------------------

    def _names(self, guild, ids: list[str]) -> str:
        if not ids:
            return "-"
        shown = []
        for uid in ids[:SHOW_NAMES]:
            m = guild.get_member(uid) if guild else None
            shown.append(m.mention if m else uid[:12] + "…")
        more = len(ids) - SHOW_NAMES
        return ", ".join(shown) + (f" and {more} more" if more > 0 else "")

    async def render(self, event: Event, guild, att: Attendees | None = None) -> vector.Embed:
        tz = zone(event.tz) if event.tz else await self.tz(guild)
        att = att or await self.store.attendees(event)
        badge = {"live": " · 🔴 happening now", "ended": " · ended", "cancelled": " · ❌ cancelled"}.get(event.status, "")
        when = fmt_when(event.start, event.end, tz)
        if event.status == "scheduled":
            when += f"\n{fmt_relative(event.start)}"
        elif event.status == "live":
            when += f"\nends {fmt_relative(event.end)}"
        e = embed(f"📅 {event.title}{badge}", event.description or "")
        e.add_field(name="When", value=when, inline=False)
        if event.location:
            e.add_field(name="Where", value=event.location, inline=True)
        if event.repeat != "none":
            e.add_field(name="Repeats", value=event.repeat, inline=True)
        host = guild.get_member(event.creator_id) if guild else None
        e.add_field(name="Host", value=host.mention if host else event.creator_id[:12] + "…", inline=True)
        cap = f"/{event.capacity}" if event.capacity else ""
        e.add_field(name=f"{GOING} Going ({len(att.going)}{cap})", value=self._names(guild, att.going), inline=False)
        if att.waitlist:
            e.add_field(name=f"⏳ Waitlist ({len(att.waitlist)})", value=self._names(guild, att.waitlist), inline=False)
        e.add_field(name=f"{MAYBE} Maybe ({len(att.maybe)})", value=self._names(guild, att.maybe), inline=True)
        e.add_field(name=f"{NO} Can't go ({len(att.no)})", value=str(len(att.no)), inline=True)
        tail = f" · react {GOING} going · {MAYBE} maybe · {NO} can't go" if event.open else ""
        e.set_footer(text=f"Event #{event.id}{tail}")
        e.timestamp = event.start                          # shown in each reader's own local time
        return e

    # -- the banner image -------------------------------------------------------------------

    def image_dir(self) -> Path:
        return Path(self.cfg.data_dir) / "event-images"

    async def save_image(self, event: Event, data: bytes, ext: str) -> Event:
        """Keep a picture someone attached; it's posted above the event instead of the drawn banner."""
        folder = self.image_dir()
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob(f"{event.id}.*"):
            old.unlink(missing_ok=True)
        path = folder / f"{event.id}.{ext}"
        await asyncio.to_thread(path.write_bytes, data)
        return await self.store.update(event.id, image_path=path.name)

    async def drop_image(self, event: Event) -> Event:
        for old in self.image_dir().glob(f"{event.id}.*"):
            old.unlink(missing_ok=True)
        return await self.store.update(event.id, image_path="")

    async def banner(self, event: Event, guild) -> vector.File | None:
        if event.image_path:
            path = self.image_dir() / event.image_path
            if path.exists():
                return vector.File(str(path), filename=f"event-{event.id}{path.suffix}")
        if not self.cfg.get("events.banner_image", True):
            return None
        tz = zone(event.tz)
        s = event.start.astimezone(tz)
        day = f"{s:%b} {s.day} {s:%a}"
        span = fmt_when(event.start, event.end, tz).split(" · ", 1)[1]
        host = guild.get_member(event.creator_id) if guild else None
        try:
            png = await asyncio.to_thread(event_card, event.title, day, span, location=event.location,
                                          host=name_of(host) if host else "", community=getattr(guild, "name", ""),
                                          repeat=event.repeat, tz_label=tz.key)
        except Exception:  # noqa: BLE001 - the event still posts without a picture
            log.exception("event banner")
            return None
        return vector.File(io.BytesIO(png), filename=f"event-{event.id}.png")

    @staticmethod
    async def image_from(message) -> tuple[bytes, str] | None:
        """The first picture attached to a command message, or None."""
        for att in getattr(message, "attachments", None) or []:
            ext = IMAGE_TYPES.get((getattr(att, "content_type", "") or "").split(";")[0].lower())
            if ext is None:
                name = (getattr(att, "filename", "") or "").lower()
                ext = next((v for v in IMAGE_TYPES.values() if name.endswith("." + v) or
                            (v == "jpg" and name.endswith(".jpeg"))), None)
            if ext is None:
                continue
            if (getattr(att, "size", 0) or 0) > MAX_IMAGE:
                raise EventError("that picture is too big (8 MB max)")
            return await att.read(), ext
        return None

    # -- posting ----------------------------------------------------------------------------

    def default_channel(self, guild, fallback=None):
        """``events.channel`` from config.yaml: an exact name or id, else the first channel whose name contains it
        ("announcements" finds "📣┊Announcements")."""
        ref = str(self.cfg.get("events.channel", "announcements") or "").strip()
        if not ref:
            return fallback
        found = self.bot.find_channel(guild, ref)
        if found is None:
            want = "".join(ch for ch in ref.lower() if ch.isalnum())
            found = next((c for c in guild.text_channels
                          if want and want in "".join(ch for ch in c.name.lower() if ch.isalnum())), None)
        return found or fallback

    async def unposted(self, event: Event) -> Event:
        return await self.store.update(event.id, message_id=None, image_message_id=None, footer_message_id=None)

    async def post(self, event: Event, channel) -> Event:
        """Three messages, like any embed with a picture: the details, the picture, then the footer.
        The details are edited as people RSVP; the reactions sit on the footer, right under the picture."""
        e = await self.render(event, channel.guild)
        body = await channel.send(e.to_markdown(part="body"))
        image_id = None
        pic = await self.banner(event, channel.guild)
        if pic is not None:
            try:
                image_id = str((await channel.send(file=pic)).id)
            except Exception as exc:  # noqa: BLE001
                log.warning("could not post the event picture: %s", exc)
        foot = await channel.send(e.to_markdown(part="footer"))
        event = await self.store.update(event.id, message_id=str(body.id), image_message_id=image_id,
                                        footer_message_id=str(foot.id), channel_id=str(channel.id))
        for emoji in (GOING, MAYBE, NO):
            try:
                await foot.add_reaction(emoji)
            except Exception:  # noqa: BLE001
                pass
        return event

    async def refresh(self, event: Event) -> None:
        """Bring the event post up to date (edits it in place; reposts if it's gone)."""
        guild = self.bot.get_guild(event.guild_id)
        ch = guild.get_channel(event.channel_id) if guild else None
        if ch is None:
            return
        async def fetch(mid):
            try:
                return await ch.fetch_message(mid) if mid else None
            except Exception:  # noqa: BLE001
                return None
        body = await fetch(event.message_id)
        try:
            if body is None:
                if event.open:
                    await self.post(event, ch)
                return
            e = await self.render(event, guild)
            await body.edit(content=e.to_markdown(part="body"))
            foot = await fetch(event.footer_message_id)
            text = e.to_markdown(part="footer")
            if foot is not None and (foot.content or "") != text:
                await foot.edit(content=text)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not update event #%s: %s", event.id, exc)

    def refresh_soon(self, event_id: int, delay: float = 2.0) -> None:
        """Batch a burst of RSVPs into one edit."""
        if (t := self._pending.get(event_id)) and not t.done():
            return

        async def later():
            await asyncio.sleep(delay)
            self._pending.pop(event_id, None)
            if (e := await self.store.get(event_id)) is not None:
                await self.refresh(e)
        self._pending[event_id] = asyncio.ensure_future(later())

    # -- creating and changing (shared with the dashboard) ----------------------------------

    async def create(self, guild, channel, host, title: str, start: dt.datetime, length: int, *,
                     description: str = "", location: str = "", repeat: str = "none", remind: list[int] | None = None,
                     capacity: int = 0, image: tuple[bytes, str] | None = None) -> Event:
        title = title.strip()[:120]
        if not title:
            raise EventError("give the event a title")
        if start.timestamp() < time.time() - 60:
            raise EventError("that time has already passed")
        if not 60 <= length <= 14 * 86400:
            raise EventError("an event lasts between 1 minute and 14 days")
        if repeat not in REPEATS:
            raise EventError(f"repeat must be one of: {', '.join(REPEATS)}")
        if self.cfg.get("events.max_per_community", 200) <= len(await self.store.upcoming(str(guild.id), 1000)):
            raise EventError("this community has too many upcoming events")
        if remind is None:
            remind = [int(m) for m in self.cfg.get("events.reminders", [60, 15]) if str(m).strip().isdigit()]
        reminders = remind
        tzname = await self.tz_name(guild)
        role_id = ""
        if self.cfg.get("events.attendee_roles", False):
            try:
                role = await guild.create_role(name=f"🎟 {title}"[:90], reason=f"event: {title}")
                role_id = str(role.id)
            except Exception as exc:  # noqa: BLE001 - the event still works without a role
                log.warning("could not create an attendee role: %s", exc)
        event = await self.store.create(str(guild.id), str(channel.id), str(host.id), title, int(start.timestamp()),
                                        int(start.timestamp()) + length, tz=tzname, description=description[:2000],
                                        location=location[:200], repeat=repeat,
                                        remind=list(reminders), capacity=max(0, int(capacity)), role_id=role_id)
        if image is not None:
            event = await self.save_image(event, *image)
        event = await self.post(event, channel)
        self.bot.emit(guild, "events", f"Event #{event.id}: {title}", fmt_when(event.start, event.end, await self.tz(guild)))
        return event

    async def change(self, guild, event: Event, field: str, value: str) -> Event:
        """Edit one thing about an event. ``field`` is one of FIELDS."""
        tz = zone(event.tz)
        value = value.strip()
        field = {"name": "title", "time": "when", "start": "when", "duration": "length", "desc": "description",
                 "where": "location", "place": "location", "reminders": "remind", "cap": "capacity",
                 "limit": "capacity", "picture": "image"}.get(field.lower(), field.lower())
        if field == "title":
            if not value:
                raise EventError("a title can't be empty")
            changes = {"title": value[:120]}
        elif field == "when":
            try:
                start = parse_when(value, tz)
            except WhenError as exc:
                raise EventError(str(exc)) from None
            length = event.ends_at - event.starts_at
            changes = {"starts_at": int(start.timestamp()), "ends_at": int(start.timestamp()) + length,
                       "status": "scheduled" if event.status in ("live", "ended") else event.status}
        elif field == "length":
            try:
                secs = parse_span(value)
            except WhenError as exc:
                raise EventError(str(exc)) from None
            changes = {"ends_at": event.starts_at + secs}
        elif field == "description":
            changes = {"description": "" if value.lower() == "none" else value[:2000]}
        elif field == "location":
            changes = {"location": "" if value.lower() == "none" else value[:200]}
        elif field == "repeat":
            value = value.lower().replace("every ", "").replace("fortnightly", "biweekly").replace("never", "none")
            value = {"day": "daily", "week": "weekly", "month": "monthly", "2 weeks": "biweekly"}.get(value, value)
            if value not in REPEATS:
                raise EventError(f"repeat must be one of: {', '.join(REPEATS)}")
            changes = {"repeat": value}
        elif field == "remind":
            changes = {"remind": parse_remind(value)}
        elif field == "capacity":
            if not value.isdigit():
                raise EventError("capacity is a number (0 = no limit)")
            changes = {"capacity": int(value)}
        elif field == "channel":
            ch = self.bot.find_channel(guild, value)
            if ch is None:
                raise EventError(f"no channel called {value!r}")
            await self._delete_post(event)
            event = await self.store.update(event.id, channel_id=str(ch.id), message_id=None)
            return await self.post(event, ch)
        elif field == "image":
            if value.lower() not in ("none", "default", "banner", "reset"):
                raise EventError("attach a picture to the command, or say `image none` to go back to the drawn banner")
            event = await self.drop_image(event)
            changes = {}
        else:
            raise EventError(f"you can change: {', '.join(FIELDS)}")
        event = await self.store.update(event.id, **changes)
        if field in BANNER_FIELDS and event.open:
            await self._delete_post(event)                 # the picture shows these, so post afresh
            ch = guild.get_channel(event.channel_id)
            if ch is not None:
                return await self.post(await self.unposted(event), ch)
        await self.refresh(event)
        return event

    async def cancel(self, guild, event: Event, by, reason: str = "") -> Event:
        att = await self.store.attendees(event)
        event = await self.store.update(event.id, status="cancelled")
        await self.refresh(event)
        await self.announce(guild, event, f"❌ {event.title} is cancelled", reason or "")
        await self.dm(guild, att.going + att.waitlist + att.maybe,
                      f"❌ **{event.title}** in {guild.name} has been cancelled" + (f": {reason}" if reason else "."))
        await self._drop_role(guild, event, delete=True)
        self.bot.emit(guild, "events", f"Event #{event.id} cancelled", f"{event.title} · by {name_of(by)}")
        return event

    async def remove(self, guild, event: Event) -> None:
        await self._delete_post(event)
        await self.drop_image(event)
        await self._drop_role(guild, event, delete=True)
        await self.store.delete(event.id)

    async def _delete_post(self, event: Event) -> None:
        guild = self.bot.get_guild(event.guild_id)
        ch = guild.get_channel(event.channel_id) if guild else None
        if ch is None:
            return
        for mid in (event.message_id, event.image_message_id, event.footer_message_id):
            if not mid:
                continue
            try:
                await (await ch.fetch_message(mid)).delete()
            except Exception:  # noqa: BLE001
                pass

    async def set_rsvp(self, guild, event: Event, user_id: str, status: str | None) -> Attendees:
        await self.store.rsvp(event.id, user_id, status)
        att = await self.store.attendees(event)
        await self._sync_role(guild, event, att)
        self.refresh_soon(event.id)
        return att

    # -- attendee roles ---------------------------------------------------------------------

    async def _sync_role(self, guild, event: Event, att: Attendees) -> None:
        role = guild.get_role(event.role_id) if event.role_id else None
        if role is None:
            return
        want = set(att.going)
        for m in list(getattr(role, "members", []) or []):
            if str(m.id) not in want:
                try:
                    await m.remove_roles(role, reason="no longer going")
                except Exception:  # noqa: BLE001
                    pass
        for uid in want:
            m = guild.get_member(uid)
            if m is not None and role not in m.roles:
                try:
                    await m.add_roles(role, reason=f"going to {event.title}")
                except Exception:  # noqa: BLE001
                    pass

    async def _drop_role(self, guild, event: Event, *, delete: bool) -> None:
        role = guild.get_role(event.role_id) if event.role_id else None
        if role is None:
            return
        try:
            if delete:
                await role.delete(reason="event over")
                await self.store.update(event.id, role_id="")
            else:
                await self._sync_role(guild, event, Attendees([], [], [], []))
        except Exception:  # noqa: BLE001
            pass

    # -- RSVP by reaction -------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        await self._react(payload, True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        await self._react(payload, False)

    async def _react(self, payload, added: bool) -> None:
        status = EMOJI.get(str(payload.emoji))
        if status is None or str(payload.user_id) == str(self.bot.user.id) or not payload.guild_id:
            return
        event = await self.store.by_message(str(payload.message_id))
        if event is None or not event.open:
            return
        guild = self.bot.get_guild(event.guild_id)
        if guild is None:
            return
        uid = str(payload.user_id)
        if added:
            await self.set_rsvp(guild, event, uid, status)
        else:
            # taking a reaction back only clears the answer if it's still the current one
            current = (await self.store.attendees(event)).status_of(uid)
            if current == status or (status == "going" and current == "waitlist"):
                await self.set_rsvp(guild, event, uid, None)

    # -- the clock --------------------------------------------------------------------------

    @tasks.loop(seconds=20)
    async def watch(self):
        now = int(time.time())
        for event in await self.store.open_events():
            try:
                await self.tick(event, now)
            except Exception:  # noqa: BLE001 - one broken event must not stop the others
                log.exception("event #%s", event.id)

    @watch.before_loop
    async def _ready(self):
        await self.bot.wait_until_ready()

    async def tick(self, event: Event, now: int) -> None:
        guild = self.bot.get_guild(event.guild_id)
        if guild is None or not self.bot.serves(guild):
            return
        if event.status == "scheduled":
            for minutes in event.remind:
                at = event.starts_at - minutes * 60
                # a reminder whose moment passed more than 10 minutes ago (the bot was off) is skipped
                if at <= now < event.starts_at and now - at < 600 and \
                        await self.store.mark_reminded(event.id, event.starts_at, minutes):
                    await self.remind(guild, event, minutes)
            if event.starts_at <= now:
                event = await self.store.update(event.id, status="live")
                if now < event.ends_at:
                    await self.announce_start(guild, event)
                await self.refresh(event)
        if event.status == "live" and event.ends_at <= now:
            await self.finish(guild, event, now)

    # -- announcements and DMs --------------------------------------------------------------

    async def announce(self, guild, event: Event, title: str, text: str) -> None:
        """A general post in the event's channel: no one is pinged, and the event's picture sits between the
        text and the footer."""
        ch = guild.get_channel(event.channel_id)
        if ch is None:
            return
        tz = zone(event.tz)
        card = embed(title, text, footer=f"Event #{event.id} · {fmt_when(event.start, event.end, tz)}")
        card.timestamp = event.start
        pic = await self.banner(event, guild)
        try:
            if pic is not None:
                card.set_image(url=f"attachment://{pic.filename}")
                await ch.send(embed=card, file=pic)
            else:
                await ch.send(embed=card)
        except Exception as exc:  # noqa: BLE001
            log.warning("event announcement failed: %s", exc)

    async def dm(self, guild, ids: list[str], text: str) -> int:
        """Personal notes go by DM only. Returns how many were delivered."""
        sent = 0
        for uid in dict.fromkeys(ids):
            user = guild.get_member(uid) or self.bot.get_user(uid)
            if user is None:
                continue
            try:
                await user.send(text)
                sent += 1
            except Exception:  # noqa: BLE001 - closed DMs are normal
                pass
        return sent

    def _where(self, event: Event) -> str:
        return f"\n📍 {event.location}" if event.location else ""

    async def remind(self, guild, event: Event, minutes: int) -> None:
        att = await self.store.attendees(event)
        when = fmt_span(minutes * 60)
        going = len(att.going)
        await self.announce(guild, event, f"⏰ {event.title} starts in {when}",
                            f"{event.description[:300]}{self._where(event)}\n\n{GOING} {going} going"
                            + (f" · {MAYBE} {len(att.maybe)} maybe" if att.maybe else "")
                            + "\nReact on the event post to join.")
        if self.cfg.get("events.dm_reminders", True):
            tz = zone(event.tz)
            await self.dm(guild, att.going + att.maybe,
                          f"⏰ Reminder: **{event.title}** in {guild.name} starts in **{when}** "
                          f"({fmt_when(event.start, event.end, tz)}).{self._where(event)}")
        self.bot.emit(guild, "events", f"Reminder: {event.title}", f"starts in {when}")

    async def announce_start(self, guild, event: Event) -> None:
        att = await self.store.attendees(event)
        await self.announce(guild, event, f"🔴 {event.title} is starting now!",
                            f"{event.description[:300]}{self._where(event)}")
        if self.cfg.get("events.dm_reminders", True):
            await self.dm(guild, att.going + att.maybe,
                          f"🔴 **{event.title}** in {guild.name} is starting now!{self._where(event)}")
        self.bot.emit(guild, "events", f"Starting: {event.title}", "")

    async def finish(self, guild, event: Event, now: int) -> None:
        if event.repeat == "none":
            event = await self.store.update(event.id, status="ended")
            await self.refresh(event)
            await self._drop_role(guild, event, delete=True)
            return
        # repeating: close this post as a record, then post the next one with fresh RSVPs
        tz = zone(event.tz)
        old = await self.store.update(event.id, status="ended")
        await self.refresh(old)
        length = event.ends_at - event.starts_at
        start = next_occurrence(event.start, event.repeat, tz)
        while start.timestamp() + length <= now:        # catch up if the bot was off for a while
            start = next_occurrence(start, event.repeat, tz)
        await self.store.clear_rsvps(event.id)
        await self._drop_role(guild, event, delete=False)
        event = await self.store.update(event.id, status="scheduled", starts_at=int(start.timestamp()),
                                        ends_at=int(start.timestamp()) + length, message_id=None,
                                        image_message_id=None, footer_message_id=None)
        ch = guild.get_channel(event.channel_id)
        if ch is not None:
            await self.post(event, ch)

    # -- commands ---------------------------------------------------------------------------

    async def _get(self, ctx, event_id: int) -> Event | None:
        event = await self.store.get(event_id)
        if event is None or event.guild_id != str(ctx.guild.id):
            await ctx.send(fail(f"No event #{event_id} here. `{ctx.prefix}event list` shows them."))
            return None
        return event

    @commands.group(name="event", aliases=["events", "ev"], invoke_without_command=True)
    async def event(self, ctx):
        """Upcoming events. Subcommands: create, list, info, edit, rsvp, who, cancel, delete, repost, ics, timezone."""
        await self.list_(ctx)

    @event.command(name="create", aliases=["new", "add", "schedule"])
    async def create_cmd(self, ctx, *, spec: str = ""):
        """`event create Game night | friday 8pm | 2h | Bring snacks` (length and description are optional)."""
        if not self.may_create(ctx.author):
            return await ctx.send(fail("Only staff can create events here."))
        parts = [p.strip() for p in spec.split("|")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            return await ctx.send(
                f"📅 **Create an event**\n`{ctx.prefix}event create Title | when | length | description`\n"
                f"e.g. `{ctx.prefix}event create Game night | friday 8pm | 2h | Bring snacks`\n"
                "When: `friday 8pm`, `tomorrow 18:30`, `nov 20 7pm`, `2026-11-20 20:00`, `in 2h`. "
                f"Times are in **{await self.tz_name(ctx.guild)}**.\n"
                f"Attach a picture to use it instead of the drawn banner. "
                f"Then: `{ctx.prefix}event edit <id> location|repeat|remind|capacity <value>`")
        title, when = parts[0], parts[1]
        length = parts[2] if len(parts) > 2 and parts[2] else ""
        desc = " | ".join(parts[3:]) if len(parts) > 3 else ""
        tz = await self.tz(ctx.guild)
        try:
            start = parse_when(when, tz)
            secs = parse_span(length) if length else int(self.cfg.get("events.default_minutes", 60)) * 60
        except WhenError as exc:
            return await ctx.send(fail(str(exc)))
        channel = self.default_channel(ctx.guild, ctx.channel)
        try:
            image = await self.image_from(ctx.message)
            event = await self.create(ctx.guild, channel, ctx.author, title, start, secs, description=desc, image=image)
        except EventError as exc:
            return await ctx.send(fail(str(exc)))
        where = "" if channel.id == ctx.channel.id else f" in #{channel.name}"
        await ctx.send(ok(f"Event #{event.id} **{event.title}** is on the calendar{where}: "
                          f"{fmt_when(event.start, event.end, tz)} ({fmt_relative(event.start)})."))

    @event.command(name="list", aliases=["upcoming", "ls"])
    async def list_(self, ctx):
        """The next events."""
        rows = await self.store.upcoming(str(ctx.guild.id), 15)
        if not rows:
            return await ctx.send(f"📅 Nothing on the calendar. `{ctx.prefix}event create` to add something.")
        counts = await self.store.counts([e.id for e in rows])
        tz = await self.tz(ctx.guild)
        lines = []
        for e in rows:
            live = "🔴 " if e.status == "live" else ""
            rep = " 🔁" if e.repeat != "none" else ""
            lines.append(f"`#{e.id}` {live}**{e.title}**{rep}\n{fmt_when(e.start, e.end, tz)} · "
                         f"{fmt_relative(e.start) if e.status == 'scheduled' else 'now'} · {GOING} {counts[e.id]['going']}")
        await ctx.send(embed=embed("📅 Upcoming events", "\n\n".join(lines),
                                   footer=f"{ctx.prefix}event info <id> · {ctx.prefix}calendar for the month"))

    @event.command(name="info", aliases=["show", "view"])
    async def info(self, ctx, event_id: int):
        """One event's details and who's coming."""
        if (event := await self._get(ctx, event_id)) is None:
            return
        e = await self.render(event, ctx.guild)
        if event.open and event.channel_id != str(ctx.channel.id):
            ch = ctx.guild.get_channel(event.channel_id)
            e.set_footer(text=f"Event #{event.id} · RSVP on the post in #{ch.name if ch else '?'} or with "
                              f"{ctx.prefix}event rsvp {event.id} going")
        await ctx.send(embed=e)

    @event.command(name="edit", aliases=["set", "change"])
    async def edit(self, ctx, event_id: int, field: str = "", *, value: str = ""):
        """`event edit 3 when saturday 7pm` · title when length description location repeat remind capacity channel image"""
        if (event := await self._get(ctx, event_id)) is None:
            return
        if not self.may_edit(ctx.author, event):
            return await ctx.send(fail("Only the host or staff can change this event."))
        if field.lower() in ("image", "picture", "banner") and not value:
            try:
                pic = await self.image_from(ctx.message)
            except EventError as exc:
                return await ctx.send(fail(str(exc)))
            if pic is None:
                return await ctx.send(fail("Attach a picture to that message, or use `image none` for the drawn banner."))
            event = await self.save_image(event, *pic)
            event = await self.change(ctx.guild, event, "repeat", event.repeat)     # reposts with the new picture
            return await ctx.send(ok(f"New picture for event #{event.id}."))
        if not field or (not value and field.lower() not in ("description", "location")):
            return await ctx.send(f"`{ctx.prefix}event edit {event_id} <field> <value>` · fields: {', '.join(FIELDS)}\n"
                                  "e.g. `location Voice lounge`, `repeat weekly`, `remind 1h, 10m`, `capacity 8`")
        try:
            event = await self.change(ctx.guild, event, field, value or "none")
        except EventError as exc:
            return await ctx.send(fail(str(exc)))
        await ctx.send(ok(f"Updated event #{event.id}."))

    @event.command(name="rsvp", aliases=["join", "going"])
    async def rsvp(self, ctx, event_id: int, answer: str = "going"):
        """`event rsvp 3 going|maybe|no|leave`"""
        if (event := await self._get(ctx, event_id)) is None:
            return
        if not event.open:
            return await ctx.send(fail("That event is over."))
        answer = answer.lower()
        status = {"yes": "going", "y": "going", "going": "going", "maybe": "maybe", "no": "no", "n": "no",
                  "leave": None, "clear": None, "none": None}.get(answer, "?")
        if status == "?":
            return await ctx.send(fail("Answer going, maybe, no or leave."))
        att = await self.set_rsvp(ctx.guild, event, str(ctx.author.id), status)
        now = att.status_of(str(ctx.author.id))
        text = {"going": "You're going", "waitlist": "It's full, so you're on the waitlist", "maybe": "Marked maybe",
                "no": "Marked can't go", None: "Your RSVP is cleared"}[now]
        await ctx.send(ok(f"{text} for **{event.title}**."))

    @event.command(name="leave", hidden=True)
    async def leave(self, ctx, event_id: int):
        await self.rsvp(ctx, event_id, "leave")

    @event.command(name="who", aliases=["attendees", "rsvps"])
    async def who(self, ctx, event_id: int):
        """Everyone who answered."""
        if (event := await self._get(ctx, event_id)) is None:
            return
        att = await self.store.attendees(event)
        def names(ids):
            return "\n".join(name_of(ctx.guild.get_member(u)) if ctx.guild.get_member(u) else u[:16] for u in ids) or "-"
        fields = [(f"{GOING} Going ({len(att.going)})", names(att.going), True)]
        if att.waitlist:
            fields.append((f"⏳ Waitlist ({len(att.waitlist)})", names(att.waitlist), True))
        fields += [(f"{MAYBE} Maybe ({len(att.maybe)})", names(att.maybe), True),
                   (f"{NO} Can't go ({len(att.no)})", names(att.no), True)]
        await ctx.send(embed=embed(f"Who's coming to {event.title}", fields=fields))

    @event.command(name="cancel")
    async def cancel_cmd(self, ctx, event_id: int, *, reason: str = ""):
        """Cancel an event (the post stays, marked cancelled, and attendees are told)."""
        if (event := await self._get(ctx, event_id)) is None:
            return
        if not self.may_edit(ctx.author, event):
            return await ctx.send(fail("Only the host or staff can cancel this event."))
        if not event.open:
            return await ctx.send(fail("That event is already over."))
        await self.cancel(ctx.guild, event, ctx.author, reason)
        if event.channel_id != str(ctx.channel.id):
            await ctx.send(ok(f"Cancelled **{event.title}**."))

    @event.command(name="delete", aliases=["remove", "rm"])
    async def delete_cmd(self, ctx, event_id: int):
        """Delete an event and its post for good."""
        if (event := await self._get(ctx, event_id)) is None:
            return
        if not self.may_manage(ctx.author):
            return await ctx.send(fail("Only staff can delete events."))
        await self.remove(ctx.guild, event)
        await ctx.send(ok(f"Deleted event #{event.id} **{event.title}**."))

    @event.command(name="repost", aliases=["bump"])
    async def repost(self, ctx, event_id: int):
        """Post the event again here (RSVPs carry over) and remove the old post."""
        if (event := await self._get(ctx, event_id)) is None:
            return
        if not self.may_edit(ctx.author, event):
            return await ctx.send(fail("Only the host or staff can do that."))
        if not event.open:
            return await ctx.send(fail("That event is over."))
        await self._delete_post(event)
        await self.post(await self.unposted(event), ctx.channel)

    @event.command(name="ics", aliases=["export", "file"])
    async def ics(self, ctx, event_id: int):
        """A calendar file for one event (opens in Google, Apple or Outlook calendars)."""
        if (event := await self._get(ctx, event_id)) is None:
            return
        data = calendar_file([event], name=event.title, community=ctx.guild.name)
        await ctx.send(f"📎 Add **{event.title}** to your calendar:",
                       file=vector.File(io.BytesIO(data), filename=f"event-{event.id}.ics"))

    @event.command(name="timezone", aliases=["tz"])
    async def timezone(self, ctx, *, name: str = ""):
        """Show or set the time zone events are typed and shown in (e.g. America/New_York)."""
        if not name:
            return await ctx.send(f"🕓 Event times are in **{await self.tz_name(ctx.guild)}**. "
                                  f"Change with `{ctx.prefix}event timezone Europe/London`.")
        if not self.may_manage(ctx.author):
            return await ctx.send(fail("Only staff can change the time zone."))
        try:
            tz = zone(name)
        except WhenError as exc:
            return await ctx.send(fail(str(exc)))
        await self.bot.stores.settings.set(str(ctx.guild.id), TZ_KEY, str(tz.key))
        now = dt.datetime.now(tz)
        await ctx.send(ok(f"Event times are now in **{tz.key}** (it's {now:%H:%M} there). "
                          "Existing events keep their time."))

    # -- the month view ---------------------------------------------------------------------

    async def month_slots(self, guild, year: int, month: int) -> tuple[list[Slot], list[tuple[Event, int, int]]]:
        tz = await self.tz(guild)
        first = dt.datetime(year, month, 1, tzinfo=tz)
        last = dt.datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=tz)
        lo, hi = int(first.timestamp()), int(last.timestamp())
        events = await self.store.between(str(guild.id), lo, hi)
        counts = await self.store.counts([e.id for e in events])
        slots, occ = [], []
        for e in events:
            for s, en in occurrences(e, lo, hi, tz):
                local = dt.datetime.fromtimestamp(s, UTC).astimezone(tz)
                live = e.status == "live" and s == e.starts_at
                slots.append(Slot(local.date(), f"{local.hour % 12 or 12}:{local.minute:02d} "
                                  f"{'AM' if local.hour < 12 else 'PM'}", e.title, counts[e.id]["going"], live))
                occ.append((e, s, en))
        occ.sort(key=lambda x: x[1])
        return slots, occ

    @commands.command(name="calendar", aliases=["cal"])
    async def calendar(self, ctx, *, which: str = ""):
        """This month's events as a picture. `calendar next`, `calendar december`, `calendar 2027-01`, `calendar ics`."""
        if which.strip().lower() in ("ics", "file", "export"):
            rows = await self.store.upcoming(str(ctx.guild.id), 500)
            if not rows:
                return await ctx.send("📅 Nothing on the calendar yet.")
            data = calendar_file(rows, name=f"{ctx.guild.name} events", community=ctx.guild.name)
            return await ctx.send(f"📎 {len(rows)} upcoming event(s). Import this file into your calendar app:",
                                  file=vector.File(io.BytesIO(data), filename="events.ics"))
        tz = await self.tz(ctx.guild)
        today = dt.datetime.now(tz).date()
        try:
            year, month = self._month(which, today)
        except EventError as exc:
            return await ctx.send(fail(str(exc)))
        slots, occ = await self.month_slots(ctx.guild, year, month)
        title = f"📅 {pycal.month_name[month]} {year}"
        lines = []
        for e, s, en in occ[:12]:
            start, end = dt.datetime.fromtimestamp(s, UTC), dt.datetime.fromtimestamp(en, UTC)
            lines.append(f"`#{e.id}` **{e.title}** · {fmt_when(start, end, tz)}")
        if len(occ) > 12:
            lines.append(f"…and {len(occ) - 12} more")
        card = embed(title, "\n".join(lines) or "Nothing scheduled this month.",
                     footer=f"{ctx.guild.name} · times in {tz.key}", timestamp=True)
        if self.cfg.get("leveling.cards", True) and self.cfg.get("events.calendar_image", True):
            try:
                png = await asyncio.to_thread(calendar_card, year, month, slots, today=today, community=ctx.guild.name,
                                              tz_label=f"Times in {tz.key}",
                                              first_weekday=6 if self.cfg.get("events.week_starts") == "sunday" else 0)
                card.set_image(url="attachment://calendar.png")
                return await ctx.send(embed=card, file=vector.File(io.BytesIO(png), filename="calendar.png"))
            except Exception:  # noqa: BLE001
                log.exception("calendar image")
        await ctx.send(embed=card)

    @staticmethod
    def _month(which: str, today: dt.date) -> tuple[int, int]:
        w = which.strip().lower()
        if w in ("", "this", "now"):
            return today.year, today.month
        if w == "next":
            return (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        if w in ("last", "prev", "previous"):
            return (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
        if (m := re.fullmatch(r"(\d{4})-(\d{1,2})", w)) and 1 <= int(m.group(2)) <= 12:
            return int(m.group(1)), int(m.group(2))
        names = {n.lower(): i for i, n in enumerate(pycal.month_name) if n} | \
                {n.lower(): i for i, n in enumerate(pycal.month_abbr) if n}
        parts = w.split()
        if parts and parts[0] in names:
            month = names[parts[0]]
            year = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else \
                (today.year + 1 if month < today.month else today.year)
            return year, month
        raise EventError("try `calendar`, `calendar next`, `calendar december` or `calendar 2027-01`")


async def setup(bot):
    await bot.add_cog(Events(bot))

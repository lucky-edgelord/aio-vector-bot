import datetime as dt
from types import SimpleNamespace

import pytest

from vectiq.cogs.events import EventError, Events, occurrences, parse_remind
from vectiq.config import Config
from vectiq.render import Slot, calendar_card
from vectiq.utils.ics import calendar_file
from vectiq.utils.when import WhenError, fmt_when, next_occurrence, parse_span, parse_when, zone

NY = zone("America/New_York")
MON_5PM = dt.datetime(2026, 11, 16, 17, 0, tzinfo=NY)


def local(text):
    return parse_when(text, NY, MON_5PM).astimezone(NY)


# -- reading times -------------------------------------------------------------------------------


@pytest.mark.parametrize("text,expect", [
    ("friday 8pm", (2026, 11, 20, 20, 0)),
    ("fri 8:30 pm", (2026, 11, 20, 20, 30)),
    ("tomorrow at 18:30", (2026, 11, 17, 18, 30)),
    ("tonight", (2026, 11, 16, 20, 0)),
    ("nov 20 7pm", (2026, 11, 20, 19, 0)),
    ("20 nov 7pm", (2026, 11, 20, 19, 0)),
    ("20th november 2027 9am", (2027, 11, 20, 9, 0)),
    ("2026-11-20 20:00", (2026, 11, 20, 20, 0)),
    ("11/20/27 3pm", (2027, 11, 20, 15, 0)),
    ("in 2h", (2026, 11, 16, 19, 0)),
    ("8pm", (2026, 11, 16, 20, 0)),
    ("4pm", (2026, 11, 17, 16, 0)),          # already past today -> tomorrow
    ("monday 9am", (2026, 11, 23, 9, 0)),    # today's 9am has passed -> next week
    ("jan 3 10am", (2027, 1, 3, 10, 0)),     # past date without a year -> next year
    ("11/20", (2026, 11, 20, 12, 0)),        # a date alone means midday
])
def test_parse_when(text, expect):
    t = local(text)
    assert (t.year, t.month, t.day, t.hour, t.minute) == expect


@pytest.mark.parametrize("bad", ["blah", "feb 30 5pm", "25pm", "nov", ""])
def test_parse_when_errors(bad):
    with pytest.raises(WhenError):
        parse_when(bad, NY, MON_5PM)


def test_spans_and_formatting():
    assert parse_span("1h30m") == parse_span("90") == parse_span("1.5 hours") == 5400
    with pytest.raises(WhenError):
        parse_span("soon")
    start = parse_when("friday 8pm", NY, MON_5PM)
    assert fmt_when(start, start + dt.timedelta(hours=2), NY) == "Fri, Nov 20 · 8:00 PM – 10:00 PM EST"
    assert parse_remind("1h, 15m") == [60, 15] and parse_remind("none") == []
    with pytest.raises(EventError):
        parse_remind("30 days")


def test_repeats_keep_local_time_across_dst():
    start = parse_when("2027-03-13 10:00", NY, MON_5PM)            # the day before clocks go forward
    nxt = next_occurrence(start, "weekly", NY).astimezone(NY)
    assert (nxt.day, nxt.hour) == (20, 10) and nxt.tzname() == "EDT"
    feb = next_occurrence(parse_when("2027-01-31 10:00", NY, MON_5PM), "monthly", NY).astimezone(NY)
    assert (feb.month, feb.day) == (2, 28)


def test_zone_errors():
    with pytest.raises(WhenError):
        zone("Mars/Base")


def test_config_checks_the_time_zone(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("events:\n  timezone: Mars/Base\n")
    with pytest.raises(Exception, match="time zone"):
        Config.load(p, env={})


# -- the store -----------------------------------------------------------------------------------


async def test_rsvps_waitlist_and_counts(stores):
    s = stores.events
    e = await s.create("g", "c", "host", "Board games", 1_900_000_000, 1_900_003_600, capacity=2)
    for u in ("a", "b", "c"):
        await s.rsvp(e.id, u, "going")
    await s.rsvp(e.id, "d", "maybe")
    att = await s.attendees(e)
    assert att.going == ["a", "b"] and att.waitlist == ["c"] and att.maybe == ["d"]
    await s.rsvp(e.id, "a", "going")            # saying going again keeps your place
    assert (await s.attendees(e)).going == ["a", "b"]
    await s.rsvp(e.id, "a", "no")               # a drops out: c moves up from the waitlist
    att = await s.attendees(e)
    assert att.going == ["b", "c"] and att.waitlist == [] and att.status_of("a") == "no"
    assert (await s.counts([e.id]))[e.id] == {"going": 2, "maybe": 1, "no": 1}
    with pytest.raises(ValueError):
        await s.rsvp(e.id, "x", "perhaps")


async def test_reminders_once_and_updates(stores):
    s = stores.events
    e = await s.create("g", "c", "host", "Talk", 1_900_000_000, 1_900_003_600, remind=[15, 60, 15])
    assert e.remind == [60, 15]
    assert await s.mark_reminded(e.id, e.starts_at, 15) is True
    assert await s.mark_reminded(e.id, e.starts_at, 15) is False
    e = await s.update(e.id, title="Talk 2", remind=[5])
    assert e.title == "Talk 2" and e.remind == [5]
    with pytest.raises(ValueError):
        await s.update(e.id, guild_id="other")
    assert await s.by_message("nope") is None
    assert await s.delete(e.id) and await s.get(e.id) is None


# -- the cog's clock -----------------------------------------------------------------------------


class Msg:
    def __init__(self, mid, kw):
        self.id, self.kw, self.edits, self.reactions = mid, kw, [], []
        self.content = kw.get("content")

    async def add_reaction(self, e):
        self.reactions.append(e)

    async def edit(self, **kw):
        self.edits.append(kw)

    async def delete(self):
        self.deleted = True


class Chan:
    def __init__(self, cid="c1", name="events"):
        self.id, self.name, self.sent, self.msgs = cid, name, [], {}
        self.guild = None

    async def send(self, content=None, **kw):
        m = Msg(f"m{len(self.sent)}", {"content": content, **kw})
        self.sent.append(m)
        self.msgs[m.id] = m
        return m

    async def fetch_message(self, mid):
        return self.msgs[mid]


class Member:
    def __init__(self, uid):
        self.id, self.mention, self.display_name, self.roles, self.dms = uid, f"@{uid}", uid, [], []
        self.guild_permissions = SimpleNamespace(manage_messages=uid == "host", manage_guild=False,
                                                 administrator=False)

    async def send(self, text):
        self.dms.append(text)


@pytest.fixture
async def cog(stores, tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("events:\n  timezone: America/New_York\n  reminders: [60, 15]\n")
    cfg = Config.load(p, env={"VECTIQ_DATA_DIR": str(tmp_path / "data")})
    ch = Chan()
    members = {u: Member(u) for u in ("host", "ann", "bob")}
    guild = SimpleNamespace(id="g1", name="G", text_channels=[ch], get_channel=lambda cid: ch if cid == "c1" else None,
                            get_member=members.get, get_role=lambda rid: None)
    ch.guild = guild
    emitted = []
    bot = SimpleNamespace(config=cfg, stores=stores, user=SimpleNamespace(id="bot"), get_guild=lambda gid: guild,
                          serves=lambda g: True, emit=lambda *a: emitted.append(a), get_user=members.get,
                          find_channel=lambda g, ref: ch if ref in ("c1", "events") else None)
    Events.watch.start = lambda self: None          # no background loop in tests
    c = Events.__new__(Events)
    c.bot, c.cfg, c.store, c._pending = bot, cfg, stores.events, {}
    c.refresh_soon = lambda eid, delay=0: None
    return SimpleNamespace(cog=c, ch=ch, guild=guild, members=members, emitted=emitted)


async def test_create_posts_with_reactions(cog):
    start = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)
    e = await cog.cog.create(cog.guild, cog.ch, cog.members["host"], "Game night", start, 7200, location="Lounge")
    body, pic, foot = cog.ch.sent[:3]                  # details, then the picture, then the footer
    assert "Game night" in body.kw["content"] and "Lounge" in body.kw["content"]
    assert pic.kw["file"].filename == f"event-{e.id}.png" and e.image_message_id == pic.id
    assert f"Event #{e.id}" in foot.kw["content"] and foot.reactions == ["✅", "🤔", "❌"]
    assert (e.message_id, e.footer_message_id) == (body.id, foot.id)
    assert (await cog.cog.store.by_message(foot.id)).id == e.id
    assert e.remind == [60, 15] and e.tz == "America/New_York"
    with pytest.raises(EventError):
        await cog.cog.create(cog.guild, cog.ch, cog.members["host"], "Late", start - dt.timedelta(days=3), 600)


async def test_reaction_rsvp(cog):
    start = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)
    e = await cog.cog.create(cog.guild, cog.ch, cog.members["host"], "Jam", start, 3600)
    p = lambda emoji: SimpleNamespace(emoji=emoji, user_id="ann", message_id=e.footer_message_id, guild_id="g1")  # noqa: E731
    await cog.cog.on_raw_reaction_add(p("✅"))
    assert (await cog.cog.store.attendees(e)).going == ["ann"]
    await cog.cog.on_raw_reaction_add(p("🤔"))        # latest reaction wins
    await cog.cog.on_raw_reaction_remove(p("✅"))     # removing an older one changes nothing
    assert (await cog.cog.store.attendees(e)).maybe == ["ann"]
    await cog.cog.on_raw_reaction_remove(p("🤔"))
    assert (await cog.cog.store.attendees(e)).status_of("ann") is None


async def test_clock_reminds_starts_and_ends(cog):
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    e = await cog.cog.store.create("g1", "c1", "host", "Talk", now + 14 * 60, now + 74 * 60, tz="UTC", remind=[60, 15])
    await cog.cog.store.rsvp(e.id, "ann", "going")
    await cog.cog.tick(e, now)                        # 15 min reminder is due, the 60 min one is long past
    notes = [m.kw["embed"] for m in cog.ch.sent if m.kw.get("embed")]
    assert len(notes) == 1 and notes[0].title == "⏰ Talk starts in 15m"
    assert "@ann" not in str(notes[0].description)                    # no pings in the channel...
    assert cog.ch.sent[0].kw["file"].filename.endswith(".png")        # ...but the picture is there
    assert cog.members["ann"].dms == [cog.members["ann"].dms[0]] and "Talk" in cog.members["ann"].dms[0]
    assert cog.members["bob"].dms == []                                # only people who answered get a DM
    await cog.cog.tick(e, now + 30)                   # never twice
    assert len([m for m in cog.ch.sent if m.kw.get("embed")]) == 1
    await cog.cog.tick(await cog.cog.store.get(e.id), now + 15 * 60)
    e = await cog.cog.store.get(e.id)
    assert e.status == "live" and any("starting now" in getattr(m.kw.get("embed"), "title", "") or ""
                                      for m in cog.ch.sent)
    assert "starting now" in cog.members["ann"].dms[-1]
    await cog.cog.tick(e, now + 80 * 60)
    assert (await cog.cog.store.get(e.id)).status == "ended"


async def test_repeating_event_rolls_forward(cog):
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    e = await cog.cog.store.create("g1", "c1", "host", "Standup", now - 7200, now - 3600, tz="UTC", repeat="daily",
                                   remind=[])
    await cog.cog.store.rsvp(e.id, "ann", "going")
    e = await cog.cog.store.update(e.id, status="live")
    await cog.cog.tick(e, now)
    e2 = await cog.cog.store.get(e.id)
    assert e2.status == "scheduled" and e2.starts_at == e.starts_at + 86400
    assert (await cog.cog.store.attendees(e2)).going == []          # a fresh RSVP list per occurrence
    assert (e2.message_id, e2.footer_message_id) == (cog.ch.sent[-3].id, cog.ch.sent[-1].id)   # and a fresh post


async def test_attached_picture_and_announcements_channel(cog):
    ann = Chan("c9", "📣┊Announcements")
    cog.guild.text_channels.append(ann)
    assert cog.cog.default_channel(cog.guild) is ann
    att = SimpleNamespace(content_type="image/png", filename="x.png", size=10)
    async def read():
        return b"\x89PNG fake"
    att.read = read
    txt = SimpleNamespace(content_type="text/plain", filename="a.txt")
    pic = await Events.image_from(SimpleNamespace(attachments=[txt, att]))
    assert pic == (b"\x89PNG fake", "png")
    start = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)
    e = await cog.cog.create(cog.guild, cog.ch, cog.members["host"], "Art show", start, 3600, image=pic)
    assert e.image_path == f"{e.id}.png" and (cog.cog.image_dir() / e.image_path).read_bytes() == b"\x89PNG fake"
    assert cog.ch.sent[1].kw["file"].filename == f"event-{e.id}.png"
    e = await cog.cog.change(cog.guild, e, "image", "none")      # back to the drawn banner, reposted
    assert e.image_path == "" and not list(cog.cog.image_dir().glob(f"{e.id}.*"))
    assert all(getattr(cog.ch.msgs[m.id], "deleted", False) for m in cog.ch.sent[:3])


async def test_change_and_cancel(cog):
    start = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2)
    e = await cog.cog.create(cog.guild, cog.ch, cog.members["host"], "Movie", start, 3600)
    e = await cog.cog.change(cog.guild, e, "repeat", "every week")
    assert e.repeat == "weekly"
    e = await cog.cog.change(cog.guild, e, "length", "2h")
    assert e.ends_at - e.starts_at == 7200
    e = await cog.cog.change(cog.guild, e, "remind", "30m")
    assert e.remind == [30]
    for field, value in (("capacity", "lots"), ("image", "http://x"), ("colour", "red"), ("repeat", "hourly")):
        with pytest.raises(EventError):
            await cog.cog.change(cog.guild, e, field, value)
    await cog.cog.store.rsvp(e.id, "bob", "going")
    e = await cog.cog.cancel(cog.guild, e, cog.members["host"], "rain")
    assert e.status == "cancelled" and cog.ch.sent[-1].kw["embed"].title == "❌ Movie is cancelled"
    assert "cancelled: rain" in cog.members["bob"].dms[-1]


async def test_month_view_expands_repeats(cog):
    tz = zone("UTC")
    e = await cog.cog.store.create("g1", "c1", "host", "Weekly", int(dt.datetime(2030, 1, 2, 18, tzinfo=tz).timestamp()),
                                   int(dt.datetime(2030, 1, 2, 19, tzinfo=tz).timestamp()), tz="UTC", repeat="weekly")
    lo, hi = int(dt.datetime(2030, 1, 1, tzinfo=tz).timestamp()), int(dt.datetime(2030, 2, 1, tzinfo=tz).timestamp())
    assert [dt.datetime.fromtimestamp(s, tz).day for s, _ in occurrences(e, lo, hi, tz)] == [2, 9, 16, 23, 30]
    await cog.cog.bot.stores.settings.set("g1", "events:timezone", "UTC")
    slots, occ = await cog.cog.month_slots(cog.guild, 2030, 1)
    assert len(slots) == 5 and slots[0].time == "6:00 PM"
    png = calendar_card(2030, 1, slots + [Slot(dt.date(2030, 1, 2), "9:00 AM", "x")] * 4, today=dt.date(2030, 1, 2))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert Events._month("next", dt.date(2026, 12, 5)) == (2027, 1)
    assert Events._month("feb", dt.date(2026, 12, 5)) == (2027, 2)
    assert Events._month("2027-03", dt.date(2026, 12, 5)) == (2027, 3)
    with pytest.raises(EventError):
        Events._month("someday", dt.date(2026, 12, 5))


async def test_ics_file(stores):
    e = await stores.events.create("g", "c", "h", "Launch, party; yes", 1_900_000_000, 1_900_003_600,
                                   description="line one\nline two " + "x" * 120, repeat="biweekly", remind=[30])
    text = calendar_file([e], community="Vector").decode()
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert "SUMMARY:Launch\\, party\\; yes" in text and "RRULE:FREQ=WEEKLY;INTERVAL=2" in text
    assert "TRIGGER:-PT30M" in text and "DTSTART:20300317T174640Z" in text
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))

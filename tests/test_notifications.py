"""Stream & video alerts: feed parsing, remembering what was seen, and posting only what's new."""

from types import SimpleNamespace

from vectiq.cogs import notifications as N
from vectiq.config import DEFAULTS

YT = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">
 <title>Some Channel</title><author><name>Some Channel</name></author>
 <entry><id>yt:video:B</id><yt:videoId>B</yt:videoId><title>Second</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=B"/><author><name>Some Channel</name></author></entry>
 <entry><id>yt:video:A</id><yt:videoId>A</yt:videoId><title>First</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=A"/></entry>
</feed>"""

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Blog</title>
<item><title>Hello</title><link>https://blog.test/hello</link><guid>h1</guid></item></channel></rss>"""


def test_parse_youtube_and_rss():
    items = N.parse_feed(YT)
    assert [i.id for i in items] == ["B", "A"] and items[0].url.endswith("v=B") and items[0].author == "Some Channel"
    rss = N.parse_feed(RSS)
    assert rss[0].id == "h1" and rss[0].title == "Hello" and rss[0].author == "Blog"


def test_youtube_id_from_link():
    cid = "UC" + "x" * 22
    assert N.youtube_channel_id(f"https://www.youtube.com/channel/{cid}") == cid


class FakeChannel:
    def __init__(self):
        self.id, self.name, self.sent = "c1", "videos", []

    async def send(self, text):
        self.sent.append(text)


async def test_first_look_remembers_then_posts_only_new(stores, monkeypatch):
    ch = FakeChannel()
    guild = SimpleNamespace(id="g1", name="Test")
    bot = SimpleNamespace(stores=stores, guilds=[guild], serves=lambda g: True, find_channel=lambda g, r: ch,
                          find_role=lambda g, r: None, emit=lambda *a: None,
                          config=SimpleNamespace(get=lambda k, d=None: DEFAULTS["notifications"] if k == "notifications" else d))
    cog = N.Notifications.__new__(N.Notifications)
    cog.bot, cog.store, cog.twitch, cog._yt_ids = bot, stores.notify, N.Twitch(), {}
    feed_xml = {"x": RSS}
    monkeypatch.setattr(N, "fetch", lambda url, **kw: feed_xml["x"])
    await stores.notify.add("g1", "rss", "https://blog.test/feed", "c1")
    assert await cog.check() == 0 and ch.sent == []            # first look: nothing posted
    feed_xml["x"] = RSS.replace(b"<item>", b"<item><title>New post</title><link>https://blog.test/new</link>"
                                b"<guid>n1</guid></item><item>", 1)
    assert await cog.check() == 1 and "New post" in ch.sent[0] and "https://blog.test/new" in ch.sent[0]
    assert await cog.check() == 0                               # not twice


async def test_twitch_needs_keys():
    import pytest

    with pytest.raises(RuntimeError, match="TWITCH_CLIENT_ID"):
        N.Twitch().live({"twitch": {"client_id_env": "NOPE1", "client_secret_env": "NOPE2"}}, ["someone"])

import datetime
from types import SimpleNamespace

import pytest

from vectiq.cogs.securitycam import KEY, SecurityCam


class Chan:
    def __init__(self, cid, name):
        self.id, self.name, self.sent = cid, name, []

    async def send(self, **kw):
        self.sent.append(kw)


class Att:
    def __init__(self, name, ok=True):
        self.filename, self.url, self.size, self._ok = name, f"https://x/{name}", 10, ok

    async def to_file(self):
        if not self._ok:
            raise OSError("gone")
        return f"file:{self.filename}"


def build(settings=None, **cfg):
    cam, other = Chan("c1", "cam"), Chan("c2", "general")
    guild = SimpleNamespace(id="g1", name="G", text_channels=[cam, other])
    store = {} if settings is None else settings

    class Settings:
        async def get(self, g, k, d=None):
            return store.get(k, d)

    values = {"securitycam.include_bots": False, "securitycam.ignore_channels": [], "securitycam.channel": ""}
    values.update(cfg)
    bot = SimpleNamespace(
        config=SimpleNamespace(get=lambda k, d=None: values.get(k, d)),
        stores=SimpleNamespace(settings=Settings()), user=SimpleNamespace(id="me"),
        serves=lambda g: True,
        find_channel=lambda g, ref: next((c for c in g.text_channels if ref in (c.id, c.name)), None))
    return SecurityCam(bot), guild, cam, other, store


def msg(guild, channel, text="hi", author="u1", bot=False, atts=()):
    return SimpleNamespace(guild=guild, channel=channel, content=text, attachments=list(atts),
                           author=SimpleNamespace(id=author, bot=bot, display_name="Ann", display_avatar=None),
                           created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc))


@pytest.mark.asyncio
async def test_echoes_with_author_channel_time_text():
    cog, g, cam, other, store = build()
    store[KEY] = "c1"
    await cog.on_message(msg(g, other, "hello there"))
    sent = cam.sent[0]["embed"]
    assert sent.description == "hello there"
    assert sent.footer.text == "#general" and sent.timestamp.year == 2026
    assert sent.author.name == "Ann"


@pytest.mark.asyncio
async def test_off_until_a_channel_is_set():
    cog, g, cam, other, _ = build()
    await cog.on_message(msg(g, other))
    assert cam.sent == []


@pytest.mark.asyncio
async def test_no_loop_and_no_own_bot_messages_and_ignore_list():
    cog, g, cam, other, store = build(**{"securitycam.ignore_channels": ["general"]})
    store[KEY] = "c1"
    await cog.on_message(msg(g, cam))                       # the camera's own channel
    await cog.on_message(msg(g, other, author="me", bot=True))
    await cog.on_message(msg(g, other, author="b2", bot=True))   # other bots off by default
    await cog.on_message(msg(g, other))                     # ignored channel
    assert cam.sent == []


@pytest.mark.asyncio
async def test_attachments_are_reuploaded_or_linked():
    cog, g, cam, other, store = build()
    store[KEY] = "c1"
    await cog.on_message(msg(g, other, "", atts=[Att("a.png"), Att("b.zip", ok=False)]))
    sent = cam.sent[0]
    assert sent["files"] == ["file:a.png"]
    assert "b.zip" in sent["embed"].fields[0].value


@pytest.mark.asyncio
async def test_config_channel_fallback():
    cog, g, cam, other, _ = build(**{"securitycam.channel": "cam"})
    await cog.on_message(msg(g, other, "x"))
    assert len(cam.sent) == 1

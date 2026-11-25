"""Lifting bans: one, all, and the list."""

from types import SimpleNamespace

import pytest

from vectiq.cogs.moderation import Moderation
from vectiq.config import Config
from vectiq.db import Database
from vectiq.stores import Stores

G = "g1"


class Ctx:
    def __init__(self, guild):
        self.guild, self.author, self.sent = guild, SimpleNamespace(id="mod", display_name="Mod"), []

    async def send(self, text=None, **kw):
        self.sent.append(text if text is not None else kw)


class Guild:
    id = G
    name = "G"

    def __init__(self, banned):
        self.banned = {u: r for u, r in banned}
        self.unbanned = []

    async def bans(self, limit=None):
        for uid, reason in list(self.banned.items())[:limit]:
            yield SimpleNamespace(user=SimpleNamespace(id=uid, display_name=uid), reason=reason)

    async def unban(self, user, reason=None):
        uid = str(getattr(user, "id", user))
        if uid not in self.banned:
            raise LookupError("not banned")
        del self.banned[uid]
        self.unbanned.append(uid)


@pytest.fixture
async def rig(tmp_path):
    cfg = Config.load("config.yaml", env={"VECTIQ_DATA_DIR": str(tmp_path)})
    db = await Database(":memory:").connect()
    stores = Stores(db)
    bot = SimpleNamespace(config=cfg, stores=stores, emit=lambda *a, **k: None, dispatch=lambda *a, **k: None,
                          user=SimpleNamespace(id="bot"), get_guild=lambda _i: None)
    cog = Moderation.__new__(Moderation)
    cog.bot, cog.cfg, cog.store = bot, cfg, stores.moderation
    yield cog, stores
    await db.close()


def user(uid):
    return SimpleNamespace(id=uid, display_name=uid)


async def test_unban_lifts_and_closes_the_ban_case(rig):
    cog, stores = rig
    guild = Guild([("u1", "spam")])
    await cog.record(guild, user("u1"), user("mod"), "ban", "spam")
    ctx = Ctx(guild)
    await cog.unban.callback(cog, ctx, user("u1"))
    assert guild.unbanned == ["u1"]
    assert not await stores.moderation.for_user(G, "u1", action="ban", active_only=True)
    assert "Unbanned" in ctx.sent[0]


async def test_unban_of_someone_not_banned_raises(rig):
    cog, _ = rig
    with pytest.raises(LookupError):
        await cog.unban.callback(cog, Ctx(Guild([])), user("nobody"))


async def test_bans_lists_reasons_and_says_when_empty(rig):
    cog, _ = rig
    ctx = Ctx(Guild([("u1", "spam")]))
    await cog.bans.callback(cog, ctx)
    assert "u1" in ctx.sent[0]["embed"].description and "spam" in ctx.sent[0]["embed"].description
    empty = Ctx(Guild([]))
    await cog.bans.callback(cog, empty)
    assert "Nobody" in empty.sent[0]


async def test_unbanall_needs_confirm_then_lifts_everyone(rig):
    cog, _ = rig
    guild = Guild([("u1", ""), ("u2", "x")])
    ctx = Ctx(guild)
    await cog.unbanall.callback(cog, ctx)
    assert guild.banned and "confirm" in ctx.sent[0]
    await cog.unbanall.callback(cog, ctx, "confirm")
    assert not guild.banned and "Lifted 2 of 2" in ctx.sent[1]

"""The onboarding flow with the rules and tutorial steps, end to end with fakes."""

from types import SimpleNamespace

import pytest

from vectiq.cogs.onboarding import RULES_KEY, Onboarding
from vectiq.config import Config
from vectiq.db import Database
from vectiq.stores import Stores

G, U = "g1", "u1"


class Chan:
    id, name = "c1", "welcome"

    def __init__(self):
        self.sent = []

    async def send(self, text=None, **kw):
        m = SimpleNamespace(id=f"m{len(self.sent) + 1}", reacted=[])

        async def add_reaction(e, m=m):
            m.reacted.append(e)

        m.add_reaction = add_reaction
        self.sent.append(kw["embed"] if "embed" in kw else text)
        self.last = m
        return m


class Member:
    bot = False
    mention = "@Ann"
    display_name = "Ann"
    id = U

    guild = None

    def __init__(self, dms_open=True):
        self.dms, self.dms_open = [], dms_open

    async def send(self, text=None, **kw):
        if not self.dms_open:
            raise OSError("closed")
        self.dms.append(kw["embed"])


@pytest.fixture
async def rig(tmp_path):
    def make(steps, **extra):
        cfg = Config.load("config.yaml", env={"VECTIQ_DATA_DIR": str(tmp_path)})
        cfg.data["onboarding"].update(steps=steps, **extra)
        return cfg

    db = await Database(":memory:").connect()
    stores = Stores(db)
    chan, member = Chan(), Member()
    guild = SimpleNamespace(id=G, name="Test", system_channel=chan, text_channels=[chan],
                            get_member=lambda uid: member, get_channel=lambda cid: chan)

    def build(steps, **extra):
        cfg = make(steps, **extra)
        bot = SimpleNamespace(config=cfg, stores=stores, serves=lambda g: True, user=SimpleNamespace(id="bot"),
                              find_channel=lambda g, ref: next((c for c in g.text_channels if ref in (c.id, c.name)), None),
                              get_guild=lambda i: guild, emit=lambda *a, **k: None, guilds=[guild])
        cfg.enabled = lambda name: True
        return Onboarding(bot)

    yield build, stores, guild, chan, member
    await db.close()


def agree(cog, message_id, emoji="✅"):
    return SimpleNamespace(guild_id=G, user_id=U, message_id=message_id, emoji=emoji)


async def test_rules_gate_the_flow_until_accepted(rig):
    build, stores, guild, chan, member = rig
    cog = build(["verify", "rules"])
    member.guild = guild
    await cog.on_member_join(member)
    assert chan.sent == []                       # still behind verification
    await cog.on_vectiq_verified(guild, member)
    assert "Be kind" in chan.sent[0].description and chan.sent[0].description.count("**") >= 4
    assert await stores.settings.get(G, RULES_KEY) == "m1" and "@Ann" in chan.sent[1]
    assert (await stores.onboarding.get(G, U))["completed_at"] is None
    await cog.on_raw_reaction_add(agree(cog, "m1"))
    row = await stores.onboarding.get(G, U)
    assert row["rules_at"] is not None and row["completed_at"] is not None


async def test_the_agree_command_and_wrong_message_reactions(rig):
    build, stores, guild, chan, member = rig
    cog = build(["verify", "rules"])
    await stores.onboarding.start(G, U)
    await cog.on_vectiq_verified(guild, member)
    await cog.on_raw_reaction_add(agree(cog, "someother"))
    assert (await stores.onboarding.get(G, U))["rules_at"] is None
    ctx = SimpleNamespace(guild=guild, author=member, sent=[])

    async def send(text=None, **kw):
        ctx.sent.append(text)

    ctx.send = send
    await cog.agree.callback(cog, ctx)
    assert "accepted" in ctx.sent[0]          # the thanks comes before anything the next steps send
    await cog.agree.callback(cog, ctx)
    assert "already" in ctx.sent[1]


async def test_tutorial_is_dmed_page_by_page_then_finishes(rig):
    build, stores, guild, chan, member = rig
    cog = build(["verify", "tutorial"])
    await cog.on_vectiq_verified(guild, member)
    assert len(member.dms) == 4 and "(1/4)" in member.dms[0].title
    assert (await stores.onboarding.get(G, U))["completed_at"] is not None


async def test_tutorial_falls_back_to_the_channel_when_dms_are_closed(rig):
    build, stores, guild, chan, member = rig
    member.dms_open = False
    cog = build(["verify", "tutorial"])
    await cog.on_vectiq_verified(guild, member)
    assert any(getattr(m, "title", "") == "Welcome tour" for m in chan.sent)


async def test_steps_run_in_the_order_given(rig):
    build, stores, guild, chan, member = rig
    cog = build(["verify", "rules", "tutorial"], rules=["Be nice."])
    await cog.on_vectiq_verified(guild, member)
    assert member.dms == []                       # not before the rules are accepted
    await cog.on_raw_reaction_add(agree(cog, "m1"))
    assert len(member.dms) == 4


def test_new_steps_validate(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("onboarding:\n  steps: [verify, rules, pick_roles, tutorial]")
    assert Config.load(p, env={}).get("onboarding.steps")[1] == "rules"

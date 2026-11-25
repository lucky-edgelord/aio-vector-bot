"""Ban appeals: the DM flow, the moderators' vote and what each outcome does."""

from types import SimpleNamespace

import pytest

from vectiq.cogs.appeals import NO, YES, Appeals
from vectiq.config import Config
from vectiq.db import Database
from vectiq.stores import Stores

G, U = "g1", "npubBanned"


class Chan:
    def __init__(self, cid="c1", name="appeals"):
        self.id, self.name, self.sent = cid, name, []

    async def send(self, text=None, **kw):
        m = SimpleNamespace(id=f"m{len(self.sent) + 1}", reactions=[])

        async def add_reaction(e, m=m):
            m.reactions.append(e)

        m.add_reaction = add_reaction
        self.sent.append(text if text is not None else kw["embed"])
        self.last = m
        return m


class Guild:
    id, name = G, "Test"

    def __init__(self):
        self.chan, self.banned, self.unbanned = Chan(), {U}, []
        self.voters = {v: SimpleNamespace(id=v, guild_permissions=SimpleNamespace(ban_members=True, administrator=False))
                       for v in ("mod1", "mod2", "mod3")}
        no_perm = SimpleNamespace(ban_members=False, administrator=False)
        self.voters["pleb"] = SimpleNamespace(id="pleb", guild_permissions=no_perm)
        self.text_channels = [self.chan]

    async def fetch_ban(self, uid):
        if uid not in self.banned:
            raise LookupError

    async def unban(self, user, reason=None):
        uid = str(getattr(user, "id", user))
        self.banned.discard(uid)
        self.unbanned.append(uid)

    def get_member(self, uid):
        return self.voters.get(str(uid))

    def get_channel(self, cid):
        return self.chan if str(cid) == self.chan.id else None


class Dm:
    def __init__(self):
        self.sent = []

    async def send(self, text=None, **kw):
        self.sent.append(text)


@pytest.fixture
async def rig(tmp_path):
    cfg = Config.load("config.yaml", env={"VECTIQ_DATA_DIR": str(tmp_path)})
    cfg.data.setdefault("appeals", {})["channel"] = "appeals"
    db = await Database(":memory:").connect()
    stores = Stores(db)
    guild, user_dm = Guild(), Dm()
    from vectiq.app import VectiqBot

    bot = SimpleNamespace(config=cfg, stores=stores, guilds=[guild], serves=lambda g: True, user=SimpleNamespace(id="bot"),
                          find_channel=VectiqBot.find_channel, get_guild=lambda i: guild if str(i) == G else None,
                          get_user=lambda i: user_dm, get_cog=lambda n: None)
    yield Appeals(bot), guild, user_dm, stores
    await db.close()


class Ctx:
    def __init__(self, author=U, guild=None):
        self.author, self.guild, self.sent = SimpleNamespace(id=author), guild, []

    async def send(self, text=None, **kw):
        self.sent.append(text if text is not None else kw["embed"])


def dm(text, author=U):
    d = Dm()
    who = SimpleNamespace(id=author, bot=False, display_name="Ban Bob")
    return SimpleNamespace(guild=None, author=who, content=text, channel=d), d


def reaction(guild, message, emoji, voter):
    return SimpleNamespace(emoji=emoji, guild_id=G, user_id=voter, message_id=message.id)


async def file_appeal(cog, guild):
    await cog.appeal.callback(cog, Ctx())
    msg, d = dm("I was wrongly flagged as a spammer, please look again.")
    await cog.on_message(msg)
    return guild.chan.last, d


async def test_dm_flow_posts_to_the_staff_channel_with_vote_reactions(rig):
    cog, guild, _, stores = rig
    ctx = Ctx()
    await cog.appeal.callback(cog, ctx)
    assert "Appeal your ban" in ctx.sent[0]
    card, d = await file_appeal(cog, guild)
    assert "wrongly flagged" in guild.chan.sent[-1].description
    assert card.reactions == [YES, NO] and "Sent" in d.sent[0]


async def test_not_banned_and_in_a_community_are_refused(rig):
    cog, guild, _, _ = rig
    guild.banned.clear()
    ctx = Ctx()
    await cog.appeal.callback(cog, ctx)
    assert "can't find a ban" in ctx.sent[0]
    inside = Ctx(guild=guild)
    await cog.appeal.callback(cog, inside)
    assert "private message" in inside.sent[0]


async def test_short_text_is_rejected_and_the_draft_stays(rig):
    cog, guild, _, _ = rig
    await cog.appeal.callback(cog, Ctx())
    msg, d = dm("pls")
    await cog.on_message(msg)
    assert "too short" in d.sent[0] and not guild.chan.sent


async def test_two_approvals_lift_the_ban_and_tell_the_user(rig):
    cog, guild, user_dm, stores = rig
    card, _ = await file_appeal(cog, guild)
    await cog.on_raw_reaction_add(reaction(guild, card, YES, "mod1"))
    assert guild.banned == {U}
    await cog.on_raw_reaction_add(reaction(guild, card, YES, "mod2"))
    assert guild.unbanned == [U]
    assert (await stores.appeals.get(1)).status == "approved"
    assert "approved" in user_dm.sent[-1]


async def test_two_denials_close_it_and_start_the_cooldown(rig):
    cog, guild, _, stores = rig
    card, _ = await file_appeal(cog, guild)
    await cog.on_raw_reaction_add(reaction(guild, card, NO, "mod1"))
    await cog.on_raw_reaction_add(reaction(guild, card, NO, "mod2"))
    assert guild.banned == {U} and (await stores.appeals.get(1)).status == "denied"
    again = Ctx()
    await cog.appeal.callback(cog, again)
    assert "appeal again in" in again.sent[0]


async def test_people_without_ban_permission_cannot_vote_and_one_voter_counts_once(rig):
    cog, guild, _, stores = rig
    card, _ = await file_appeal(cog, guild)
    await cog.on_raw_reaction_add(reaction(guild, card, YES, "pleb"))
    await cog.on_raw_reaction_add(reaction(guild, card, YES, "mod1"))
    await cog.on_raw_reaction_add(reaction(guild, card, YES, "mod1"))
    assert await stores.appeals.tally(1) == (1, 0) and guild.banned == {U}


async def test_a_second_appeal_while_one_is_open_is_refused(rig):
    cog, guild, _, _ = rig
    await file_appeal(cog, guild)
    ctx = Ctx()
    await cog.appeal.callback(cog, ctx)
    assert "already with the moderators" in ctx.sent[0]


async def test_appealvote_command_and_the_appeals_list(rig):
    cog, guild, _, stores = rig
    await file_appeal(cog, guild)
    staff = Ctx(author="mod1", guild=guild)
    staff.author = guild.voters["mod1"]
    await cog.appealvote.callback(cog, staff, 1, "yes")
    assert "1 for, 0 against" in staff.sent[0]
    listing = Ctx(guild=guild)
    listing.author = guild.voters["mod1"]
    await cog.appeals.callback(cog, listing)
    assert "#1" in listing.sent[0].description and "1 for" in listing.sent[0].description

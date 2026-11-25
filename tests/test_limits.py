"""Role-based command limits: who may run what, and how the rules are set."""

from types import SimpleNamespace

import pytest
from vector.ext import commands

from vectiq.cogs.limits import Limits, allowed, rule_for


class Role:
    def __init__(self, rid, name):
        self.id, self.name = rid, name


MOD, VIP, EVERY = Role("r1", "Moderator"), Role("r2", "VIP"), Role("r0", "everyone")


class Settings:
    def __init__(self):
        self.d = {}

    async def get(self, g, k, default=None):
        return self.d.get((g, k), default)

    async def set(self, g, k, v):
        self.d[(g, k)] = v


def command(name, cog=None, parent=None):
    c = SimpleNamespace(name=name.split()[-1], qualified_name=name, cog_name=cog, root_parent=parent)
    return c


@pytest.fixture
def lim():
    cmds = [command("ban", "Moderation"), command("quantum", "Quantum"), command("tickets list", "Tickets"),
            command("limit", "Limits")]
    bot = SimpleNamespace(stores=SimpleNamespace(settings=Settings()), config=SimpleNamespace(owners=["npubOwner"]),
                          add_check=lambda f: None, remove_check=lambda f: None, walk_commands=lambda: cmds,
                          cogs={"Moderation": 1, "Quantum": 1, "Tickets": 1, "Limits": 1},
                          get_command=lambda n: next((c for c in cmds if c.qualified_name == n), None),
                          find_role=lambda g, ref: next((r for r in g.roles if ref.lower() in (r.id, r.name.lower())), None))
    guild = SimpleNamespace(id="g1", owner_id="npubGuildOwner", roles=[EVERY, MOD, VIP])
    return Limits(bot), bot, guild, cmds


def ctx(guild, command, roles=(), uid="u1", admin=False):
    author = SimpleNamespace(id=uid, roles=list(roles), is_admin=lambda: admin, is_owner=lambda: False)
    return SimpleNamespace(guild=guild, command=command, author=author)


def test_most_specific_rule_wins_and_matching_is_case_insensitive():
    limits = {"Tickets": ["r1"], "tickets list": ["r2"]}
    assert rule_for(command("tickets list", "Tickets"), limits) == ("tickets list", ["r2"])
    assert rule_for(command("tickets close", "Tickets"), limits) == ("tickets", ["r1"])
    assert rule_for(command("ban", "Moderation"), limits) is None
    assert allowed(SimpleNamespace(roles=[VIP]), ["r2"]) and not allowed(SimpleNamespace(roles=[]), ["r2"])


async def test_unlimited_commands_and_dms_pass(lim):
    cog, _, guild, cmds = lim
    assert await cog.check(ctx(guild, cmds[0]))
    await cog.save(guild, "ban", ["r1"])
    assert await cog.check(SimpleNamespace(guild=None, command=cmds[0], author=None))      # DMs are never limited


async def test_a_limited_command_needs_the_role(lim):
    cog, _, guild, cmds = lim
    await cog.save(guild, "ban", ["r1"])
    assert await cog.check(ctx(guild, cmds[0], [MOD]))
    with pytest.raises(commands.CheckFailure) as err:
        await cog.check(ctx(guild, cmds[0], [VIP]))
    assert "Moderator" in str(err.value)


async def test_a_whole_module_can_be_limited_and_admins_owners_bypass(lim):
    cog, _, guild, cmds = lim
    await cog.save(guild, "Quantum", ["r2"])
    quantum = cmds[1]
    assert await cog.check(ctx(guild, quantum, [VIP]))
    with pytest.raises(commands.CheckFailure):
        await cog.check(ctx(guild, quantum, []))
    assert await cog.check(ctx(guild, quantum, [], admin=True))
    assert await cog.check(ctx(guild, quantum, [], uid="npubOwner"))
    assert await cog.check(ctx(guild, quantum, [], uid="npubGuildOwner"))


async def test_the_limit_commands_cannot_be_locked_out(lim):
    cog, _, guild, cmds = lim
    assert cog.known("limit") is None and cog.known("limits") is None
    await cog.settings.set("g1", "command_limits", {"limit": ["r1"]})
    assert await cog.check(ctx(guild, cmds[3], []))


async def test_setting_listing_and_clearing_through_chat(lim):
    cog, _, guild, _ = lim
    sent = []

    async def send(text=None, **kw):
        sent.append(kw["embed"] if "embed" in kw else text)

    c = SimpleNamespace(guild=guild, send=send, prefix="!")
    await cog.limit.callback(cog, c, "ban", roles="Moderator, VIP")
    assert (await cog.get(guild)) == {"ban": ["r1", "r2"]}
    await cog.limit.callback(cog, c, "nonsense", roles="VIP")
    assert "don't know" in sent[-1]
    await cog.limit.callback(cog, c, "ban", roles="Wizard")
    assert "No role" in sent[-1]
    await cog.limits.callback(cog, c)
    assert "Moderator, VIP" in sent[-1].description
    await cog.limit_clear.callback(cog, c, target="BAN")
    assert await cog.get(guild) == {}
    await cog.limit_clear.callback(cog, c, target="ban")
    assert "isn't limited" in sent[-1]

"""Verification features ported from GateBot: CAPTCHA links, device check, age, invite gate, softbans."""

import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from vectiq.cogs import verification as vmod
from vectiq.cogs.moderation import Moderation
from vectiq.cogs.verification import Verification
from vectiq.config import Config
from vectiq.dashboard.verify_page import add_verify_routes
from vectiq.stores.gate import canonical_fingerprint

FP = json.dumps(["v1", "UA/1", "Linux", "en", "UTC", "1x1", "24", "8", "4", "abc", "0"])


class Role:
    def __init__(self, name, pos=1):
        self.id, self.name, self.position = f"r-{name}", name, pos

    def __le__(self, other):
        return self.position <= other.position


class Perms(SimpleNamespace):
    def __getattr__(self, name):
        return False


class Member:
    def __init__(self, guild, uid, name="Sam", staff=False):
        self.guild, self.id, self.npub, self.display_name, self.name = guild, uid, uid, name, name
        self.mention, self.bot, self.roles, self.dms = f"@{name}", False, [], []
        self.kicked = self.banned = 0
        self.guild_permissions = Perms(manage_messages=staff)
        self._staff = staff

    def is_admin(self):
        return self._staff

    def is_owner(self):
        return False

    async def add_roles(self, *roles, reason=None):
        self.roles += [r for r in roles if r not in self.roles]

    async def remove_roles(self, *roles, reason=None):
        self.roles = [r for r in self.roles if r not in roles]

    async def kick(self, reason=None):
        self.kicked += 1

    async def ban(self, reason=None):
        self.banned += 1

    async def send(self, text):
        self.dms.append(text)


class Msg:
    def __init__(self, channel, text, author=None):
        self.channel, self.content, self.author = channel, text, author
        self.guild = getattr(channel, "guild", None)
        self.deleted = False

    async def delete(self, delay=None):
        self.deleted = True


class Channel:
    def __init__(self, guild, cid, name):
        self.guild, self.id, self.name, self.mention, self.sent = guild, cid, name, f"#{name}", []

    async def send(self, text=None, **kw):
        m = Msg(self, text)
        self.sent.append(m)
        return m


class Guild:
    def __init__(self, gid, name):
        self.id, self.name = gid, name
        self.default_role = Role("everyone", 0)
        self.roles, self.members, self.invited = [self.default_role], [], []
        self.system_channel = Channel(self, f"{gid}-c", "verify")
        self.text_channels = [self.system_channel]
        self.me = Member(self, "npub1bot", "Vectiq", staff=True)

    def get_member(self, uid):
        return next((m for m in self.members if m.id == uid), None)

    def get_channel(self, cid):
        return next((c for c in self.text_channels if c.id == cid), None)

    async def create_role(self, name, reason=None):
        r = Role(name)
        self.roles.append(r)
        return r

    async def invite(self, npub):
        self.invited.append(npub)

    def join(self, uid, name="Sam", **kw):
        m = Member(self, uid, name, **kw)
        self.members.append(m)
        return m


class Bot:
    def __init__(self, cfg, stores, guilds):
        self.config, self.stores, self.guilds = cfg, stores, guilds
        self.user = SimpleNamespace(id="npub1bot")
        self.events, self.cogs = [], {}

    def serves(self, g):
        return True

    def get_guild(self, gid):
        return next((g for g in self.guilds if g.id == gid), None)

    def get_cog(self, name):
        return self.cogs.get(name)

    def find_channel(self, guild, ref):
        ref = str(ref).strip().lstrip("#")
        return next((c for c in guild.text_channels if ref and ref in (c.id, c.name)), None)

    def find_role(self, guild, ref):
        return next((r for r in guild.roles if str(ref) and str(ref).lower() in (r.id, r.name.lower())), None)

    async def ensure_role(self, guild, name):
        return self.find_role(guild, name) or await guild.create_role(name)

    def emit(self, guild, kind, title, text=""):
        self.events.append((kind, title))

    def dispatch(self, *a):
        self.events.append(("dispatch", a[0]))


@pytest.fixture
def world(stores, tmp_path, monkeypatch):
    def make(extra=""):
        p = tmp_path / "config.yaml"
        p.write_text("prefix: '!'\nverification:\n  mode: captcha\n  public_url: https://v.example\n"
                     "  captcha:\n    site_key: k\n" + extra)
        cfg = Config.load(p, env={})
        lobby, home = Guild("g1", "Lobby"), Guild("g2", "Home")
        bot = Bot(cfg, stores, [lobby, home])
        cog = Verification(bot)
        bot.cogs["Verification"] = cog

        async def captcha_ok(token, ip):
            return token == "good"
        cog.check_captcha = captcha_ok
        return SimpleNamespace(bot=bot, cog=cog, g=lobby, home=home, gate=stores.gate)
    monkeypatch.setattr(vmod, "INVITE_KICK_SECONDS", 0)
    return make


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)


def token_from(member):
    return member.dms[-1].split("/verify/")[1].split()[0]


# -- the store ----------------------------------------------------------------------------

def test_fingerprint_is_bounded_and_canonical():
    assert canonical_fingerprint(FP) == json.dumps(json.loads(FP), separators=(",", ":"))
    assert canonical_fingerprint("[]") is None
    assert canonical_fingerprint("x" * 5000) is None
    assert canonical_fingerprint(json.dumps(["v2"] + ["a"] * 10)) is None
    assert canonical_fingerprint(json.dumps(["v1", "a\nb"] + ["a"] * 9)) is None


async def test_one_verification_per_device_and_marks_expire(stores):
    g = stores.gate
    h = await g.device_hashes("g", ip="1.2.3.4", cookie="c" * 32, fingerprint=FP)
    assert len(h) == 3 and all(len(x) == 64 for x in h)
    assert "1.2.3.4" not in "".join(h)
    assert await g.try_mark_device_verified("g", "a", h, days=30, is_adult=False)
    other = await g.device_hashes("g", ip="1.2.3.4", cookie=None, fingerprint=None)   # same IP only
    assert not await g.try_mark_device_verified("g", "b", other, days=30, is_adult=False)
    assert await g.is_verified("g", "a") and not await g.is_verified("g", "b")
    # another community is separate
    assert await g.try_mark_device_verified("h", "b", await g.device_hashes("h", ip="1.2.3.4", cookie=None, fingerprint=None),
                                            days=30, is_adult=False)
    # after the window the device can verify again
    await stores.db.execute("UPDATE verify_marks SET at=?", (int(time.time()) - 31 * 86400,))
    assert await g.try_mark_device_verified("g", "b", other, days=30, is_adult=True)
    assert await g.is_adult("g", "b")


async def test_links_are_single_use_newest_only_and_expire(stores):
    g = stores.gate
    old = await g.new_link("g", "u")
    new = await g.new_link("g", "u")
    assert await g.link(old, 10) is None
    assert await g.claim(new) and not await g.claim(new)
    assert (await g.link(new, 10))["used"] == 1
    t = await g.new_link("g", "v")
    await stores.db.execute("UPDATE verify_links SET created_at=? WHERE token=?", (int(time.time()) - 700, t))
    assert await g.link(t, 10) is None


async def test_softban_counts_kicks(stores):
    g = stores.gate
    await g.softban("g", "u", "spam")
    assert await g.is_softbanned("g", "u")
    assert await g.add_kick("g", "u") == 1 and await g.add_kick("g", "u") == 2
    assert await g.unsoftban("g", "u") and not await g.is_softbanned("g", "u")


# -- the flow -------------------------------------------------------------------------------

async def test_join_dms_a_private_link_and_public_notice_names_only_the_site(world):
    w = world()
    sam = w.g.join("npub1sam")
    await w.cog.on_member_join(sam)
    assert "https://v.example/verify/" in sam.dms[-1]
    notice = w.g.system_channel.sent[-1].content
    assert "v.example" in notice and "/verify/" not in notice


async def test_dm_failure_falls_back_to_a_public_link(world):
    w = world()
    sam = w.g.join("npub1sam")

    async def closed(text):
        raise RuntimeError("DMs closed")
    sam.send = closed
    await w.cog.on_member_join(sam)
    assert "https://v.example/verify/" in w.g.system_channel.sent[-1].content


async def test_captcha_success_grants_role_and_records(world):
    w = world()
    sam = w.g.join("npub1sam")
    await w.cog.send_link(w.g, sam)
    tok = token_from(sam)
    code, _ = await w.cog.finish(tok, captcha="bad", age=None, ip="1.1.1.1", cookie=None, fingerprint=FP)
    assert code == 400
    code, msg = await w.cog.finish(tok, captcha="good", age=None, ip="1.1.1.1", cookie=None, fingerprint=FP)
    assert code == 200 and "verified" in msg
    assert any(r.name == "Verified" for r in sam.roles)
    assert await w.gate.is_verified("g1", "npub1sam")
    assert ("dispatch", "vectiq_verified") in w.bot.events
    code, _ = await w.cog.finish(tok, captcha="good", age=None, ip="1.1.1.1", cookie=None, fingerprint=FP)
    assert code == 400   # used


async def test_second_account_from_same_device_is_refused_or_softbanned(world):
    for action, kicked, softbanned in (("refuse", 0, False), ("softban", 1, True)):
        w = world(f"  on_duplicate: {action}\n")
        await w.gate.reset("g1")
        a, b = w.g.join(f"npub1a{action}"), w.g.join(f"npub1b{action}")
        for m in (a, b):
            await w.cog.send_link(w.g, m)
        assert (await w.cog.finish(token_from(a), captcha="good", age=None, ip="9.9.9.9", cookie=None, fingerprint=FP))[0] == 200
        code, _ = await w.cog.finish(token_from(b), captcha="good", age=None, ip="9.9.9.9", cookie=None, fingerprint=FP)
        assert code == 403 and b.kicked == kicked
        assert await w.gate.is_softbanned("g1", b.id) is softbanned


async def test_minimum_age(world):
    w = world("  min_age: 18\n  adult_role: Adults\n")
    kid, adult = w.g.join("npub1kid"), w.g.join("npub1old")
    for m in (kid, adult):
        await w.cog.send_link(w.g, m)
    code, _ = await w.cog.finish(token_from(kid), captcha="good", age=None, ip="1", cookie=None, fingerprint=FP)
    assert code == 400
    code, _ = await w.cog.finish(token_from(kid), captcha="good", age=15, ip="1", cookie=None, fingerprint=FP)
    assert code == 403 and kid.kicked == 1 and await w.gate.is_softbanned("g1", "npub1kid")
    assert (await w.cog.finish(token_from(adult), captcha="good", age=30, ip="2", cookie=None, fingerprint=FP))[0] == 200
    assert await w.gate.is_adult("g1", "npub1old")


async def test_rejoin_restores_role_without_a_new_check(world):
    w = world()
    sam = w.g.join("npub1sam")
    await w.gate.mark_verified("g1", "npub1sam", method="captcha")
    await w.cog.on_member_join(sam)
    assert sam.dms == [] and any(r.name == "Verified" for r in sam.roles)
    sam.roles = []
    await w.cog.on_message(Msg(w.g.system_channel, "hi", sam))
    assert any(r.name == "Verified" for r in sam.roles)


async def test_gate_hides_and_softbans_spam(world):
    w = world("  gate: all\n  spam_kick: 3\n")
    sam = w.g.join("npub1sam")
    msgs = [Msg(w.g.system_channel, f"hi {i}", sam) for i in range(3)]
    for m in msgs[:2]:
        await w.cog.on_message(m)
    assert all(m.deleted for m in msgs[:2]) and len(sam.dms) == 2 and sam.kicked == 0
    await w.cog.on_message(msgs[2])
    assert sam.kicked == 1 and await w.gate.is_softbanned("g1", "npub1sam")
    # staff and the verify command pass
    mod = w.g.join("npub1mod", staff=True)
    m = Msg(w.g.system_channel, "hello", mod)
    await w.cog.on_message(m)
    assert not m.deleted


async def test_invite_gate_invites_then_removes_from_lobby(world):
    w = world("  invite_to: Home\n")
    sam = w.g.join("npub1sam")
    await w.cog.send_link(w.g, sam)
    assert "Home" in sam.dms[-1]
    code, msg = await w.cog.finish(token_from(sam), captcha="good", age=None, ip="1", cookie=None, fingerprint=FP)
    await settle()
    assert code == 200 and "Home" in msg
    assert w.home.invited == ["npub1sam"] and sam.kicked == 1
    assert await w.gate.is_verified("g2", "npub1sam") and not await w.gate.is_verified("g1", "npub1sam")


async def test_softbanned_member_is_kicked_on_sight_then_banned(world):
    w = world("  softban_escalate: 2\n")
    mod = Moderation.__new__(Moderation)
    mod.bot, mod.cfg = w.bot, w.bot.config
    sam = w.g.join("npub1sam")
    sam.roles.append(Role("Verified"))
    await w.gate.softban("g1", "npub1sam", "spam")
    await mod.on_member_join(sam)
    assert sam.kicked == 1 and sam.roles == [] and sam.banned == 0
    await mod.on_member_join(sam)
    assert sam.banned == 1


def test_warnings_explain_what_is_missing(world):
    w = world("  gate: all\n")
    w.g.me._staff = False
    w.g.me.guild_permissions = Perms()
    text = " ".join(w.cog.warnings(w.g))
    assert "Manage Roles" in text and "Kick Members" in text and "Manage Messages" in text
    assert "CAPTCHA_SECRET" in text


# -- the web page ---------------------------------------------------------------------------

async def test_page_and_submit(world):
    from fastapi import FastAPI

    w = world("  min_age: 18\n")
    sam = w.g.join("npub1sam")
    await w.cog.send_link(w.g, sam)
    tok = token_from(sam)
    app = FastAPI()
    add_verify_routes(app, w.bot)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as c:
        r = await c.get(f"/verify/{tok}")
        assert r.status_code == 200 and "Verify for Lobby" in r.text and "id=age" in r.text
        assert "challenges.cloudflare.com" in r.headers["content-security-policy"]
        assert "vq_device" in r.headers["set-cookie"] and "httponly" in r.headers["set-cookie"].lower()
        assert (await c.get("/verify/nope")).status_code == 404
        assert (await c.get("/verify-assets/verify.js")).status_code == 200
        r = await c.post(f"/verify/{tok}", data={"x": 1})
        assert r.status_code == 415
        r = await c.post(f"/verify/{tok}", json={"captcha": "good", "fingerprint": "junk", "age": 20})
        assert r.status_code == 400
        r = await c.post(f"/verify/{tok}", json={"captcha": "good", "fingerprint": FP, "age": 20})
        assert r.status_code == 200, r.text
        assert (await c.get(f"/verify/{tok}")).status_code == 400

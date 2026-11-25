"""The dashboard API against a fake bot and a real (in-memory) database."""

from __future__ import annotations

import time
from types import SimpleNamespace

import httpx
import pytest

from vectiq.config import Config
from vectiq.dashboard import schema
from vectiq.dashboard.access import clean_npub
from vectiq.dashboard.server import create_app
from vectiq.stores.dashboard import PasswordError, hash_password, verify_password

ADMIN = "npub1" + "a" * 58
MEMBER = "npub1" + "c" * 58
OWNER = "npub1" + "d" * 58
H = {"X-Requested-With": "vectiq"}


class FakePerms:
    def __init__(self, admin=False):
        self.administrator = admin
        self.manage_guild = admin


class FakeMember:
    def __init__(self, npub, name, admin=False):
        self.npub, self.id, self.display_name, self.name = npub, npub, name, name
        self.bot, self.roles, self.display_avatar = False, [], None
        self.guild_permissions = FakePerms(admin)
        self._admin = admin
        self.mention = f"nostr:{npub}"

    def is_admin(self):
        return self._admin

    def is_timed_out(self):
        return False


class FakeGuild:
    def __init__(self):
        self.id, self.name, self.owner_id = "g1", "Test Community", OWNER
        self.members = [FakeMember(ADMIN, "Ada", admin=True), FakeMember(MEMBER, "Bob"), FakeMember(OWNER, "Olga", admin=True)]
        self.text_channels, self.roles, self.capabilities = [], [], {"manage_roles": False}

    def get_member(self, npub):
        return next((m for m in self.members if m.npub == npub), None)

    def get_channel(self, cid):
        return None

    def get_role(self, rid):
        return None


class FakeBot:
    def __init__(self, config, stores):
        self.config, self.stores, self.db = config, stores, stores.db
        self.guilds = [FakeGuild()]
        self.user = SimpleNamespace(npub="npub1bot", id="npub1bot", display_name="Vectiq", display_avatar=None)
        self.command_prefix = config.prefix
        self.sent: list[tuple[str, str]] = []

    def serves(self, guild):
        return True

    def get_guild(self, gid):
        return next((g for g in self.guilds if g.id == gid), None)

    def get_cog(self, name):
        return None

    def get_user(self, npub):
        bot = self

        class U:
            async def send(self, text):
                bot.sent.append((npub, text))
        return U()


@pytest.fixture
async def env(stores, tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("prefix: '!'\nmodules:\n  dashboard: true\n")
    cfg = Config.load(p, env={})
    bot = FakeBot(cfg, stores)
    app = create_app(bot)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    yield SimpleNamespace(bot=bot, client=client, store=stores.dashboard, cfg=cfg)
    await client.aclose()


async def login(c, username="ada", password="correct horse battery"):
    return await c.post("/api/auth/login", json={"username": username, "password": password}, headers=H)


# -- passwords and accounts --------------------------------------------------------------------------


def test_password_hashing():
    h = hash_password("correct horse battery")
    assert h.startswith("scrypt$") and "correct" not in h
    assert verify_password("correct horse battery", h)
    assert not verify_password("correct horse batterY", h)
    assert not verify_password("x", "garbage")
    assert hash_password("same password!") != hash_password("same password!")   # salted


async def test_user_rules(stores):
    s = stores.dashboard
    with pytest.raises(PasswordError):
        await s.create_user("ada", ADMIN, "short")
    with pytest.raises(PasswordError):
        await s.create_user("a d a", ADMIN, "long enough password")
    with pytest.raises(PasswordError):
        await s.create_user("adalovelace", ADMIN, "AdaLovelace")
    await s.create_user("ada", ADMIN, "correct horse battery")
    with pytest.raises(PasswordError):
        await s.create_user("ADA", ADMIN, "another long password")      # usernames are case-insensitive
    assert (await s.check_login("Ada", "correct horse battery"))[0] == ADMIN


async def test_lockout_after_failures(stores):
    s = stores.dashboard
    await s.create_user("ada", ADMIN, "correct horse battery")
    for _ in range(s.LOCK_AFTER):
        assert (await s.check_login("ada", "nope nope nope"))[0] is None
    npub, why = await s.check_login("ada", "correct horse battery")
    assert npub is None and "Try again" in why                            # locked even with the right password
    await s.set_password("ada", "a brand new password")                    # resetting unlocks
    assert (await s.check_login("ada", "a brand new password"))[0] == ADMIN


def test_clean_npub():
    assert clean_npub(" nostr:" + ADMIN.upper() + " ") == ADMIN
    assert clean_npub("npub1short") is None and clean_npub("nsec1" + "a" * 58) is None


# -- the API -------------------------------------------------------------------------------------------


async def test_password_sign_in_and_session(env):
    await env.store.create_user("ada", ADMIN, "correct horse battery")
    c = env.client
    assert (await c.get("/api/me")).status_code == 401
    r = await login(c, password="wrong password!")
    assert r.status_code == 401 and r.json()["detail"] == "Wrong username or password."
    r = await login(c)
    assert r.status_code == 200
    assert "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()
    me = (await c.get("/api/me")).json()
    assert me["user"]["name"] == "Ada" and not me["owner"] and me["communities"][0]["id"] == "g1"
    assert (await c.post("/api/auth/logout", headers=H)).status_code == 200
    assert (await c.get("/api/me")).status_code == 401


async def test_unknown_user_and_non_admin(env):
    await env.store.create_user("bob", MEMBER, "correct horse battery")
    assert (await login(env.client, "nobody")).status_code == 401
    r = await login(env.client, "bob")
    assert r.status_code == 403                       # right password, but Bob manages nothing


async def test_admin_role_removed_mid_session(env):
    await env.store.create_user("ada", ADMIN, "correct horse battery")
    await login(env.client)
    env.bot.guilds[0].members[0]._admin = False
    env.bot.guilds[0].members[0].guild_permissions = FakePerms(False)
    assert (await env.client.get("/api/me")).status_code == 403


async def test_writes_need_the_header(env):
    await env.store.create_user("ada", ADMIN, "correct horse battery")
    r = await env.client.post("/api/auth/login", json={"username": "ada", "password": "correct horse battery"})
    assert r.status_code == 403                       # a cross-site form post can't add the header


async def test_security_headers(env):
    r = await env.client.get("/")
    assert r.status_code == 200 and "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"


async def test_vector_code_sign_in(env):
    c = env.client
    r = await c.post("/api/auth/request", json={"npub": ADMIN}, headers=H)
    assert r.status_code == 200 and env.bot.sent and env.bot.sent[0][0] == ADMIN
    code = env.bot.sent[0][1].split("Code: **")[1][:6]
    assert (await c.post("/api/auth/verify", json={"npub": ADMIN, "code": "000000" if code != "000000" else "111111"},
                         headers=H)).status_code == 400
    assert (await c.post("/api/auth/verify", json={"npub": ADMIN, "code": code}, headers=H)).status_code == 200
    assert (await c.post("/api/auth/verify", json={"npub": ADMIN, "code": code}, headers=H)).status_code == 400  # once
    # strangers get the same answer and no DM
    r = await c.post("/api/auth/request", json={"npub": MEMBER}, headers=H)
    assert r.status_code == 200 and len(env.bot.sent) == 1


async def test_vector_code_can_be_turned_off(env):
    env.cfg.apply_overrides({"dashboard.vector_code_login": False})
    assert (await env.client.post("/api/auth/request", json={"npub": ADMIN}, headers=H)).status_code == 403
    assert (await env.client.get("/api/auth/options")).json()["vector_code"] is False


async def test_own_account_and_password_change(env):
    c = env.client
    r = await c.post("/api/auth/request", json={"npub": ADMIN}, headers=H)
    code = env.bot.sent[-1][1].split("Code: **")[1][:6]
    await c.post("/api/auth/verify", json={"npub": ADMIN, "code": code}, headers=H)
    assert (await c.post("/api/account", json={"username": "ada", "password": "correct horse battery"},
                         headers=H)).status_code == 200
    assert (await c.post("/api/account", json={"username": "ada2", "password": "correct horse battery"},
                         headers=H)).status_code == 409
    r = await c.put("/api/account/password", json={"username": "ada", "current": "nope", "new": "x" * 12}, headers=H)
    assert r.status_code == 400
    r = await c.put("/api/account/password", json={"username": "ada", "current": "correct horse battery",
                                                   "new": "another fine password"}, headers=H)
    assert r.status_code == 200
    assert (await env.store.check_login("ada", "another fine password"))[0] == ADMIN


async def test_users_are_owner_only(env):
    await env.store.create_user("ada", ADMIN, "correct horse battery")
    await env.store.create_user("olga", OWNER, "correct horse battery")
    await login(env.client)
    assert (await env.client.get("/api/users")).status_code == 403
    owner = httpx.AsyncClient(transport=env.client._transport, base_url="http://test")
    await login(owner, "olga")                         # no owners in config: the community owner counts
    assert (await owner.get("/api/users")).status_code == 200
    r = await owner.post("/api/users", json={"username": "bob", "npub": MEMBER, "password": "correct horse battery"},
                         headers=H)
    assert r.status_code == 200 and "can't sign in" in r.json()["message"]
    assert (await owner.delete("/api/users/bob", headers=H)).status_code == 200
    await owner.aclose()


async def test_settings_overrides(env):
    await env.store.create_user("olga", OWNER, "correct horse battery")
    c = env.client
    await login(c, "olga")
    r = await c.put("/api/settings", json={"changes": {"economy.daily_amount": 500, "prefix": "?"}}, headers=H)
    assert r.status_code == 200
    assert env.cfg.get("economy.daily_amount") == 500 and env.bot.command_prefix == "?"
    assert (await env.store.overrides())["economy.daily_amount"] == 500
    bad = await c.put("/api/settings", json={"changes": {"leveling.xp_min": 900, "leveling.xp_max": 10}}, headers=H)
    assert bad.status_code == 400 and env.cfg.get("leveling.xp_min") == 15      # invalid combos change nothing
    assert (await c.put("/api/settings", json={"changes": {"nsec": "x"}}, headers=H)).status_code == 400
    r = await c.put("/api/settings", json={"changes": {"modules.games": False}}, headers=H)
    assert r.json()["restart"] == [] and "Switching off: Mini games" in r.json()["message"]   # applied live
    assert (await c.delete("/api/settings/economy.daily_amount", headers=H)).status_code == 200
    assert env.cfg.get("economy.daily_amount") == 200 and "economy.daily_amount" not in await env.store.overrides()


async def test_overview_and_members(env):
    await env.store.create_user("ada", ADMIN, "correct horse battery")
    await login(env.client)
    await env.bot.stores.levels.add_xp("g1", MEMBER, 300)
    await env.bot.stores.moderation.add("g1", MEMBER, ADMIN, "warn", "spam")
    o = (await env.client.get("/api/c/g1/overview")).json()
    assert o["community"]["members"] == 3 and o["bot_can"] == {"manage_roles": False}
    m = (await env.client.get("/api/c/g1/members?filter=warned")).json()
    assert m["total"] == 1 and m["members"][0]["warnings"] == 1 and m["members"][0]["xp"] == 300
    assert (await env.client.get("/api/c/nope/overview")).status_code == 404
    # moderation module off in the fake bot
    r = await env.client.post(f"/api/c/g1/members/{MEMBER}/action", json={"action": "warn"}, headers=H)
    assert r.status_code == 409


def test_schema_paths_exist_in_defaults():
    cfg = Config.load("config.yaml", env={})
    for path, f in schema.FIELDS.items():
        assert cfg.get(path, KeyError) is not KeyError, path
        if f["type"] == "int":
            assert isinstance(cfg.get(path), int), path


def test_coerce():
    assert schema.coerce("communities", "a\n\n b ") == ["a", "b"]
    assert schema.coerce("leveling.xp_min", "20") == 20
    for path, value in (("leveling.xp_min", -1), ("modules.games", "yes"), ("moderation.warn_action", "explode")):
        with pytest.raises(schema.FieldError):
            schema.coerce(path, value)


async def test_audit_log(env):
    await env.store.create_user("ada", ADMIN, "correct horse battery")
    await login(env.client)
    entries = (await env.client.get("/api/c/g1/audit")).json()["entries"]
    assert entries[0]["action"] == "signed in" and entries[0]["at"] <= time.time()


async def test_securitycam_page(env):
    from vectiq.cogs.securitycam import SecurityCam

    class Chan:
        def __init__(self, cid, name):
            self.id, self.name, self.category, self.sent = cid, name, None, []

        async def send(self, **kw):
            self.sent.append(kw)

    g = env.bot.guilds[0]
    cam, general = Chan("c1", "cam"), Chan("c2", "general")
    g.text_channels = [cam, general]
    g.get_channel = lambda cid: next((c for c in g.text_channels if c.id == cid), None)
    env.bot.find_channel = lambda guild, ref: next((c for c in guild.text_channels if ref in (c.id, c.name)), None)
    sc = SecurityCam(env.bot)
    env.bot.get_cog = lambda name: sc if name == "SecurityCam" else None
    await env.store.create_user("ada", ADMIN, "correct horse battery")
    await login(env.client)

    d = (await env.client.get("/api/c/g1/securitycam")).json()
    assert d["enabled"] and d["channel"] == ""
    assert (await env.client.post("/api/c/g1/securitycam/test", headers=H)).status_code == 400
    r = await env.client.put("/api/c/g1/securitycam", json={"channel": "c1", "ignore": ["c2", "nope"]}, headers=H)
    assert r.status_code == 200
    d = (await env.client.get("/api/c/g1/securitycam")).json()
    assert d["channel"] == "c1" and d["ignore"] == ["c2"]
    assert (await env.client.post("/api/c/g1/securitycam/test", headers=H)).status_code == 200
    assert cam.sent and await sc.ignored_channels(g) == ["c2"]
    await env.client.put("/api/c/g1/securitycam", json={"channel": ""}, headers=H)
    assert (await env.client.get("/api/c/g1/securitycam")).json()["channel"] == ""


async def test_setup_wizard_steps_and_new_settings(env):
    await env.store.create_user("olga", OWNER, "correct horse battery")
    c = env.client
    await login(c, "olga")
    d = (await c.get("/api/settings")).json()
    assert [s["id"] for s in d["wizard"]][:3] == ["basics", "features", "channels"]
    changes = {"moderation.log_channel": "mod-log", "verification.log_channel": "verify-log",
               "tickets.log_channel": "tickets", "welcome.leave_channel": "goodbyes", "onboarding.log_channel": "joins",
               "verification.gate": "all", "verification.min_age": 18}
    r = await c.put("/api/settings", json={"changes": changes}, headers=H)
    assert r.status_code == 200, r.text
    assert env.cfg.get("verification.gate") == "all" and env.cfg.get("tickets.log_channel") == "tickets"
    # captcha needs a site key: refused as a whole
    bad = await c.put("/api/settings", json={"changes": {"verification.mode": "captcha"}}, headers=H)
    assert bad.status_code == 400 and env.cfg.get("verification.mode") == "question"
    ok = await c.put("/api/settings", json={"changes": {"verification.mode": "captcha",
                                                         "verification.captcha.site_key": "k"}}, headers=H)
    assert ok.status_code == 200 and "Mode" in ok.json()["restart"]


async def test_import_preview_then_apply_with_a_restore_point(env, tmp_path):
    from vectiq.backup import RestorePoints

    env.cfg.data_dir = str(tmp_path)
    env.bot.restore_points = RestorePoints(env.cfg, env.bot.db)
    await env.store.create_user("olga", OWNER, "correct horse battery")
    c = env.client
    await login(c, "olga")
    exported = (await c.get("/api/settings/export")).text
    assert "prefix" in exported
    text = exported.replace("prefix: '!'", "prefix: '?'").replace('prefix: "!"', 'prefix: "?"') + "\nnonsense: 1\n"
    pre = (await c.post("/api/settings/import", json={"yaml": text}, headers=H)).json()
    assert [x["path"] for x in pre["changes"]] == ["prefix"] and env.cfg.get("prefix") == "!"
    assert any(s.startswith("nonsense") for s in pre["skipped"])
    r = await c.post("/api/settings/import", json={"yaml": text, "apply": True}, headers=H)
    assert r.status_code == 200 and env.cfg.get("prefix") == "?"
    assert env.bot.restore_points.list()[0].label == "Before importing settings"
    bad = await c.post("/api/settings/import", json={"yaml": "a: [", "apply": True}, headers=H)
    assert bad.status_code == 400


async def test_restore_points_page(env, tmp_path):
    from vectiq.backup import RestorePoints

    env.cfg.data_dir = str(tmp_path)
    env.bot.restore_points = RestorePoints(env.cfg, env.bot.db)
    await env.store.create_user("olga", OWNER, "correct horse battery")
    await env.store.create_user("ada", ADMIN, "correct horse battery")
    c = env.client
    await login(c, "ada")
    assert (await c.get("/api/restore-points")).status_code == 403          # owners only
    await login(c, "olga")
    r = await c.post("/api/restore-points", json={"label": "Before the event season"}, headers=H)
    assert r.status_code == 200
    pts = (await c.get("/api/restore-points")).json()["points"]
    assert pts[0]["label"] == "Before the event season" and pts[0]["kind"] == "manual"
    await c.put("/api/settings", json={"changes": {"prefix": "?"}, "checkpoint": "Before the setup wizard"}, headers=H)
    assert env.cfg.get("prefix") == "?"
    pid = pts[0]["id"]
    dl = await c.get(f"/api/restore-points/{pid}/download")
    assert dl.status_code == 200 and dl.headers["content-type"] == "application/zip"
    r = await c.post(f"/api/restore-points/{pid}/rollback", headers=H)
    assert r.status_code == 200, r.text
    assert env.cfg.get("prefix") == "!"                                       # settings went back too
    labels = [p["label"] for p in (await c.get("/api/restore-points")).json()["points"]]
    assert labels[0].startswith("Before rolling back") and "Before the setup wizard" in labels
    assert (await c.delete(f"/api/restore-points/{pid}", headers=H)).status_code == 200
    assert (await c.post(f"/api/restore-points/{pid}/rollback", headers=H)).status_code == 404


async def test_securitycam_live_feed_and_switch(env):
    import datetime
    from types import SimpleNamespace

    from vectiq.cogs.securitycam import SecurityCam

    g = env.bot.guilds[0]
    cam, general = SimpleNamespace(id="c1", name="cam"), SimpleNamespace(id="c2", name="general")
    g.text_channels = [cam, general]
    env.bot.find_channel = lambda guild, ref: next((c for c in guild.text_channels if ref in (c.id, c.name)), None)
    env.bot.user = SimpleNamespace(id="bot")
    sc = SecurityCam(env.bot)
    env.bot.get_cog = lambda name: sc if name == "SecurityCam" else None
    await env.store.create_user("ada", ADMIN, "correct horse battery")
    await login(env.client)

    def say(channel, text, author="u1", bot=False):
        return SimpleNamespace(guild=g, channel=channel, content=text, attachments=[SimpleNamespace(filename="a.png")],
                               author=SimpleNamespace(id=author, bot=bot, display_name="Ann", display_avatar=None),
                               created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc))

    await sc.on_message(say(general, "hello"))
    await sc.on_message(say(general, "from a bot", author="b2", bot=True))     # bots are skipped
    await sc.on_message(say(general, "mine", author="bot", bot=True))           # so is the bot itself
    await sc.on_message(say(general, "second"))
    d = (await env.client.get("/api/c/g1/securitycam/feed")).json()
    assert d["enabled"] and [e["text"] for e in d["entries"]] == ["hello", "second"] and d["last"] == 2
    assert d["entries"][0]["channel"] == "general" and d["entries"][0]["attachments"] == ["a.png"]
    later = (await env.client.get("/api/c/g1/securitycam/feed?after=1")).json()
    assert [e["text"] for e in later["entries"]] == ["second"]
    env.bot.config.data.setdefault("securitycam", {})["dashboard_feed"] = False
    assert (await env.client.get("/api/c/g1/securitycam/feed")).json()["enabled"] is False
    await sc.on_message(say(general, "unseen"))
    assert len(sc.feed["g1"]) == 2


async def test_cases_bans_and_audit_page_with_totals(env):
    await env.store.create_user("ada", ADMIN, "correct horse battery")
    await login(env.client)
    for i in range(7):
        await env.bot.stores.moderation.add("g1", "u1", "mod", "warn", f"r{i}")
    first = (await env.client.get("/api/c/g1/cases?limit=3")).json()
    assert first["total"] == 7 and [c["reason"] for c in first["cases"]] == ["r6", "r5", "r4"]
    last = (await env.client.get("/api/c/g1/cases?limit=3&offset=6")).json()
    assert [c["reason"] for c in last["cases"]] == ["r0"]
    assert (await env.client.get("/api/c/g1/cases?action=ban")).json()["total"] == 0
    audit = (await env.client.get("/api/c/g1/audit?limit=1")).json()
    assert audit["total"] >= 1 and len(audit["entries"]) == 1
    assert (await env.client.get("/api/c/g1/audit?offset=999")).json()["entries"] == []

"""Dashboard access by role: the community's owner (or a bot owner) decides which Vector roles may see or change
which parts of the dashboard."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from tests.test_dashboard import ADMIN, MEMBER, OWNER, FakeBot, FakeMember, H, login
from vectiq.config import Config
from vectiq.dashboard.access import FULL, PRESETS, area_of, clean_levels, merge
from vectiq.dashboard.server import create_app


class Role:
    def __init__(self, rid, name):
        self.id, self.name, self.colour = rid, name, 0

    def is_default(self):
        return self.id == "everyone"


@pytest.fixture
async def env(stores, tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("prefix: '!'\nmodules:\n  dashboard: true\n")
    cfg = Config.load(p, env={})
    bot = FakeBot(cfg, stores)
    g = bot.guilds[0]
    mods, helpers = Role("r-mods", "Mods"), Role("r-help", "Helpers")
    g.roles = [Role("everyone", "@everyone"), mods, helpers]
    g.get_role = lambda rid: next((r for r in g.roles if r.id == rid), None)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(bot)), base_url="http://test")
    for name, npub in (("olga", OWNER), ("ada", ADMIN), ("bob", MEMBER)):
        await stores.dashboard.create_user(name, npub, "correct horse battery")
    yield SimpleNamespace(bot=bot, g=g, client=client, mods=mods, helpers=helpers, store=stores.dashboard)
    await client.aclose()


def bob(env) -> FakeMember:
    return env.g.get_member(MEMBER)


async def save(env, rules, admins="full"):
    await login(env.client, "olga")
    r = await env.client.put("/api/c/g1/access", json={"admins": admins, "rules": rules}, headers=H)
    assert r.status_code == 200, r.text
    await env.client.post("/api/auth/logout", headers=H)


def test_areas_of_requests():
    assert area_of("GET", ["cases"]) == ("moderation", False)
    assert area_of("POST", ["members", "u1", "action"]) == ("moderation", True)
    assert area_of("POST", ["members", "u1", "xp"]) == ("leveling", True)
    assert area_of("POST", ["members", "u1", "roles"]) == ("members", True)
    assert area_of("GET", ["channels"]) == ("", False) and area_of("POST", ["channels"]) == ("structure", True)
    assert area_of("PUT", ["access"]) == (None, True) and area_of("GET", ["something-new"]) == (None, False)
    assert clean_levels("moderator") == PRESETS["moderator"] and clean_levels({"members": "admin", "nope": "view"}) == {}
    assert merge({"members": "view"}, {"members": "manage", "audit": "view"}) == {"members": "manage", "audit": "view"}


async def test_a_member_without_access_cant_sign_in_until_a_role_is_given_access(env):
    assert (await login(env.client, "bob")).status_code == 403
    bob(env).roles = [env.mods]
    await save(env, [{"role_id": "r-mods", "areas": "moderator"}])
    r = await login(env.client, "bob")
    assert r.status_code == 200
    me = (await env.client.get("/api/me")).json()
    assert me["communities"][0]["access"] == PRESETS["moderator"] and not me["communities"][0]["configure"]
    c = env.client
    assert (await c.get("/api/c/g1/audit")).status_code == 200                      # moderator: audit log to look at
    r = await c.put("/api/c/g1/securitycam", json={"channel": ""}, headers=H)
    assert r.status_code == 403 and "don't have access to Security cam" in r.json()["detail"]
    r = await c.post("/api/c/g1/announce", json={"text": "hi"}, headers=H)
    assert r.status_code == 403
    assert (await c.get("/api/c/g1/access")).status_code == 403                       # can't change who has access
    assert (await c.get("/api/c/g1/channels")).status_code != 403                     # pickers work for anyone with access


async def test_view_only_can_look_but_not_change(env):
    bob(env).roles = [env.helpers]
    await save(env, [{"role_id": "r-help", "areas": {"audit": "view", "announce": "view"}}])
    await login(env.client, "bob")
    assert (await env.client.get("/api/c/g1/audit")).status_code == 200
    r = await env.client.post("/api/c/g1/announce", json={"text": "hi"}, headers=H)
    assert r.status_code == 403 and r.json()["detail"] == "You can look at Announce but not change it."


async def test_two_roles_add_up(env):
    bob(env).roles = [env.mods, env.helpers]
    await save(env, [{"role_id": "r-mods", "areas": {"audit": "view"}}, {"role_id": "r-help", "areas": {"audit": "manage",
                                                                                                         "tickets": "view"}}])
    await login(env.client, "bob")
    access = (await env.client.get("/api/me")).json()["communities"][0]["access"]
    assert access == {"audit": "manage", "tickets": "view"}


async def test_the_owner_can_limit_community_admins(env):
    await login(env.client, "ada")
    assert (await env.client.get("/api/me")).json()["communities"][0]["access"] == FULL     # admins: full by default
    r = await env.client.get("/api/c/g1/access")
    assert r.status_code == 403 and "community's owner" in r.json()["detail"]            # even full access can't
    await env.client.post("/api/auth/logout", headers=H)
    await save(env, [], admins="viewer")
    await login(env.client, "ada")
    assert (await env.client.get("/api/c/g1/audit")).status_code == 200
    r = await env.client.post("/api/c/g1/announce", json={"text": "hi"}, headers=H)
    assert r.status_code == 403
    await env.client.post("/api/auth/logout", headers=H)
    await save(env, [], admins="none")
    assert (await login(env.client, "ada")).status_code == 403                          # no access at all now


async def test_taking_the_role_away_works_at_once(env):
    bob(env).roles = [env.mods]
    await save(env, [{"role_id": "r-mods", "areas": "moderator"}])
    await login(env.client, "bob")
    assert (await env.client.get("/api/c/g1/audit")).status_code == 200
    bob(env).roles = []
    assert (await env.client.get("/api/c/g1/audit")).status_code in (403, 404)
    assert (await env.client.get("/api/me")).status_code == 403


async def test_the_owners_page_and_its_checks(env):
    await login(env.client, "olga")
    d = (await env.client.get("/api/c/g1/access")).json()
    assert [r["name"] for r in d["roles"]] == ["Mods", "Helpers"] and d["admins"] == FULL
    assert {a["id"] for a in d["areas"]} >= {"members", "moderation", "audit"} and "moderator" in d["presets"]
    r = await env.client.put("/api/c/g1/access", json={"rules": [{"role_id": "r-gone", "areas": "full"}]}, headers=H)
    assert r.status_code == 400 and "isn't in this community" in r.json()["detail"]
    r = await env.client.put("/api/c/g1/access", json={"rules": [{"role_id": "r-mods", "areas": "viewer"},
                                                                 {"role_id": "r-mods", "areas": "full"}]}, headers=H)
    assert r.status_code == 400 and "twice" in r.json()["detail"]
    await env.client.put("/api/c/g1/access", json={"rules": [{"role_id": "r-mods", "areas": "helper"}]}, headers=H)
    assert (await env.store.access_rules())["g1"]["roles"][0]["areas"] == PRESETS["helper"]       # kept in the database
    entries = (await env.client.get("/api/c/g1/audit")).json()["entries"]
    assert entries[0]["action"] == "changed dashboard access"


async def test_rules_survive_a_restart(env, stores):
    bob(env).roles = [env.mods]
    await save(env, [{"role_id": "r-mods", "areas": "moderator"}])
    fresh = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(env.bot)), base_url="http://test")
    assert (await login(fresh, "bob")).status_code == 200
    await fresh.aclose()

"""The shared management layer (dashboard and MCP), the Channels & roles API, and the MCP tools."""

import pytest

from tests.fake_community import Guild, fake_bot
from vectiq.manage import ManageError, Manager, perms_list


@pytest.fixture
def setup():
    g = Guild()
    return g, Manager(fake_bot(g))


async def test_channels_and_categories(setup):
    g, m = setup
    cat = await m.create_category(g, "Events")
    ch = await m.create_channel(g, "🎉┊party", "text", "Events", topic="fun", private=True)
    voice = await m.create_channel(g, "Hangout", "voice", "events")
    s = m.structure(g)
    assert [c["name"] for c in s["categories"][0]["channels"]] == ["🎉┊party", "Hangout"]
    assert s["categories"][0]["channels"][0]["private"] and voice["kind"] == "voice"
    assert m.channel(g, "party").id == ch["id"]                      # loose names work
    await m.edit_channel(g, "party", name="party-time", category="", read_only=True)
    assert m.channel(g, "party-time").category_id is None and m.channel(g, "party-time").read_only
    await m.rename_category(g, cat["id"], "Socials")
    assert await m.delete_category(g, "Socials") == "Socials" and m.structure(g)["categories"] == []
    assert await m.delete_channel(g, "#party-time") == "party-time"
    with pytest.raises(ManageError, match="text, voice or forum"):
        await m.create_channel(g, "x", "stage")
    with pytest.raises(ManageError, match="no channel"):
        m.channel(g, "nope")


async def test_permissions_overwrites(setup):
    g, m = setup
    mods = await m.create_role(g, "Mods", permissions=["manage_messages", "kick_members"], colour_hex="#1abc9c",
                               hoist=True)
    r = await m.set_overwrite(g, "general", "everyone", allow=[], deny=["send_messages"])
    assert r["deny"] == ["send_messages"]
    await m.set_overwrite(g, "general", "Mods", allow=["send_messages"])
    await m.set_overwrite(g, "general", "npub1" + "a" * 58, allow=["attach_files"])
    ows = {o["name"]: o for o in m.structure(g)["channels"][0]["overwrites"]}
    assert ows["@everyone"]["deny"] == ["send_messages"] and ows["Mods"]["allow"] == ["send_messages"]
    assert ows["Ada"]["kind"] == "member"
    await m.set_overwrite(g, "general", "Mods")                     # empty resets
    assert "Mods" not in {o["name"] for o in m.structure(g)["channels"][0]["overwrites"]}
    with pytest.raises(ManageError, match="both allow and deny"):
        await m.set_overwrite(g, "general", "everyone", allow=["speak"], deny=["speak"])
    with pytest.raises(ManageError, match="unknown permission"):
        await m.set_overwrite(g, "general", "everyone", allow=["fly"])
    assert mods["name"] == "Mods"


async def test_roles(setup):
    g, m = setup
    await m.create_role(g, "Mods", permissions=["kick_members"])
    await m.create_role(g, "Helpers")
    r = await m.edit_role(g, "mods", name="Moderators", permissions=["kick_members", "ban_members"], colour_hex="#ff0000")
    assert r["name"] == "Moderators" and r["permissions"] == ["kick_members", "ban_members"]
    assert await m.order_roles(g, ["Helpers", "Moderators"]) == ["Helpers", "Moderators"]
    assert [x["name"] for x in m.structure(g)["roles"]] == ["Helpers", "Moderators"]
    assert await m.everyone_permissions(g, ["view_channel"]) == ["view_channel"]
    with pytest.raises(ManageError, match="everyone"):
        await m.delete_role(g, "everyone")
    assert await m.delete_role(g, "Helpers") == "Helpers"
    with pytest.raises(ManageError, match="colour"):
        await m.create_role(g, "x", colour_hex="green")
    assert perms_list(6) == ["manage_channels", "manage_guild"]


async def test_members_and_messages(setup):
    g, m = setup
    await m.create_role(g, "VIP")
    assert "gave VIP to Ada" == await m.give_role(g, "ada", "VIP")
    assert m.members(g, "ada")[0]["roles"] == ["VIP"]
    await m.give_role(g, "Ada", "VIP", give=False)
    assert m.members(g, "ada")[0]["roles"] == []
    m.bot.stores = type("S", (), {"moderation": type("M", (), {"add": staticmethod(_add)})()})()
    assert (await m.moderate(g, "bob", "timeout", minutes=5)).startswith("timeout")
    assert g.members[1].events[0][0] == "timeout"
    with pytest.raises(ManageError, match="minutes"):
        await m.moderate(g, "bob", "timeout")
    await m.send(g, "general", "hello")
    assert (await m.history(g, "general"))[-1]["text"] == "hello"
    with pytest.raises(ManageError, match="several communities"):
        Manager(fake_bot(g, Guild("Other", "g2"))).community("")
    assert Manager(fake_bot(g, Guild("Other", "g2"))).community("oth").name == "Other"


async def _add(*a, **k):
    return 1


async def test_mcp_tools(setup, stores):
    """The MCP server, called through a real FastMCP client."""
    from fastmcp import Client
    from fastmcp.exceptions import ToolError

    from vectiq.mcp_server import build

    g, _ = setup
    bot = fake_bot(g)
    bot.stores = stores
    bot.config = type("C", (), {"enabled": lambda self, n: False, "get": lambda self, k, d=None: d})()
    async with Client(build(bot, token=None)) as c:
        names = {t.name for t in await c.list_tools()}
        assert {"create_channel", "set_permissions", "create_role", "moderate", "send_message",
                "change_setting"} <= names
        r = await c.call_tool("create_channel", {"name": "news", "kind": "text"})
        assert r.data["name"] == "news"
        await c.call_tool("create_role", {"name": "Mods", "permissions": ["kick_members"]})
        await c.call_tool("set_permissions", {"where": "news", "target": "everyone", "deny": ["send_messages"]})
        s = (await c.call_tool("get_structure", {})).data
        assert any(ch["name"] == "news" and ch["overwrites"] for ch in s["channels"])
        with pytest.raises(ToolError, match="no channel"):
            await c.call_tool("delete_channel", {"channel": "nope"})
    log = await stores.dashboard.audit_log("g1")
    assert {e["action"] for e in log} >= {"created channel", "created role", "changed permissions"}
    async with Client(build(bot, token=None, read_only=True)) as c:
        names = {t.name for t in await c.list_tools()}
        assert "get_structure" in names and "create_channel" not in names and "send_message" not in names


async def test_mcp_token_check(tmp_path, monkeypatch):
    from vectiq.mcp_server import Token, token_for

    t = Token("vq_secret")
    assert await t.verify_token("vq_secret") and await t.verify_token("vq_wrong") is None
    cfg = type("C", (), {"get": lambda self, k, d=None: "NO_SUCH_ENV"})()
    a = token_for(cfg, str(tmp_path))
    assert a.startswith("vq_") and token_for(cfg, str(tmp_path)) == a
    assert oct((tmp_path / "mcp-token").stat().st_mode)[-3:] == "600"
    monkeypatch.setenv("NO_SUCH_ENV", "from-env")
    assert token_for(cfg, str(tmp_path)) == "from-env"


async def test_channels_and_roles_dashboard_api(stores, tmp_path):
    """The Channels & roles page's routes, signed in as a community admin."""
    import httpx

    from tests.test_dashboard import ADMIN, MEMBER, FakeBot, FakePerms, H
    from vectiq.config import Config
    from vectiq.dashboard.server import create_app

    p = tmp_path / "config.yaml"
    p.write_text("prefix: '!'\nmodules:\n  dashboard: true\n")
    bot = FakeBot(Config.load(p, env={}), stores)
    g = Guild()
    g.owner_id = "npub1" + "d" * 58
    g.members[0].npub = g.members[0].id = ADMIN
    g.members[0].guild_permissions = FakePerms(True)
    g.members[1].npub = g.members[1].id = MEMBER
    g.members[1].guild_permissions = FakePerms(False)
    bot.guilds = [g]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(bot)), base_url="http://test") as c:
        await stores.dashboard.create_user("ada", ADMIN, "correct horse battery")
        await c.post("/api/auth/login", json={"username": "ada", "password": "correct horse battery"}, headers=H)
        s = (await c.get("/api/c/g1/structure")).json()
        assert s["channels"][0]["name"] == "general" and len(s["permissions"]) == 26
        r = await c.post("/api/c/g1/categories", json={"name": "Events"}, headers=H)
        cid = r.json()["category"]["id"]
        r = await c.post("/api/c/g1/channels", json={"name": "party", "kind": "voice", "category": cid}, headers=H)
        assert r.json()["message"] == "Created #party."
        r = await c.post("/api/c/g1/roles", json={"name": "Mods", "colour": "#1abc9c", "permissions": ["kick_members"]},
                         headers=H)
        rid = r.json()["role"]["id"]
        assert (await c.put("/api/c/g1/overwrites", json={"where": "party", "target": rid, "allow": ["speak"]},
                            headers=H)).json()["message"] == "Saved Mods in party."
        assert (await c.patch(f"/api/c/g1/roles/{rid}", json={"name": "Moderators"}, headers=H)).status_code == 200
        assert (await c.put("/api/c/g1/everyone", json={"permissions": ["view_channel"]}, headers=H)).status_code == 200
        bad = await c.post("/api/c/g1/channels", json={"name": "x", "kind": "stage"}, headers=H)
        assert bad.status_code == 400 and "text, voice or forum" in bad.json()["detail"]
        s = (await c.get("/api/c/g1/structure")).json()
        assert s["categories"][0]["channels"][0]["overwrites"][0]["name"] == "Moderators"
        assert s["everyone"] == ["view_channel"]
        assert (await c.delete(f"/api/c/g1/categories/{cid}", headers=H)).status_code == 200
        log = await stores.dashboard.audit_log("g1")
        assert {"created category", "created channel", "created role", "changed permissions"} <= {e["action"] for e in log}
        # plain members can't reach it
        await stores.dashboard.create_user("bob", MEMBER, "another long password")
        await c.post("/api/auth/logout", headers=H)
        await c.post("/api/auth/login", json={"username": "bob", "password": "another long password"}, headers=H)
        assert (await c.get("/api/c/g1/structure")).status_code in (401, 403, 404)


async def test_mcp_over_http_needs_the_token(setup, stores):
    """The real transport: streamable HTTP with a bearer token, as Claude or `vectiq --mcp` connects."""
    import asyncio
    import socket

    import httpx
    import uvicorn
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    from vectiq.mcp_server import build

    g, _ = setup
    bot = fake_bot(g)
    bot.stores = stores
    bot.config = type("C", (), {"enabled": lambda self, n: False, "get": lambda self, k, d=None: d})()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(build(bot, token="vq_test").http_app(path="/mcp"), host="127.0.0.1",
                                           port=port, log_level="warning", lifespan="on"))
    server.install_signal_handlers = lambda: None
    task = asyncio.ensure_future(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.05)
        url = f"http://127.0.0.1:{port}/mcp"
        async with httpx.AsyncClient() as h:
            r = await h.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                             headers={"Accept": "application/json, text/event-stream"})
            assert r.status_code == 401
        async with Client(StreamableHttpTransport(url, headers={"Authorization": "Bearer vq_test"})) as c:
            r = await c.call_tool("list_communities", {})
            assert r.structured_content["result"][0]["name"] == "Test"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)


def test_vector_refusals_are_explained():
    from vectiq.manage import explain

    assert "Upgrading the community" in explain(RuntimeError("this community still uses the legacy roster"))
    assert explain(RuntimeError("something else")) == "something else"

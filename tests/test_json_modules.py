"""JSON modules: the format, what they do when they run, installing them into a real bot, exporting, marketplaces."""

from __future__ import annotations

import datetime
import json
from types import SimpleNamespace

import pytest

from vectiq import modules
from vectiq.config import Config
from vectiq.jsonmods import fmt
from vectiq.jsonmods.library import Library, LibraryError, discover
from vectiq.jsonmods.manager import JsonModules
from vectiq.jsonmods.market import MarketError, Marketplace
from vectiq.jsonmods.runtime import STATE, build, fill, heard

RESERVED = tuple(m.name for m in modules.BUILTIN)


def faq(**over) -> dict:
    m = {"format": "vectiq-module", "version": 1, "id": "faq", "name": "FAQ", "summary": "Answers questions",
         "release": "1.0.0", "settings": [{"key": "rules", "label": "Rules", "type": "longtext", "default": "Be kind."}],
         "commands": [{"name": "rules", "help": "Show the rules", "reply": "{mention}: {settings.rules}", "cooldown": 5}],
         "autoresponders": [{"match": "word", "phrases": ["rules"], "reply": "See {prefix}rules", "cooldown": 0}]}
    m.update(over)
    return m


CODE = {"format": "vectiq-module", "id": "codey", "name": "Codey", "summary": "Has code", "code": {
    "entry": "cog", "files": {
        "__init__.py": "",
        "helper.py": "WORD = 'pong'\n",
        "cog.py": "from vector.ext import commands\nfrom .helper import WORD\n\n"
                  "class Codey(commands.Cog):\n    @commands.command()\n    async def ping2(self, ctx):\n"
                  "        await ctx.send(WORD)\n\nasync def setup(bot):\n    await bot.add_cog(Codey())\n"}}}


@pytest.fixture
def registry():
    saved = list(modules.REGISTRY)
    yield
    modules.REGISTRY[:] = saved
    modules._publish()


# -- the format -------------------------------------------------------------------------------------------


def test_the_template_is_valid_and_clean():
    r = fmt.validate(fmt.template(), reserved=RESERVED)
    assert r.ok and not r.warnings
    assert fmt.summary(r.module)["commands"] == ["hello", "flip", "about"] and fmt.kind(r.module) == "data"


def test_broken_parts_are_skipped_with_notes_not_rejected():
    r = fmt.validate({"name": "My Thing", "commands": [
        {"name": "bad name", "reply": "x"}, {"name": "ok", "reply": "y"}, {"name": "empty"}, {"name": "OK", "reply": "z"}],
        "timers": [{"channel": "general", "at": "25:99", "reply": "x"}],
        "settings": [{"key": "n", "type": "int", "default": "seven"}]}, reserved=RESERVED)
    assert r.ok and r.module["id"] == "my_thing" and [c["name"] for c in r.module["commands"]] == ["ok"]
    notes = " ".join(r.warnings)
    for bit in ("bad name", "has no reply", "already used", "25:99", "default doesn't fit", 'no "id"', "no help text"):
        assert bit in notes, bit
    assert r.module["settings"][0]["default"] == 0 and "timers" not in r.module


def test_real_problems_are_errors():
    cases = [
        ("{nope", "valid JSON"), ([], "JSON object"), ({"commands": [{"name": "a", "reply": "b"}]}, '"name" is required'),
        ({"name": "x", "id": "leveling", "commands": [{"name": "a", "reply": "b"}]}, "built-in"),
        ({"name": "Nothing here"}, "does nothing"), ({"format": "other", "name": "x"}, '"format"'),
        ({"name": "Future", "version": 9, "commands": [{"name": "a", "reply": "b"}]}, "newer Vectiq"),
        (b" " * (fmt.MAX_FILE_BYTES + 1), "at most"),
    ]
    for raw, words in cases:
        r = fmt.validate(raw, reserved=RESERVED)
        assert not r.ok and words in " ".join(r.errors), (raw if not isinstance(raw, bytes) else "big", r.errors)


def test_code_paths_are_kept_inside_the_module():
    files = {"../up.py": "", "/abs.py": "", "a\\b.py": "", "run.sh": "", "ok/fine.py": "async def setup(bot): pass"}
    r = fmt.validate({"name": "C", "id": "cc", "code": {"entry": "ok.fine", "files": files}}, reserved=RESERVED)
    text = " ".join(r.errors)
    assert not r.ok and all(bad in text for bad in ("../up.py", "/abs.py", "a\\\\b.py", "run.sh"))
    r = fmt.validate({"name": "C", "id": "cc", "code": {"entry": "missing", "files": {"a.py": ""}}}, reserved=RESERVED)
    assert not r.ok and "no missing.py" in " ".join(r.errors)


def test_private_settings_are_marked():
    r = fmt.validate(faq(settings=[{"key": "api_token", "label": "Token", "default": "x"},
                                   {"key": "motto", "label": "Motto", "default": "hi", "private": True}]), reserved=RESERVED)
    assert all(s.get("private") for s in r.module["settings"])


# -- filling text and hearing phrases ---------------------------------------------------------------------


def test_fill_knows_only_its_own_placeholders():
    out = fill("{user} {settings.rules} {settings.nope} {__class__} {0} {args}", {"user": "Ann", "args": "x"},
               {"rules": "Be kind", "nums": [1]})
    assert out == "Ann Be kind {settings.nope} {__class__} {0} x"
    assert fill("{settings.nums}", {}, {"nums": ["a", "b"]}) == "a, b"


def test_heard():
    assert heard("contains", ["hello"], "Oh HELLO there") and heard("word", ["gm"], "gm all!")
    assert not heard("word", ["rule"], "rules") and heard("exact", ["ping"], "  Ping ")
    assert heard("startswith", ["how do"], "How do I") and heard("endswith", ["?"], "ok?") and not heard("contains", [""], "x")


# -- running ------------------------------------------------------------------------------------------------


class Out:
    def __init__(self):
        self.sent, self.reactions = [], []

    async def send(self, text=None, embed=None):
        self.sent.append(text if embed is None else embed)


def fake_bot(settings=None):
    cfg = SimpleNamespace(prefix="!", get=lambda k, d=None: {"faq": settings or {"rules": "Be kind."}}.get(k, d))
    return SimpleNamespace(config=cfg, serves=lambda g: True, get_command=lambda n: None, get_cog=lambda n: None,
                           guilds=[], find_channel=lambda g, r: None, user=SimpleNamespace(id="bot", display_name="Vectiq"))


def ctx(content="!rules", roles=(), channel="general"):
    out = Out()
    author = SimpleNamespace(id="u1", display_name="Ann", mention="@Ann", bot=False,
                             roles=[SimpleNamespace(name=r) for r in roles])
    chan = SimpleNamespace(id="c1", name=channel, send=out.send)
    guild = SimpleNamespace(id="g1", name="Home", member_count=9)

    async def react(e):
        out.reactions.append(e)

    async def nothing():
        return None

    msg = SimpleNamespace(content=content, author=author, channel=chan, guild=guild, add_reaction=react, delete=nothing)
    return SimpleNamespace(author=author, channel=chan, guild=guild, message=msg, send=out.send, out=out)


async def test_a_command_answers_with_settings_and_cools_down():
    m = fmt.validate(faq(), reserved=RESERVED).module
    cog = build(fake_bot(), m, "vectiq_json.faq")
    c = ctx()
    await cog.run_command(m["commands"][0], c, "")
    await cog.run_command(m["commands"][0], c, "")
    assert c.out.sent == ["@Ann: Be kind."]


async def test_roles_and_channels_limit_a_command():
    m = fmt.validate(faq(commands=[{"name": "staff", "help": "x", "reply": "ok", "roles": ["Mod"],
                                    "channels": ["staff-room"]}], autoresponders=None), reserved=RESERVED).module
    cog = build(fake_bot(), m, "vectiq_json.faq")
    for roles, chan, want in (([], "staff-room", "❌"), (["Mod"], "general", "❌"), (["mod"], "🛡┊Staff Room", "ok")):
        c = ctx(roles=roles, channel=chan)
        await cog.run_command(m["commands"][0], c, "")
        assert c.out.sent[-1].startswith(want), (roles, chan)


async def test_autoresponders_answer_once_and_ignore_bots_and_commands():
    m = fmt.validate(faq(autoresponders=[{"match": "word", "phrases": ["rules"], "reply": "See {prefix}rules", "react": ["📜"],
                                          "cooldown": 0}]), reserved=RESERVED).module
    cog = build(fake_bot(), m, "vectiq_json.faq")
    c = ctx("what are the rules?")
    await cog.on_message(c.message)
    assert c.out.sent == ["See !rules"] and c.out.reactions == ["📜"]
    for content, is_bot in (("rules", True), ("!rules", False), ("nothing to see", False)):
        c = ctx(content)
        c.message.author.bot = is_bot
        await cog.on_message(c.message)
        assert not c.out.sent


async def test_changing_a_timer_time_counts_from_the_new_time():
    """Seen live: the time was changed on the dashboard after the module loaded with a time already past."""
    now = datetime.datetime.now(datetime.timezone.utc)
    if now.hour < 3 or now.hour == 23:
        pytest.skip("needs room before and after now on the same day")
    settings = {"time": (now - datetime.timedelta(hours=2)).strftime("%H:%M")}
    bot = fake_bot()
    bot.config.get = lambda k, d=None: {"daily": settings}.get(k, d)
    m = fmt.validate({"name": "Daily", "id": "daily", "settings": [{"key": "time", "label": "Time", "default": "09:00"}],
                      "timers": [{"channel": "x", "at": "{settings.time}", "reply": "hi"}]}, reserved=RESERVED).module
    cog = build(bot, m, "vectiq_json.daily")
    assert cog.due(0, m["timers"][0]) is False                  # loaded after today's time: waits for tomorrow
    settings["time"] = now.strftime("%H:%M")                     # changed to right now on the dashboard
    assert cog.due(0, m["timers"][0]) is True and cog.due(0, m["timers"][0]) is False
    cog.clock.cancel()


async def test_clashing_commands_are_skipped_and_reported():
    bot = fake_bot()
    bot.get_command = lambda n: object() if n == "rules" else None
    build(bot, fmt.validate(faq(), reserved=RESERVED).module, "vectiq_json.faq")
    assert "!rules already belongs" in STATE["faq"]["skipped"][0]


async def test_timers_post_in_each_community_that_has_the_channel_in_turn():
    out = Out()
    bot = fake_bot({"chan": "chat"})
    bot.config.get = lambda k, d=None: {"daily": {"chan": "chat"}}.get(k, d)
    bot.guilds = [SimpleNamespace(id="A", name="A", member_count=1), SimpleNamespace(id="B", name="B", member_count=1)]
    bot.find_channel = lambda g, ref: SimpleNamespace(name="chat", send=out.send) if g.id == "A" and ref == "chat" else None
    m = fmt.validate({"name": "Daily", "id": "daily", "settings": [{"key": "chan", "label": "Channel", "default": "chat"}],
                      "timers": [{"channel": "{settings.chan}", "every_minutes": 60, "order": "in_turn",
                                  "replies": ["one", "two"]}]}, reserved=RESERVED).module
    cog = build(bot, m, "vectiq_json.daily")
    assert await cog.post(0, m["timers"][0]) == 1 and await cog.post(0, m["timers"][0]) == 1
    assert out.sent == ["one", "two"]
    assert cog.due(0, m["timers"][0], now=0) is False and cog.due(0, m["timers"][0], now=3601) is True
    cog.clock.cancel()


async def test_a_daily_time_that_already_passed_waits_for_tomorrow():
    now = datetime.datetime.now(datetime.timezone.utc)
    m = fmt.validate({"name": "Daily", "id": "daily", "timers": [{"channel": "x", "at": "00:00", "reply": "hi"}]},
                     reserved=RESERVED).module
    cog = build(fake_bot(), m, "vectiq_json.daily")
    right_now = {**m["timers"][0], "at": now.strftime("%H:%M")}
    assert cog.due(0, right_now) is True and cog.due(0, right_now) is False      # once a day
    if now.hour >= 3:
        earlier = {**m["timers"][0], "at": (now - datetime.timedelta(hours=3)).strftime("%H:%M")}
        assert cog.due(1, earlier) is False
    cog.clock.cancel()


# -- in a real bot ------------------------------------------------------------------------------------------


@pytest.fixture
def bot_env(tmp_path, make_bot, registry):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("prefix: '!'\n")
    cfg = Config.load(cfg_path, env={"VECTIQ_DATA_DIR": str(tmp_path / "data")})
    bot = make_bot(cfg)
    bot.is_ready = lambda: True
    return SimpleNamespace(bot=bot, cfg=cfg, jm=JsonModules(bot), lib=Library(tmp_path / "data"))


async def test_install_switches_on_and_adds_commands_and_settings(bot_env):
    e = bot_env
    done = await e.jm.install_text(json.dumps(faq()), source="file faq.module.json", by="npub1owner")
    assert "switched it on" in done["message"]
    m = modules.get("faq")
    assert m and m.source.startswith("json ") and e.cfg.enabled("faq") and e.cfg.get("faq.rules") == "Be kind."
    from vectiq.dashboard import schema

    assert "faq.rules" in schema.FIELDS and "modules.faq" in schema.FIELDS
    assert e.bot.get_command("rules") is not None and "vectiq_json.faq" in e.bot.extensions
    assert e.lib.file("faq").exists() and e.jm.installed()[0]["on"]


async def test_update_reloads_and_removal_takes_everything_away(bot_env):
    e = bot_env
    await e.jm.install_text(json.dumps(faq()), source="x", by="o")
    newer = faq(release="1.1.0", commands=[{"name": "rules", "help": "x", "reply": "v2"},
                                            {"name": "invite", "help": "x", "reply": "Join us"}],
                settings=[{"key": "rules", "label": "Rules", "type": "longtext", "default": "Be kind."},
                          {"key": "link", "label": "Link", "default": "https://example.org"}])
    done = await e.jm.install_text(json.dumps(newer), source="x", by="o")
    assert "Updated FAQ 1.1.0 and reloaded" in done["message"]
    assert e.bot.get_command("invite") is not None and e.cfg.get("faq.link") == "https://example.org"
    await e.bot.set_module("faq", False, "o")
    assert e.bot.get_command("rules") is None and e.bot.get_cog("FAQ") is None      # off = gone
    await e.bot.set_module("faq", True, "o")
    assert e.bot.get_command("rules") is not None
    await e.jm.remove("faq", by="o")
    assert modules.get("faq") is None and e.bot.get_command("rules") is None and not e.lib.file("faq").exists()


async def test_removing_a_module_that_was_switched_on_leaves_the_config_valid(bot_env):
    e = bot_env
    await e.jm.install_text(json.dumps(faq()), source="x", on=False, by="o")
    await e.jm.install_text(json.dumps(faq(id="other", name="Other", commands=[{"name": "other", "help": "x", "reply": "y"}],
                                           autoresponders=None)), source="x", on=False, by="o")
    await e.bot.set_module("faq", True, "o")                  # saved as a dashboard override
    await e.bot.set_module("other", True, "o")
    assert "modules.faq" in e.cfg.overrides
    await e.jm.remove("faq", by="o")
    assert "modules.faq" not in e.cfg.overrides and "faq" not in e.cfg.data["modules"]
    assert "modules.faq" not in await e.bot.stores.dashboard.overrides()
    await e.bot.set_module("other", False, "o")                # the rest of the config still works
    await e.jm.remove("other", by="o")
    e.cfg.validate()


async def test_installed_modules_come_back_after_a_restart(bot_env, tmp_path, registry):
    await bot_env.jm.install_text(json.dumps(faq()), source="x", by="o")
    modules.forget("faq")
    cfg = Config.load(tmp_path / "config.yaml", env={"VECTIQ_DATA_DIR": str(tmp_path / "data")})
    assert modules.get("faq") is not None and cfg.get("faq.rules") == "Be kind."


async def test_code_needs_permission_and_runs_with_its_own_files(bot_env):
    e = bot_env
    with pytest.raises(LibraryError, match="Allow modules with code"):
        await e.jm.install_text(json.dumps(CODE), source="x", by="o")
    assert not e.lib.file("codey").exists()
    e.cfg.data["marketplace"]["allow_code"] = True
    done = await e.jm.install_text(json.dumps(CODE), source="x", by="o")
    assert "It's off" in done["message"] and not e.cfg.enabled("codey")        # code never switches itself on
    await e.bot.set_module("codey", True, "o")
    assert e.bot.get_command("ping2") is not None
    await e.bot.set_module("codey", False, "o")
    assert e.bot.get_command("ping2") is None


async def test_a_plugin_with_the_same_name_is_not_replaced(bot_env, tmp_path):
    folder = tmp_path / "modules" / "faq"
    folder.mkdir(parents=True)
    (folder / "__init__.py").write_text("from vectiq.plugin import Module\nMODULE = Module(name='faq', label='Mine', "
                                        "help='h', group='Fun')\nasync def setup(bot):\n    pass\n")
    modules.discover([tmp_path / "modules"], force=True)
    with pytest.raises(LibraryError, match="already a module called faq"):
        await bot_env.jm.install_text(json.dumps(faq()), source="x", by="o")
    assert bot_env.jm.check(json.dumps(faq()))["blocked"]


async def test_export_round_trips_and_can_carry_your_settings(bot_env):
    e = bot_env
    await e.jm.install_text(json.dumps(faq(settings=[{"key": "rules", "label": "Rules", "default": "Be kind."},
                                                     {"key": "api_token", "label": "Token", "default": ""}])), source="x", by="o")
    await e.bot.set_module("faq", True, "o")
    e.cfg.data["faq"]["rules"] = "Our own rules"
    e.cfg.data["faq"]["api_token"] = "s3cret"
    plain = e.jm.export("faq")
    assert plain["settings"][0]["default"] == "Be kind." and plain == e.lib.read("faq")
    mine = e.jm.export("faq", with_settings=True)
    assert mine["settings"][0]["default"] == "Our own rules" and "s3cret" not in json.dumps(mine)
    with pytest.raises(LibraryError, match="built into Vectiq"):
        e.jm.export("leveling")


async def test_a_folder_plugin_exports_as_a_working_code_module(bot_env, tmp_path):
    e = bot_env
    d = tmp_path / "modules" / "hello"
    d.mkdir(parents=True)
    (d / "__init__.py").write_text(
        "from vectiq.plugin import Module, field\n"
        "MODULE = Module(name='hello', label='Hello', help='Says hi', group='Fun', version='2.0.1', cogs=('.cog',),\n"
        "                defaults={'word': 'hi'}, settings=(field('hello.word', 'Word', 'text'),))\n")
    (d / "cog.py").write_text("from vector.ext import commands\n\nclass H(commands.Cog):\n    @commands.command()\n"
                              "    async def hello(self, ctx):\n        await ctx.send(ctx.bot.config.get('hello.word'))\n\n"
                              "async def setup(bot):\n    await bot.add_cog(H())\n")
    (d / "__pycache__").mkdir()
    (d / "__pycache__" / "x.pyc").write_bytes(b"\0")
    modules.discover([tmp_path / "modules"], force=True)
    out = e.jm.export("hello")
    assert out["code"]["entry"] == "cog" and sorted(out["code"]["files"]) == ["__init__.py", "cog.py"]
    assert out["release"] == "2.0.1" and out["settings"] == [{"key": "word", "label": "Word", "type": "text", "default": "hi"}]
    # it installs as its own JSON module under another id and works
    e.cfg.data["marketplace"]["allow_code"] = True
    copy = {**out, "id": "hello_copy", "name": "Hello copy"}
    copy["code"] = {**out["code"], "files": {**out["code"]["files"], "cog.py": out["code"]["files"]["cog.py"].replace(
        "def hello", "def hello_again")}}
    await e.jm.install_text(json.dumps(copy), source="x", on=True, by="o")
    assert e.bot.get_command("hello_again") is not None


def test_a_broken_installed_file_is_reported_not_loaded(tmp_path, registry):
    lib = Library(tmp_path)
    lib.dir.mkdir(parents=True)
    lib.file("oops").write_text("{not json")
    assert discover(tmp_path) == []
    assert "valid JSON" in modules.PROBLEMS[str(lib.file("oops"))]


# -- marketplaces --------------------------------------------------------------------------------------------


def catalog(*mods: dict) -> tuple[dict, dict[str, bytes]]:
    files = {f"{m['id']}.module.json": fmt.dumps(fmt.validate(m, reserved=RESERVED).module).encode() for m in mods}
    entries = [{"id": n.split(".")[0], "file": n, "sha256": fmt.digest(b), "kind": "data"} for n, b in files.items()]
    return {"format": fmt.CATALOG_FORMAT, "version": 1, "modules": entries}, files


def fake_get(cat: dict, files: dict, seen: list | None = None):
    def get(url, limit):
        if seen is not None:
            seen.append(url)
        name = url.rsplit("/", 1)[1]
        if name == "catalog.json":
            return json.dumps(cat).encode()
        if name in files:
            return files[name]
        raise MarketError("not found")
    return get


async def test_marketplace_downloads_and_checks_files():
    cat, files = catalog(faq())
    seen = []
    mp = Marketplace("lucky-edgelord/aio-marketplace", "main", get=fake_get(cat, files, seen))
    m, raw, entry = await mp.download("faq")
    assert m["id"] == "faq" and fmt.digest(raw) == entry["sha256"]
    assert seen[0] == "https://raw.githubusercontent.com/lucky-edgelord/aio-marketplace/main/modules/catalog.json"
    await mp.catalog()
    assert len(seen) == 2                                     # the catalog is cached for a while


async def test_marketplace_refuses_tampered_files_odd_entries_and_bad_sources():
    cat, files = catalog(faq())
    files["faq.module.json"] = files["faq.module.json"].replace(b"Be kind", b"Be evil")
    with pytest.raises(MarketError, match="checksum"):
        await Marketplace("a/b", get=fake_get(cat, files)).download("faq")
    cat["modules"] += [{"id": "x", "file": "../../etc/passwd", "sha256": "0" * 64}, {"id": "Y", "file": "y.module.json"}]
    got = await Marketplace("a/b", get=fake_get(cat, files)).catalog()
    assert [e["id"] for e in got["modules"]] == ["faq"]
    for repo, branch in (("no slash", "main"), ("a/b", "../x"), ("https://evil.example/a", "main"), ("a/b", "")):
        with pytest.raises(MarketError):
            Marketplace(repo, branch)
    with pytest.raises(MarketError, match="no module catalog"):
        await Marketplace("a/b", get=lambda u, n: b'{"hello": 1}').catalog()


async def test_install_from_a_marketplace_and_see_updates(bot_env, monkeypatch):
    e = bot_env
    cat, files = catalog(faq())
    e.jm._market = Marketplace("lucky-edgelord/aio-marketplace", "main", get=fake_get(cat, files))
    got = await e.jm.browse()
    assert got["modules"][0]["installed_release"] == "" and not got["error"]
    await e.jm.install_from_market("faq", by="o")
    assert e.lib.source("faq")["source"] == "marketplace lucky-edgelord/aio-marketplace"
    cat2, files2 = catalog(faq(release="1.2.0"))
    e.jm._market = Marketplace("lucky-edgelord/aio-marketplace", "main", get=fake_get(cat2, files2))
    got = await e.jm.browse()
    assert got["modules"][0]["update"] is True
    await e.jm.install_from_market("faq", by="o")
    assert (await e.jm.browse())["modules"][0]["update"] is False


# -- MCP --------------------------------------------------------------------------------------------------


async def test_an_assistant_can_write_check_add_and_remove_a_module(bot_env):
    from fastmcp import Client
    from fastmcp.exceptions import ToolError

    from vectiq.mcp_server import build

    e = bot_env
    async with Client(build(e.bot, token=None)) as c:
        guide = (await c.call_tool("module_format_guide", {})).data
        assert "vectiq-module" in guide["instructions"] and guide["example"]["id"] == "hello_world"
        text = json.dumps(faq())
        checked = (await c.call_tool("check_module_json", {"module_json": text})).data
        assert checked["ok"] and checked["module"]["commands"] == ["rules"]
        added = (await c.call_tool("add_module_json", {"module_json": text})).data
        assert "switched it on" in added["message"] and e.bot.get_command("rules") is not None
        exported = (await c.call_tool("export_module_json", {"name": "faq"})).data
        assert json.loads(exported)["id"] == "faq"
        with pytest.raises(ToolError, match="Allow modules with code"):
            await c.call_tool("add_module_json", {"module_json": json.dumps(CODE)})
        await c.call_tool("remove_json_module", {"module_id": "faq"})
        assert e.bot.get_command("rules") is None
    async with Client(build(e.bot, token=None, read_only=True)) as c:
        names = {t.name for t in await c.list_tools()}
        assert "check_module_json" in names and "add_module_json" not in names and "remove_json_module" not in names


# -- pictures --------------------------------------------------------------------------------------------------


def test_icons_and_images_come_only_from_the_marketplace():
    base = {"format": fmt.FORMAT, "version": 1, "id": "pics", "name": "Pics", "summary": "s",
            "commands": [{"name": "p", "help": "h", "reply": "x"}]}
    ok = fmt.validate({**base, "icon": "🎱", "images": ["media/pics/a.webp",
                                                       {"src": "media/pics/b.png", "caption": "Hello"}]})
    assert ok.ok and ok.module["icon"] == "🎱" and not ok.warnings
    assert ok.module["images"] == [{"src": "media/pics/a.webp", "caption": ""}, {"src": "media/pics/b.png", "caption": "Hello"}]
    assert fmt.summary(ok.module)["images"][1]["caption"] == "Hello"
    bad = fmt.validate({**base, "icon": "<img src=x>", "images": ["https://example.com/x.png", "media/../secret.png",
                                                                 "media/x.svg", {"src": 5}, *["media/p/x.png"] * 8]})
    assert bad.ok and "icon" not in bad.module and len(bad.module["images"]) == fmt.MAX_IMAGES
    assert sum("skipped" in w for w in bad.warnings) >= 4 and any("icon" in w for w in bad.warnings)
    assert fmt.validate({**base, "icon": "media/pics/icon.png"}).module["icon"] == "media/pics/icon.png"


async def test_the_catalog_keeps_safe_pictures_and_says_where_they_are():
    cat, files = catalog(faq())
    cat["modules"][0].update(icon="javascript:alert(1)", images=[{"src": "media/faq/a.png", "caption": "x" * 500},
                                                                  {"src": "//evil/x.png"}, "media/faq/b.png"])
    got = await Marketplace("a/b", get=fake_get(cat, files)).catalog()
    e = got["modules"][0]
    assert got["media"] == "https://raw.githubusercontent.com/a/b/main/modules/"
    assert e["icon"] == "" and e["images"] == [{"src": "media/faq/a.png", "caption": "x" * 160}]


async def test_installed_modules_know_where_their_pictures_are(bot_env):
    e = bot_env
    assert e.jm.media_for("marketplace lucky-edgelord/aio-marketplace").endswith("/lucky-edgelord/aio-marketplace/main/modules/")
    assert e.jm.media_for("file pasted") == "" and e.jm.media_for("marketplace ../x") == ""


def test_a_cog_inside_a_code_module_belongs_to_that_module(registry):
    modules.register(modules.Module(name="picsy", label="Picsy", help="h", group="Fun", cogs=("vectiq_json.picsy",)))
    assert modules.owner_of("vectiq_json.picsy") == modules.owner_of("vectiq_json.picsy.cog") == "picsy"
    assert modules.owner_of("vectiq_json.picsyx.cog") == "cog"

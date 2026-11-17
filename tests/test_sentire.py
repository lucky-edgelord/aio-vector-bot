"""Sentire as a module: its sentinel.toml, supervising the process, and its dashboard page."""

import asyncio
import os
import stat
import sys

import pytest
import tomllib

from vectiq.config import Config, ConfigError
from vectiq.sentire import config as sconf
from vectiq.sentire.install import find_binary, identity
from vectiq.sentire.process import Sidecar
from vectiq.sentire.toml import dumps

NPUB = "npub1" + "q" * 58

FAKE = f"""#!{sys.executable}
import os, sys, time, signal
signal.signal(signal.SIGTERM, lambda *a: (print("bye", flush=True), sys.exit(0)))
cfg = open(sys.argv[1]).read()
print("key set" if os.environ.get("SENTINEL_NSEC", "").startswith("nsec1") else "key missing", flush=True)
print("HOME=" + os.environ.get("HOME", ""), flush=True)
print("Sentinel online as {NPUB}", flush=True)
print("armed warn" if "warn = true" in cfg else "unarmed", flush=True)
if os.environ.get("CRASH"):
    sys.exit(3)
while True:
    time.sleep(0.2)
"""


def fake_binary(tmp_path):
    path = tmp_path / "sentinel"
    path.write_text(FAKE)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def test_sentinel_toml_from_settings():
    cfg = {"arm": {"warn": True, "delete": True}, "banned_words": ["darn", "*heck*"], "blocked_links": ["*.Evil.com"],
           "vision": {"enabled": True, "model": "gemma"}, "raid": {"response": "ban"},
           "extra": {"limits": {"max_actions_per_hour": 50}, "bot": {"profile": {"about": "hi"}}}}
    data = sconf.build(cfg, communities=["abc"], mod_channel="mod-log")
    parsed = tomllib.loads(dumps(data))
    assert parsed["bot"]["nsec_env"] == "SENTINEL_NSEC" and parsed["bot"]["communities"] == ["abc"]
    assert parsed["bot"]["mod_channel"] == "mod-log" and parsed["bot"]["profile"] == {"name": "Sentire", "about": "hi"}
    assert parsed["arm"] == {"warn": True, "delete": True, "kick": False, "ban": False, "raid": False}
    assert parsed["rules"]["words"][0]["patterns"] == ["darn", "*heck*"]
    assert parsed["rules"]["links"][0]["domains"] == ["evil.com"]
    assert [s["response"] for s in parsed["ladder"]["steps"]] == ["warn", "kick", "ban"]
    assert parsed["vision"]["enabled"] and parsed["vision"]["communities"] == ["abc"]
    assert parsed["limits"]["max_actions_per_hour"] == 50 and parsed["raid"]["response"] == "ban"
    assert sconf.build({}, communities=[])["vision"] == {"enabled": False}
    assert sconf.build({}, communities=[])["bot"]["communities"] == ["*"]


def test_bad_settings_are_refused_before_sentire_sees_them(tmp_path):
    assert sconf.problems({"ladder": {"warn_at": 5, "kick_at": 3, "ban_at": 9}})
    p = tmp_path / "config.yaml"
    p.write_text("sentire:\n  raid:\n    response: explode\n")
    with pytest.raises(ConfigError, match="raid.response"):
        Config.load(p, env={})


def test_identity_is_made_once_and_kept_private(tmp_path):
    a = identity(str(tmp_path))
    assert a.startswith("nsec1") and identity(str(tmp_path)) == a
    mode = os.stat(tmp_path / "sentire" / "identity.env").st_mode
    assert not mode & (stat.S_IRGRP | stat.S_IROTH)


def test_finding_the_program(tmp_path):
    assert find_binary("", str(tmp_path)) is None or find_binary("", str(tmp_path)).name in ("sentinel", "sentire")
    b = fake_binary(tmp_path)
    assert find_binary(str(b), str(tmp_path)) == b.resolve()


async def test_sidecar_runs_reports_and_stops(tmp_path):
    b = fake_binary(tmp_path)
    conf = tmp_path / "sentinel.toml"
    sconf.write(conf, sconf.build({"arm": {"warn": True}}, communities=["x"]))
    sc = Sidecar(b, conf, {"SENTINEL_NSEC": "nsec1test", "HOME": str(tmp_path)})
    sc.start()
    for _ in range(50):
        if sc.npub:
            break
        await asyncio.sleep(0.1)
    await asyncio.sleep(0.3)
    assert sc.running and sc.npub == NPUB
    text = "\n".join(sc.lines)
    assert "key set" in text and f"HOME={tmp_path}" in text and "armed warn" in text
    await sc.stop()
    assert not sc.running and "bye" in "\n".join(sc.lines)


async def test_sidecar_restarts_after_a_crash(tmp_path, monkeypatch):
    b = fake_binary(tmp_path)
    conf = tmp_path / "sentinel.toml"
    sconf.write(conf, sconf.build({}, communities=[]))
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep())
    sc = Sidecar(b, conf, {"SENTINEL_NSEC": "nsec1test", "CRASH": "1"})
    sc.start()
    for _ in range(200):
        if sc.restarts >= 2:
            break
        await _real_sleep(0.05)
    await sc.stop()
    assert sc.restarts >= 2 and "Sentire stopped (exit 3)" in "\n".join(sc.lines)


_real_sleep = asyncio.sleep


def _fast_sleep():
    async def sleep(seconds, *a, **k):
        await _real_sleep(min(seconds, 0.01))
    return sleep


async def test_module_runs_sentire_and_draws_its_page(tmp_path, make_bot):
    b = fake_binary(tmp_path)
    p = tmp_path / "config.yaml"
    p.write_text(f"modules:\n  sentire: true\nsentire:\n  binary: {b}\n  arm:\n    warn: true\n")
    cfg = Config.load(p, env={"VECTIQ_DATA_DIR": str(tmp_path / "data")})
    assert not cfg.enabled("sentire_official")           # one Sentire at a time
    bot = make_bot(cfg)
    bot.is_ready = lambda: True
    await bot.sync_modules()
    cog = bot.get_cog("Sentire")
    for _ in range(50):
        if cog.sidecar and cog.sidecar.npub:
            break
        await asyncio.sleep(0.1)
    st = cog.status()
    assert st["running"] and st["npub"] == NPUB and st["armed"] == ["warn"]
    toml = tomllib.loads((tmp_path / "data" / "sentire" / "sentinel.toml").read_text())
    assert toml["arm"]["warn"] is True
    panel = await cog.dashboard_panel(None, "npub1owner")
    kinds = [s["type"] for s in panel["sections"]]
    assert kinds[0] == "status" and "log" in kinds and panel["refresh"]
    assert any("Sentinel online" in line for line in next(s for s in panel["sections"] if s["type"] == "log")["lines"])
    assert bot.get_command("sentire restart").checks and bot.get_command("sentire invite").checks
    await bot.unload_extension("vectiq.cogs.sentire")    # switching the module off stops the program
    assert not cog.sidecar.running


async def test_without_the_program_it_says_how_to_install(tmp_path, make_bot, monkeypatch):
    monkeypatch.setattr("vectiq.cogs.sentire.find_binary", lambda *a: None)
    p = tmp_path / "config.yaml"
    p.write_text("modules:\n  sentire: true\n")
    cfg = Config.load(p, env={"VECTIQ_DATA_DIR": str(tmp_path / "data")})
    bot = make_bot(cfg)
    bot.is_ready = lambda: True
    await bot.sync_modules()
    await asyncio.sleep(0.05)
    st = bot.get_cog("Sentire").status()
    assert not st["running"] and "--install-sentire" in st["error"]


async def test_dashboard_panel_api(stores, tmp_path):
    """Any module's page: listed in /api/me, drawn by /api/panel, buttons through /action."""
    import httpx
    from tests.test_dashboard import ADMIN, FakeBot, H

    from vectiq.dashboard.server import create_app

    class Widget:
        dashboard_page = {"label": "Widget", "icon": "★", "scope": "community"}
        pressed = []

        async def dashboard_panel(self, guild, viewer):
            return {"title": "Widget", "sections": [
                {"type": "status", "items": [{"label": "Count", "value": len(self.pressed)}]},
                {"type": "actions", "items": [{"id": "press", "label": "Press"},
                                              {"id": "wipe", "label": "Wipe", "owner": True}]}]}

        async def dashboard_action(self, action, guild, viewer, data):
            if action == "boom":
                raise RuntimeError("nope")
            self.pressed.append((action, guild.id))
            return "Pressed."

    p = tmp_path / "config.yaml"
    p.write_text("prefix: '!'\nmodules:\n  dashboard: true\n")
    cfg = Config.load(p, env={})
    bot = FakeBot(cfg, stores)
    w = Widget()
    bot.cogs = {"Widget": w}
    app = create_app(bot)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await stores.dashboard.create_user("ada", ADMIN, "correct horse battery")
        await c.post("/api/auth/login", json={"username": "ada", "password": "correct horse battery"}, headers=H)
        me = (await c.get("/api/me")).json()
        name = me["panels"][0]["module"]
        assert me["panels"][0]["label"] == "Widget"
        panel = (await c.get(f"/api/panel/{name}?gid=g1")).json()
        actions = next(s for s in panel["sections"] if s["type"] == "actions")["items"]
        assert [a["id"] for a in actions] == ["press"]          # owner-only buttons are hidden from admins
        r = await c.post(f"/api/panel/{name}/action/press", json={"gid": "g1"}, headers=H)
        assert r.json()["message"] == "Pressed." and w.pressed == [("press", "g1")]
        assert (await c.post(f"/api/panel/{name}/action/wipe", json={"gid": "g1"}, headers=H)).status_code == 403
        assert (await c.post(f"/api/panel/{name}/action/boom", json={"gid": "g1"}, headers=H)).status_code == 404
        assert (await c.get(f"/api/panel/{name}")).status_code == 400          # community page needs a community
        assert (await c.get("/api/panel/nothing?gid=g1")).status_code == 404


def test_main_still_starts_the_bot_after_the_sentire_flag(monkeypatch, tmp_path):
    """Regression: `from .sentire.install import build` inside main() shadowed the bot's build()."""
    import vectiq.__main__ as entry

    called = {}

    async def fake_build(config):
        called["built"] = True
        raise SystemExit(0)

    monkeypatch.setattr(entry, "build", fake_build)          # must exist at module level
    monkeypatch.setenv("VECTOR_NSEC", "nsec1placeholder")
    p = tmp_path / "config.yaml"
    p.write_text("prefix: '!'\n")
    with pytest.raises(SystemExit):
        entry.main(["--config", str(p)])
    assert called.get("built")

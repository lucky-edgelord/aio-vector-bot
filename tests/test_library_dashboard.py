"""The Marketplace page's API, against a real bot (no network): owners only, checking, installing, exporting."""

from __future__ import annotations

import json

import httpx
import pytest

from tests.test_json_modules import faq
from vectiq import modules
from vectiq.config import Config
from vectiq.dashboard.server import create_app
from vectiq.jsonmods import fmt
from vectiq.jsonmods.market import MarketError, Marketplace

OWNER = "npub1" + "d" * 58
OTHER = "npub1" + "e" * 58
H = {"X-Requested-With": "vectiq"}


@pytest.fixture
async def dash(tmp_path, make_bot, db):
    saved = list(modules.REGISTRY)
    p = tmp_path / "config.yaml"
    p.write_text(f"prefix: '!'\nowners: [{OWNER}, {OTHER}]\n")
    cfg = Config.load(p, env={"VECTIQ_DATA_DIR": str(tmp_path / "data")})
    bot = make_bot(cfg)
    bot.is_ready = lambda: True
    app = create_app(bot)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    await bot.stores.dashboard.create_user("olga", OWNER, "correct horse battery")
    r = await client.post("/api/auth/login", json={"username": "olga", "password": "correct horse battery"}, headers=H)
    assert r.status_code == 200, r.text
    yield client, bot, cfg
    await client.aclose()
    modules.REGISTRY[:] = saved
    modules._publish()


async def test_only_owners_get_in(dash, tmp_path):
    client, bot, cfg = dash
    cfg.data["owners"] = [OTHER]                              # Olga is no longer an owner
    for method, url in (("GET", "/api/library"), ("GET", "/api/library/browse"), ("POST", "/api/library/check"),
                        ("POST", "/api/library/install"), ("DELETE", "/api/library/faq"), ("GET", "/api/library/export/faq")):
        r = await client.request(method, url, json={}, headers=H)
        assert r.status_code in (401, 403), (url, r.status_code)


async def test_check_install_toggle_export_remove(dash):
    client, bot, cfg = dash
    text = json.dumps(faq())
    c = (await client.post("/api/library/check", json={"text": text}, headers=H)).json()
    assert c["ok"] and c["module"]["commands"] == ["rules"] and not c["blocked"]
    bad = (await client.post("/api/library/check", json={"text": "{"}, headers=H)).json()
    assert not bad["ok"] and "valid JSON" in bad["errors"][0]
    r = await client.post("/api/library/install", json={"text": text, "filename": "faq.module.json"}, headers=H)
    assert r.status_code == 200 and "switched it on" in r.json()["message"]
    assert bot.get_command("rules") is not None
    lib = (await client.get("/api/library")).json()
    assert lib["installed"][0]["id"] == "faq" and lib["installed"][0]["on"] and lib["installed"][0]["settings"]
    assert json.loads(lib["template"])["format"] == "vectiq-module" and "JSON" in lib["prompt"]
    r = await client.put("/api/settings", json={"changes": {"faq.rules": "No spam."}}, headers=H)   # its own setting
    assert r.status_code == 200 and cfg.get("faq.rules") == "No spam."
    r = await client.get("/api/library/export/faq?settings=true")
    assert r.status_code == 200 and "faq.module.json" in r.headers["content-disposition"]
    assert r.json()["settings"][0]["default"] == "No spam."
    r = await client.delete("/api/library/faq", headers=H)
    assert r.status_code == 200 and bot.get_command("rules") is None
    audit = [row["action"] for row in await bot.stores.dashboard.audit_log("", 20)]
    assert "installed a module" in audit and "removed a module" in audit


async def test_code_modules_are_refused_until_allowed(dash):
    client, bot, cfg = dash
    from tests.test_json_modules import CODE

    c = (await client.post("/api/library/check", json={"text": json.dumps(CODE)}, headers=H)).json()
    assert c["ok"] and "Allow modules with code" in c["blocked"]
    assert c["module"]["files"] == ["__init__.py", "cog.py", "helper.py"]
    r = await client.post("/api/library/install", json={"text": json.dumps(CODE)}, headers=H)
    assert r.status_code == 400 and "Allow modules with code" in r.json()["detail"]
    r = await client.put("/api/settings", json={"changes": {"marketplace.allow_code": True}}, headers=H)
    assert r.status_code == 200
    r = await client.post("/api/library/install", json={"text": json.dumps(CODE)}, headers=H)
    assert r.status_code == 200 and "It's off" in r.json()["message"]


async def test_browse_preview_and_install_from_a_marketplace(dash, monkeypatch):
    client, bot, cfg = dash
    raw = fmt.dumps(fmt.validate(faq(), reserved=()).module).encode()
    cat = {"format": "vectiq-catalog", "version": 1, "modules": [
        {"id": "faq", "file": "faq.module.json", "sha256": fmt.digest(raw), "name": "FAQ", "group": "Community",
         "kind": "data", "release": "1.0.0", "summary": "Answers", "commands": ["rules"]}]}

    def get(url, limit):
        if url.endswith("catalog.json"):
            return json.dumps(cat).encode()
        if url.endswith("faq.module.json"):
            return raw
        raise MarketError("not found")

    real = Marketplace.__init__
    monkeypatch.setattr(Marketplace, "__init__", lambda self, repo, branch="main", **_: real(self, repo, branch, get=get))
    d = (await client.get("/api/library/browse")).json()
    assert not d["error"] and d["modules"][0]["id"] == "faq" and d["groups"] == ["Community"]
    p = (await client.post("/api/library/preview", json={"id": "faq"}, headers=H)).json()
    assert p["ok"] and p["module"]["name"] == "FAQ"
    r = await client.post("/api/library/install", json={"id": "faq"}, headers=H)
    assert r.status_code == 200 and bot.get_command("rules") is not None
    d = (await client.get("/api/library/browse")).json()
    assert d["modules"][0]["installed_release"] == "1.0.0" and d["modules"][0]["update"] is False
    r = await client.post("/api/library/install", json={"id": "nothing"}, headers=H)
    assert r.status_code == 400 and "no module nothing" in r.json()["detail"]


async def test_an_unreachable_marketplace_is_explained(dash, monkeypatch):
    client, bot, cfg = dash

    def offline(url, limit):
        raise MarketError("couldn't reach GitHub (timed out)")

    real = Marketplace.__init__
    monkeypatch.setattr(Marketplace, "__init__", lambda self, repo, branch="main", **_: real(self, repo, branch, get=offline))
    d = (await client.get("/api/library/browse")).json()
    assert d["modules"] == [] and "couldn't reach GitHub" in d["error"]

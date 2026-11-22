"""Restore points (System Restore-style) and settings import/export."""

import argparse
import zipfile

import pytest
import yaml

from vectiq.__main__ import _config_files
from vectiq.backup import RestorePoints, cli
from vectiq.config import Config
from vectiq.config_io import ImportError_, export_yaml, parse, plan
from vectiq.dashboard import schema
from vectiq.db import Database
from vectiq.stores import Stores

BASE = open("config.yaml").read()


@pytest.fixture
async def setup(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(BASE)
    data = tmp_path / "data"
    monkeypatch.setenv("VECTIQ_DATA_DIR", str(data))
    cfg = Config.load(tmp_path / "config.yaml", env={"VECTIQ_DATA_DIR": str(data)})
    db = await Database(cfg.db_path).connect()
    yield cfg, db, Stores(db), RestorePoints(cfg, db)
    await db.close()


async def test_points_hold_everything_but_the_key(setup):
    cfg, db, stores, rp = setup
    (rp._pictures()).mkdir(parents=True)
    (rp._pictures() / "1.png").write_bytes(b"png")
    p = await rp.create("Before the event season")
    assert p.kind == "manual" and p.label == "Before the event season" and p.schema > 0
    with zipfile.ZipFile(rp.path(p)) as z:
        names = set(z.namelist())
    assert {"manifest.json", "vectiq.db", "config.yaml", "settings-export.yaml", "event-images/1.png"} <= names
    assert not any(".env" in n for n in names)
    assert rp.get("1").id == p.id and rp.get(p.id).id == p.id and rp.get("9") is None


async def test_rollback_goes_back_live_and_can_be_undone(setup):
    cfg, db, stores, rp = setup
    await stores.economy.adjust("g", "u", 500, "test")
    before = await rp.create("Rich")
    await stores.economy.adjust("g", "u", -400, "spent")
    (rp._pictures()).mkdir(parents=True, exist_ok=True)
    (rp._pictures() / "new.png").write_bytes(b"x")
    assert ((await stores.economy.wallet("g", "u")).balance) < 500

    r = await rp.rollback(before)
    assert r["database"] and (await stores.economy.wallet("g", "u")).balance >= 500     # same connection, new contents
    assert not (rp._pictures() / "new.png").exists()
    undo = rp.get(r["undo"])
    assert undo.kind == "automatic" and "Before rolling back" in undo.label

    await rp.rollback(undo)                                                   # and back again
    assert ((await stores.economy.wallet("g", "u")).balance) < 500


async def test_rollback_restores_config_yaml(setup):
    cfg, db, stores, rp = setup
    p = await rp.create("Original")
    cfg_path = cfg.path
    cfg_path.write_text(BASE + "\n# changed\n")
    await rp.rollback(p)
    assert cfg_path.read_text() == BASE


async def test_newer_restore_points_are_refused(setup, tmp_path):
    cfg, db, stores, rp = setup
    p = await rp.create("x")
    import sqlite3
    with zipfile.ZipFile(rp.path(p)) as z:
        z.extract("vectiq.db", tmp_path / "x")
    con = sqlite3.connect(tmp_path / "x" / "vectiq.db")
    con.execute("PRAGMA user_version = 999")
    con.close()
    with pytest.raises(ValueError, match="newer version"):
        await db.restore_from(tmp_path / "x" / "vectiq.db")


async def test_pruning_keeps_manual_and_automatic_apart(setup):
    cfg, db, stores, rp = setup
    cfg.apply_overrides({"backup.keep_automatic": 2, "backup.keep_manual": 1})
    for i in range(4):
        await rp.create(f"auto {i}", "scheduled")
    await rp.create("mine 1")
    await rp.create("mine 2")
    kinds = [p.kind for p in rp.list()]
    assert kinds.count("scheduled") == 2 and kinds.count("manual") == 1
    assert rp.list()[0].label == "mine 2"


async def test_cli_backup_list_restore(setup, capsys):
    cfg, db, stores, rp = setup
    await db.close()
    ns = argparse.Namespace(backup="Before upgrade", list_backups=False, restore=None, yes=True)
    assert await cli(cfg, ns) == 0
    ns = argparse.Namespace(backup=None, list_backups=True, restore=None, yes=True)
    await cli(cfg, ns)
    assert "Before upgrade" in capsys.readouterr().out
    ns = argparse.Namespace(backup=None, list_backups=False, restore="1", yes=True)
    assert await cli(cfg, ns) == 0
    assert "To undo" in capsys.readouterr().out
    await db.connect()


# -- import / export -------------------------------------------------------------------------

def test_export_has_no_key_and_reimports_cleanly(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(BASE)
    cfg = Config.load(p, env={"VECTOR_NSEC": "nsec1secret"})
    text = export_yaml(cfg)
    assert "nsec1secret" not in text and text.startswith("# Vectiq settings")
    pl = plan(cfg, parse(text))
    assert pl.changes == {} and pl.unchanged > 50


def test_import_plan_dashboard_vs_terminal(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(BASE)
    cfg = Config.load(p, env={})
    data = {"prefix": "?", "verification": {"gate": "all", "min_age": "lots"}, "nonsense": 1,
            "webhooks": {"hooks": [{"name": "x", "channel": "y"}]}, "leveling": {"rewards": {"5": "Regular"}}}
    dash = plan(cfg, data, editable=schema.FIELDS, coerce=schema.coerce)
    assert dash.changes == {"prefix": "?", "verification.gate": "all"}
    assert any("min_age" in e or "Minimum age" in e for e in dash.errors)
    assert any(s.startswith("nonsense") for s in dash.skipped)
    assert any(s.startswith("webhooks.hooks") for s in dash.skipped)
    term = plan(cfg, data)
    assert term.changes["webhooks.hooks"] == [{"name": "x", "channel": "y"}]
    assert term.changes["leveling.rewards"] == {"5": "Regular"}
    with pytest.raises(ImportError_):
        parse("- just\n- a list\n")
    with pytest.raises(ImportError_):
        parse("a: [unclosed")


async def test_cli_import_and_export(tmp_path, capsys, monkeypatch):
    data = tmp_path / "data"
    p = tmp_path / "config.yaml"
    p.write_text(BASE)
    cfg = Config.load(p, env={"VECTIQ_DATA_DIR": str(data)})
    out = tmp_path / "out.yaml"
    ns = argparse.Namespace(export_config=str(out), import_config=None, yes=True)
    assert await _config_files(cfg, ns) == 0
    exported = yaml.safe_load(out.read_text())
    exported["prefix"] = "?"
    exported["verification"]["gate"] = "channel"
    out.write_text(yaml.safe_dump(exported))
    ns = argparse.Namespace(export_config=None, import_config=str(out), yes=True)
    assert await _config_files(cfg, ns) == 0
    new = p.read_text()
    assert yaml.safe_load(new)["prefix"] == "?" and yaml.safe_load(new)["verification"]["gate"] == "channel"
    assert new.count("#") == BASE.count("#")                 # comments kept
    assert RestorePoints(cfg).list()[0].label == "Before importing out.yaml"


async def test_export_skips_old_dashboard_switches(tmp_path, capsys):
    from vectiq.db import Database
    from vectiq.stores.dashboard import DashboardStore

    p = tmp_path / "config.yaml"
    p.write_text(BASE)
    cfg = Config.load(p, env={"VECTIQ_DATA_DIR": str(tmp_path / "data")})
    db = await Database(cfg.db_path).connect()
    store = DashboardStore(db)
    await store.set_override("modules.automod", False, "npub1x")
    await store.set_override("modules.gone_plugin", True, "npub1x")
    await store.set_override("prefix", "?", "npub1x")
    await db.close()
    out = tmp_path / "out.yaml"
    assert await _config_files(cfg, argparse.Namespace(export_config=str(out), import_config=None, yes=True)) == 0
    exported = yaml.safe_load(out.read_text())
    assert exported["prefix"] == "?" and exported["modules"]["sentire"] is False
    assert "modules.gone_plugin" in capsys.readouterr().err

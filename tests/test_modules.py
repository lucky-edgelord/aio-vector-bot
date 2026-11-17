"""Every feature is a module that loads only when on, and can be switched on and off while running."""

import subprocess
import sys

from vectiq import modules
from vectiq.config import DEFAULTS, Config, upgrade_legacy
from vectiq.dashboard import schema

BUILTIN = [m.name for m in modules.BUILTIN]
ONE_PER_JOB = [m for m in BUILTIN if m != "sentire"]       # both Sentire modules do automod's job; one runs


def test_registry_matches_config_and_dashboard():
    assert set(DEFAULTS["modules"]) == set(BUILTIN)
    assert all(f"modules.{m}" in schema.FIELDS for m in modules.NAMES)
    assert all(m.group in modules.GROUPS for m in modules.REGISTRY)
    wizard_features = next(s for s in schema.WIZARD if s["id"] == "features")["paths"]
    assert wizard_features == [f"modules.{m}" for m in modules.NAMES]       # plugins included


def test_example_config_lists_every_module():
    cfg = Config.load("config.yaml", env={})
    import yaml

    raw = yaml.safe_load(open("config.yaml"))
    assert set(raw["modules"]) == set(BUILTIN)
    assert cfg.get("sentire.arm.warn") is False


async def test_switch_every_module_on_off_and_on_again(make_bot, tmp_path):
    cfg = Config.load("config.yaml", env={"VECTIQ_DATA_DIR": str(tmp_path)})
    bot = make_bot(cfg)
    for m in ONE_PER_JOB:
        cfg.data["modules"][m] = True
    r = await bot.sync_modules()
    assert r["problems"] == [] and len(r["loaded"]) == len(ONE_PER_JOB)
    assert {"Sentire (official)", "LinkSafety", "ImageGuard", "Notifications", "Music"} <= set(bot.cogs)
    for m in modules.NAMES:
        cfg.data["modules"][m] = False
    r = await bot.sync_modules()
    assert set(bot.cogs) == {"Core", "Restore points"} and len(r["unloaded"]) == len(ONE_PER_JOB)
    cfg.data["modules"]["music"] = True
    r = await bot.sync_modules()
    assert r["loaded"] == ["music"] and "Music" in bot.cogs
    await bot.sync_modules()                         # nothing changed: nothing happens
    assert set(bot.cogs) == {"Core", "Restore points", "Music"}


async def test_missing_package_is_reported_not_fatal(make_bot, tmp_path, monkeypatch):
    cfg = Config.load("config.yaml", env={"VECTIQ_DATA_DIR": str(tmp_path)})
    cfg.data["modules"]["music"] = True
    monkeypatch.setattr(modules.Module, "missing", lambda self: ["yt_dlp"] if self.name == "music" else [])
    bot = make_bot(cfg)
    r = await bot.sync_modules()
    assert "music" in r["problems"] and "Music" not in bot.cogs and "Moderation" in bot.cogs
    assert 'pip install "vectiq[music]"' in bot.module_problems["music"]


def test_modules_that_are_off_are_never_imported(tmp_path):
    code = (
        "import asyncio, sys\n"
        "from vectiq.config import Config\nfrom vectiq.db import Database\nfrom vectiq.app import VectiqBot\n"
        "async def main():\n"
        f"    cfg = Config.load('config.yaml', env={{'VECTIQ_DATA_DIR': {str(tmp_path)!r}}})\n"
        "    bot = VectiqBot(cfg, await Database(':memory:').connect())\n"
        "    await bot.sync_modules()\n"
        "    bad = [m for m in ('vectiq.cogs.music', 'vectiq.cogs.imageguard', 'vectiq.cogs.dashboard', 'yt_dlp',"
        " 'fastapi', 'vectiq.cogs.linksafety') if m in sys.modules]\n"
        "    print(bad)\n"
        "asyncio.run(main())\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip().splitlines()[-1] == "[]"


def test_old_automod_settings_become_sentire():
    """The built-in automod was replaced by Sentire: old configs switch Sentire on and keep their banned words."""
    old = {"moderation": {"warn_threshold": 2, "automod": {"enabled": True, "banned_words": ["x"]}}}
    new = upgrade_legacy(old)
    assert new["modules"]["sentire"] is True and "automod" not in new["moderation"]
    assert new["sentire"]["banned_words"] == ["x"]
    newer = upgrade_legacy({"modules": {"automod": False}, "automod": {"words": {"list": ["y"]}}})
    assert newer["modules"] == {"sentire": False} and newer["sentire"]["banned_words"] == ["y"]
    assert "automod" not in newer
    assert upgrade_legacy({"prefix": "!"}) == {"prefix": "!"}



async def test_group_checks_protect_subcommands(make_bot, tmp_path):
    """`!module off music` must be owner-only like `!module`; `!imageguard block` needs Manage Messages too."""
    cfg = Config.load("config.yaml", env={"VECTIQ_DATA_DIR": str(tmp_path)})
    for m in ONE_PER_JOB:
        cfg.data["modules"][m] = True
    bot = make_bot(cfg)
    await bot.sync_modules()
    unguarded = []
    for cog in bot.cogs.values():
        for cmd in cog.walk_commands():
            parent = getattr(cmd, "parent", None)
            if parent is not None and parent.checks and not all(c in cmd.checks for c in parent.checks):
                unguarded.append(cmd.qualified_name)
    assert unguarded == []
    assert bot.get_command("module off").checks and bot.get_command("vectiq reload").checks


def test_old_dashboard_settings_are_upgraded_not_thrown_away():
    from vectiq.config import upgrade_overrides

    used, dropped = upgrade_overrides({"modules.automod": True, "automod.words.list": ["z"], "automod.caps.percent": 70,
                                       "modules.gone_plugin": True, "prefix": "?"})
    assert used == {"modules.sentire": True, "sentire.banned_words": ["z"], "prefix": "?"}
    assert set(dropped) == {"automod.words.list", "automod.caps.percent", "modules.gone_plugin"}

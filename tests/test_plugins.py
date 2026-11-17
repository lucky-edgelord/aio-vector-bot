"""Plugins: modules found in a folder or an installed package, swapped with built-ins, reloaded while running."""

import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from vectiq import modules
from vectiq.config import Config, ConfigError
from vectiq.dashboard import schema

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "vectiq-ai-automod"

PLUGIN = '''
from vector.ext import commands
from vectiq.plugin import Module, field

MODULE = Module(name="{name}", label="{label}", help="test plugin", group="Safety", provides="{provides}",
                defaults={{"word": "hi"}}, settings=(field("{name}.word", "Word", "text"),), default=True)

class P(commands.Cog, name="{label}"):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name="{name}", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def grp(self, ctx):
        await ctx.send(self.bot.config.get("{name}.word"))

    @grp.command(name="sub")
    async def sub(self, ctx):
        pass

VERSION = 1

async def setup(bot):
    await bot.add_cog(P(bot))
'''


@pytest.fixture
def registry():
    """Put the module list back the way it was after each test."""
    saved = list(modules.REGISTRY)
    yield
    modules.REGISTRY[:] = saved
    modules._publish()


def write_plugin(folder: Path, name: str, label: str, provides: str = "") -> Path:
    d = folder / name
    d.mkdir(parents=True)
    (d / "__init__.py").write_text(textwrap.dedent(PLUGIN.format(name=name, label=label, provides=provides)))
    return d / "__init__.py"


def config_in(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(Path("config.yaml").read_text())
    return cfg


async def test_folder_plugin_is_found_listed_and_configurable(registry, tmp_path):
    write_plugin(tmp_path / "modules", "greeter", "Greeter")
    cfg = Config.load(config_in(tmp_path), env={"VECTIQ_DATA_DIR": str(tmp_path / "data")})
    m = modules.get("greeter")
    assert m and not m.builtin and m.source.startswith("folder") and m.cogs == ("vectiq_plugins.greeter",)
    assert cfg.enabled("greeter") is False                       # plugins never switch themselves on
    assert cfg.get("greeter.word") == "hi"                       # their settings section is there
    assert "greeter.word" in schema.FIELDS and "modules.greeter" in schema.FIELDS
    assert any(st["id"] == "plugin-greeter" for st in schema.WIZARD)
    assert schema.coerce("greeter.word", " yo ") == "yo"


async def test_load_reload_unload_while_running(registry, tmp_path, make_bot):
    src = write_plugin(tmp_path / "modules", "greeter", "Greeter")
    cfg = Config.load(config_in(tmp_path), env={"VECTIQ_DATA_DIR": str(tmp_path / "data")})
    bot = make_bot(cfg)
    await bot.sync_modules()
    assert "Greeter" not in bot.cogs
    await bot.set_module("greeter", True, "owner")
    assert "Greeter" in bot.cogs and bot.get_command("greeter sub").checks      # group checks reach subcommands
    src.write_text(src.read_text().replace("VERSION = 1", "VERSION = 2"))
    await bot.reload_module("greeter")
    assert sys.modules["vectiq_plugins.greeter"].VERSION == 2
    r = await bot.set_module("greeter", False, "owner")
    assert r["unloaded"] == ["greeter"] and "Greeter" not in bot.cogs


async def test_a_plugin_swaps_with_the_builtin_it_replaces(registry, tmp_path, make_bot):
    write_plugin(tmp_path / "modules", "smartmod", "Smart mod", provides="automod")
    cfg = Config.load(config_in(tmp_path), env={"VECTIQ_DATA_DIR": str(tmp_path / "data")})
    assert "sentire_official" in [m.name for m in modules.same_slot("smartmod")]
    bot = make_bot(cfg)
    await bot.set_module("sentire_official", True, "owner")
    assert "Sentire (official)" in bot.cogs
    await bot.set_module("smartmod", True, "owner")             # swap
    assert "Smart mod" in bot.cogs and "Sentire (official)" not in bot.cogs
    assert cfg.enabled("smartmod") and not cfg.enabled("sentire_official")
    await bot.set_module("sentire_official", True, "owner")     # and back
    assert "Sentire (official)" in bot.cogs and "Smart mod" not in bot.cogs


def test_two_modules_for_one_job_is_a_config_error(registry, tmp_path):
    write_plugin(tmp_path / "modules", "smartmod", "Smart mod", provides="automod")
    path = config_in(tmp_path)
    path.write_text(path.read_text().replace("  sentire: false", "  sentire: true\n  smartmod: true"))
    with pytest.raises(ConfigError, match="both do automod"):
        Config.load(path, env={"VECTIQ_DATA_DIR": str(tmp_path / "data")})


def test_broken_plugins_are_reported_not_fatal(registry, tmp_path):
    bad = tmp_path / "modules" / "broken"
    bad.mkdir(parents=True)
    (bad / "__init__.py").write_text("raise RuntimeError('oops')\n")
    (tmp_path / "modules" / "nomanifest.py").write_text("x = 1\n")
    Config.load(config_in(tmp_path), env={"VECTIQ_DATA_DIR": str(tmp_path / "data")})
    assert any("oops" in why for why in modules.PROBLEMS.values())
    assert any("MODULE" in why for why in modules.PROBLEMS.values())


def test_plugins_cant_take_a_builtin_name(registry):
    with pytest.raises(ValueError, match="built-in"):
        modules.register(modules.Module("sentire", "Fake", "x", "Safety", ("x",)))


def test_entry_point_plugins(registry, monkeypatch):
    fake = modules.Module("from_pip", "From pip", "x", "Fun", ("somepkg.cog",), default=True)
    ep = SimpleNamespace(name="from_pip", value="somepkg:MODULE", load=lambda: fake,
                         dist=SimpleNamespace(name="vectiq-from-pip", version="1.2.3"))
    monkeypatch.setattr(modules.importlib.metadata, "entry_points", lambda group: [ep])
    found = modules.discover([], force=True)
    m = modules.get("from_pip")
    assert found and m.source == "package vectiq-from-pip" and m.version == "1.2.3" and m.default is False


def test_new_module_template_loads(registry, tmp_path):
    from vectiq.plugin_template import create

    path = create("my_feature", str(config_in(tmp_path)))
    Config.load(tmp_path / "config.yaml", env={"VECTIQ_DATA_DIR": str(tmp_path / "data")})
    assert path.exists() and modules.get("my_feature").label == "My Feature"
    assert "my_feature.greeting" in schema.FIELDS


async def test_example_ai_automod(registry, monkeypatch, make_bot, tmp_path):
    """The example package from examples/ works as a drop-in replacement for automod."""
    monkeypatch.syspath_prepend(str(EXAMPLE))
    import vectiq_ai_automod
    from vectiq_ai_automod import cog as ai

    modules.register(vectiq_ai_automod.MODULE)
    assert vectiq_ai_automod.MODULE.slot == "automod"
    assert ai.parse('Sure! {"flag": true, "rule": "No spam", "reason": "ad"}')["flag"] is True
    assert ai.parse("I can't tell")["flag"] is False

    cfg = Config.load("config.yaml", env={"VECTIQ_DATA_DIR": str(tmp_path)})
    bot = make_bot(cfg)
    await bot.set_module("ai_automod", True, "owner")
    assert "AI automod" in bot.cogs and not cfg.enabled("sentire")
    calls = []
    monkeypatch.setattr(ai, "ask_model", lambda c, t: calls.append(t) or {"flag": "scam" in t, "rule": "No scams",
                                                                              "reason": ""})
    hits = []

    async def fake_enforce(bot_, message, **kw):
        hits.append(kw["reason"])

    monkeypatch.setattr(ai, "enforce", fake_enforce)
    cog = bot.get_cog("AI automod")
    ai = sys.modules[type(cog).__module__]           # the module the bot loaded (extensions load a fresh copy)
    monkeypatch.setattr(ai, "ask_model", lambda c, t: calls.append(t) or {"flag": "scam" in t, "rule": "No scams",
                                                                              "reason": ""})
    monkeypatch.setattr(ai, "enforce", fake_enforce)
    guild = SimpleNamespace(id="g")
    channel = SimpleNamespace(id="c")

    def msg(text):
        author = SimpleNamespace(id="u", bot=False, roles=[], guild_permissions=SimpleNamespace(manage_messages=False))
        return SimpleNamespace(guild=guild, channel=channel, author=author, content=text, attachments=[])

    await cog.on_message(msg("this is a totally normal chat message"))
    await cog.on_message(msg("click here for a crypto scam giveaway"))
    await cog.on_message(msg("ok"))                                      # too short for the model
    assert hits == ["No scams"] and len(calls) == 2

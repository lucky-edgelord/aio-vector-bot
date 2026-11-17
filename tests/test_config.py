import pytest

from vectiq.config import Config, ConfigError
from vectiq.utils.durations import DurationError, format_duration, parse_duration


def write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text)
    return p


def test_shipped_config_is_valid():
    cfg = Config.load("config.yaml", env={})
    assert cfg.prefix == "!" and cfg.enabled("games")


def test_defaults_fill_missing_keys(tmp_path):
    cfg = Config.load(write(tmp_path, "prefix: '?'\nleveling:\n  xp_min: 1\n  xp_max: 2\n"), env={})
    assert cfg.prefix == "?" and cfg.get("leveling.cooldown_seconds") == 60 and cfg.get("leveling.xp_min") == 1


def test_missing_file_uses_defaults(tmp_path):
    assert Config.load(tmp_path / "nope.yaml", env={}).enabled("economy")


@pytest.mark.parametrize("text", [
    "prefix: ''", "modules:\n  nonsense: true", "moderation:\n  warn_action: explode",
    "leveling:\n  xp_min: 9\n  xp_max: 3", "webhooks:\n  hooks:\n    - name: a", "webhooks:\n  hooks: nope",
    "webhooks:\n  hooks:\n    - {name: a, channel: x}\n    - {name: a, channel: y}", "- a list", "a: [unclosed",
])
def test_bad_config_is_rejected(tmp_path, text):
    with pytest.raises(ConfigError):
        Config.load(write(tmp_path, text), env={})


def test_hooks_are_exposed(tmp_path):
    cfg = Config.load(write(tmp_path, "webhooks:\n  hooks:\n    - {name: ci, channel: deploys, events: [mod]}\n"), env={})
    assert cfg.hooks[0]["name"] == "ci" and cfg.hooks[0]["events"] == ["mod"]


def test_env_supplies_secrets_not_yaml(tmp_path):
    cfg = Config.load(write(tmp_path, "prefix: '!'"), env={"VECTOR_NSEC": "nsec1x", "VECTIQ_DATA_DIR": "/d"})
    assert cfg.nsec == "nsec1x" and cfg.db_path == "/d/vectiq.db"


@pytest.mark.parametrize("text,secs", [("30", 1800), ("90m", 5400), ("1h30m", 5400), ("2d", 172800), ("45S", 45)])
def test_parse_duration(text, secs):
    assert parse_duration(text) == secs


@pytest.mark.parametrize("text", ["", "abc", "0m", "5x", "1h junk"])
def test_parse_duration_rejects(text):
    with pytest.raises(DurationError):
        parse_duration(text)


def test_format_duration():
    assert format_duration(45) == "45s" and format_duration(5400) == "1h30m" and format_duration(90000) == "1d1h"


def test_dotenv_reads_without_overriding(tmp_path):
    from vectiq.config import load_dotenv

    f = tmp_path / ".env"
    f.write_text("# comment\nA=1\nexport B='two words'\nC=\"3\"\nKEEP=new\n\nbad line\n")
    env = {"KEEP": "old"}
    assert load_dotenv(f, env) == 3
    assert env == {"KEEP": "old", "A": "1", "B": "two words", "C": "3"}
    assert load_dotenv(tmp_path / "missing", env) == 0


def test_dashboard_host_env_override(tmp_path):
    from vectiq.config import DEFAULTS, Config

    cfg = Config.load(tmp_path / "none.yaml", env={"VECTIQ_DASHBOARD_HOST": "0.0.0.0"})
    assert cfg.data["dashboard"]["host"] == "0.0.0.0"
    assert DEFAULTS["dashboard"]["host"] == "127.0.0.1"   # the shared defaults are not touched

"""The setup wizard (terminal and dashboard) and channel settings."""

from types import SimpleNamespace

import yaml

from vectiq.app import VectiqBot
from vectiq.dashboard import schema
from vectiq.wizard import run, set_value

BASE = open("config.yaml").read()


def test_every_wizard_step_uses_known_settings():
    assert all(p in schema.FIELDS for st in schema.WIZARD for p in st["paths"])
    channels = [f["path"] for f in schema.FIELDS.values() if f["type"] == "channel"]
    for p in ("moderation.log_channel", "verification.log_channel", "welcome.leave_channel", "onboarding.log_channel",
              "tickets.log_channel", "securitycam.channel", "verification.channel", "onboarding.channel"):
        assert p in channels
    assert schema.coerce("tickets.log_channel", "  mod-log ") == "mod-log"


def test_set_value_keeps_comments_and_layout():
    t = set_value(BASE, "verification.mode", "captcha")
    t = set_value(t, "verification.captcha.site_key", "abc")
    t = set_value(t, "verification.gate", "off")
    t = set_value(t, "owners", ["npub1x", "npub1y"])
    d = yaml.safe_load(t)
    assert d["verification"]["mode"] == "captcha" and d["verification"]["captcha"]["site_key"] == "abc"
    assert d["verification"]["gate"] == "off" and d["owners"] == ["npub1x", "npub1y"]
    assert t.count("#") == BASE.count("#")             # no comment lost
    assert len(t.splitlines()) == len(BASE.splitlines())
    line = next(x for x in t.splitlines() if x.startswith("  mode: captcha"))
    assert line.index("#") == next(x for x in BASE.splitlines() if x.startswith("  mode: question")).index("#")


def test_set_value_replaces_block_lists_and_adds_missing_keys():
    t = set_value("a:\n  items:\n    - x\n    - y\n  keep: 1\n", "a.items", ["z"])
    assert yaml.safe_load(t) == {"a": {"items": ["z"], "keep": 1}}
    t = set_value("a:\n  keep: 1\n", "a.b.c", True)
    assert yaml.safe_load(t) == {"a": {"keep": 1, "b": {"c": True}}}


def drive(p, reply):
    """Run the terminal wizard, answering each prompt with reply(screen_text, prompt)."""
    lines, screen = [], []

    def say(x):
        lines.append(x)
        screen.append(x)

    def ask(q):
        text = "\n".join(screen)
        screen.clear()
        return reply(text, q)
    code = run(p, ask=ask, say=say, tty=False)
    return code, "\n".join(lines)


def test_cli_wizard_walks_screen_by_screen_and_saves(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(BASE)

    def reply(text, q):
        if "What should my commands start with?" in text:
            return "?"
        if "Where should I write down warnings" in text:
            return "mod-log"
        if q.startswith("Save?"):
            return "y"
        return ""
    code, out = drive(p, reply)
    assert code == 0, out
    d = yaml.safe_load(p.read_text())
    assert d["prefix"] == "?" and d["moderation"]["log_channel"] == "mod-log"
    assert (tmp_path / "config.yaml.bak").read_text() == BASE
    assert "Vectiq › Hi! I'm Vectiq" in out and "All set!" in out
    assert "┌ Vectiq setup · Channels" in out


def test_cli_wizard_features_checklist_and_skipping(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(BASE)
    seen = []

    def reply(text, q):
        seen.append(text)
        if "Pick what I should do" in text and "[ ] Security cam" in text:
            n = next(line.split(".")[0].strip("│ ") for line in text.splitlines() if "Security cam" in line)
            return n
        if "Which channel gets a copy of every message?" in text:
            return "staff-cam"
        if q.startswith("Save?"):
            return "y"
        return "s" if "· The basics" in text else ""
    code, out = drive(p, reply)
    assert code == 0, out
    d = yaml.safe_load(p.read_text())
    assert d["modules"]["securitycam"] is True and d["securitycam"]["channel"] == "staff-cam"
    assert not any("Who owns me?" in t for t in seen)      # skipped the rest of The basics


def test_cli_wizard_back_and_bad_answers(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(BASE)
    asked = {"warn": 0}

    def reply(text, q):
        if "How many warnings before I step in?" in text:
            asked["warn"] += 1
            if asked["warn"] == 1:
                return "lots"
            if asked["warn"] == 2:
                assert "Sorry, that didn't work" in text
                return "<"
            return "5"
        if q.startswith("Save?"):
            return "y"
        return ""
    code, out = drive(p, reply)
    assert code == 0 and asked["warn"] == 3
    assert yaml.safe_load(p.read_text())["moderation"]["warn_threshold"] == 5


def test_cli_wizard_refuses_invalid_combinations(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(BASE)

    def reply(text, q):
        if "How should new members prove they're human?" in text:
            return "3"                                  # captcha, but no site key given
        if q.startswith("Save?"):
            return "y"
        return ""
    code, out = drive(p, reply)
    assert code == 1 and "isn't valid" in out and p.read_text() == BASE
    assert "· CAPTCHA" in out                           # the CAPTCHA screens appeared once chosen


def test_cli_wizard_nothing_changed(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(BASE)
    code, out = drive(p, lambda text, q: "")
    assert code == 0 and "Nothing changed." in out and p.read_text() == BASE


def test_cli_wizard_quit(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(BASE)
    code, out = drive(p, lambda text, q: "q")
    assert code == 0 and p.read_text() == BASE


def test_channels_match_loosely():
    chans = [SimpleNamespace(id="1", name="🛡┊mod-log"), SimpleNamespace(id="2", name="📣┊Announcements")]
    g = SimpleNamespace(text_channels=chans)
    assert VectiqBot.find_channel(g, "mod-log") is chans[0]
    assert VectiqBot.find_channel(g, "#announcements") is chans[1]
    assert VectiqBot.find_channel(g, "2") is chans[1]
    assert VectiqBot.find_channel(g, "nope") is None and VectiqBot.find_channel(g, "") is None

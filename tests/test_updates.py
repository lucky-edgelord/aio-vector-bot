"""Update check and updater, against real git repositories in a temp folder."""

import shutil
import subprocess
from types import SimpleNamespace

import pytest

from vectiq import updates
from vectiq.cogs.updates import Updates
from vectiq.config import Config


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"], "HOME": str(cwd)})


@pytest.fixture
def repos(tmp_path):
    origin, mine = tmp_path / "origin", tmp_path / "mine"
    origin.mkdir()
    git("init", "-q", "-b", "main", cwd=origin)
    (origin / "pyproject.toml").write_text("[project]\nname='x'\n")
    (origin / "config.yaml").write_text("a: 1\n")
    git("add", "-A", cwd=origin)
    git("commit", "-qm", "first", cwd=origin)
    subprocess.run(["git", "clone", "-q", str(origin), str(mine)], check=True, capture_output=True)
    return origin, mine


def publish(origin, name="new.txt", message="Add a thing"):
    (origin / name).write_text("x")
    git("add", "-A", cwd=origin)
    git("commit", "-qm", message, cwd=origin)


def test_version_ordering():
    assert updates.version_key("v1.10.0") > updates.version_key("1.9.9") > updates.version_key("0.1.0")
    assert updates.version_key("1.2.0-rc1") == (1, 2, 0)


async def test_up_to_date_then_behind(repos):
    origin, mine = repos
    info = await updates.check(root=mine)
    assert info.kind == "git" and info.behind == 0 and not info.error
    publish(origin)
    publish(origin, "b.txt", "Another")
    info = await updates.check(root=mine)
    assert info.behind == 2 and info.changes == ["Another", "Add a thing"] and info.can_update


async def test_apply_pulls_and_keeps_your_config(repos):
    origin, mine = repos
    (mine / "config.yaml").write_text("a: 2   # mine\n")
    publish(origin)
    ok, message = await updates.apply(mine, pip=False)
    assert ok, message
    assert (mine / "new.txt").exists()
    assert (mine / "config.yaml").read_text() == "a: 2   # mine\n"
    assert (await updates.check(root=mine)).behind == 0


async def test_your_own_code_edits_block_the_update(repos):
    origin, mine = repos
    (mine / "pyproject.toml").write_text("[project]\nname='edited'\n")
    publish(origin)
    info = await updates.check(root=mine)
    assert info.dirty and not info.can_update and "edited" in info.how
    ok, message = await updates.apply(mine, pip=False)
    assert not ok and "edited" in message and not (mine / "new.txt").exists()


async def test_a_copy_that_is_not_a_checkout_cannot_update(tmp_path):
    shutil.copy(__file__, tmp_path / "x.py")
    ok, message = await updates.apply(tmp_path, pip=False)
    assert not ok and "git" in message


async def test_release_check_for_other_installs(monkeypatch, tmp_path):
    async def newer(repo):
        return "9.0.0", "https://example.test/rel"

    monkeypatch.setattr(updates, "_latest_release", newer)
    info = await updates.check(root=tmp_path, kind="package")
    assert info.behind == 1 and info.latest == "9.0.0" and not info.can_update and info.how

    async def same(repo):
        return updates.__version__, ""

    monkeypatch.setattr(updates, "_latest_release", same)
    assert (await updates.check(root=tmp_path, kind="package")).behind == 0

    async def boom(repo):
        raise OSError("offline")

    monkeypatch.setattr(updates, "_latest_release", boom)
    assert "offline" in (await updates.check(root=tmp_path, kind="package")).error


class Settings:
    def __init__(self):
        self.d = {}

    async def get(self, g, k, default=None):
        return self.d.get((g, k), default)

    async def set(self, g, k, v):
        self.d[(g, k)] = v


@pytest.fixture
async def cog(tmp_path):
    cfg = Config.load("config.yaml", env={"VECTIQ_DATA_DIR": str(tmp_path)})
    cfg.data["owners"] = ["npubOwner"]
    sent = []

    class Owner:
        async def send(self, text):
            sent.append(text)

    points = []

    async def create(label, kind):
        points.append((label, kind))

    bot = SimpleNamespace(config=cfg, stores=SimpleNamespace(settings=Settings()), get_user=lambda i: Owner(),
                          restore_points=SimpleNamespace(create=create), wait_until_ready=lambda: None)
    c = Updates.__new__(Updates)
    c.bot, c.cfg, c.info = bot, cfg, None
    import asyncio

    c._lock = asyncio.Lock()
    yield c, sent, points


async def test_owners_are_told_once_per_new_version(cog, monkeypatch):
    c, sent, _ = cog

    async def fake(repo):
        return updates.UpdateInfo(kind="git", latest="abc123", behind=3, can_update=True, checked_at=__import__("time").time())

    monkeypatch.setattr(updates, "check", fake)
    await c.loop.coro(c)
    await c.loop.coro(c)
    assert len(sent) == 1 and "abc123" in sent[0] and "update now" in sent[0]


async def test_install_makes_a_restore_point_updates_and_restarts(cog, monkeypatch):
    c, _, points = cog
    calls = []

    async def fake(repo):
        return updates.UpdateInfo(kind="git", latest="abc", behind=1, can_update=True)

    async def applied(*a, **k):
        calls.append("apply")
        return True, "Updated."

    monkeypatch.setattr(updates, "check", fake)
    monkeypatch.setattr(updates, "apply", applied)
    monkeypatch.setattr(updates, "restart", lambda: calls.append("restart"))
    ok, message = await c.install("npubOwner")
    assert ok and "Restarting" in message and points == [("Before updating to abc", "automatic")]
    import asyncio

    await asyncio.sleep(3.2)
    assert calls == ["apply", "restart"]


async def test_install_refuses_when_up_to_date_or_dirty(cog, monkeypatch):
    c, _, points = cog

    async def level(repo):
        return updates.UpdateInfo(kind="git", behind=0)

    monkeypatch.setattr(updates, "check", level)
    ok, message = await c.install()
    assert not ok and "up to date" in message and not points

    async def dirty(repo):
        return updates.UpdateInfo(kind="git", behind=2, can_update=False, how="You've edited Vectiq's own files.")

    monkeypatch.setattr(updates, "check", dirty)
    ok, message = await c.install()
    assert not ok and "edited" in message and not points


async def test_auto_install_updates_once_per_version_and_tells_owners(cog, monkeypatch):
    c, sent, points = cog
    c.cfg.data["updates"]["auto_install"] = True
    runs = []

    async def fake(repo):
        return updates.UpdateInfo(kind="git", latest="v2", behind=1, can_update=True, checked_at=__import__("time").time())

    async def applied(*a, **k):
        runs.append(1)
        return False, "git pull failed"

    monkeypatch.setattr(updates, "check", fake)
    monkeypatch.setattr(updates, "apply", applied)
    await c.loop.coro(c)
    await c.loop.coro(c)
    assert runs == [1] and len(sent) == 1 and "couldn't" in sent[0] and points


def test_cli_check_and_update(repos, monkeypatch, capsys):
    from vectiq.__main__ import main

    origin, mine = repos
    monkeypatch.setattr(updates, "ROOT", mine)
    real = updates.check

    async def local(repo, root=mine, kind=None):
        return await real(repo, root)

    monkeypatch.setattr(updates, "check", local)
    assert main(["--check-update"]) == 0 and "up to date" in capsys.readouterr().out
    publish(origin)
    assert main(["--check-update"]) == 10 and "Add a thing" in capsys.readouterr().out
    real_apply = updates.apply

    async def local_apply(root=mine, **kw):
        return await real_apply(root, pip=False)

    monkeypatch.setattr(updates, "apply", local_apply)
    monkeypatch.chdir(mine.parent)
    assert main(["--update", "--config", str(mine / "config.yaml")]) in (0, 1)

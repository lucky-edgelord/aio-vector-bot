"""The bot's Vector profile (name, about, picture) from the ``profile:`` settings."""

from pathlib import Path
from types import SimpleNamespace

from vectiq.app import VectiqBot as Vectiq
from vectiq.config import Config


class Me:
    def __init__(self, name="Vectiq", about=""):
        self._profile = SimpleNamespace(name=name, about=about, avatar_url="")
        self.name, self.calls = name, []

    async def edit(self, **kw):
        self.calls.append(kw)
        self._profile = SimpleNamespace(name=kw.get("username", self._profile.name),
                                        about=kw.get("about", self._profile.about), avatar_url="x")


def bot(tmp_path: Path, profile: str, me: Me):
    (tmp_path / "config.yaml").write_text(f"profile: {profile}\n")
    cfg = Config.load(tmp_path / "config.yaml", env={"VECTIQ_DATA_DIR": str(tmp_path / "data")})
    return SimpleNamespace(config=cfg, user=me), cfg


async def test_empty_profile_changes_nothing(tmp_path):
    me = Me()
    b, _ = bot(tmp_path, "{}", me)
    assert await Vectiq.apply_profile(b) == [] and me.calls == []


async def test_name_about_and_picture_are_set_once(tmp_path):
    (tmp_path / "her.png").write_bytes(b"\x89PNG fake")
    me = Me()
    b, cfg = bot(tmp_path, '{name: Vectoria, about: "Ask me with !vec", avatar: her.png}', me)
    assert await Vectiq.apply_profile(b) == ["name", "about", "picture"]
    assert me.calls[0] == {"username": "Vectoria", "about": "Ask me with !vec", "avatar": str(tmp_path / "her.png")}
    assert await Vectiq.apply_profile(b) == []                      # a restart doesn't upload the same picture again
    (tmp_path / "her.png").write_bytes(b"\x89PNG new picture")
    assert await Vectiq.apply_profile(b) == ["picture"]             # a changed file is uploaded


async def test_a_missing_picture_is_skipped_and_failures_never_raise(tmp_path):
    me = Me()
    b2, _ = bot(tmp_path, "{name: Vectoria, avatar: nowhere.png}", me)
    assert await Vectiq.apply_profile(b2) == ["name"]

    async def boom(**kw):
        raise RuntimeError("relay down")
    me2 = Me()
    me2.edit = boom
    b3, _ = bot(tmp_path, "{name: Someone}", me2)
    assert await Vectiq.apply_profile(b3) == []


async def test_change_settings_keeps_and_applies_them(tmp_path):
    from vectiq.db import Database
    from vectiq.stores import Stores

    (tmp_path / "config.yaml").write_text("profile: {about: from the file}\n")
    cfg = Config.load(tmp_path / "config.yaml", env={"VECTIQ_DATA_DIR": str(tmp_path / "data")})
    db = await Database(cfg.db_path).connect()
    applied = []

    async def apply_settings():
        applied.append(dict(cfg.overrides))
        return {}
    fake = SimpleNamespace(config=cfg, stores=Stores(db), apply_settings=apply_settings)
    await Vectiq.change_settings(fake, {"profile.name": "Vectoria", "profile.about": "from the file"}, "npub1me")
    assert cfg.get("profile.name") == "Vectoria" and cfg.overrides == {"profile.name": "Vectoria"}
    assert await fake.stores.dashboard.overrides() == {"profile.name": "Vectoria"} and applied
    await Vectiq.change_settings(fake, {"profile.name": None}, "npub1me")
    assert cfg.get("profile.name") == "" and await fake.stores.dashboard.overrides() == {}
    await db.close()

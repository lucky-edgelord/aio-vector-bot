import pytest

from vectiq.config import Config, ConfigError


async def test_onboarding_progress(stores):
    s = stores.onboarding
    assert not await s.mark("g", "u", "verified_at")                 # nothing in progress yet
    await s.start("g", "u")
    assert await s.mark("g", "u", "verified_at") and not await s.mark("g", "u", "verified_at")
    assert await s.complete("g", "u") and not await s.complete("g", "u")
    assert not await s.mark("g", "u", "picked_at")                   # finished flows don't change
    assert await s.counts("g") == {"started": 1, "completed": 1}
    with pytest.raises(ValueError):
        await s.mark("g", "u", "hacked; DROP TABLE")


def test_onboarding_config_validation(tmp_path):
    def load(text):
        p = tmp_path / "c.yaml"
        p.write_text(text)
        return Config.load(p, env={})

    with pytest.raises(ConfigError):
        load("onboarding:\n  steps: [dance]")
    assert load("onboarding:\n  steps: [pick_roles]\n  role_menu: {}").get("onboarding.role_menu")   # defaults fill in
    assert load("onboarding:\n  steps: [verify]").get("onboarding.steps") == ["verify"]
    assert Config.load("config.yaml", env={}).get("onboarding.role_menu")["🎮"] == "Gamer"

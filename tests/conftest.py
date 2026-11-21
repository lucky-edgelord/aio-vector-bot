import pytest

from vectiq.db import Database
from vectiq.stores import Stores


@pytest.fixture
async def db():
    database = await Database(":memory:").connect()
    yield database
    await database.close()


@pytest.fixture
async def stores(db):
    return Stores(db)


class FakeBank:
    def __init__(self, balances=None):
        self.b = dict(balances or {})

    async def balance(self, npub):
        return self.b.get(npub, 0)

    async def adjust(self, npub, amount, reason):
        if self.b.get(npub, 0) + amount < 0:
            raise ValueError("insufficient")
        self.b[npub] = self.b.get(npub, 0) + amount
        return self.b[npub]


@pytest.fixture
def bank():
    return FakeBank({"a": 500, "b": 500})


SETTINGS = {"winner_coins": 50, "draw_coins": 10, "trivia_coins_per_point": 10, "slots_max_bet": 1000}


@pytest.fixture
def settings():
    return dict(SETTINGS)


@pytest.fixture
async def make_bot(db):
    """Build VectiqBots for a test and unload their modules afterwards, so no loop outlives the test."""
    from vectiq.app import VectiqBot

    bots = []

    def make(cfg):
        cfg.data["linksafety"]["lists"] = []        # never download blocklists in tests
        bot = VectiqBot(cfg, db)
        bots.append(bot)
        return bot

    yield make
    for bot in bots:
        for ext in list(bot.extensions):
            try:
                await bot.unload_extension(ext)
            except Exception:  # noqa: BLE001
                pass


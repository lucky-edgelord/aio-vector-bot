from .economy import EconomyStore, InsufficientFunds
from .levels import LevelStore, level_for_xp, xp_for_level
from .misc import ActivityStore, GameStatsStore, GiveawayStore, OnboardingStore, RoleMenuStore, SettingsStore, VerificationStore
from .moderation import ModerationStore
from .tickets import TicketStore

__all__ = (
    "ActivityStore",
    "EconomyStore",
    "GameStatsStore",
    "GiveawayStore",
    "InsufficientFunds",
    "LevelStore",
    "ModerationStore",
    "RoleMenuStore",
    "SettingsStore",
    "Stores",
    "TicketStore",
    "VerificationStore", "OnboardingStore",
    "level_for_xp",
    "xp_for_level",
)


class Stores:
    """Every store, built over one Database."""

    def __init__(self, db):
        self.db = db
        self.settings = SettingsStore(db)
        self.moderation = ModerationStore(db)
        self.levels = LevelStore(db)
        self.economy = EconomyStore(db)
        self.tickets = TicketStore(db)
        self.verification = VerificationStore(db)
        self.role_menus = RoleMenuStore(db)
        self.giveaways = GiveawayStore(db)
        self.games = GameStatsStore(db)
        self.activity = ActivityStore(db)
        self.onboarding = OnboardingStore(db)

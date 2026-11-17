"""The stable API for writing Vectiq modules (plugins). Import from here, not from Vectiq's internals.

A minimal folder plugin, ``modules/hello/__init__.py``::

    from vector.ext import commands
    from vectiq.plugin import Module, field

    MODULE = Module(
        name="hello", label="Hello", help="Says hello", group="Fun",
        defaults={"greeting": "Hi there"},
        settings=(field("hello.greeting", "Greeting", "text"),),
    )

    class Hello(commands.Cog):
        def __init__(self, bot):
            self.bot = bot

        @commands.command()
        async def hello(self, ctx):
            await ctx.send(self.bot.config.get("hello.greeting"))

    async def setup(bot):
        await bot.add_cog(Hello(bot))

A module can also put a page on the dashboard, with no JavaScript: give the cog ``dashboard_page`` and two
methods, and the dashboard draws whatever ``dashboard_panel`` returns::

    class Hello(commands.Cog):
        dashboard_page = {"label": "Hello", "icon": "☺", "scope": "community"}   # or "bot"; "owner_only": True

        async def dashboard_panel(self, guild, viewer):     # guild is None for scope "bot"
            return {"title": "Hello", "refresh": 10, "sections": [
                {"type": "status", "items": [{"label": "Said hello", "value": 42, "tone": "green"}]},
                {"type": "text", "text": "Anything to explain."},
                {"type": "list", "title": "Recent", "items": [{"title": "Alex", "detail": "2 min ago", "tag": "new"}]},
                {"type": "table", "columns": ["Who", "Count"], "rows": [["Alex", 3]]},
                {"type": "log", "lines": ["…"]},
                {"type": "actions", "items": [{"id": "reset", "label": "Reset", "kind": "danger",
                                               "confirm": "Start counting again?", "owner": True}]},
            ]}

        async def dashboard_action(self, action, guild, viewer, data):   # a button was pressed
            return "Done."                                               # shown to the person; raise to show an error

See docs/writing-modules.md for slots (replacing a built-in), packaging with pip, and what ``bot`` offers.
"""

from __future__ import annotations

from .dashboard.schema import field
from .modules import Module
from .utils.checks import is_owner
from .utils.embeds import embed, fail, name_of, ok
from .utils.enforce import ACTIONS, enforce, exempt

API_VERSION = 1

__all__ = ("API_VERSION", "ACTIONS", "Module", "embed", "enforce", "exempt", "fail", "field", "is_owner", "name_of",
           "ok")

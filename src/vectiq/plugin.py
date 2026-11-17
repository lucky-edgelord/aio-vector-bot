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

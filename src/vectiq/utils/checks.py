from __future__ import annotations

from vector.ext import commands


def is_owner():
    """Bot owners come from ``owners`` in config.yaml."""

    async def predicate(ctx: commands.Context) -> bool:
        owners = ctx.bot.config.owners
        me = str(getattr(ctx.author, "npub", None) or ctx.author.id)
        if me not in owners:
            raise commands.CheckFailure("Only a Vectiq owner can do that.")
        return True

    return commands.check(predicate)


def module_enabled(name: str):
    """Disable a whole cog's commands when its module is switched off in config.yaml."""

    async def predicate(ctx: commands.Context) -> bool:
        if not ctx.bot.config.enabled(name):
            raise commands.CheckFailure(f"The {name} module is switched off.")
        return True

    return commands.check(predicate)

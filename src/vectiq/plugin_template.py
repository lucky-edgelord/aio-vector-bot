"""``vectiq --new-module NAME``: a starter folder plugin to edit."""

from __future__ import annotations

from pathlib import Path

TEMPLATE = '''"""{label}: a Vectiq module. Edit me, then `!module reload {name}` in chat to load the new code."""

from vector.ext import commands

from vectiq.plugin import Module, embed, field

MODULE = Module(
    name="{name}",
    label="{label}",
    help="Describe what {label} does in one line",
    group="Community",               # Safety, Members, Community, Fun or Integrations (or a new one)
    # provides="automod",            # set this to take the place of a built-in module instead
    defaults={{"greeting": "Hello from {label}!"}},          # becomes `{name}:` in config.yaml
    settings=(field("{name}.greeting", "Greeting", "text", "What `{name}` says"),),  # dashboard + wizard
    wizard="Let's set up {label}.",
    version="0.1.0",
)


class {cls}(commands.Cog, name="{label}"):
    # A page on the dashboard, drawn from the data dashboard_panel returns (delete these to have none)
    dashboard_page = {{"label": "{label}", "icon": "◆", "scope": "community"}}

    def __init__(self, bot):
        self.bot = bot
        self.count = 0

    async def dashboard_panel(self, guild, viewer):
        return {{"title": "{label}", "sections": [
            {{"type": "status", "items": [{{"label": "Times used", "value": self.count}}]}},
            {{"type": "actions", "items": [{{"id": "reset", "label": "Reset the count"}}]}},
        ]}}

    async def dashboard_action(self, action, guild, viewer, data):
        self.count = 0
        return "Count reset."

    @property
    def cfg(self) -> dict:
        return self.bot.config.get("{name}", {{}})

    @commands.command(name="{name}")
    async def main(self, ctx):
        """Say the greeting."""
        self.count += 1
        await ctx.send(embed=embed("{label}", self.cfg.get("greeting", "")))

    @commands.Cog.listener()
    async def on_message(self, message):
        pass                          # react to every message here

    async def cog_unload(self):
        pass                          # stop loops and close connections here, so the module can be switched off


async def setup(bot):
    await bot.add_cog({cls}(bot))
'''


def create(name: str, config_path: str | None = None) -> Path:
    if not name.isidentifier() or name != name.lower():
        raise ValueError("use a lowercase name with letters, digits and _, e.g. ai_automod")
    from . import modules

    if name in modules.NAMES:
        raise ValueError(f"there's already a module called {name}")
    folder = Path(config_path or "config.yaml").resolve().parent / "modules" / name
    if folder.exists():
        raise ValueError(f"{folder} already exists")
    folder.mkdir(parents=True)
    label = name.replace("_", " ").title()
    cls = "".join(p.title() for p in name.split("_")) or "Plugin"
    (folder / "__init__.py").write_text(TEMPLATE.format(name=name, label=label, cls=cls), "utf-8")
    return folder / "__init__.py"

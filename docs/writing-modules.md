---
title: Writing modules
group: Reference
order: 6
summary: Add your own feature, or replace a built-in one (say, an AI automod), as a plugin you drop in a folder or install with pip.
---

Every Vectiq feature is a module, and you can add your own. A plugin module behaves exactly like a built-in one. It shows up in `!modules`, the dashboard and the setup wizard. It loads only while it's switched on, and it can be switched on, off, swapped or reloaded while the bot runs.

A plugin can:

- **add something new**: a feature Vectiq doesn't have, with its own commands, listeners, settings and wizard step;
- **replace a built-in**: set `provides="automod"` and it does automod's job instead. Switching it on switches the built-in off, and the other way round. Only one module per job runs.

## Your first module in two minutes

```sh
vectiq --new-module hello_world        # writes modules/hello_world/__init__.py next to config.yaml
```

Then, in chat as an owner:

```text
!module scan              finds the new module
!module on hello_world    loads it
!hello_world              your command
!module reload hello_world   after you edit the file: loads the new code, no restart
```

The file it writes is a complete module:

```python
from vector.ext import commands
from vectiq.plugin import Module, embed, field

MODULE = Module(
    name="hello_world",
    label="Hello World",
    help="Describe what Hello World does in one line",
    group="Community",
    defaults={"greeting": "Hello from Hello World!"},
    settings=(field("hello_world.greeting", "Greeting", "text"),),
)

class HelloWorld(commands.Cog, name="Hello World"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="hello_world")
    async def main(self, ctx):
        await ctx.send(embed=embed("Hello World", self.bot.config.get("hello_world.greeting")))

async def setup(bot):
    await bot.add_cog(HelloWorld(bot))
```

## The manifest

`MODULE = Module(...)` tells Vectiq about the module. Vectiq reads it to list the module even while it's off, so keep this part light: put heavy imports inside the cog or `setup`.

| Field | Meaning |
|---|---|
| `name` | Lowercase id: `modules.<name>` in config.yaml, `!module on <name>`. It can't be a built-in's name. |
| `label`, `help`, `group` | What people see. `group` is Safety, Members, Community, Fun, Integrations, or a new one. |
| `cogs` | Where the code is. Blank means the plugin's own file; `.cog` means `cog.py` inside a plugin folder; packages give full import paths. |
| `provides` | The job it does. Blank means its own name. `"automod"`, `"verification"`, `"music"`... replace that built-in. |
| `defaults` | Its settings section, `<name>:` in config.yaml. |
| `settings` | `field(...)`s shown on the dashboard's Settings page and asked in the setup wizard. Paths start with `<name>.`. |
| `wizard` | What the setup wizard says before asking those settings. |
| `imports`, `install` | Python packages it needs, and the command that installs them. If they're missing, the module stays off and says so. |
| `version`, `author` | Shown by `!module info`. |

A plugin always starts switched off, so installing one never changes what the bot does until an owner switches it on.

## What `bot` gives you

Modules are [cogs](https://discordpy.readthedocs.io/en/stable/ext/commands/cogs.html), so commands, listeners (`on_message`, `on_member_join`, reactions...) and `tasks.loop` work as usual. Import Vectiq's helpers from `vectiq.plugin`, the stable API:

- `bot.config.get("<name>.setting")` reads your settings. They update live when someone changes them on the dashboard, and `on_vectiq_config_reload` fires.
- `bot.stores.*` and `bot.db` give you the database; `bot.find_channel(guild, "mod-log")` matches names loosely; `bot.emit(guild, kind, title, text)` feeds webhooks.
- `enforce(bot, message, source=..., reason=..., action=...)` removes, warns, times out or logs exactly as automod does. `exempt(bot, message, cfg)` skips staff and exempt roles and channels.
- `embed`, `ok`, `fail`, `name_of`, `is_owner`, `field` cover messages, checks and settings.

Stop loops and close connections in `cog_unload`, so the module can be switched off cleanly.

## Sharing it with pip

Make a package and declare an entry point in the `vectiq.modules` group:

```toml
[project]
name = "vectiq-my-module"

[project.entry-points."vectiq.modules"]
my_module = "vectiq_my_module:MODULE"
```

Anyone can then install it:

```sh
vectiq --install-module vectiq-my-module
vectiq --install-module "git+https://github.com/you/vectiq-my-module"
```

Then in chat: `!module scan` and `!module on my_module`. `vectiq --uninstall-module my_module` removes it again.

Owners can also install from chat with `!module install <package>`, if `plugins.allow_install: true`. It's off by default because it runs pip on the bot's computer.

## Example: an AI automod

[`examples/vectiq-ai-automod`](https://github.com/lucky-edgelord/aio-vector-bot/tree/main/examples/vectiq-ai-automod) is a complete plugin in about 120 lines. It replaces the built-in automod: it runs the built-in rules first, then asks any OpenAI-compatible model (a local Ollama by default, so messages stay on your computer) whether a message breaks your rules.

```sh
vectiq --install-module "git+https://github.com/lucky-edgelord/aio-vector-bot#subdirectory=examples/vectiq-ai-automod"
```

```text
!module scan
!module on ai_automod      ✅ AI automod is on. It replaces Automod, which is now off.
!aicheck you're all idiots
```

!!! warning "Plugins run with the bot's full access"
    A plugin is Python code with the same access as the bot: its key, its database and your computer. Install only plugins you trust, and only let owners you trust install them.

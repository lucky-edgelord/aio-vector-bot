---
title: JSON modules
group: Reference
order: 7
summary: A whole module in one JSON file. Write one (or ask an AI to), import it, export yours, share it.
---

A JSON module is a Vectiq module kept in a single file, `<id>.module.json`. The file says what the module is called, which settings it has, and what it does:

- **commands**, like `!rules`, that answer with text or a card, pick a random reply, or react;
- **autoresponders** that reply or react when someone says a phrase;
- **timers** that post in a channel every so often, or at a time of day;
- and, optionally, **Python code**, for anything else.

Vectiq knows how to run commands, autoresponders and timers, so a module without code runs nothing from the file: it can only say things, react and post on a schedule. That's what makes it safe to get modules from a [marketplace](marketplace.md) or a friend. Modules with code are a different matter, and are off until you allow them.

Once added, a JSON module is a module like any other: it's in `!modules`, under Settings → Modules, it switches on and off without a restart, and its settings are on the dashboard.

## An example

```json
{
  "format": "vectiq-module",
  "version": 1,
  "id": "server_rules",
  "name": "Server rules",
  "summary": "A !rules command, and a pointer when someone asks about the rules.",
  "group": "Community",
  "release": "1.0.0",
  "settings": [
    { "key": "rules", "label": "The rules", "type": "longtext", "default": "1. Be kind.\n2. No spam." }
  ],
  "commands": [
    { "name": "rules", "help": "Show the rules", "cooldown": 10,
      "card": { "title": "Rules of {community}" }, "reply": "{settings.rules}" }
  ],
  "autoresponders": [
    { "match": "word", "phrases": ["rules"], "reply": "The rules: {prefix}rules", "cooldown": 120 }
  ]
}
```

Add it and **Server rules** appears in your modules, with *The rules* as a setting. Change the text on the dashboard, and `!rules` says the new text at once.

## Writing one

The quickest way is to ask an AI. On the dashboard, **Marketplace → Add a module → Copy a prompt for an AI** copies instructions that describe the format. Paste them into Claude (or another AI), say what you want ("a module that welcomes people who say hi and has a !schedule command with our meeting times"), and paste the answer back into the same box. It's checked as you type, and nothing is installed until you press **Install**.

You can also start from **Start from the template**, which fills the box with a small module that uses every part. With the [MCP server](mcp.md) on, an assistant can do all of this itself: `module_format_guide`, `check_module_json`, `add_module_json`.

The checker is forgiving, like Lilith Learning Lab's course checker: a command with a bad name or no reply is skipped with a note, and the rest of the module still works. Only things that make the module unusable are errors (no name, not JSON, nothing in it).

## The parts

### About the module

| Key | Meaning |
|---|---|
| `format`, `version` | Always `"vectiq-module"` and `1`. A file from a newer version asks you to update Vectiq. |
| `id` | 2–32 lowercase letters, digits and `_`, starting with a letter. Made from `name` if you leave it out. It can't be a built-in module's name. |
| `name`, `summary` | What it's called, and one line about it. |
| `group` | Where it's listed: Community, Fun, Members, Safety or Integrations. |
| `release` | Its version, like `1.2.0`. The marketplace offers an update when the file changes. |
| `description`, `author`, `license`, `homepage`, `tags` | Shown in the marketplace. |
| `provides` | A job it does instead of a built-in module, like `automod`. Only one module does each job, so switching it on switches the other off. |

### Settings

```json
{ "key": "channel", "label": "Channel", "type": "channel", "default": "general", "help": "Where to post" }
```

Types: `text`, `longtext`, `int`, `number`, `bool`, `channel`, `enum` (with `options`), `list`. Ints and numbers can have `min` and `max`. Use a setting anywhere in the module's text as `{settings.channel}`. A setting marked `"private": true`, or whose key looks like a token, password or key, is never put in an export.

### Commands

```json
{ "name": "8ball", "aliases": ["eightball"], "help": "Ask the 8-ball", "cooldown": 5,
  "replies": ["🎱 Yes.", "🎱 No.", "🎱 Ask again later."] }
```

| Key | Meaning |
|---|---|
| `name`, `aliases`, `help` | The command, other names for it, and what `!help` says. |
| `reply` or `replies` | What to say, or a list to pick from at random. |
| `card` | `{ "title": "…", "color": "#59fcb3" }`: answer with a card instead of plain text. |
| `react` | Emoji to react to the command with. |
| `cooldown` | Seconds each person waits between uses (default 3). |
| `roles`, `channels` | Only these roles may use it, only in these channels. Leave out for everyone, everywhere. |
| `dm` | Answer in a direct message. |
| `delete_trigger` | Delete the message that used the command. |

If another module already has a command of the same name, that command is left out and the Marketplace page says so.

### Autoresponders

```json
{ "match": "word", "phrases": ["good morning", "gm"], "react": ["☀️"], "cooldown": 30 }
```

`match` is `contains`, `word` (a whole word or phrase), `exact`, `startswith` or `endswith`, ignoring case. An autoresponder can reply, react, or both. Its `cooldown` (default 60 seconds) is per channel. Messages from bots and messages that start a command are ignored, and only the first autoresponder that matches answers.

### Timers

```json
{ "channel": "{settings.channel}", "at": "18:00", "timezone": "Europe/London", "order": "random",
  "replies": ["What made you smile today?", "What are you working on?"] }
```

Use `every_minutes` (5 or more) or `at` (a 24-hour time, or a setting). `order` is `random` or `in_turn`. The post goes to the channel with that name in every community the bot serves that has one. If the bot starts after today's time has passed, it waits for tomorrow rather than posting late.

### Text

Replies, card titles and timer channels can use `{user}` (their name), `{mention}`, `{args}` (what they typed after the command), `{channel}`, `{community}`, `{members}`, `{prefix}` and `{settings.key}`. Anything else in braces is left as written.

### Code

```json
"code": {
  "entry": "cog",
  "files": { "__init__.py": "", "cog.py": "from vector.ext import commands\n…\nasync def setup(bot):\n    await bot.add_cog(MyCog(bot))\n" },
  "packages": { "httpx": "httpx>=0.27" }
}
```

A module can carry Python files, written like a [plugin](writing-modules.md). `entry` names the file whose `setup(bot)` is called; the files are a package, so they can import each other with `from .helper import x`. `packages` lists what it needs from pip (import name → requirement); Vectiq tells you to install them if they're missing.

Code runs on the bot's computer with the bot's access, so:

- It is only accepted when **Settings → Marketplace → Allow modules with code** is on (`marketplace.allow_code`). It's off by default.
- It's added switched off, and never switches itself on.
- Before you add it, the dashboard lists every file in it.

A module can have code *and* commands, autoresponders and timers; both run.

## Adding, exporting and removing

| | Dashboard | Chat (owners) | Terminal |
|---|---|---|---|
| Check a file | Marketplace → Add a module | | `vectiq --check-module FILE` |
| Add a file | Marketplace → Add a module | | `vectiq --import-module FILE` (add `--allow-code` for code) |
| Add from the marketplace | Marketplace → Browse | `!module get <id>` | |
| Export | Marketplace → Installed → Export | | `vectiq --export-module NAME [--with-settings] [--out FILE]` |
| Remove | Marketplace → Installed → Remove | `!module remove <id>` | |

**Export** works for JSON modules and for any plugin in a folder: a folder plugin becomes a module with code, so you can share a plugin you wrote as one file. **With my settings** makes your current values the defaults (private settings excluded), handy for sharing a module you've filled in.

Added modules live in `data/json-modules/`: the module file itself, and `<id>.source.json` saying where it came from. Removing a module deletes those, but keeps its settings in case you add it again. Every add, update and remove is in the dashboard's audit log.

---
title: Modules
group: Start here
order: 6
summary: Every feature is a module. Switch any of them on or off while the bot runs; only the ones that are on are loaded.
---

Vectiq is built from modules: moderation, automod, music, the dashboard and so on. Only modules that are switched on are loaded, so a bot that only does moderation never imports the music or dashboard code, and starts faster and uses less memory.

Switching a module on or off takes effect **straight away**. There's no restart. You can do it in four places:

| Where | How |
|---|---|
| Chat | `!modules` lists every module. Owners use `!module on music` and `!module off games`. |
| Setup wizard | The **Features** screen, on the dashboard or with `vectiq --setup`. |
| Dashboard | **Settings → Modules**. |
| config.yaml | The `modules:` section, then `!vectiq reload`. |

A switch made in chat or on the dashboard is kept in the database and survives restarts. It sits on top of `config.yaml` until you reset it.

## Adding and swapping modules

Modules don't have to come with Vectiq. Drop a plugin into the `modules/` folder or install one with pip, and it appears alongside the built-in ones. A plugin can add a new feature or **replace** a built-in one: an AI automod, a different verification, another music player. Only one module does each job, so switching on the replacement switches the built-in off, without a restart.

| Command | Does |
|---|---|
| `!module info <name>` | where a module comes from, and what it can replace |
| `!module scan` | finds plugins you just added |
| `!module reload <name>` | loads a module's code again from disk |
| `!module install <package>` | installs a plugin with pip (only with `plugins.allow_install: true`) |
| `vectiq --modules` | lists everything, plugins included, in the terminal |
| `vectiq --install-module <package>` | installs a plugin |
| `vectiq --new-module <name>` | starts a plugin of your own |

See [Writing modules](writing-modules.md) for how to make one.

## The modules

{{modules}}

## Modules that need extra packages

Some modules use packages that most people don't need, so they aren't installed by default. A module whose package is missing stays off and says what to install. `!modules` shows it in orange.

| Module | Install |
|---|---|
| Music | `pip install "vectiq[music]"` and ffmpeg |
| Web dashboard | `pip install "vectiq[dashboard]"` |
| Image guard with NudeNet | `pip install "vectiq[nudenet]"` |
| Image guard with nsfw-detector | `pip install "vectiq[nsfw-detector]"` |
| Everything | `pip install "vectiq[all]"` |

With the installers, run the pip command in the bot's folder as `.venv/bin/pip install -e ".[music]"`. With Docker, set `EXTRAS` when building (see [Docker](docker.md)).

## Settings

{{config:modules}}

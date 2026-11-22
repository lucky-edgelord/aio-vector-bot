---
title: Getting started
group: Start here
order: 1
summary: Install Vectiq, give the bot its own Vector account and put it to work in your community.
---

Vectiq is a bot you run yourself. You install it on a computer that stays on (a Mac mini, a Linux server, a spare laptop), give it its own Vector account, and invite that account to your community. This page takes you from nothing to the bot answering `!ping`.

## What you need

- A computer that can stay on and online. The bot keeps a connection open to Vector, so it only works while it is running.
- A Vector account **just for the bot**. Create a new one in the Vector app, or let the installer generate one.
- Admin rights in the community you want the bot in.

!!! warning "Use a separate account"
    Never give the bot your personal key. The bot's key sits in a file on the computer running it, and the account needs powerful roles in your community. Keep your own account out of it.

The installer gets everything else (Python, Rust, ffmpeg) for you.

## Install

Copy one line into a terminal. The same line installs and, run again later, updates.

macOS and Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/lucky-edgelord/aio-vector-bot/main/get.sh | sh
```

Windows, in PowerShell:

```powershell
irm https://raw.githubusercontent.com/lucky-edgelord/aio-vector-bot/main/get.ps1 | iex
```

What it does:

1. Gets git if it's missing, and downloads Vectiq to `~/vectiq` (set `VECTIQ_DIR` first to use another folder).
2. Installs what the bot needs: Python, Rust and CMake (to build the Vector SDK), and ffmpeg (for music and talking videos). On a Mac that's Homebrew; on Linux apt, dnf, pacman, zypper or apk (it asks for your password); on Windows winget.
3. Asks for the bot's key, and any community invite links. Leave the key blank to create a new account; it's saved in `.env`, so back that file up.
4. Offers the setup wizard, checks `config.yaml`, and starts the bot when you log in (macOS, Windows) or when the computer starts (Linux). Logs go to `~/vectiq/data/vectiq.log`.

The first install compiles the Vector SDK and takes several minutes. Running the line again pulls the newest Vectiq and keeps your settings and data.

Options: on macOS and Linux they go after `sh -s --`, as in `... | sh -s -- --no-service` (install, but don't start at login; run `~/vectiq/run.sh` yourself) or `--yes` (no questions; reads `VECTOR_NSEC` and `VECTIQ_INVITE_URLS` from the environment). On Windows set `$env:VECTIQ_NO_SERVICE = "1"` or `$env:VECTIQ_YES = "1"` before the line. If an AI agent is installing it for you, point it at [AGENTS.md](https://github.com/lucky-edgelord/aio-vector-bot/blob/main/AGENTS.md).

To remove it: `~/vectiq/uninstall.sh` (`~\vectiq\uninstall.ps1` on Windows).

## Put the bot in your community

There are two ways in:

1. **Invite link.** Put one or more community invite links in `.env` as `VECTIQ_INVITE_URLS`, separated by spaces. The bot joins each one once, the first time it starts.
2. **From the Vector app.** Invite the bot's account the way you would invite any member.

By default the bot serves every community it is in. To limit it, list names or ids under `communities` in `config.yaml`.

## Give it the permissions it needs

In your community, create a role for the bot and give it the permissions for the features you use:

| Feature | Permission |
|---|---|
| Warn, timeout | Moderate Members |
| Kick, ban, tempban | Kick Members, Ban Members |
| Purge | Manage Messages |
| Lock, slowmode, tickets | Manage Channels |
| Role menus, verification, level rewards, onboarding | Manage Roles |

You don't have to grant everything. Without a permission the bot keeps running and answers with a message that names what is missing, so you can add permissions as you turn features on.

## Check that it works

In any channel the bot can read, type:

```
!ping
!about
!help
```

`!ping` answers right away, `!about` lists which modules are on, and `!help` lists every command grouped by feature. If nothing answers, see [Troubleshooting](troubleshooting.md).

## Set it up

Run the setup wizard and the bot asks you what it needs, one question at a time:

```sh
python -m vectiq --setup
```

Or open **Setup wizard** on the [dashboard](dashboard.md). See [Configuration](configuration.md#the-setup-wizard).

## Where to go next

- Decide what to switch on: [Configuration](configuration.md) explains `config.yaml`.
- Keep new members human: [Verification](verification.md).
- Make sure you can undo mistakes: [Restore points](restore-points.md).
- Set up the things members see first: [Welcome and onboarding](onboarding.md).
- Keep it running reliably: [Deployment](deployment.md).
- Browse everything the bot can do in the [command list](commands.md).

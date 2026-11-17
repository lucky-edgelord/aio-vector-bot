---
title: Getting started
group: Start here
order: 1
summary: Install Vectiq, give the bot its own Vector account and put it to work in your community.
---

Vectiq is a bot you run yourself. You install it on a computer that stays on (a Mac mini, a Linux server, a spare laptop), give it its own Vector account, and invite that account to your community. This page takes you from nothing to the bot answering `!ping`.

## What you need

- A computer that can stay on and online. The bot keeps a connection open to Vector, so it only works while it is running.
- Python 3.10 or newer.
- A Vector account **just for the bot**. Create a new one in the Vector app, or let the installer generate one.
- Admin rights in the community you want the bot in.

!!! warning "Use a separate account"
    Never give the bot your personal key. The bot's key sits in a file on the computer running it, and the account needs powerful roles in your community. Keep your own account out of it.

The Vector SDK that Vectiq builds on has a Rust core. The first install compiles it, which takes several minutes and needs `rustc`, `cargo` and `cmake`. The macOS installer gets them from Homebrew for you.

## Install

Start by downloading the code:

```sh
git clone https://github.com/lucky-edgelord/aio-vector-bot
cd aio-vector-bot
```

### macOS

On a Mac, one script does the rest:

```sh
./install.sh
```

It installs Homebrew packages, creates a virtual environment, asks for the bot's key and any invite links, checks your `config.yaml`, and starts the bot at login. Leave the key blank to generate a new account (the key is saved in `.env`, so back it up). Logs go to `data/vectiq.log`.

Useful variations: `./install.sh --no-service` installs without starting at login, and `./install.sh --yes` skips every question and reads `VECTOR_NSEC` and `VECTIQ_INVITE_URLS` from the environment.

### With pip or pipx

You don't need to clone anything. This works on Linux and macOS, and needs `rustc`/`cargo` and `cmake` the first time because the Vector SDK is compiled from source.

```sh
pipx install "vectiq[dashboard,webhooks] @ git+https://github.com/lucky-edgelord/aio-vector-bot"
mkdir my-bot && cd my-bot
vectiq --init          # writes config.yaml and .env here
vectiq --setup         # friendly wizard; then put VECTOR_NSEC in .env
vectiq
```

Plain `pip install` in a virtual environment works the same way. Update with `pipx upgrade vectiq`, or reinstall with `--force` to pick up the newest commit. `vectiq --version` shows what you have.

### Linux

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[webhooks,dashboard]"
cp .env.example .env && chmod 600 .env
```

Open `.env` and set `VECTOR_NSEC` to the bot's key. Then check the configuration and start the bot:

```sh
.venv/bin/python -m vectiq --check
.venv/bin/python -m vectiq
```

To keep it running after you log out, see [Deployment](deployment.md#linux-with-systemd).

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

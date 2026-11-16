---
title: Configuration
group: Start here
order: 2
summary: How config.yaml works, which settings live where, and how to change them safely.
---

Everything about how Vectiq behaves is in one file, `config.yaml`, in the folder you cloned. Every setting has a comment next to it, and the full list with defaults is in the [settings reference](config-reference.md).

## Changing settings

1. Edit `config.yaml`.
2. Check it: `python -m vectiq --check` (or `./run.sh --check` on a Mac). A mistake gets a plain message such as `events.timezone: unknown time zone 'Mars/Base'` instead of a crash.
3. Apply it. Most changes take effect when you run `!vectiq reload` in chat (bot owners only). Turning a module on or off needs a restart.

!!! note "Restart on a Mac"
    The installer runs the bot as a login item. Restart it with `launchctl kickstart -k gui/$(id -u)/com.vectiq.bot`.

## Modules

Each feature is a module with a switch under `modules:`. Switch off what you don't need and its commands, background jobs and database tables stay idle.

```yaml
modules:
  moderation: true
  leveling: true
  events: true
  securitycam: false      # off until you want it
  dashboard: false
```

The security cam and the dashboard start switched off because they are the two features that need a deliberate decision. See the [modules table](config-reference.md#modules) for the full list.

## Who can do what

Vectiq checks permissions against Vector itself. A moderator needs the matching Vector permission to use a moderation command, so there is no separate permission list to keep in sync.

Some commands are for the person running the bot rather than for community staff (`!vectiq reload`, `!webhooks`). They work for the accounts listed under `owners`:

```yaml
owners:
  - npub1...your own account...
```

If `owners` is empty, nobody has owner rights, so set it once you know your npub.

## Secrets

Keys and tokens stay out of `config.yaml`. They live in `.env`, which is created from `.env.example` and should only be readable by you (`chmod 600 .env`):

| Variable | What it is |
|---|---|
| `VECTOR_NSEC` | The bot's account key. Required. |
| `VECTIQ_INVITE_URLS` | Community invite links the bot joins once, separated by spaces. |
| `VECTIQ_DATA_DIR` | Where the database and the bot's identity are kept. Defaults to `data`. |
| `WEBHOOKS_ADMIN_KEY` | Optional key that protects the webhook admin endpoint. |

## Settings changed in the dashboard

If you use the [dashboard](dashboard.md), settings you change there are saved in the database and layered on top of `config.yaml`. The file itself is never rewritten, so your comments stay. Each changed setting shows a "dashboard" tag and can be reset to the value in the file, and **Export YAML** downloads the merged result if you want to move it back into the file.

## Per-community settings

A few things are set per community, from chat, because they differ between communities: the event time zone (`!event timezone`), the security cam channel (`!securitycam set`) and role menus. Everything else in `config.yaml` applies to every community the bot serves.

## All settings

{{config:general}}

Every other section of the file has its own table on the [settings reference](config-reference.md) page, and the guide for each module explains the settings that matter most.

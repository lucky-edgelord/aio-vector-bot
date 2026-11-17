---
title: Deployment
group: Start here
order: 3
summary: Keep Vectiq running, put the dashboard behind HTTPS, update it and back it up.
---

This page is about running the bot for the long term: starting it automatically, keeping it up to date and keeping the data safe.

## Running in the foreground

`./run.sh` starts the bot in the terminal and Ctrl-C stops it. It is the quickest way to try things, and extra arguments are passed along, for example `./run.sh --check`.

## macOS

`./install.sh` creates a launchd agent called `com.vectiq.bot` that starts the bot at login and restarts it if it stops. Logs are in `data/vectiq.log`.

```sh
launchctl kickstart -k gui/$(id -u)/com.vectiq.bot     # restart
tail -f data/vectiq.log                                # watch the log
./uninstall.sh                                         # stop it and remove the login item
```

`uninstall.sh` keeps your `data/` folder and `.env`. Delete the whole folder to remove everything.

!!! note "Not yet tested on a real Mac"
    The macOS installer and launchd agent have been written carefully but have not yet been run on a physical Mac. If something is off, please [open an issue](https://github.com/lucky-edgelord/aio-vector-bot/issues).

## Linux with systemd

Create `/etc/systemd/system/vectiq.service`, adjusting the user and paths:

```ini
[Unit]
Description=Vectiq community bot
After=network-online.target
Wants=network-online.target

[Service]
User=vectiq
WorkingDirectory=/opt/aio-vector-bot
ExecStart=/opt/aio-vector-bot/.venv/bin/python -m vectiq
Restart=always
RestartSec=15

[Install]
WantedBy=multi-user.target
```

Then enable it and follow the log:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now vectiq
journalctl -u vectiq -f
```

## The dashboard and webhooks over HTTPS

Both the [dashboard](dashboard.md) and the [webhook server](webhooks.md) are plain HTTP and listen on your machine. To reach them from elsewhere, put an HTTPS reverse proxy in front. With Caddy that is one line, and it gets the certificate for you:

```sh
caddy reverse-proxy --from dash.example.com --to 127.0.0.1:8090
```

Then set `dashboard.base_url` to the `https://` address. That tells the dashboard to mark its cookies Secure and to use the right address in sign-in links. A private network such as Tailscale works too and needs no public address.

## Updating

```sh
git pull
.venv/bin/pip install -e ".[webhooks,dashboard]"
```

Then restart the bot. Database changes are applied automatically when it starts, and each one is applied only once. A restore point is made first, so you can go back if the update causes trouble. Read the [changelog](changelog.md) first if you are updating across several versions.

## Backups

The bot makes [restore points](restore-points.md) on its own: every day, before updates change the database, and before imports and rollbacks. Point `backup.dir` at another disk so a failed drive doesn't take the backups with it.

To copy just the database by hand while the bot runs, use SQLite's own backup command, which is safe in the middle of a write:

```sh
sqlite3 data/vectiq.db ".backup backup.db"
```

Also keep a copy of `.env` somewhere private. It holds the bot's key, which is the bot's account, and restore points deliberately leave it out. If you lose it, you can create a new bot account, but it will be a different member of your community.

## Logs and health

The bot logs what it loads on start, one line per module, and warns when a feature can't work (a missing permission, a channel it can't find). Run it with `-v` for more detail. `!vectiq stats` in chat shows the database size and row counts, and `!ping` confirms it is answering.

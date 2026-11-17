---
title: Docker
group: Start here
order: 4
summary: Run Vectiq in a container with Docker Compose, on Linux, a NAS or a server.
---

The Docker image runs the same bot as the Mac install. Your settings live in `docker-config/` and everything the bot writes (database, restore points, logs) lives in `docker-data/`, both next to the compose file, so removing or rebuilding the container never loses anything.

## Start it

```sh
git clone https://github.com/lucky-edgelord/aio-vector-bot && cd aio-vector-bot
echo 'VECTOR_NSEC=nsec1...' > .env          # the bot's key; add VECTIQ_INVITE_URLS=... to join communities
docker compose up -d
docker compose logs -f
```

The first build compiles the Vector SDK, so it takes a few minutes. On first start the commented example `config.yaml` is copied into `docker-config/`.

## Set it up

```sh
docker compose run --rm -it vectiq python -m vectiq --setup
```

This is the same friendly setup wizard as everywhere else. You can also edit `docker-config/config.yaml` by hand, then `docker compose restart`, or use the dashboard.

## Dashboard and other ports

The dashboard listens on port 8090 inside the container and is published only on `127.0.0.1` by default. Put HTTPS (Caddy, Tailscale and so on) in front for remote use, and set `dashboard.base_url` to the address people open. Webhooks (8080) and the CAPTCHA page need that port published too: uncomment the line in `docker-compose.yml`.

## Backups, updates and tools

```sh
docker compose run --rm vectiq python -m vectiq --backup "before update"   # restore point
docker compose run --rm vectiq python -m vectiq --list-backups
git pull && docker compose up -d --build                                   # update
```

Restore points are saved in `docker-data/restore-points`; copy that folder off the machine for a real backup. Stop the bot before `--restore`.

## Settings

| Variable | Meaning |
|---|---|
| `VECTOR_NSEC` | The bot's key (required). |
| `VECTIQ_INVITE_URLS` | Space-separated invite links to join. |
| `VECTIQ_DASHBOARD_HOST` | Dashboard address; the image sets `0.0.0.0` so the published port works. |

The image sets `VECTIQ_CONFIG=/config/config.yaml` and `VECTIQ_DATA_DIR=/data`. It runs as a non-root user (uid 10001); if the folders on the host are owned by someone else, run `sudo chown -R 10001 docker-config docker-data`.

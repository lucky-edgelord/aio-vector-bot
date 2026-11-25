---
title: Updates
group: Start here
order: 6
summary: Find out when a newer Vectiq is out, and install it in one click from the dashboard or with one chat command.
---

# Updates

Vectiq looks for a newer version now and then (every 12 hours by default). When one is ready it sends each bot owner one private message. Nothing is installed until you say so.

## Installing an update

- **Dashboard:** open **Updates** in the menu (owners only) and press **Update now**.
- **Chat:** `!update` shows what's new, `!update now` installs it.

Either way Vectiq first makes a [restore point](restore-points.md), pulls the new version (your own `config.yaml` is kept), installs any new packages and restarts itself a few seconds later. If a service manager runs Vectiq, it just sees the same process carry on. If anything fails along the way you are told why and nothing is left half-done; the restore point is there if you want to roll back.

## What can update itself

A copy installed with the one-line installer (a `git` checkout) can. If you edited Vectiq's own files, it won't overwrite them: undo or commit those edits first. Copies run from Docker or a package can still check, and they tell you the command to run instead (for Docker: `docker compose pull && docker compose up -d`).

## Settings

```yaml
updates:
  check: true          # look for updates now and then
  every_hours: 12      # how often
  notify: true         # DM the owners once per new version
  restart: true        # restart by itself after updating
  repo: lucky-edgelord/aio-vector-bot
```

Turn `check` off and nothing contacts GitHub on its own. You can still check by hand.

---
title: Image guard
group: Community
order: 4
summary: Polices pictures. A blocklist of known pictures always works; nudity detection can run on your computer or through an API.
---

The image guard looks at every picture posted (JPEG, PNG, GIF, WebP...). It has two parts.

## The blocklist

Reply to a picture with `!imageguard block spam` and it's removed, along with every later copy. The match uses a picture fingerprint (a perceptual hash), so resized, cropped a little or re-saved copies are caught too. `match_distance` sets how close counts as the same picture: 0 means identical only, and the default of 6 catches most re-uploads.

The blocklist needs nothing extra installed and is kept per community. `!imageguard list` shows it and `!imageguard unblock 3` removes an entry.

## Nudity detection

Set `detector` to have pictures scored for nudity. A picture scoring `threshold` (0 to 1) or more is removed, and with `remember: true` its fingerprint joins the blocklist, so a repost isn't scored again.

| Detector | Runs | Setup |
|---|---|---|
| `off` | | Blocklist only. |
| `nudenet` | on your computer | `pip install "vectiq[nudenet]"`. Small, private, no account. |
| `nsfw-detector` | on your computer | `pip install "vectiq[nsfw-detector]"`, which pulls in TensorFlow, plus a model file (below). |
| `sightengine` | Sightengine's API | An account; put `SIGHTENGINE_USER` and `SIGHTENGINE_SECRET` in `.env`. |
| `http` | your own API | `http.url`. Vectiq posts the picture as multipart field `media` and reads the score from `score_field`. |

Local detectors load their model the first time a picture is checked, not at start-up, and run in the background so chat doesn't slow down.

### nsfw-detector

[nsfw-detector](https://pypi.org/project/nsfw-detector/) runs GantMan's open model. It sorts pictures into drawings, hentai, neutral, porn and sexy, and Vectiq adds up porn and hentai (and sexy, with `count_sexy: true`). Download a Keras `.h5` model from the [nsfw_model releases](https://github.com/GantMan/nsfw_model/releases), then:

```yaml
imageguard:
  detector: nsfw-detector
  nsfw_detector:
    model_path: /path/to/nsfw_mobilenet2.224x224.h5
```

The package hasn't been updated since 2021, needs TensorFlow, and is GPLv3 licensed (Vectiq doesn't bundle it). NudeNet is lighter if you have no preference.

## Exceptions and actions

`allow_channels` turns checks off in channels where anything goes, such as an adults-only channel. Staff with Manage Messages and `exempt_roles` are skipped. `action` decides what happens: `delete` removes the message and says why, `warn` also adds a warning, `timeout` also mutes the member for `timeout_minutes`, and `log` only tells the mod log.

Use `!imageguard test` on a picture (attach it, or reply to it) to see its blocklist match and detector score without removing anything.

!!! note "No detector is perfect"
    Every detector sometimes flags a safe picture or misses one. Try `action: log` first, check the mod log, then tune `threshold`.

## Commands

{{commands:Image guard}}

## Settings

{{config:imageguard}}

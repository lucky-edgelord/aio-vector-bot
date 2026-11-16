---
title: Security cam
group: Community
order: 8
summary: Echo every message from every channel into one staff channel, with the author, channel, time and attachments.
---

The security cam copies every message from every channel into one channel of your choice, so staff can follow the whole community in one place. It is **off by default** because it shows everything, including channels members expect to be quiet.

!!! warning "Make the camera channel staff-only"
    Everything said anywhere in the community appears in the camera channel. Anyone who can read it can read everything. Restrict it to the people who should see all messages, and think about whether members should be told it exists.

## Turning it on

1. Set `securitycam: true` under `modules` in `config.yaml` and restart.
2. In the channel you want to receive the echoes, type `!securitycam set`. Or name it: `!securitycam set staff-cam`. You need Manage Community.

`!securitycam` shows where messages are going right now and `!securitycam off` stops it. You can also choose the channel on the **Security cam** page of the [dashboard](dashboard.md), or put a channel name in `securitycam.channel` in `config.yaml`.

## What an echo looks like

Each message arrives in three parts:

1. The author's name and what they wrote.
2. Any attachments, re-uploaded so they are still there after the original is gone. A file that can't be copied (too large, or unavailable) is listed with its link instead.
3. A footer with the channel it came from and the time it was sent.

## What is left out

- The camera channel itself, so it can never loop on itself.
- The bot's own messages.
- Other bots, unless you set `securitycam.include_bots: true`.
- Any channels you list in `securitycam.ignore_channels`, or switch off on the dashboard page. Use this for a channel where people share private things.

```yaml
securitycam:
  channel: staff-cam
  include_bots: false
  ignore_channels: [therapy-corner]
```

## Settings

{{config:securitycam}}

## Commands

{{commands:Security cam}}

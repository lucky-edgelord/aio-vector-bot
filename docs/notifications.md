---
title: Stream & video alerts
group: Connect
order: 3
summary: Post in a channel when a YouTube channel uploads, a Twitch channel goes live, or any RSS or Atom feed has something new.
---

Turn alerts on with `!module on notifications`, then add feeds in chat:

```text
!notify add youtube @SomeChannel #videos
!notify add twitch somestreamer #live @Viewers
!notify add rss https://blog.example.com/feed.xml #news
!notify
!notify remove 2
```

YouTube takes a channel link, an `@handle` or a channel id, and needs no account or key. Twitch needs a free app from [dev.twitch.tv](https://dev.twitch.tv/console/apps): put its `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET` in `.env`. RSS and Atom take a feed link.

When a feed is added, what's already there is remembered and not posted, so you won't get a flood of old videos. After that, everything new is posted, at most `max_per_check` per feed each time.

## In config.yaml

Feeds can also be declared in `config.yaml`, which is handy for keeping them in version control:

```yaml
notifications:
  channel: announcements
  messages:
    youtube: "📺 {author} just uploaded **{title}**\n{url}"
  feeds:
    - {type: youtube, source: "@SomeChannel", channel: videos}
    - {type: twitch, source: somestreamer, channel: live, role: Viewers}
```

`{title}`, `{url}`, `{author}` and `{kind}` work in messages.

!!! note "YouTube live streams"
    YouTube's feed lists uploads and premieres. A stream shows up when YouTube publishes its page, which is usually when it's scheduled or starts.

## Commands

{{commands:Stream & video alerts}}

## Settings

{{config:notifications}}

---
title: Automod
group: Community
order: 2
summary: Removes spam, mass mentions, shouting, banned words, invite links, floods and risky files. Every rule has its own switch.
---

Automod checks each message as it's posted and removes the ones that break a rule. Turn it on with `!module on automod`, or in the setup wizard.

People with **Manage Messages** are never checked, and neither are bots. You can also skip roles and channels with `exempt_roles` and `exempt_channels`.

## Rules

| Rule | Removes | On by default |
|---|---|---|
| `mentions` | messages that mention more than `max` people | yes |
| `caps` | shouting: at least `percent`% capitals in a message of `min_length` letters or more | yes |
| `invites` | invite links to Vector communities, Discord, Telegram, WhatsApp, Signal and Matrix | yes |
| `flood` | more than `messages` messages in `seconds` from one person | yes |
| `duplicates` | the same message more than `repeats` times in `seconds` | yes |
| `files` | attachments with risky extensions (.exe, .bat, .scr, .apk...) | yes |
| `words` | banned words (whole words; `partial: true` also matches inside words) | no |
| `links` | every link, except domains in `allow` | no |
| `zalgo` | glitchy text stacked with combining marks | no |

To let your own community's invite through, add part of it to `invites.allow`.

## What happens

`action` decides what automod does, and a rule can set its own `action` to override it:

- `delete` removes the message and says why. The notice disappears after a minute.
- `warn` also adds a warning, which counts toward [Moderation](moderation.md)'s warning threshold.
- `timeout` also warns and mutes the member for `timeout_minutes`.
- `log` removes nothing and only tells the mod log. It's useful for trying a rule out first.

Removed messages are noted in `moderation.log_channel`.

```yaml
automod:
  action: delete
  words: {enabled: true, list: [heck, darn]}
  flood: {enabled: true, messages: 5, seconds: 6, action: timeout}
```

For dangerous links (scams, malware), use [Link safety](link-safety.md) as well. It checks against lists of hundreds of thousands of known bad sites.

## Commands

{{commands:Automod}}

## Settings

{{config:automod}}

---
title: Webhooks
group: Connect
order: 1
summary: Declare webhooks in YAML so outside tools can post into a channel, and mirror Vectiq events there.
---

A webhook is a secret URL that lets an outside tool (GitHub, a monitoring service, a script) post a message into a channel. With Vectiq you list the webhooks you want in `config.yaml` and the bot creates them for you.

## Declaring a webhook

```yaml
webhooks:
  server:
    enabled: true                    # also serve the HTTP endpoint so outside tools can post
    base_url: "https://hooks.example.com"
  hooks:
    - name: deploys                  # unique name
      channel: deploys               # channel name or id
      notify: [owners]               # who is DMed the secret URL when it is created
      events: [mod, levels]          # Vectiq events mirrored into the channel
```

Each hook has:

| Field | Meaning |
|---|---|
| `name` | A unique name. It is how you refer to the hook in commands. |
| `community` | The community name. Leave it out when the bot is only in one. |
| `channel` | The channel the hook posts into. |
| `notify` | Who gets the URL by DM when it is created: `owners`, or a list of npubs. |
| `events` | Which Vectiq events are copied into the channel. |

## What happens on start

When the bot starts, and when you run `!webhooks sync`, it creates any hook that doesn't exist yet and sends each person in `notify` the secret URL **once**. The bot stores only a hash of the secret, so it can't show it to you again. If you lose a URL, make a new one with `!webhooks rotate deploys`, which stops the old one from working.

## Mirroring events

List event kinds under `events` and the bot posts a line into the channel whenever one happens:

| Event | When |
|---|---|
| `mod` | A warning, timeout, kick or ban |
| `joins`, `leaves` | Someone joins or leaves |
| `levels` | Someone levels up |
| `tickets` | A ticket is opened or closed |
| `giveaways` | A giveaway starts or ends |
| `games` | A mini game finishes |
| `onboarding` | A member finishes onboarding |
| `events` | An event is created, reminded, started or cancelled |

## Letting outside tools post

Hooks use the SDK's Discord-compatible format, so any tool that can post to a Discord webhook works. Take the URL the bot sent you and use it where the tool asks for a Discord webhook URL.

Posting from outside needs the HTTP endpoint on, which means `webhooks.server.enabled: true`, `pip install "vector-sdk-py[webhooks]"` (the installer does this), and HTTPS in front of it for anything beyond your own network. See [Deployment](deployment.md#the-dashboard-and-webhooks-over-https). The `base_url` must be the address people outside reach it at.

`!webhooks test deploys` sends a test message through a hook so you can check it.

## Commands

{{commands:Webhooks}}

## Settings

{{config:webhooks}}

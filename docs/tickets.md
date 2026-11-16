---
title: Tickets
group: Community
order: 4
summary: Private support channels, claimed by staff and closed with a command or a reaction.
---

Tickets give each request its own private channel. Members open one, staff pick it up, and when it is resolved anyone with access closes it. The conversation is kept as a transcript.

## How it works

1. A member types `!tickets open I can't see the rules channel`. The bot creates a private channel, `ticket-` plus a number, that only the member and your support team can see.
2. Staff type `!tickets claim` in the channel to say they are handling it.
3. When it is done, the member who opened it or any staff member types `!tickets close`, or reacts with 🔒 on any message in the ticket.
4. The channel is deleted, and the conversation stays in the transcript.

Close with a reaction by changing the emoji, or turn it off by leaving it blank:

```yaml
tickets:
  close_emoji: "🔒"
```

## Setting it up

```yaml
tickets:
  category: Support           # where ticket channels are created
  support_role: Moderator     # this role sees every ticket
  max_open_per_user: 2
  transcripts: true
```

The bot needs Manage Channels to create the channels. Without a `support_role`, only the bot and the opener can see a ticket, so name one.

## Transcripts

With `transcripts: true`, the bot keeps the messages of each ticket. Staff read one with `!tickets transcript 12`, and the [dashboard](dashboard.md) shows the same thing as a conversation. Transcripts stay after the channel is deleted.

## Communities on the legacy roster

Vector communities on the legacy roster don't accept per-channel permission settings. When that happens, Vectiq creates a plain private channel and gives the opener and your support role access to it another way, so tickets still work. If you see two similarly named channels, a first attempt was rejected and the second one succeeded. The bot reuses a channel with the same name when it can.

## Commands

{{commands:Tickets}}

## Settings

{{config:tickets}}

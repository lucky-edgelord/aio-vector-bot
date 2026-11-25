---
title: Ban appeals
---

# Ban appeals

A banned person can ask to come back. They fill the appeal in by private message, it lands in a staff channel, and your moderators vote on it. No one has to hunt for the person or relay anything.

## Set up

1. Keep `appeals: true` under `modules` in `config.yaml` (it is on by default).
2. Choose the staff channel: set `appeals.channel`, or leave it blank to use `moderation.log_channel`. Keep it private.
3. Optional: `appeals.questions` (the form; edit, add or remove questions), `appeals.votes_needed` (default 2), `appeals.cooldown_days` (default 7), `appeals.min_chars` and `appeals.max_chars`.

## For the banned person

The moment someone is banned (by a Vectiq command, the dashboard, or by hand in the Vector app) the bot messages them: it sends them the appeal form: a few questions, asked one at a time in the DM. Their answers are the appeal. If their DMs are closed, or they changed their mind, they can start it themselves by messaging the bot:

```
!appeal
```

The bot checks that you are banned, then sends you the form. If you are banned from more than one community, add its name: `!appeal Cool Place`. `!appeal cancel` stops a draft. You get a message when the moderators decide. After a denial you wait `appeals.cooldown_days` before appealing again.

## For moderators

Each appeal appears as a card with ✅ and ❌ reactions. Anyone with the Ban Members permission can vote by reacting. When `votes_needed` people approve, the ban is lifted (it is recorded as an unban case) and the person is told. When that many deny, the appeal closes. Changing your mind is fine: your latest vote counts, once.

If reactions are not working, use `!appealvote 3 yes` or `!appealvote 3 no`. `!appeals` lists open appeals and their votes.

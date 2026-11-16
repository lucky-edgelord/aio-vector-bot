---
title: Welcome and onboarding
group: Community
order: 5
summary: Greet new members, verify them with a question and let them pick roles.
---

Three modules work together to look after a new member: **welcome** greets them, **verification** makes sure they are a person, and **onboarding** walks them through the steps and lets them pick roles. You can use any of them alone.

## Welcome messages

```yaml
welcome:
  enabled: true
  channel: general            # blank = the community's system channel
  message: "Welcome to {community}, {mention}! You are member #{count}."
  leave_message: "{name} has left {community}."
  dm_message: ""              # optional private message
```

The placeholders are `{mention}`, `{name}`, `{community}` and `{count}` (the number of members). `!testwelcome` previews the message in the channel. Staff need Manage Community to run it.

## Verification

Verification asks a new member a question before they get a role. It has two modes:

- `question` (default): the bot asks a small arithmetic question and the member answers with `!verify 12`. After `max_attempts` wrong answers they are locked out until staff help.
- `button`: the member reacts with ✅ to the bot's message in the verification channel.

```yaml
verification:
  mode: question
  role: Verified              # granted on success, created if missing
  max_attempts: 3
  channel: welcome
```

Staff can verify someone by hand with `!forceverify @sam`. Use the Verified role to hide your other channels, so only verified members see them.

## Onboarding

Onboarding strings the steps together in order. The default is verify, then pick roles:

```yaml
onboarding:
  steps: [verify, pick_roles]
  channel: welcome
  required: false
  title: "Pick your interests"
  prompt: "Welcome! Pick your roles below, then say hi."
  done_message: "{mention} you're all set. Enjoy {community}!"
  role_menu:
    "🎮": Gamer
    "🎨": Artist
    "💻": Dev
```

The role menu is built from the `role_menu` list: emoji on the left, role name on the right, with the roles created if they don't exist. Members react to pick, and take the reaction back to drop the role. It is the same as a [role menu](role-menus.md) you would build by hand.

Progress is stored for each member. With `required: true`, a member finishes onboarding only once they have picked a role. When someone finishes, an `onboarding` event is sent, which a [webhook](webhooks.md) can mirror into a channel. `!onboarding` shows how many members have started and finished, and posts the role menu again if it is missing.

## Commands

{{commands:Welcome}}

{{commands:Verification}}

{{commands:Onboarding}}

## Settings

### Welcome

{{config:welcome}}

### Verification

{{config:verification}}

### Onboarding

{{config:onboarding}}

---
title: Sentire (automod)
group: Community
order: 2
summary: Vectiq's automod is Sentire, by JSKitty. Run your own copy, set up from Vectiq, or invite the official Sentire-001.
---

[Sentire](https://github.com/VectorPrivacy/Sentire) is a moderation bot for Vector communities, made by JSKitty of VectorPrivacy, and it's Vectiq's automod. Each member carries one strike score that decays over time, raids are contained as a single event, and a vision model you choose judges media. It's a separate program written in Rust, with its own Vector account.

There are two modules, and one of them runs at a time:

| Module | What it does |
|---|---|
| **Sentire** (`sentire`) | Vectiq builds and runs **your own copy**. Its rules come from Vectiq's settings, dashboard and wizard, and it has its own Vector account. |
| **Sentire (official)** (`sentire_official`) | Vectiq invites **Sentire-001**, the copy VectorPrivacy runs. Nothing to build. Its rules are set with its own chat commands. |

## Your own copy

The **Sentire module** runs it for you:

- **Builds or finds it:** Vectiq builds Sentire for you, or uses one you point it at.
- **Writes its config:** Vectiq writes Sentire's `sentinel.toml` from Vectiq's settings, so you configure it in `config.yaml`, on the dashboard or in the setup wizard like any other module.
- **Runs it:** it starts while the module is on, restarts it if it stops, and stops it when you switch the module off.
- **Invites it:** Vectiq invites it into your communities and gives it a role for what it's allowed to do.
- **Shows it:** its status and live log are on the dashboard's **Sentire** page and in `!sentire`.

Both Sentire modules do automod's job, so switching one on switches the other off (and any automod plugin, such as the [AI automod example](writing-modules.md#example-an-ai-automod)). If you turn on its vision lane, switch [Image guard](image-guard.md)'s detector off too, so pictures aren't judged twice.

### Set it up

```sh
vectiq --install-sentire          # downloads and builds Sentire (needs Rust; the installers set it up)
```

Then:

1. **Switch it on:** `!module on sentire`, or Settings → Modules on the dashboard.
2. **Bring it into a community:** in that community, `!sentire invite`, or **Invite Sentire here** on the dashboard's Sentire page. When it joins, Vectiq gives it a role called **Sentire**.
3. **Decide what it may do:** Sentire starts by only watching and reporting. Arm what it may do under Settings → Sentire: warn, delete, kick, ban, contain raids.

It gets its own Vector identity, made once and kept in `data/sentire/identity.env`. Back that file up with your data. Its own database sits beside it in `data/sentire`.

### Settings

Everything below writes the `sentinel.toml` Vectiq keeps in `data/sentire`. A change restarts Sentire with the new file. For anything Vectiq doesn't expose, put it under `extra:` exactly as Sentire's example config spells it:

```yaml
sentire:
  arm: {warn: true, delete: true}
  banned_words: [slur1, "*partial*"]
  extra:
    limits:
      max_actions_per_hour: 50
```

You can also keep your own file and set `config_file:` to its path; Vectiq then runs Sentire with it as it is.

{{config:sentire}}

## Sentire's own commands

Sentire answers its own slash commands in the community: `/help`, `/status`, `/why <member>`, `/pardon <member>`, `/words`, `/links`, `/ladder` and more. Changes made there are kept in Sentire's own database and win over the file. See [its README](https://github.com/VectorPrivacy/Sentire#chat-commands).

## Vectiq's commands

{{commands:Sentire}}

With Sentire (official) on, `sentire` and `sentire invite` work the same way for the official bot.

## The official Sentire-001

If you'd rather not build or run anything, switch on **Sentire (official)** instead: `!module on sentire_official`. Then, in each community, run `!sentire invite`, or press **Invite Sentire here** on the dashboard's Sentire page. Vectiq invites the official Sentire-001:

```
npub1pc5sdve5w6wczjhhnzu4te7ayjujlprm2y4ndx044gzsqx0gq64qytz06y
```

When it joins, Vectiq gives it a role. Sentire-001 does what its role allows, so the settings under Settings → Sentire (official) decide that:

| Setting | Role permission | Lets it |
|---|---|---|
| `delete` (on by default) | Manage Messages | delete what it convicts |
| `kick` | Kick | kick on its ladder, contain raids |
| `ban` | Ban | ban |

Change them and the role is updated in every community it's in. Its rules (words, links, ladder) belong to Sentire-001 itself: set them in the community with `/words`, `/links` and `/ladder`. `!sentire` shows whether it's there and what it may do.

{{config:sentire_official}}

## Docker

Build the image with Sentire inside: set `SENTIRE: "1"` under `args` in `docker-compose.yml`, then `docker compose up -d --build`.

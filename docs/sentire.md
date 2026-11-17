---
title: Sentire
group: Community
order: 5
summary: Run the Sentire moderation bot beside Vectiq, set up from Vectiq's settings, dashboard and wizard.
---

[Sentire](https://github.com/VectorPrivacy/Sentire) is a moderation bot for Vector communities, made by VectorPrivacy. Each member carries one strike score that decays over time, raids are contained as a single event, and a vision model you choose judges media. It's a separate program written in Rust, with its own Vector account.

The **Sentire module** runs it for you:

- **Builds or finds it:** Vectiq builds Sentire for you, or uses one you point it at.
- **Writes its config:** Vectiq writes Sentire's `sentinel.toml` from Vectiq's settings, so you configure it in `config.yaml`, on the dashboard or in the setup wizard like any other module.
- **Runs it:** it starts while the module is on, restarts it if it stops, and stops it when you switch the module off.
- **Invites it:** Vectiq invites it into your communities and gives it a role for what it's allowed to do.
- **Shows it:** its status and live log are on the dashboard's **Sentire** page and in `!sentire`.

Sentire does automod's job, so switching it on switches Vectiq's [Automod](automod.md) off, and back. If you turn on its vision lane, switch [Image guard](image-guard.md)'s detector off too, so pictures aren't judged twice.

## Set it up

```sh
vectiq --install-sentire          # downloads and builds Sentire (needs Rust; the installers set it up)
```

Then:

1. **Switch it on:** `!module on sentire`, or Settings → Modules on the dashboard.
2. **Bring it into a community:** in that community, `!sentire invite`, or **Invite Sentire here** on the dashboard's Sentire page. When it joins, Vectiq gives it a role called **Sentire**.
3. **Decide what it may do:** Sentire starts by only watching and reporting. Arm what it may do under Settings → Sentire: warn, delete, kick, ban, contain raids.

It gets its own Vector identity, made once and kept in `data/sentire/identity.env`. Back that file up with your data. Its own database sits beside it in `data/sentire`.

## Settings

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

## Docker

Build the image with Sentire inside: set `SENTIRE: "1"` under `args` in `docker-compose.yml`, then `docker compose up -d --build`.

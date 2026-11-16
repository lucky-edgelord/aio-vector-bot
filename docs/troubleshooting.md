---
title: Troubleshooting
group: Reference
order: 3
summary: Fixes for the problems people hit most often, from a silent bot to a dashboard that won't sign in.
---

Start with the log. Run the bot in a terminal (`./run.sh`) or read it with `journalctl -u vectiq -f` if it runs as a service. Most problems are named there.

## The bot doesn't answer commands

- **Is it in the community?** Invite it and check `!ping`.
- **Is it using the right prefix?** The default is `!`. Check `prefix` in `config.yaml`.
- **Is the feature on?** A command from a module set to `false` under `modules` doesn't exist. `!help` lists what is on.
- **Does it have the permissions?** It needs to read and send in that channel.
- **Is it set up for this community?** If `communities` lists names, the community must be among them, or leave the list empty to serve all.

## "Only one Vector bot can run per process"

The Vector library allows one bot per process. Two copies of Vectiq on the same account, or the bot and your own test script, can't share one process. Stop the other and start again.

## Sign-in codes don't arrive

The code is sent as a DM from the bot. If the dashboard says it sent one and nothing comes:

- Make sure the npub you entered is yours and is an admin of a community the bot is in, or one of the bot's `owners`.
- Check that you can receive DMs from the bot, and look in message requests.
- Type `!dashboard` in chat, or use a username and password made with `vectiq --add-user`, instead.

## The dashboard is blank or says "can't reach the server"

- Is the bot running, with `modules.dashboard: true`?
- The `base_url` must be the address you really use. A mismatch between `http` and `https` stops sign-in cookies from working.
- Behind a proxy, check it forwards to the right `port`.

## Events

- **"I couldn't understand that time."** Write the time as you'd say it: `friday 8pm`, `nov 20 7pm`, `in 2h`. Add the date if the day is not obvious.
- **The time is wrong by hours.** The community's time zone is not set. Use `!event timezone <zone>`, with a name like `Europe/Berlin`.
- **No reminders arrive by DM.** Someone with DMs closed can't be reached. Reminders for events the bot slept through are skipped.
- **The event went to the wrong channel.** The bot looks for a channel matching `events.channel`. Rename the channel or change the setting.
- **The banner shows boxes instead of symbols.** The banner font can't draw emoji, so they are removed from the title on purpose.

## Mini games

- **The app says "retry".** The bot only trusts frames that come straight from a player's own device. Opening the game again fixes it.
- **Nobody can join.** With `games.join_when: opened`, the bot joins when the first player opens the app. If a player can't open it, update Vector.

## The security cam

- **No echoes appear.** Check `!securitycam` shows a channel, and that `modules.securitycam` is `true`. The bot needs to be able to send in that channel.
- **Some attachments are links, not files.** Files that can't be copied (too large or gone) are linked instead.

## Webhooks

- **The URL was lost.** The bot shows it once. Run `!webhooks rotate <name>` to make a new one.
- **Outside tools get no answer.** Check `webhooks.server.enabled`, that the extra is installed (`pip install "vector-sdk-py[webhooks]"`) and that the `base_url` is reachable from outside.

## The database

- **"database is locked."** Two copies of the bot are using the same `data/vectiq.db`. Stop one.
- **Back up and restore.** Copy it with `sqlite3 data/vectiq.db ".backup backup.db"` while the bot runs. To restore, stop the bot and put the file back.

## Still stuck?

Open an [issue](https://github.com/lucky-edgelord/aio-vector-bot/issues) with the log lines around the problem. Leave out any key, nsec or sign-in code.

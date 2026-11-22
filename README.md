# AIO Vector Bot (Vectiq)

[![CI](https://github.com/lucky-edgelord/aio-vector-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/lucky-edgelord/aio-vector-bot/actions/workflows/ci.yml)
[![Docs](https://github.com/lucky-edgelord/aio-vector-bot/actions/workflows/pages.yml/badge.svg)](https://lucky-edgelord.github.io/aio-vector-bot/)

**Documentation: https://lucky-edgelord.github.io/aio-vector-bot/**

An all-in-one community bot for any Vector community. Clone it, give it its own key, edit `config.yaml`, run it. The package and command are called `vectiq`.

A community-management bot for [Vector](https://vectorapp.io), in the spirit of [Logiq](https://github.com/programmify/Logiq) (a Discord MEE6 alternative), written from scratch on `vector-sdk-py` with **SQLite** instead of MongoDB.

Moderation, automod by **[Sentire](https://github.com/VectorPrivacy/Sentire)** (run your own, or invite the official one), **link safety** (oisd.nl blocklists), an **image guard** (picture blocklist plus optional nudity detection), leveling with image rank cards, an economy and shop, tickets, **CAPTCHA verification**, onboarding, reaction roles, giveaways, an event calendar, **YouTube / Twitch / RSS alerts**, **music in voice channels**, welcome messages, analytics, **WebXDC mini games** refereed by the bot, **webhooks you declare in YAML**, a **web dashboard** (including creating channels, categories, roles and permissions), an **MCP server** so Claude or other AI assistants can manage your communities, a **setup wizard** (dashboard and terminal), settings **import and export**, and **restore points** you can roll back to.

**Everything is a module, and modules are pluggable.** Switch any feature on or off while the bot runs (`!module on music`, the dashboard or the wizard); only what's on is loaded. Add your own, or replace a built-in one (an AI automod instead of Sentire, say), by dropping a plugin into `modules/` or `pip install`ing it; swap and reload them live. See [Modules](https://lucky-edgelord.github.io/aio-vector-bot/modules.html) and [Writing modules](https://lucky-edgelord.github.io/aio-vector-bot/writing-modules.html); [`examples/vectiq-ai-automod`](examples/vectiq-ai-automod) is a complete plugin.

**A module can be one JSON file.** Commands, autoresponders and timers (and optionally Python) in a single `.module.json`: write one or ask an AI to, add it on the dashboard's **Marketplace** page, export yours to share, or get one from the [marketplace](https://lucky-edgelord.github.io/aio-marketplace/) with `!module get <id>`. Modules without code can only talk, react and post; modules with code stay off until you allow them. See [JSON modules](https://lucky-edgelord.github.io/aio-vector-bot/json-modules.html) and [Marketplace](https://lucky-edgelord.github.io/aio-vector-bot/marketplace.html). The idea comes from how [Lilith Learning Lab](https://github.com/lucky-edgelord/Lilith-Learning-Lab) shares courses.

![The web dashboard's overview page: member, message and moderation stats, a 30-day activity chart and the busiest channels](docs/images/dashboard-overview.png)

<p align="center">
  <img src="docs/images/leaderboard-card.png" alt="The leaderboard card the bot posts in chat: eight members with avatars, XP, message counts and level badges" width="49%">
  <img src="docs/images/rank-card.png" alt="A member's rank card: avatar, rank, level, messages and progress to the next level" width="49%">
</p>
<p align="center"><sub>The leaderboard and rank cards members get in chat with <code>!leaderboard</code> and <code>!rank</code>.</sub></p>

<sub>All images show a made-up demo community. Regenerate them with <code>python tools/screenshots.py</code>.</sub>

```
src/vectiq/
  app.py, config.py, __main__.py      wiring, typed config.yaml loader, CLI
  db/        database.py, migrations.py     async SQLite facade + versioned schema
  stores/    one small class per feature (all SQL lives here)
  cogs/      one cog per feature (all Vector I/O lives here)
  games/     pure game rules + packager; apps/ holds the WebXDC front-ends
  render/    Pillow rank and leaderboard images
tests/       pytest: stores, rules, config, rendering, the referee cog
```

Rules never touch the network and stores never touch Vector, so almost everything is unit-tested without a live bot.

## Quick start

One line installs everything and starts the bot at login. Run it again later to update.

**macOS and Linux**

```sh
curl -fsSL https://raw.githubusercontent.com/lucky-edgelord/aio-vector-bot/main/get.sh | sh
```

**Windows** (PowerShell)

```powershell
irm https://raw.githubusercontent.com/lucky-edgelord/aio-vector-bot/main/get.ps1 | iex
```

Vectiq goes in `~/vectiq` (set `VECTIQ_DIR` for another folder). Asking an AI agent to install it for you? Point it at [AGENTS.md](AGENTS.md).

Or from a clone:

```sh
git clone https://github.com/lucky-edgelord/aio-vector-bot
cd aio-vector-bot
```

### macOS and Linux (e.g. a Mac mini)

```sh
./install.sh            # packages (Homebrew / apt / dnf / ...), Rust, venv, .env, launchd or systemd service
```

It asks for the bot's key (blank generates a new account) and optional community invite links. Then, in your Vector community, give the bot's account a role with the permissions it needs (Manage Roles, Manage Channels, Manage Messages, Moderate Members, Kick/Ban). Without them Vectiq still runs and tells you which permission is missing. Type `!help` anywhere.

Manual start: `./run.sh` (foreground), `./run.sh --check` (validate `config.yaml`), `./uninstall.sh`.
### Windows

```powershell
.\install.ps1          # winget: Python, Git, CMake, Rust, C++ build tools; venv; .env; scheduled task at logon
```

### Docker

```sh
echo 'VECTOR_NSEC=nsec1...' > .env
docker compose up -d          # settings in ./docker-config, data in ./docker-data
```

See the [Docker guide](docs/docker.md) for the setup wizard, ports and backups.

### pip / pipx

```sh
pipx install "vectiq[dashboard,webhooks] @ git+https://github.com/lucky-edgelord/aio-vector-bot"
mkdir my-bot && cd my-bot && vectiq --init && vectiq --setup
```

`--init` writes `config.yaml` and `.env` in the current folder; put the bot's `VECTOR_NSEC` in `.env`, then run `vectiq`.

### Linux

```sh
python3 -m venv .venv && .venv/bin/pip install -e ".[webhooks,dashboard]"
cp .env.example .env && chmod 600 .env    # put the bot's VECTOR_NSEC in it
.venv/bin/python -m vectiq --check && .venv/bin/python -m vectiq
```

The SDK (`vector-sdk-py`) is installed from [GitHub](https://github.com/lucky-edgelord/vector-sdk-py) and compiled from Rust on first install, so you need `rustc`/`cargo` and `cmake` (the macOS installer gets them from Homebrew), and the first install takes several minutes.

Use a **separate Vector account for the bot**, never your personal key.

## What was ported from Logiq

| Logiq | Vectiq | Notes |
|---|---|---|
| Moderation | `moderation` | warn/delwarn/clearwarns, timeout, kick, ban, tempban (auto-lifts), unban, purge, lock/unlock, soft slowmode, cases + history |
| Leveling | `leveling` | MEE6 curve, cooldown, level-up messages, role rewards, **image rank card and leaderboard** |
| Economy | `economy` | wallet + bank, daily streaks, work, pay, shop with roles and stock, rich list, transaction history |
| Tickets | `tickets` | private channel per ticket, claim, close by command or 🔒 reaction, stored transcript |
| Web dashboard | `dashboard` | FastAPI dashboard with username/password logins tied to Vector admin roles (off by default) |
| Verification | `verification` | arithmetic question or a ✅ reaction |
| Role menus | `roles` | reaction roles, add and remove |
| Giveaways | `giveaways` | react 🎉, timed, multiple winners, reroll |
| Welcome | `welcome` | templated join/leave messages |
| Games | `games` | Tic-Tac-Toe, Connect Four, Trivia, Slots as **WebXDC mini apps** |
| Utilities / analytics | `utility` | userinfo, poll, activity chart |
| Events | `events` | event calendar: RSVPs, waitlists, repeats, reminders (channel + DM), banner pictures, month picture, .ics |
| Security cam | `securitycam` | echo every message (author, channel, time, text, attachments) into one staff channel; off by default |
| (new) | `onboarding`, `webhooks` | welcome → verify → pick roles; YAML-declared webhooks |

Not ported: music, Twitch/YouTube/Twitter alerts, temporary voice channels and the web dashboard. They don't map onto Vector (or were off in Logiq).

## Configuration: `config.yaml`

Every feature is a module you can switch off, and every number is a setting. `!vectiq reload` re-reads it (turning a module on or off needs a restart). Secrets stay in `.env`. `python -m vectiq --check` validates the file and gives a clear error for mistakes.

### Webhooks from YAML

```yaml
webhooks:
  server:
    enabled: true                    # also serve the HTTP endpoint so GitHub, Grafana, CI... can post
    base_url: "https://hooks.example.com"
  hooks:
    - name: deploys                  # unique name
      channel: deploys               # channel name or id
      notify: [owners]               # who is DMed the secret URL when it is created (owners | npub...)
      events: [mod, levels]          # Vectiq events mirrored into the channel
```

On start (and `!webhooks sync`) Vectiq creates the missing hooks, DMs you each URL **once** (tokens are stored hashed, so a lost URL is replaced with `!webhooks rotate <name>`), and mirrors the listed events into the channel: `mod`, `joins`, `leaves`, `levels`, `tickets`, `giveaways`, `games`, `onboarding`. Hooks use the SDK's Discord-compatible format, so any tool that can post to a Discord webhook works by swapping the URL. Enabling the server needs `pip install "vector-sdk-py[webhooks]"` (the installer does this) and HTTPS in front of it.

### Event calendar

```
!event create Game night | friday 8pm | 2h | Bring snacks
```

Times can be typed as `friday 8pm`, `tomorrow 18:30`, `nov 20 7pm`, `2026-11-20 20:00` or `in 2h`, read in the community's time zone (`events.timezone`, or `!event timezone America/New_York`). Each event goes to the announcements channel (`events.channel`; `announcements` finds `📣┊Announcements`): the details, then a picture, then the footer where members react ✅ going, 🤔 maybe or ❌ can't go. The picture is a drawn banner, or whatever you attach to the command (`!event edit <id> image` with a picture changes it later). The post updates as people answer; with `capacity` set, extra people go on a waitlist and move up when someone drops out.

Before it starts, a general reminder (no pings, with the picture) goes in the channel and a personal reminder goes by DM to everyone going or maybe (`events.reminders`, default 60 and 15 minutes). Repeating events (`!event edit <id> repeat weekly`) post a fresh RSVP list for each occurrence. `!calendar` shows the month as a picture, `!event ics <id>` and `!calendar ics` give calendar files for Google, Apple and Outlook.

![Event calendar](docs/images/calendar.png)

### Setup wizard

`python -m vectiq --setup`, or **Setup wizard** on the dashboard: the bot asks what it needs, one question per screen, like an installer, and skips what doesn't apply. The terminal version writes `config.yaml` and keeps every comment.

<p align="center"><img src="docs/images/dashboard-wizard-choice.png" alt="The setup wizard: a list of stages on the left, the bot asking a question on the right, Back and Continue at the bottom" width="80%"></p>

### Verification

A question, a ✅ reaction, or a **CAPTCHA web page** reached by a personal one-time link. Optional: hide messages until people verify, one verification per device (hashed IP, cookie and browser marks), a minimum age with an adults-only role, a lobby that invites verified members to the real community, and softbans that kick on sight and escalate to a ban. See [Verification](https://lucky-edgelord.github.io/aio-vector-bot/verification.html).

### Restore points and settings files

Like System Restore: the database, `config.yaml`, dashboard settings and event pictures are saved daily and before risky changes (imports, the wizard, upgrades, rollbacks), and you can make your own. Roll back from the dashboard, chat (`!restorepoint`) or the terminal (`--restore`); a rollback can itself be undone. Settings export and import as YAML, with a preview of every change (`--export-config`, `--import-config`, or Settings on the dashboard). The bot's key is never included in either.

### Security cam

Turn on `modules.securitycam`, then run `!securitycam set #channel` (Manage Server), or pick the channel on the dashboard's Security cam page. Every message in every other channel is copied there: the author's name and text, then any attachments, then the source channel and time. The camera channel itself and the bot's own messages are never echoed; other bots are skipped unless `securitycam.include_bots` is on, and you can skip channels in config.yaml or on the dashboard. **Make the camera channel staff-only** — it shows everything.

### Onboarding

```yaml
onboarding:
  steps: [verify, pick_roles]
  role_menu: { "🎮": Gamer, "🎨": Artist, "💻": Dev }   # roles are created if missing
  required: false        # true: only complete once they pick a role
```

New member → welcome → verification → a role menu built from the YAML (the same reaction roles as `!rolemenu`) → done message. Progress is stored per member and finishing fires an `onboarding` event.

## Web dashboard

A FastAPI dashboard runs inside the bot. Turn it on with `modules.dashboard: true`, restart, and open `http://localhost:8090`. A community's owner chooses which Vector roles can use it and what they can see or change (**Dashboard access**: Everything, Moderator, Helper, Look only, or area by area).

<p align="center">
  <img src="docs/images/dashboard-login.png" alt="Sign-in page with username and password, and an option to get a code from Vector instead" width="49%">
  <img src="docs/images/dashboard-member.png" alt="A member's panel: level, XP and coins, moderation buttons, roles, and XP and coin adjustments" width="49%">
</p>
<p align="center">
  <img src="docs/images/dashboard-members.png" alt="Members list with roles, level, XP, coins and warnings, plus search and filters" width="49%">
  <img src="docs/images/dashboard-leveling.png" alt="Leveling page with the leaderboard card, role rewards and the full ranking" width="49%">
</p>
<p align="center">
  <img src="docs/images/dashboard-ticket.png" alt="A support ticket's saved transcript shown as chat bubbles" width="49%">
  <img src="docs/images/dashboard-settings.png" alt="Settings page with tabs per module and leveling options" width="49%">
</p>
<p align="center">
  <img src="docs/images/dashboard-giveaways.png" alt="Giveaways page with running and ended giveaways and their entry counts" width="70%">
  <img src="docs/images/dashboard-phone.png" alt="The overview on a phone" width="22%">
</p>
<p align="center">
  <img src="docs/images/dashboard-marketplace-browse.png" alt="The Marketplace page's Browse tab: module cards with icons, a cover picture for Vectoria, and Get buttons" width="49%">
  <img src="docs/images/dashboard-marketplace-installed.png" alt="The Marketplace page's Installed tab: an installed module with its icon, on/off switch, Settings, Export and Remove, and a section to save any module as a file" width="49%">
</p>
<p align="center">
  <img src="docs/images/dashboard-access.png" alt="Dashboard access: choose what each Vector role can see or change, area by area" width="60%">
  <img src="docs/images/dashboard-marketplace-phone.png" alt="The marketplace on a phone: module cards with icons, and the menu behind a button" width="22%">
</p>

**Signing in** is by username and password. Every login belongs to a Vector account (npub), and that account's admin role in Vector decides which communities it can manage, checked on every request: remove someone's admin role and their dashboard access goes with it.

```sh
.venv/bin/python -m vectiq --add-user alice --npub npub1...    # asks for the password (10+ characters)
.venv/bin/python -m vectiq --list-users
.venv/bin/python -m vectiq --set-password alice                # also unlocks a locked account
.venv/bin/python -m vectiq --delete-user alice
```

Owners can also create logins on the **Users** page, and anyone signed in can change their password on **My account**. As a fallback (no password yet, or forgot it) admins can get a one-time code by Vector DM from the sign-in page or with `!dashboard`; turn that off with `dashboard.vector_code_login: false`.

**Pages:** overview with 30-day activity, members (warn, timeout, kick, ban, roles, XP, coins, full record), moderation cases and bans, leveling and role rewards (with the leaderboard card), economy and shop, tickets with transcripts, role menus, giveaways, games, onboarding, announcements, an audit log of every dashboard action, settings, webhooks and users.

**Settings** edited in the dashboard are saved in the database and layered over `config.yaml`, which is never rewritten (its comments stay). Each changed setting shows a "dashboard" tag and can be reset to the file's value; **Export YAML** downloads the merged result. Module switches and the dashboard's own address need a restart.

**Security:** passwords are hashed with scrypt; five wrong passwords lock a login for 15 minutes; sign-in is rate-limited per IP; sessions are HttpOnly, SameSite=Strict cookies stored hashed; every change needs a same-origin header (no CSRF); the pages send a strict Content-Security-Policy. It listens on `127.0.0.1` by default. To reach it from elsewhere, put it behind HTTPS (for example `caddy reverse-proxy --from dash.example.com --to 127.0.0.1:8090`, or Tailscale) and set `dashboard.base_url` to the `https://` address so cookies are marked Secure.

## Commands

| Area | Commands |
|---|---|
| Modules | `modules` `module on/off/info/reload <name>` `module scan` `module install/uninstall` |
| MCP | `mcp` (shows how to connect an AI assistant) |
| Sentire (automod) | `sentire` `sentire invite` `sentire log` `sentire restart` `sentire install` |
| Safety | `linksafety` `linksafety check/update` `imageguard` `imageguard block/unblock/list/test` |
| Music | `play` `search` `playnext` `queue` `nowplaying` `skip` `forceskip` `skipto` `back` `replay` `seek` `pause` `resume` `loop` `shuffle` `move` `remove` `clearqueue` `removedupes` `leavecleanup` `volume` `filter` `247` `join` `leave` |
| Alerts | `notify` `notify add youtube/twitch/rss` `notify remove` `notify check` |
| Moderation | `softban` `warn` `warnings` `delwarn` `clearwarns` `timeout` `untimeout` `kick` `ban` `tempban` `unban` `case` `history` `modlog` `purge` `lock` `unlock` `slowmode` |
| Leveling | `rank` `leaderboard` `levelreward add/remove` `givexp` `resetxp` `levelcurve` |
| Economy | `balance` `daily` `work` `pay` `deposit` `withdraw` `richest` `transactions` `shop` `buy` `inventory` `addmoney` |
| Dashboard | `dashboard` (DMs you a one-time sign-in link) |
| Tickets | `ticket open/close/claim/list/transcript`, or react 🔒 in the ticket to close (`tickets.close_emoji`) |
| Roles & access | `rolemenu create/list/delete` `verify` `forceverify` `onboarding` |
| Giveaways | `giveaway start/end/reroll/cancel/list` |
| Games | `games` `game <name>` `gamestats` `gameboard` |
| Utility | `userinfo` `communityinfo` `poll` `analytics` `testwelcome` `about` `ping` |
| Events | `event create` `event list` `event info` `event edit` `event rsvp` `event who` `event cancel` `event delete` `event repost` `event ics` `event timezone` `calendar` |
| Security cam | `securitycam` `securitycam set [channel]` `securitycam off` |
| Owner | `vectiq reload/stats`, `webhooks`, `webhooks sync/rotate/test` |

Moderation commands are gated by the matching Vector permission. Owner commands use `owners:` in `config.yaml`.

## Mini games (WebXDC)

`!game tictactoe | connect4 | trivia | slots` posts a small web app into the chat. Players open it in Vector and **the bot joins the app's realtime channel as the referee**: it owns the board, the clock, the random numbers and the coins, so a modified client can't cheat.

- Tic-Tac-Toe and Connect Four: two seats, spectators welcome, rematch.
- Trivia: lobby, 8 timed questions, faster correct answers score more; coins per correct answer.
- Slots: bet your real wallet; wins and losses are written to SQLite.
- Winners are paid (`games.winner_coins`) and recorded for `!gamestats` / `!gameboard`.
- The bot only acts on **verified** senders (frames that arrive directly from a player's device). A relayed frame is asked to retry. `games.allow_unverified` exists for testing only: leave it off.

Add a game: write `games/<name>.py` (a `Game` subclass), a front-end in `games/apps/<name>/` (`index.html`, `manifest.toml` with `id = "vectiq-<name>"`, `icon.png`) and register it in `games/registry.py`.

## Data

One SQLite file at `data/vectiq.db` (WAL mode). The schema is versioned in `db/migrations.py` and applied on start; never edit an applied migration, append a new one. Back it up with `sqlite3 data/vectiq.db ".backup backup.db"`. All ids are `TEXT` (Vector uses npub/hex strings).

## Development

`python tools/screenshots.py --chrome /path/to/chrome` rebuilds the images in `docs/images/` from a made-up demo community (needs `pip install playwright`).

```sh
pip install -e ".[dev]" && pytest && ruff check .
```

## Credits

- **[Vector](https://github.com/VectorPrivacy/Vector)** by **[JSKitty](https://github.com/JSKitty)** and the [VectorPrivacy](https://github.com/VectorPrivacy) team (MIT): the private, open-source messenger Vectiq lives in, and the Rust core underneath `vector-sdk-py`. Vectiq wouldn't exist without it.
- **[Sentire](https://github.com/VectorPrivacy/Sentire)** by JSKitty (MIT): Vectiq's automod. The Sentire module builds, configures and runs your own copy; Sentire (official) invites the Sentire-001 that VectorPrivacy runs. Vectiq doesn't include Sentire's code; it downloads and builds it when you ask.
- **[GateBot](https://gitworkshop.dev/henk.tech/Gatebot)** by henk.tech (MIT): the CAPTCHA verification flow (personal one-time links, the domain-only public notice, the age step), one verification per device with expiring hashed IP, cookie and browser marks, the message gate with a spam limit, the invite-gate lobby, softbans that kick on sight and escalate to a real ban, lasting verification records with role restore on rejoin, and the permission check. Vectiq's version is a Python rewrite of those ideas, not a copy of the code.
- **[Logiq](https://github.com/programmify/Logiq)**: the feature set Vectiq started from.
- **[FastMCP](https://gofastmcp.com)** for the MCP server.
- **[oisd](https://oisd.nl)** for the domain blocklists link safety downloads; **[yt-dlp](https://github.com/yt-dlp/yt-dlp)** and **[FFmpeg](https://ffmpeg.org)** for music; **[NudeNet](https://github.com/notAI-tech/NudeNet)** and **[nsfw_model / nsfw-detector](https://github.com/GantMan/nsfw_model)** as optional image detectors (installed separately, not bundled).

## Contributing

Issues and pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

## Known limits

- The macOS installer and launchd agent have not yet been run on a real Mac; reports welcome.
- Communities still on Vector's legacy roster don't accept per-channel permission overwrites. Tickets fall back to a private channel with per-member access; `lock`/`unlock` may need the community upgraded.
- The rank and leaderboard colours approximate Vector's look (dark canvas, green accent, ◤◢ motif); change them in `render/cards.py`.
- Games were verified with the real rules driven through a headless browser and with the cog tested against a fake session. A full two-player round trip over Vector's network has not yet been confirmed from a real Vector client.
- Automod, link safety, the image guard, alerts, live module switching and the music cards were tested live in a Vector community. Music **audio** hasn't been heard yet: from the cloud test machine, Vector's voice connection (and the Mini App realtime channel) never connects to other people, even with the bare SDK, so audio playback and a two-player game round trip still need a test from a normal computer.
- Fonts: Inter (SIL OFL) is bundled for the cards; see `assets/fonts/Inter-OFL.txt`.

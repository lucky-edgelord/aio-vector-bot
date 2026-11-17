# Changelog

## Unreleased
- pip install: `pipx install "vectiq[dashboard,webhooks] @ git+https://github.com/lucky-edgelord/aio-vector-bot"`, `vectiq --init` (writes config.yaml and .env), `vectiq --version`, the example files bundled in the package, and `--setup` creating a missing config.yaml.
- Docker: a `Dockerfile` and `docker-compose.yml` (settings in `docker-config/`, data in `docker-data/`), a CI image build, `VECTIQ_DASHBOARD_HOST`, and a Docker guide.
- Verification, with ideas from GateBot (henk.tech, MIT): a `captcha` mode with a personal one-time link and a
  CAPTCHA page (Turnstile, hCaptcha or reCAPTCHA); lasting verification records with the role restored on rejoin
  or the next message; one verification per device (keyed hashes of IP, cookie and browser, expiring after
  `device_check_days`) with `on_duplicate: refuse | kick | softban`; `min_age` and an `adult_role` claimed with
  `!adult`; an invite-gate lobby (`invite_to`); `gate: channel | all` hides messages until people verify, with a
  `spam_kick` limit; `!unverify`, `!verification` (setup and permission check), `!verification reset`.
- Softbans: `!softban` takes roles and kicks, kicks again on sight, and becomes a ban after `softban_escalate`
  returns; `!unban` lifts softbans too.
- Channel settings match names loosely everywhere ("mod-log" finds "🛡┊mod-log"). New channels:
  `verification.log_channel`, `tickets.log_channel`, `welcome.leave_channel`, `onboarding.log_channel`.
  `!communityinfo` shows the community id.
- Setup wizard, installer-style and conversational, on the dashboard and in the terminal (`vectiq --setup`, which
  edits `config.yaml` in place and keeps every comment). The installer offers to run it.
- Settings export and import as YAML with a preview of every change: dashboard Settings, `--export-config`,
  `--import-config`.
- Restore points, like System Restore: daily, before imports, the wizard, database upgrades and rollbacks, and
  by hand with a description. Roll back live from the dashboard, `!restorepoint` or `vectiq --restore`; every
  rollback can be undone. The bot's key is never included.
- Documentation site on GitHub Pages: guides for every feature, a command reference and a settings reference built
  from the code and `config.yaml`, search, and a link checker (`python tools/build_docs.py`). Every setting in
  `config.yaml` now has a comment.
- Event calendar: `!event create Title | friday 8pm | 2h | details` (natural times in the community's time zone),
  posts in the announcements channel with a drawn banner or an attached picture between the text and footer,
  RSVP by reaction (going / maybe / can't go) with capacity and waitlist, repeats (daily, weekly, biweekly,
  monthly), general reminders in the channel and personal reminders by DM, optional attendee roles, `!calendar`
  month picture, `.ics` export, edit/cancel/repost, and an Events section in dashboard Settings.
- Security cam (off by default): echoes every message from every channel into one staff channel with the
  author, channel, time, text and attachments. `!securitycam set/off`, a dashboard page and a Settings section.
- Web dashboard (FastAPI, off by default): username/password logins tied to Vector npubs, optional sign-in by
  Vector DM code, members and moderation, leveling, economy, tickets, role menus, giveaways, games, onboarding,
  announcements, audit log, settings layered over config.yaml, webhooks and user management.
- `vectiq --add-user/--set-password/--delete-user/--list-users` for dashboard logins.
- Cog logic the dashboard reuses moved into plain methods (moderation `record`/`escalate`, giveaways `launch`,
  role menus `build_menu`, games `post_game`, webhooks `rotate_url`/`status`).
- Fonts are now included in non-editable installs.

## 0.1.0
- First release: moderation, leveling (image cards), economy and shop, tickets, verification, onboarding, reaction roles,
  giveaways, welcome, analytics, WebXDC mini games (Tic-Tac-Toe, Connect Four, Trivia, Slots), YAML-declared webhooks.
- Tickets close with a 🔒 reaction (configurable `tickets.close_emoji`) and work on communities still on the legacy
  roster (private channel plus per-member access instead of overwrites).
- SQLite storage with versioned migrations; typed, validated `config.yaml`.

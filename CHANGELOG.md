# Changelog

## Unreleased
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

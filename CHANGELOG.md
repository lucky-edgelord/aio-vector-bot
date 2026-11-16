# Changelog

## 0.1.0
- First release: moderation, leveling (image cards), economy and shop, tickets, verification, onboarding, reaction roles,
  giveaways, welcome, analytics, WebXDC mini games (Tic-Tac-Toe, Connect Four, Trivia, Slots), YAML-declared webhooks.
- Tickets close with a 🔒 reaction (configurable `tickets.close_emoji`) and work on communities still on the legacy
  roster (private channel plus per-member access instead of overwrites).
- SQLite storage with versioned migrations; typed, validated `config.yaml`.

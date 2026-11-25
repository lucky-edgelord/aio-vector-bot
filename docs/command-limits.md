---
title: Command limits
group: Community
order: 5
summary: Only let certain roles use a command, or every command of a module.
---

# Command limits

Some commands should not be for everyone. A limit says which roles may use a command, or every command of a module. Anyone else who tries gets a short note saying which roles can.

## In chat

You need Manage Community.

```
!limit ban Moderator, Admin
!limit quantum VIP
!limit "tickets list" Support
!limits
!limit clear ban
```

- The first word is a command (`ban`, or `tickets list` for a subcommand) or a module name (`Quantum`, `Tickets`).
- Then the roles, separated by commas. Role names, mentions and ids all work.
- A command's own limit wins over the limit on its module. Limiting `Tickets` limits all its commands; limiting `tickets list` as well gives that one a different set of roles.
- `!limits` lists everything that is limited. `!limit clear <name>` opens it up again.

## On the dashboard

**Command limits** (in the menu, with Channels & roles) does the same with a list of commands and a role picker.

## Good to know

- Server owners, administrators and bot owners can always use everything, so you cannot lock yourself out. `!limit` and `!limits` themselves can never be limited.
- Limits are per community, because roles are.
- Limits apply to commands typed in a community. Private messages are not limited.
- A command's own permission checks (like Ban Members for `!ban`) still apply on top of its limit.

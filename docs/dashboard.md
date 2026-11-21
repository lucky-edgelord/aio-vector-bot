---
title: Web dashboard
group: Connect
order: 2
summary: Manage your community from a browser, with sign-in by Vector code, a dashboard page for each feature and an audit log.
---

![The dashboard overview](images/dashboard-overview.png)

The dashboard is a web page where staff manage the bot without typing commands. Everything it does is also available as a chat command, and every change is recorded in the audit log.

## Turning it on

```yaml
modules:
  dashboard: true
dashboard:
  host: 127.0.0.1
  port: 8090
  base_url: "http://localhost:8090"
```

Restart the bot and open `http://localhost:8090`. With `host: 127.0.0.1` only the computer running the bot can reach the page. To use it from elsewhere, put HTTPS in front of it and set `base_url` to the public address. See [Deployment](deployment.md#the-dashboard-and-webhooks-over-https).

## Signing in

![The sign-in page](images/dashboard-login.png)

There are two ways in. The bot's `owners`, a community's owner and its admins can sign in, and so can anyone whose Vector role the community's owner has given access (see [Dashboard access](#dashboard-access)).

**Username and password.** Create a login on the machine running the bot, tied to your Vector account:

```sh
vectiq --add-user sam --npub npub1...   # asks for a password of 10+ characters
vectiq --list-users
vectiq --set-password sam
vectiq --delete-user sam
```

**A code from Vector.** Enter your npub on the sign-in page and the bot sends a one-time code by DM that works for `dashboard.code_minutes` (10) minutes. You can also type `!dashboard` in chat to get a sign-in link by DM. Turn this off with `dashboard.vector_code_login: false` if you only want passwords.

A sign-in lasts `dashboard.session_days` (7) days. Too many wrong attempts are slowed down, and an npub that isn't allowed gets the same answer as one that is, so nobody can probe for accounts.

## Dashboard access

Each community decides who can use its part of the dashboard, by Vector role. Open **Dashboard access** in the community's menu; only the community's owner and the bot's owners see it.

For community admins (Vector's admin role or Manage Community) and for any role you add, choose what they get:

| Choice | Can |
|---|---|
| Everything | see and change every page of the community (the default for admins) |
| Moderator | change Members, Moderation and Tickets; look at Overview, Onboarding and the Audit log |
| Helper | change Tickets; look at Overview and Members |
| Look only | see every page, change nothing |
| Nothing | no access |
| Custom | area by area: no access, can look, or can change |

The areas are Overview, Members, Moderation, Tickets, Channels & roles, Role menus, Onboarding, Leveling, Economy, Giveaways, Games, Security cam, Announce, Module pages and the Audit log. Someone with several roles gets the most any of them allows. Pages they can't open aren't in their menu, and a page they can only look at says so and hides its buttons. The bot checks every request too, so a hidden button can't be pressed anyway.

Changes apply at once, even to people already signed in, and so does taking a role away in Vector. The community's owner and the bot's owners always have full access, and bot-wide pages (Settings, Marketplace, Webhooks, Users, Restore points) stay with the bot's owners. Every change is in the audit log.

## What is on each page

| Page | What you can do |
|---|---|
| Overview | Messages, joins and leaves per day, and your busiest channels |
| Members | Search members, open one to see their level, coins and warnings, and adjust them |
| Moderation | Cases, active timeouts and bans, filters, and the log channel |
| Leveling | The leaderboard, XP settings, level rewards and no-XP channels |
| Economy | Balances, the shop and the richest members |
| Tickets | Open and closed tickets, with the full transcript of each |
| Role menus | Create and edit role menus |
| Giveaways | Start, end and reroll giveaways |
| Games | Results and leaderboards for each game |
| Onboarding | The welcome message, verification and onboarding steps |
| Security cam | Choose the channel and the channels to leave out |
| Setup wizard | Set the bot up by answering questions, one per screen (owners) |
| Restore points | Make restore points, roll back to one, download them (owners) |
| Announce | Post a message as the bot into any channel |
| Audit log | Who changed what, and when |

Pages only appear for features that are turned on.

![A member page](images/dashboard-member.png)

![Giveaways](images/dashboard-giveaways.png)

## Settings

![Settings](images/dashboard-settings.png)

The Settings page edits the values in [config.yaml](configuration.md). **Export** and **Import** move them in and out as a YAML file; see [Exporting and importing](configuration.md#exporting-and-importing-settings). A value you change here is saved on top of the file, so it takes effect without a restart and survives updates. Reset a value to go back to the file's setting.

Some settings only apply when the bot starts, such as the dashboard's own address. The page tells you when a restart is needed.

## On a phone

The dashboard works on a narrow screen: the menu folds away and tables become lists.

![The dashboard on a phone](images/dashboard-phone.png)

## Safety

- Sign-in codes and links work once and expire.
- Pages that change something need a signed-in session and check your role in that community on every request.
- Every change is written to the audit log with who made it.
- Nothing about the dashboard is open to the internet unless you put it there. Keep `host: 127.0.0.1` unless you have HTTPS in front.

## Settings

{{config:dashboard}}

## Channels & roles

The **Channels & roles** page lets you shape a community without leaving the dashboard:

- **Channels and categories:** create text, voice and forum channels, rename them, move them between categories, make them private or read-only, and delete them.
- **Per-channel and per-category permissions:** for @everyone, a role or a member, with ✓ allow, / inherit and ✕ deny for each permission.
- **Roles:** create and edit them (name, colour, shown separately, mentionable, permissions), reorder them, delete them, and set what @everyone may do.

Giving members roles is on the **Members** page. The same actions are available to AI assistants through the [MCP server](mcp.md). Everything is written to the audit log.

## Marketplace

The **Marketplace** page (owners) adds, updates and removes [JSON modules](json-modules.md): browse a [marketplace](marketplace.md) on GitHub, add a file or paste JSON (checked as you type), and export modules to share.

## Module pages

Modules can add their own pages under **Modules** in the menu: [Sentire](sentire.md), [MCP](mcp.md), and any plugin that describes one (see [Writing modules](writing-modules.md#a-page-on-the-dashboard)).

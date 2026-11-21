---
title: MCP server
group: Connect
order: 4
summary: Let Claude or any MCP client manage your communities through Vectiq: channels, roles, permissions, members, messages, modules and settings.
---

With the **MCP server** module on, Vectiq speaks the [Model Context Protocol](https://modelcontextprotocol.io), so an AI assistant like Claude can do what you'd otherwise do on the dashboard. You could say "make an Events category with a voice channel only Mods can talk in", or "who has the VIP role?".

It's built with [FastMCP](https://gofastmcp.com) and runs inside the bot.

## Switch it on

```sh
pip install "vectiq[mcp]"          # .venv/bin/pip install -e ".[mcp]" in the bot's folder
```

Then `!module on mcp`, or Settings → Modules. The server listens on `http://127.0.0.1:8770/mcp`, on this computer only. Every request needs a token: Vectiq makes one in `data/mcp-token`, or set `VECTIQ_MCP_TOKEN` in `.env` to choose it. `!mcp` and the dashboard's **MCP** page show the address and how to connect, and the page can replace the token.

## Connect an assistant

**Claude Desktop** and other apps that start a program: add a server whose command is `vectiq --mcp`, run in the bot's folder. It reads the token itself and passes everything to the running bot.

```json
{
  "mcpServers": {
    "vectiq": {
      "command": "/path/to/aio-vector-bot/.venv/bin/vectiq",
      "args": ["--mcp"],
      "cwd": "/path/to/aio-vector-bot"
    }
  }
}
```

**Clients that connect over HTTP** (Claude Code, the API's MCP connector and others): use the address and send `Authorization: Bearer <token>`. To reach it from another computer, put HTTPS in front (Caddy, Tailscale…) and keep the token secret.

## What it can do

| Area | Tools |
|---|---|
| Looking | `list_communities`, `get_structure`, `list_members`, `read_messages`, `list_modules`, `get_settings` |
| Channels | `create_channel`, `edit_channel`, `delete_channel`, `create_category`, `rename_category`, `delete_category` |
| Permissions | `set_permissions` (a channel or category, for @everyone, a role or a member), `set_everyone_permissions` |
| Roles | `create_role`, `edit_role`, `delete_role`, `order_roles`, `give_role`, `take_role` |
| Members | `moderate` (warn, timeout, kick, ban, unban; recorded as a case) |
| Messages | `send_message` |
| Vectiq | `set_module`, `change_setting` |
| [JSON modules](json-modules.md) | `module_format_guide`, `check_module_json`, `browse_marketplace`, `export_module_json`, `add_module_json`, `add_module_from_marketplace`, `remove_json_module` |

An assistant can write a new feature for your community as a JSON module: it reads `module_format_guide`, checks its work with `check_module_json`, then adds it. Modules with code still need *Allow modules with code*.

Community tools take the community's name, or nothing if the bot serves just one. Channels, roles and members can be named instead of using ids. The tools are the same actions the dashboard's **Channels & roles** page uses, so they behave the same way.

Everything an assistant changes is in the dashboard's audit log as `mcp`. Set `read_only: true` to let assistants look but not change anything.

!!! warning "An assistant acts as the bot"
    With the token, an assistant can do anything the bot can, including deleting channels and banning members. Keep the token private, use `read_only` when you only want answers, and review what it plans to do before you approve destructive actions.

## Settings

{{config:mcp}}

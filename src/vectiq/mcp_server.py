"""Vectiq as an MCP server (FastMCP): lets Claude or any MCP client run your communities.

The tools call the same ``vectiq.manage.Manager`` the dashboard uses, so both behave the same, and every change is
written to the dashboard's audit log as ``mcp``. ``mcp.read_only: true`` leaves only the tools that read.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken, TokenVerifier
from pydantic import Field

from . import modules
from .manage import PERMISSIONS, ManageError, Manager, explain

log = logging.getLogger("vectiq.mcp")

INSTRUCTIONS = """Vectiq manages Vector communities (an encrypted, Nostr-based messenger) as a bot.
Start with list_communities. Every community tool takes `community` (its name or id; it can be left empty when the
bot serves just one). Channels, categories, roles and members can be named instead of using ids.
Permissions use these names: """ + ", ".join(p["name"] for p in PERMISSIONS) + """.
Changes take effect in the real community straight away: confirm destructive ones (delete, ban) with the person."""

Community = Annotated[str, Field(description="Community name or id; empty if the bot serves only one")]


class Token(TokenVerifier):
    """One bearer token, compared in constant time."""

    def __init__(self, token: str):
        super().__init__()
        self._token = token

    async def verify_token(self, token: str) -> AccessToken | None:
        if token and hmac.compare_digest(token.encode(), self._token.encode()):
            return AccessToken(token=token, client_id="vectiq-owner", scopes=[])
        return None


def token_for(cfg, data_dir: str) -> str:
    """The token from the configured env var, or one made once and kept in data/mcp-token (owner-readable only)."""
    env = cfg.get("mcp.token_env", "VECTIQ_MCP_TOKEN")
    if env and os.environ.get(env):
        return os.environ[env]
    path = Path(data_dir) / "mcp-token"
    if path.exists():
        return path.read_text("utf-8").strip()
    tok = "vq_" + secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(tok + "\n")
    return tok


def build(bot, *, token: str | None, read_only: bool = False) -> FastMCP:
    m = Manager(bot)
    mcp = FastMCP("Vectiq", instructions=INSTRUCTIONS, auth=Token(token) if token else None,
                  version=getattr(__import__("vectiq"), "__version__", None))

    def g(community: str):
        try:
            return m.community(community)
        except ManageError as exc:
            raise ToolError(str(exc)) from None

    async def done(guild, action: str, detail: str, coro):
        try:
            out = await coro
        except ManageError as exc:
            raise ToolError(str(exc)) from None
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"Vector refused: {explain(exc)}") from None
        try:
            await bot.stores.dashboard.audit("mcp", action, detail[:480], str(guild.id) if guild is not None else "")
        except Exception:  # noqa: BLE001
            pass
        return out

    def write(fn):
        """Register a tool that changes something (skipped in read-only mode)."""
        if not read_only:
            mcp.tool(fn)
        return fn

    # -- reading -------------------------------------------------------------------------------

    @mcp.tool
    async def list_communities() -> list[dict]:
        """The communities this bot serves, with member counts."""
        return m.communities()

    @mcp.tool
    async def get_structure(community: Community = "") -> dict:
        """Categories, channels (with their permission overwrites), roles and what @everyone may do."""
        s = m.structure(g(community))
        s.pop("permissions", None)
        return s

    @mcp.tool
    async def list_members(community: Community = "", query: str = "", limit: int = 50) -> list[dict]:
        """Members (name, npub, roles), optionally filtered by part of a name or npub."""
        return m.members(g(community), query, max(1, min(limit, 500)))

    @mcp.tool
    async def read_messages(channel: str, community: Community = "", limit: int = 20) -> list[dict]:
        """The latest messages in a channel, oldest first (at most 100)."""
        guild = g(community)
        try:
            return await m.history(guild, channel, limit)
        except ManageError as exc:
            raise ToolError(str(exc)) from None

    @mcp.tool
    async def list_modules() -> list[dict]:
        """Every Vectiq module (feature), whether it's on, and which job it does."""
        problems = getattr(bot, "module_problems", {})
        return [{"name": x.name, "label": x.label, "on": bot.config.enabled(x.name), "group": x.group,
                 "job": x.slot, "plugin": not x.builtin, "problem": problems.get(x.name, "")}
                for x in modules.REGISTRY]

    @mcp.tool
    async def get_settings(prefix: str = "") -> list[dict]:
        """Settings you can change with change_setting: path, label, type, current value. Filter by path prefix."""
        from .dashboard import schema

        out = []
        for path, f in schema.FIELDS.items():
            if prefix and not path.startswith(prefix):
                continue
            out.append({"path": path, "label": f["label"], "type": f["type"], "value": bot.config.get(path),
                        "options": f.get("options") or None, "help": f.get("help", "")})
        return out

    # -- channels and categories ---------------------------------------------------------------

    @write
    async def create_channel(name: str, community: Community = "", kind: str = "text", category: str = "",
                             topic: str = "", private: bool = False) -> dict:
        """Create a channel. kind: text, voice or forum. category: a category name or id (optional)."""
        guild = g(community)
        return await done(guild, "created channel", name, m.create_channel(guild, name, kind, category, topic, private))

    @write
    async def edit_channel(channel: str, community: Community = "", name: str | None = None,
                           topic: str | None = None, category: str | None = None, private: bool | None = None,
                           read_only: bool | None = None) -> dict:
        """Rename a channel, change its topic, move it to a category ("" = none), or make it private/read-only."""
        guild = g(community)
        return await done(guild, "edited channel", channel, m.edit_channel(
            guild, channel, name=name, topic=topic, category=category, private=private, read_only=read_only))

    @write
    async def delete_channel(channel: str, community: Community = "") -> str:
        """Delete a channel and its messages. Can't be undone: confirm with the person first."""
        guild = g(community)
        return "deleted #" + await done(guild, "deleted channel", channel, m.delete_channel(guild, channel))

    @write
    async def create_category(name: str, community: Community = "") -> dict:
        """Create a category to group channels."""
        guild = g(community)
        return await done(guild, "created category", name, m.create_category(guild, name))

    @write
    async def rename_category(category: str, name: str, community: Community = "") -> dict:
        """Rename a category."""
        guild = g(community)
        return await done(guild, "renamed category", category, m.rename_category(guild, category, name))

    @write
    async def delete_category(category: str, community: Community = "") -> str:
        """Delete a category (its channels stay, without a category)."""
        guild = g(community)
        return "deleted " + await done(guild, "deleted category", category, m.delete_category(guild, category))

    @write
    async def set_permissions(where: str, target: str, community: Community = "", allow: list[str] | None = None,
                              deny: list[str] | None = None) -> dict:
        """Permissions in one channel or category for `target`: "everyone", a role, or a member's npub.
        Listed permissions are allowed or denied; everything else is inherited. Both empty resets the target."""
        guild = g(community)
        return await done(guild, "changed permissions", f"{where} {target}",
                          m.set_overwrite(guild, where, target, allow or [], deny or []))

    # -- roles ---------------------------------------------------------------------------------

    @write
    async def create_role(name: str, community: Community = "", permissions: list[str] | None = None,
                          colour: str = "", hoist: bool = False, mentionable: bool = False) -> dict:
        """Create a role. colour like #1abc9c; hoist shows its members separately."""
        guild = g(community)
        return await done(guild, "created role", name, m.create_role(
            guild, name, permissions=permissions or [], colour_hex=colour, hoist=hoist, mentionable=mentionable))

    @write
    async def edit_role(role: str, community: Community = "", name: str | None = None,
                        permissions: list[str] | None = None, colour: str | None = None, hoist: bool | None = None,
                        mentionable: bool | None = None) -> dict:
        """Change a role. `permissions` replaces the whole list."""
        guild = g(community)
        return await done(guild, "edited role", role, m.edit_role(
            guild, role, name=name, permissions=permissions, colour_hex=colour, hoist=hoist, mentionable=mentionable))

    @write
    async def delete_role(role: str, community: Community = "") -> str:
        """Delete a role."""
        guild = g(community)
        return "deleted " + await done(guild, "deleted role", role, m.delete_role(guild, role))

    @write
    async def order_roles(order: list[str], community: Community = "") -> list[str]:
        """Put roles in order, highest first (names or ids)."""
        guild = g(community)
        return await done(guild, "reordered roles", ", ".join(order), m.order_roles(guild, order))

    @write
    async def set_everyone_permissions(permissions: list[str], community: Community = "") -> list[str]:
        """What every member may do (the whole list)."""
        guild = g(community)
        return await done(guild, "changed @everyone", "", m.everyone_permissions(guild, permissions))

    # -- members -------------------------------------------------------------------------------

    @write
    async def give_role(member: str, role: str, community: Community = "") -> str:
        """Give a member a role. member: name or npub."""
        guild = g(community)
        return await done(guild, "gave role", f"{role} {member}", m.give_role(guild, member, role, True))

    @write
    async def take_role(member: str, role: str, community: Community = "") -> str:
        """Take a role from a member."""
        guild = g(community)
        return await done(guild, "removed role", f"{role} {member}", m.give_role(guild, member, role, False))

    @write
    async def moderate(member: str, action: str, community: Community = "", reason: str = "",
                       minutes: int = 0) -> str:
        """warn, timeout (needs minutes), kick, ban or unban (member = npub). Recorded as a moderation case.
        Confirm kicks and bans with the person first."""
        guild = g(community)
        return await done(guild, f"moderation: {action}", f"{member} {reason}",
                          m.moderate(guild, member, action, reason=reason, minutes=minutes, by="mcp"))

    # -- messages ------------------------------------------------------------------------------

    @write
    async def send_message(channel: str, text: str, community: Community = "") -> dict:
        """Post a message as the bot."""
        guild = g(community)
        return await done(guild, "sent message", f"#{channel}", m.send(guild, channel, text))

    # -- modules and settings ------------------------------------------------------------------

    @write
    async def set_module(name: str, on: bool) -> dict:
        """Switch a module on or off now (no restart). Switching one on swaps out a module doing the same job."""
        if modules.get(name) is None:
            raise ToolError(f"no module called {name}")
        r = await bot.set_module(name, bool(on), "mcp")
        await done(None, f"module {'on' if on else 'off'}", name, _noop())
        return r

    @write
    async def change_setting(path: str, value: Any) -> dict:
        """Change one setting (see get_settings), like the dashboard does. Lists are JSON arrays."""
        from .config import ConfigError
        from .dashboard import schema

        if path not in schema.FIELDS:
            raise ToolError(f"unknown setting {path}; see get_settings")
        if isinstance(value, str) and schema.FIELDS[path]["type"] == "list" and value.strip().startswith("["):
            value = json.loads(value)
        try:
            coerced = schema.coerce(path, value)
            merged = {**bot.config.overrides, path: coerced}
            bot.config.apply_overrides(merged)
        except (schema.FieldError, ConfigError) as exc:
            raise ToolError(str(exc)) from None
        await bot.stores.dashboard.set_override(path, coerced, "mcp")
        await done(None, "changed setting", path, _noop())
        await bot.apply_settings()
        return {"path": path, "value": bot.config.get(path)}

    return mcp


async def _noop():
    return None


async def bridge(url: str, token: str) -> None:
    """``vectiq --mcp``: speak MCP over stdio (what desktop apps expect) and pass it to the running bot."""
    from fastmcp.client.transports import StreamableHttpTransport
    from fastmcp.server import create_proxy

    proxy = create_proxy(StreamableHttpTransport(url, headers={"Authorization": f"Bearer {token}"}), name="Vectiq")
    await proxy.run_stdio_async(show_banner=False)

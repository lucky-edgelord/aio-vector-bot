"""An in-memory Vector community with the parts of the SDK that vectiq.manage uses."""

from __future__ import annotations

import itertools
from types import SimpleNamespace

from vector.permissions import PermissionOverwrite, Permissions

_ids = itertools.count(1)


class Role:
    def __init__(self, guild, name, permissions=0, colour=0, hoist=False, mentionable=False, default=False):
        self.guild, self.id, self.name = guild, "everyone" if default else f"r{next(_ids)}", name
        self.permissions, self.colour = Permissions(int(permissions)), colour
        self.hoist, self.mentionable, self._default, self.position = hoist, mentionable, default, 0

    def is_default(self):
        return self._default

    def is_bot_managed(self):
        return False

    @property
    def members(self):
        return [m for m in self.guild.members if self in m.roles]

    async def edit(self, **kw):
        for k, v in kw.items():
            setattr(self, k, Permissions(int(v)) if k == "permissions" else v)

    async def delete(self):
        self.guild.roles.remove(self)


class Member:
    def __init__(self, guild, npub, name):
        self.guild, self.npub, self.id, self.display_name, self.name = guild, npub, npub, name, name
        self.roles, self.bot, self.events = [guild.default_role], False, []

    async def add_roles(self, *roles, reason=None):
        self.roles += [r for r in roles if r not in self.roles]

    async def remove_roles(self, *roles, reason=None):
        self.roles = [r for r in self.roles if r not in roles]

    async def kick(self, reason=None):
        self.events.append(("kick", reason))

    async def ban(self, reason=None):
        self.events.append(("ban", reason))

    async def timeout(self, until, reason=None):
        self.events.append(("timeout", until))


class Place:
    def __init__(self, guild, name):
        self.guild, self.id, self.name = guild, f"c{next(_ids)}", name
        self._ow: dict = {}

    @property
    def overwrites(self):
        return dict(self._ow)

    async def set_permissions(self, target, *, overwrite=None):
        if overwrite is None:
            self._ow.pop(target, None)
        else:
            self._ow[target] = overwrite


class Category(Place):
    async def edit(self, name=None, **kw):
        self.name = name or self.name
        return self

    async def delete(self):
        self.guild.categories.remove(self)
        for ch in self.guild.channels:
            if ch.category_id == self.id:
                ch.category_id = None


class Channel(Place):
    def __init__(self, guild, name, view="chat", category=None, topic=None, private=False):
        super().__init__(guild, name)
        self.view, self.topic, self.private, self.read_only = view, topic, private, False
        self.category_id = category.id if category else None
        self.sent: list[str] = []

    async def edit(self, **kw):
        for k, v in kw.items():
            if k == "category":
                self.category_id = v.id if v else None
            elif k != "position":
                setattr(self, k, v)
        return self

    async def delete(self):
        self.guild.channels.remove(self)

    async def send(self, text):
        self.sent.append(text)
        return SimpleNamespace(id=f"m{next(_ids)}")

    async def history(self, limit=20):
        for i, t in enumerate(reversed(self.sent[-limit:])):
            yield SimpleNamespace(id=f"h{i}", content=t, author=SimpleNamespace(display_name="Bot", npub="npub1bot"),
                                  created_at=None, attachments=[])


class Guild:
    def __init__(self, name="Test", gid="g1"):
        self.id, self.name = gid, name
        self.default_role = Role(self, "@everyone", Permissions(view_channel=True, send_messages=True), default=True)
        self.roles = [self.default_role]
        self.categories: list[Category] = []
        self.channels: list[Channel] = [Channel(self, "general")]
        self.members = [Member(self, "npub1" + "a" * 58, "Ada"), Member(self, "npub1" + "b" * 58, "Bob")]
        self.unbanned: list[str] = []

    @property
    def text_channels(self):
        return [c for c in self.channels if c.view == "chat"]

    def get_channel(self, cid):
        return next((c for c in self.channels if c.id == cid), None)

    def get_member(self, npub):
        return next((m for m in self.members if m.npub == npub), None)

    async def create_text_channel(self, name, category=None, topic=None, private=False):
        self.channels.append(Channel(self, name, "chat", category, topic, private))
        return self.channels[-1]

    async def create_voice_channel(self, name, category=None, private=False):
        self.channels.append(Channel(self, name, "voice", category, None, private))
        return self.channels[-1]

    async def create_forum(self, name, category=None, topic=None, private=False):
        self.channels.append(Channel(self, name, "forum", category, topic, private))
        return self.channels[-1]

    async def create_category(self, name):
        self.categories.append(Category(self, name))
        return self.categories[-1]

    async def create_role(self, name, permissions=0, colour=0, hoist=False, mentionable=False):
        r = Role(self, name, permissions, colour, hoist, mentionable)
        self.roles.append(r)
        return r

    async def edit_role_positions(self, positions):
        for r, p in positions.items():
            r.position = p

    async def set_default_permissions(self, perms):
        self.default_role.permissions = Permissions(int(perms))

    async def unban(self, npub):
        self.unbanned.append(npub)


def fake_bot(*guilds):
    """Enough of VectiqBot for the manager, the MCP tools and the dashboard."""
    from vectiq.app import VectiqBot

    return SimpleNamespace(guilds=list(guilds), serves=lambda g: True, find_channel=VectiqBot.find_channel,
                           user=SimpleNamespace(id="npub1bot", npub="npub1bot"), get_cog=lambda name: None)


__all__ = ["Guild", "PermissionOverwrite"]

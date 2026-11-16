"""Make the README images from a made-up demo community (no real accounts, nothing goes to Vector).

    pip install -e ".[dev]" playwright
    python tools/screenshots.py --chrome /path/to/chrome     # writes docs/images/*.png

It starts the real dashboard app over a fake bot whose data lives in a temporary SQLite file, signs in
with a demo login and screenshots each page, then renders the rank and leaderboard cards.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import random
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw

from vectiq.config import Config
from vectiq.db import Database
from vectiq.render import Entry, leaderboard_card, rank_card
from vectiq.stores import Stores

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
PORT = 8099
BASE = f"http://127.0.0.1:{PORT}"
GID = "demo-community"
NAMES = [
    "Nova",
    "Pixel Fox",
    "Juniper",
    "Atlas",
    "Mira K.",
    "Orbit",
    "Sable",
    "Wren",
    "Kai",
    "Lumen",
    "Tobi",
    "Echo",
    "Rook",
    "Indigo",
    "Marlow",
    "Quill",
    "Zephyr",
    "Ash",
    "Coral",
    "Vex",
]
PALETTES = [
    ((89, 252, 179), (20, 90, 70)),
    ((124, 183, 255), (30, 50, 110)),
    ((255, 160, 122), (110, 40, 40)),
    ((255, 214, 102), (110, 80, 20)),
    ((200, 150, 255), (60, 30, 110)),
    ((120, 230, 240), (20, 80, 100)),
]


def npub(i: int) -> str:
    return "npub1" + hashlib.sha256(f"demo{i}".encode()).hexdigest()[:58].translate(str.maketrans("bio1", "cde2"))


def make_avatar(i: int) -> bytes:
    rnd = random.Random(i)
    light, dark = PALETTES[i % len(PALETTES)]
    img = Image.new("RGB", (256, 256), dark)
    d = ImageDraw.Draw(img)
    for k in range(5):
        r = rnd.randint(50, 140)
        x, y = rnd.randint(-40, 256), rnd.randint(-40, 256)
        shade = tuple(int(dark[c] + (light[c] - dark[c]) * (0.35 + 0.15 * k)) for c in range(3))
        d.ellipse((x - r, y - r, x + r, y + r), fill=shade)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# -- a fake bot shaped like the parts of VectiqBot the dashboard uses ------------------------------------


class Asset:
    def __init__(self, i):
        self.url, self._i = f"{BASE}/demo-avatars/{i}.png", i

    async def read(self):
        return make_avatar(self._i)


class Perms:
    def __init__(self, admin):
        self.administrator = self.manage_guild = admin


class Role:
    def __init__(self, rid, name, colour):
        self.id, self.name, self.colour = rid, name, SimpleNamespace(value=colour)

    def is_default(self):
        return False


class Channel:
    def __init__(self, cid, name, category=None):
        self.id, self.name, self.category, self.private = (
            cid,
            name,
            SimpleNamespace(name=category) if category else None,
            False,
        )


class Member:
    def __init__(self, i, name, admin=False, roles=(), timed_out=False):
        self.npub = self.id = npub(i)
        self.display_name = self.name = name
        self.display_avatar = Asset(i)
        self.bot = name == "Vectiq"
        self.roles, self._admin, self._to = list(roles), admin, timed_out
        self.guild_permissions = Perms(admin)
        self.joined_at = time.time() - random.Random(i).randint(2, 400) * 86400
        self.mention = f"nostr:{self.npub}"

    def is_admin(self):
        return self._admin

    def is_timed_out(self):
        return self._to


class Guild:
    def __init__(self):
        self.id, self.name = GID, "Nebula Builders"
        self.roles = [
            Role("r1", "Admin", 0x59FCB3),
            Role("r2", "Moderator", 0x7CB7FF),
            Role("r3", "Gamer", 0xFF9F7A),
            Role("r4", "Artist", 0xC896FF),
            Role("r5", "Dev", 0xFFD666),
            Role("r6", "Verified", 0x8C8E94),
        ]
        r = {x.name: x for x in self.roles}
        self.members = [Member(0, "Nova", True, [r["Admin"], r["Dev"]])]
        for i, n in enumerate(NAMES[1:], start=1):
            roles = [r["Verified"]] + [
                r[x] for x in ("Gamer", "Artist", "Dev") if random.Random(i * 7 + len(x)).random() < 0.4
            ]
            if i in (3, 8):
                roles.insert(0, r["Moderator"])
            self.members.append(Member(i, n, admin=i == 3, roles=roles, timed_out=i == 11))
        self.members += [Member(100 + k, f"npub1demo{k}…") for k in range(7)]
        self.owner_id = self.members[0].npub
        self.text_channels = [
            Channel("c1", "📣┊announcements", "Info"),
            Channel("c2", "💬┊general", "Community"),
            Channel("c3", "🎮┊games", "Community"),
            Channel("c4", "🛠️┊dev-chat", "Community"),
            Channel("c5", "🎨┊art", "Community"),
            Channel("c6", "🤖┊bot-commands", "Bots"),
        ]
        self.capabilities = {
            "manage_roles": True,
            "manage_channels": True,
            "manage_messages": True,
            "moderate_members": True,
            "kick": True,
            "ban": True,
        }

    def get_member(self, n):
        return next((m for m in self.members if m.npub == n), None)

    def get_channel(self, cid):
        return next((c for c in self.text_channels if c.id == cid), None)

    def get_role(self, rid):
        return next((r for r in self.roles if r.id == rid), None)

    async def bans(self, limit=None):
        for i, reason in ((200, "spam links"), (201, "raid account")):
            yield SimpleNamespace(
                user=SimpleNamespace(npub=npub(i), id=npub(i), display_name=f"npub1spam{i}…", display_avatar=None),
                reason=reason,
            )


class Bot:
    def __init__(self, config, stores):
        self.config, self.stores, self.db = config, stores, stores.db
        self.guilds = [Guild()]
        self.user = SimpleNamespace(npub=npub(999), id=npub(999), display_name="Vectiq", display_avatar=None)
        self.command_prefix = "!"
        hooks = SimpleNamespace(
            status=lambda: [
                {
                    "name": "deploys",
                    "channel": "🛠️┊dev-chat",
                    "events": ["mod"],
                    "community": GID,
                    "channel_id": "c4",
                    "channel_name": "🛠️┊dev-chat",
                },
                {
                    "name": "mod-log",
                    "channel": "🤖┊bot-commands",
                    "events": ["mod", "joins", "leaves", "tickets"],
                    "community": GID,
                    "channel_id": "c6",
                    "channel_name": "🤖┊bot-commands",
                },
            ]
        )
        self.cogs = {"Games": object(), "Onboarding": object(), "Webhooks": hooks}

    def serves(self, g):
        return True

    def get_guild(self, gid):
        return self.guilds[0] if gid == GID else None

    def get_cog(self, name):
        return self.cogs.get(name)

    def get_user(self, n):
        return self.guilds[0].get_member(n)

    async def fetch_user(self, n):
        return self.guilds[0].get_member(n)


# -- demo data ---------------------------------------------------------------------------------------------


async def seed(stores: Stores, guild: Guild) -> None:
    rnd = random.Random(42)
    people = [m for m in guild.members if not m.name.startswith("npub1demo")]
    for i, m in enumerate(people):
        await stores.levels.add_xp(GID, m.npub, int(9000 / (i + 1.3)) + rnd.randint(0, 300))
        await stores.db.execute(
            "UPDATE levels SET messages=? WHERE guild_id=? AND user_id=?",
            (int(900 / (i + 1)) + rnd.randint(5, 40), GID, m.npub),
        )
        await stores.economy.adjust(GID, m.npub, rnd.randint(80, 4000), "daily", start=100)
    mod = people[0].npub
    for who, action, reason, ago in (
        (5, "warn", "spamming emoji in #general", 3),
        (5, "warn", "again, please stop", 2),
        (11, "timeout", "heated argument", 1),
        (9, "warn", "off-topic in #dev-chat", 5),
        (14, "kick", "ignoring warnings", 9),
        (12, "warn", "self-promotion", 0.3),
    ):
        c = await stores.moderation.add(
            GID,
            people[who].npub,
            mod,
            action,
            reason,
            expires_at=int(time.time() + 3600) if action == "timeout" else None,
        )
        await stores.db.execute("UPDATE mod_cases SET created_at=? WHERE id=?", (int(time.time() - ago * 86400), c.id))
    for i, (subject, lines) in enumerate(
        (
            (
                "Can't see the art channel",
                [
                    "Hi! I joined yesterday but #art is hidden for me.",
                    "Did you pick 🎨 in the role menu?",
                    "Oh! That fixed it, thanks",
                ],
            ),
            ("Report: spam DMs", ["Someone keeps sending me links in DMs."]),
            ("Lost my daily streak", ["My streak reset even though I claimed yesterday."]),
        )
    ):
        t = await stores.tickets.create(GID, people[6 + i].npub, subject)
        for j, line in enumerate(lines):
            await stores.tickets.log(t.id, (people[6 + i] if j % 2 == 0 else people[3]).npub, line)
        if i == 0:
            await stores.tickets.claim(t.id, people[3].npub)
            await stores.tickets.close(t.id, people[3].npub)
    for prize, mins, ended in (
        ("Custom role colour", 2 * 60 * 24, False),
        ("1,000 coins", 45, False),
        ("Nitro-style badge", -600, True),
    ):
        g = await stores.giveaways.create(GID, "c1", people[0].npub, prize, 1, int(time.time() + mins * 60))
        for m in people[: rnd.randint(4, 15)]:
            await stores.giveaways.enter(g.id, m.npub)
        if ended:
            await stores.giveaways.finish(g.id)
    menu = await stores.role_menus.create(GID, "c2", "m1", "Pick your interests")
    for emoji, rid, label in (("🎮", "r3", "Gamer"), ("🎨", "r4", "Artist"), ("💻", "r5", "Dev")):
        await stores.role_menus.add_option(menu.id, emoji, rid, label)
    await stores.levels.set_reward(GID, 5, "r6")
    await stores.levels.set_reward(GID, 10, "r3")
    for name, price, desc, role in (
        ("VIP pass", 2500, "Shiny name colour for a month", "r5"),
        ("Sticker pack", 300, "Five custom emoji", None),
        ("Shout-out", 800, "A post in #announcements", None),
    ):
        await stores.economy.add_item(GID, name, price, desc, role, None if price > 1000 else 20)
    for game in ("tictactoe", "connect4", "trivia", "slots"):
        for m in people[:6]:
            for _ in range(rnd.randint(1, 9)):
                await stores.games.record(GID, m.npub, game, won=rnd.random() < 0.45, score=rnd.randint(0, 30))
    for d in range(30):
        day = time.strftime("%Y-%m-%d", time.gmtime(time.time() - d * 86400))
        base = 160 + 70 * (1 if (d % 7) in (1, 2) else 0) + rnd.randint(-40, 60) - d * 2
        for cid, share in (("c2", 0.55), ("c3", 0.2), ("c4", 0.15), ("c5", 0.1)):
            await stores.activity.bump(
                GID,
                cid,
                messages=int(base * share),
                day=day,
                joins=rnd.randint(0, 4) if cid == "c2" else 0,
                leaves=rnd.randint(0, 1) if cid == "c2" else 0,
            )
    for k in range(9):
        await stores.onboarding.start(GID, people[k + 5].npub)
        if k < 7:
            await stores.onboarding.complete(GID, people[k + 5].npub)


# -- screenshots ---------------------------------------------------------------------------------------------


async def main(chrome: str | None) -> None:
    import uvicorn
    from fastapi.staticfiles import StaticFiles
    from playwright.async_api import async_playwright

    from vectiq.dashboard.server import create_app

    OUT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    avatars = tmp / "avatars"
    avatars.mkdir()
    for i in list(range(len(NAMES))):
        (avatars / f"{i}.png").write_bytes(make_avatar(i))
    (tmp / "config.yaml").write_text("owners: []\nmodules:\n  dashboard: true\n")
    cfg = Config.load(tmp / "config.yaml", env={})
    db = await Database(str(tmp / "demo.db")).connect()
    stores = Stores(db)
    bot = Bot(cfg, stores)
    await seed(stores, bot.guilds[0])
    await stores.dashboard.create_user("nova", bot.guilds[0].owner_id, "demo password 123")
    app = create_app(bot)
    app.mount("/demo-avatars", StaticFiles(directory=avatars), name="demo-avatars")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    task = asyncio.ensure_future(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=chrome, args=["--no-sandbox"])
        ctx = await browser.new_context(viewport={"width": 1360, "height": 860}, device_scale_factor=2)
        page = await ctx.new_page()

        async def shot(name, url=None, wait=1200, full=False):
            if url:
                await page.goto(BASE + url)
            await page.wait_for_timeout(wait)
            await page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
            print("wrote", name)

        await page.goto(BASE)
        await page.wait_for_selector("input[autocomplete=username]")
        await page.fill("input[autocomplete=username]", "nova")
        await shot("dashboard-login", wait=300)
        await page.fill("input[type=password]", "demo password 123")
        await page.click("form button.primary")
        await page.wait_for_selector(".side")
        await shot("dashboard-overview", f"/#/c/{GID}/overview", 2500)
        await shot("dashboard-members", f"/#/c/{GID}/members", 1800)
        await page.click("tbody tr.click >> nth=4")
        await shot("dashboard-member", wait=1800)
        await shot("dashboard-leveling", f"/#/c/{GID}/leveling", 2500)
        await page.goto(BASE + f"/#/c/{GID}/tickets/")
        await page.wait_for_timeout(1200)
        await page.click(".item.click >> nth=2")
        await shot("dashboard-ticket", wait=1200)
        await shot("dashboard-giveaways", f"/#/c/{GID}/giveaways", 1200)
        await shot("dashboard-settings", "/#/settings/leveling", 1200)
        phone = await browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        await phone.add_cookies(await ctx.cookies())
        page = await phone.new_page()
        await shot("dashboard-phone", f"/#/c/{GID}/overview", 2500)
        await browser.close()

    server.should_exit = True
    await task
    await db.close()

    # the cards members see in chat
    db = await Database(str(tmp / "demo.db")).connect()
    rows = await Stores(db).levels.leaderboard(GID, 8)
    await db.close()
    guild = bot.guilds[0]
    index = {m.npub: i for i, m in enumerate(guild.members)}
    entries = [
        Entry(
            position=r.position,
            name=guild.get_member(r.user_id).display_name,
            level=r.level,
            xp=r.xp,
            into=r.into_level,
            span=r.level_span,
            messages=r.messages,
            avatar=make_avatar(index[r.user_id]),
            ident=r.user_id,
        )
        for r in rows
    ]
    (OUT / "leaderboard-card.png").write_bytes(leaderboard_card(entries, community=guild.name))
    (OUT / "rank-card.png").write_bytes(rank_card(entries[1], community=guild.name))
    print("wrote cards")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--chrome", help="path to a Chrome/Chromium binary (default: Playwright's own)")
    asyncio.run(main(ap.parse_args().chrome))

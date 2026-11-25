"""The dashboard's FastAPI app: sign-in by Vector DM, then a JSON API the single-page front end calls.

It runs inside the bot's own event loop (see cogs/dashboard.py), so every handler can use the live
bot, its stores and its cogs directly. Nothing here talks to Vector except through those.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .. import modules
from ..config import ConfigError
from ..games.registry import GAMES
from ..render import Entry, leaderboard_card
from ..stores import InsufficientFunds
from ..stores.dashboard import PasswordError
from ..utils.durations import DurationError, format_duration, parse_duration
from ..utils.embeds import avatar_bytes, embed, name_of
from . import schema
from .access import AREAS, LEVELS, PRESETS, Access, area_of, clean_levels, clean_npub

log = logging.getLogger("vectiq.dashboard")
STATIC = Path(__file__).resolve().parent / "static"
FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
COOKIE = "vectiq_session"
GENERIC_SENT = "If that account can manage a community here, a sign-in code is on its way in Vector."


# -- small helpers --------------------------------------------------------------------------------


def avatar_url(user: Any) -> str | None:
    try:
        asset = getattr(user, "display_avatar", None)
        url = getattr(asset, "url", None)
        return url if isinstance(url, str) and url.startswith(("https://", "http://")) else None
    except Exception:  # noqa: BLE001
        return None


# npub -> (name, avatar url), filled in the background by Profiles (members' profiles aren't loaded up front)
PROFILES: dict[str, tuple[str | None, str | None]] = {}


def person(user: Any, npub: str | None = None) -> dict:
    npub = str(getattr(user, "npub", None) or npub or getattr(user, "id", ""))
    name = name_of(user, "") if user is not None else ""
    avatar = avatar_url(user) if user is not None else None
    if not name or name.startswith("npub1"):
        cached_name, cached_avatar = PROFILES.get(npub, (None, None))
        name, avatar = cached_name or name, avatar or cached_avatar
    return {"id": npub, "name": name or npub[:12] + "…", "avatar": avatar}


class Profiles:
    """Fetch members' Vector profiles a few at a time so the dashboard can show names and pictures."""

    def __init__(self, bot, concurrency: int = 4):
        self.bot = bot
        self.sem = asyncio.Semaphore(concurrency)
        self.tried: dict[str, float] = {}
        self.tasks: set[asyncio.Task] = set()

    def want(self, npubs) -> None:
        now = time.monotonic()
        for npub in npubs:
            if npub in PROFILES or now - self.tried.get(npub, -1e9) < 3600:
                continue
            self.tried[npub] = now
            task = asyncio.ensure_future(self._one(npub))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    async def _one(self, npub: str) -> None:
        async with self.sem:
            try:
                user = await asyncio.wait_for(self.bot.fetch_user(npub), 10)
            except Exception:  # noqa: BLE001 - no profile published, relay slow: try again later
                return
            name = name_of(user, "")
            PROFILES[npub] = (None if not name or name.startswith("npub1") else name, avatar_url(user))


def who(guild: Any, npub: str) -> dict:
    m = guild.get_member(npub) if guild is not None else None
    return person(m, npub)


def ts(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(value.timestamp())
    except Exception:  # noqa: BLE001
        return None


def channel_json(ch: Any) -> dict:
    cat = getattr(ch, "category", None)
    return {"id": str(ch.id), "name": ch.name, "category": getattr(cat, "name", None),
            "private": bool(getattr(ch, "private", False))}


def role_json(r: Any) -> dict:
    colour = getattr(r, "colour", None)
    value = getattr(colour, "value", colour) if colour is not None else 0
    return {"id": str(r.id), "name": r.name, "color": f"#{int(value or 0):06x}" if value else None,
            "default": bool(getattr(r, "is_default", lambda: False)())}


class RateLimit:
    """Sliding-window limiter kept in memory (enough for one bot process)."""

    def __init__(self, limit: int, window: float):
        self.limit, self.window = limit, window
        self.hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now, q = time.monotonic(), self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


def fail(status: int, message: str):
    raise HTTPException(status_code=status, detail=message)


# -- the app ---------------------------------------------------------------------------------------


def role_hex(role: Any) -> str | None:
    """A role's colour as #rrggbb, whether the SDK gives a number or a Colour object (``.value``); None if unset."""
    c = getattr(role, "colour", None)
    c = getattr(c, "value", c)
    try:
        n = int(c or 0)
    except (TypeError, ValueError):
        return None
    return f"#{n:06x}" if n else None


def create_app(bot) -> FastAPI:  # noqa: C901 - one closure keeps every route next to the bot it uses
    cfg = bot.config
    store = bot.stores.dashboard
    access = Access(bot)
    ip_limit = RateLimit(10, 600)
    verify_limit = RateLimit(20, 600)
    login_limit = RateLimit(20, 600)
    profiles = Profiles(bot)
    app = FastAPI(title="Vectiq dashboard", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.profiles = profiles

    def secure_cookie() -> bool:
        return str(cfg.get("dashboard.base_url", "")).startswith("https://")

    @app.middleware("http")
    async def headers(request: Request, call_next):
        # Same-origin JSON only: a cross-site form can't add this header, so it can't change anything.
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/") \
                and request.headers.get("x-requested-with") != "vectiq":
            return JSONResponse({"detail": "Missing X-Requested-With header."}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault(   # the verification page sets its own, to allow the CAPTCHA
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: https: http:; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def start_session(response: Response, token: str) -> None:
        days = int(cfg.get("dashboard.session_days", 7))
        response.set_cookie(COOKIE, token, max_age=days * 86400, httponly=True, samesite="strict",
                            secure=secure_cookie(), path="/")

    loaded = {"rules": False}

    async def ensure_rules() -> None:
        if not loaded["rules"]:
            await access.load(store)
            loaded["rules"] = True

    area_label = {a: label for a, label, _ in AREAS}

    @app.middleware("http")
    async def area_guard(request: Request, call_next):
        """What a role may see or change in a community (Dashboard access). Sign-in itself is checked by the routes."""
        if request.url.path.startswith("/api/"):
            await ensure_rules()                  # sign-in needs them too, before any session exists
        parts = request.url.path.split("/")
        gid, rest, area_hint = None, [], None
        if request.url.path.startswith("/api/c/") and len(parts) > 3:
            gid, rest = parts[3], [p for p in parts[4:] if p]
        elif request.url.path.startswith("/api/panel/"):
            gid, area_hint = request.query_params.get("gid") or None, "modules"
            if request.method == "POST" and gid is None:
                try:
                    gid = str((await request.json()).get("gid") or "") or None
                except Exception:  # noqa: BLE001 - the route reports a bad body
                    gid = None
        token = request.cookies.get(COOKIE, "")
        if gid and token:
            session = await store.session(token)
            g = bot.get_guild(gid) if session else None
            if g is not None and bot.serves(g):
                await ensure_rules()
                if access.levels(g, session.npub):
                    area, write = (area_hint, request.method != "GET") if area_hint else area_of(request.method, rest)
                    if not access.allows(g, session.npub, area, write):
                        label = area_label.get(area or "", "")
                        if area is None:
                            msg = "Only people with full access to this community's dashboard can do that."
                        elif write and access.levels(g, session.npub).get(area) == "view":
                            msg = f"You can look at {label} but not change it."
                        else:
                            msg = f"You don't have access to {label} in this community."
                        return JSONResponse({"detail": msg}, status_code=403)
        return await call_next(request)

    async def current(request: Request) -> str:
        await ensure_rules()
        session = await store.session(request.cookies.get(COOKIE, ""))
        if session is None:
            fail(401, "Please sign in.")
        if not access.may_sign_in(session.npub):
            fail(403, "You no longer manage any community this bot serves.")
        return session.npub

    async def owner(npub: str = Depends(current)) -> str:
        if not access.is_owner(npub):
            fail(403, "Only bot owners can do that.")
        return npub

    def community(guild_id: str, npub: str):
        g = access.guild(npub, guild_id)
        if g is None:
            fail(404, "Community not found, or you don't manage it.")
        return g

    def cog(name: str):
        c = bot.get_cog(name)
        if c is None:
            fail(409, f"The {name.lower()} module is turned off.")
        return c

    async def audit(npub: str, action: str, detail: str = "", guild: Any = None) -> None:
        await store.audit(npub, action, detail, str(guild.id) if guild is not None else "")

    async def body(request: Request) -> dict:
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001
            fail(400, "Send JSON.")
        if not isinstance(data, dict):
            fail(400, "Send a JSON object.")
        return data

    def channel(guild: Any, channel_id: Any):
        ch = guild.get_channel(str(channel_id or ""))
        if ch is None or ch not in guild.text_channels:
            fail(400, "Pick a text channel.")
        return ch

    def target(guild: Any, npub: str, user_id: str, *, must_be_member: bool = True):
        m = guild.get_member(user_id)
        if m is None and must_be_member:
            fail(404, "That member isn't in this community.")
        if user_id == npub:
            fail(400, "You can't do that to yourself.")
        if user_id == str(bot.user.id):
            fail(400, "That's the bot.")
        if user_id == str(guild.owner_id):
            fail(400, "You can't do that to the community owner.")
        return m

    async def act(coro, what: str):
        try:
            return await coro
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - usually a missing permission on Vector's side
            fail(502, f"Couldn't {what}: {exc}")

    # -- pages ---------------------------------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    if cfg.get("verification.mode") == "captcha" and cfg.get("modules.verification"):
        from .verify_page import add_verify_routes

        add_verify_routes(app, bot)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.mount("/fonts", StaticFiles(directory=FONTS), name="fonts")

    # -- sign-in -------------------------------------------------------------------------------------

    def ip_of(request: Request) -> str:
        return request.client.host if request.client else "?"

    async def begin(request: Request, response: Response, npub: str, how: str) -> None:
        days = int(cfg.get("dashboard.session_days", 7))
        start_session(response, await store.new_session(npub, days * 86400, request.headers.get("user-agent", "")))
        await audit(npub, "signed in", how)

    @app.get("/api/auth/options")
    async def auth_options():
        return {"password": True, "vector_code": bool(cfg.get("dashboard.vector_code_login", True)),
                "bot": person(bot.user) if bot.user else None}

    @app.post("/api/auth/login")
    async def login(request: Request, response: Response):
        data = await body(request)
        if not login_limit.allow(ip_of(request)):
            fail(429, "Too many sign-in attempts. Try again in a few minutes.")
        username = str(data.get("username", "")).strip()[:64]
        password = str(data.get("password", ""))[:256]
        if not username or not password:
            fail(400, "Enter your username and password.")
        npub, why = await store.check_login(username, password)
        if npub is None:
            fail(401, why)
        if not access.may_sign_in(npub):
            fail(403, "This account's Vector npub doesn't manage any community this bot serves.")
        await begin(request, response, npub, f"password ({username})")
        return {"ok": True}

    @app.post("/api/auth/request")
    async def request_code(request: Request):
        if not cfg.get("dashboard.vector_code_login", True):
            fail(403, "Sign-in with a Vector code is turned off. Use your username and password.")
        data = await body(request)
        ip = request.client.host if request.client else "?"
        if not ip_limit.allow(ip):
            fail(429, "Too many sign-in attempts. Try again in a few minutes.")
        npub = clean_npub(str(data.get("npub", "")))
        if npub is None:
            fail(400, "That doesn't look like an npub.")
        if not access.may_sign_in(npub) or await store.recent_logins(npub, 600) >= 3:
            return {"ok": True, "message": GENERIC_SENT}   # same answer either way: no account probing
        await send_link(npub)
        return {"ok": True, "message": GENERIC_SENT}

    async def send_link(npub: str) -> None:
        minutes = int(cfg.get("dashboard.code_minutes", 10))
        code, link = await store.new_login(npub, minutes * 60)
        base = str(cfg.get("dashboard.base_url", "")).rstrip("/")
        text = (f"🔐 **Vectiq dashboard sign-in**\nCode: **{code}**\nOr open: {base}/auth/link?t={link}\n"
                f"It works once and expires in {minutes} minutes. If you didn't ask for this, ignore it.")
        try:
            user = bot.get_user(npub) or await bot.fetch_user(npub)
            await user.send(text)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not DM a sign-in code to %s: %s", npub[:12], exc)

    app.state.send_link = send_link

    @app.post("/api/auth/verify")
    async def verify(request: Request, response: Response):
        data = await body(request)
        npub = clean_npub(str(data.get("npub", "")))
        code = str(data.get("code", "")).strip()
        ip = request.client.host if request.client else "?"
        if not verify_limit.allow(ip):
            fail(429, "Too many attempts. Try again in a few minutes.")
        if npub is None or not code.isdigit() or not await store.redeem_code(npub, code):
            fail(400, "That code is wrong or has expired. Ask for a new one.")
        if not access.may_sign_in(npub):
            fail(403, "You don't manage any community this bot serves.")
        await begin(request, response, npub, "Vector code")
        return {"ok": True}

    @app.get("/auth/link", include_in_schema=False)
    async def magic(request: Request, t: str = ""):
        npub = await store.redeem_link(t) if t and cfg.get("dashboard.vector_code_login", True) else None
        if npub is None or not access.may_sign_in(npub):
            return HTMLResponse("<p>This sign-in link has expired or was already used. "
                                "<a href='/'>Ask for a new one</a>.</p>", status_code=400)
        response = RedirectResponse("/", status_code=303)
        await begin(request, response, npub, "Vector link")
        return response

    @app.post("/api/auth/logout")
    async def logout(request: Request, response: Response):
        await store.end_session(request.cookies.get(COOKIE, ""))
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.post("/api/auth/logout-everywhere")
    async def logout_all(response: Response, npub: str = Depends(current)):
        n = await store.end_all_sessions(npub)
        response.delete_cookie(COOKIE, path="/")
        await audit(npub, "signed out everywhere", f"{n} session(s)")
        return {"ok": True, "ended": n}

    # -- accounts -------------------------------------------------------------------------------------

    def user_json(r: Any) -> dict:
        return {"username": r["username"], "npub": r["npub"], "person": person(access.actor(r["npub"]), r["npub"]),
                "created_at": r["created_at"], "updated_at": r["updated_at"], "created_by": r["created_by"],
                "last_login": r["last_login"], "locked": r["locked_until"] > time.time(),
                "can_sign_in": access.may_sign_in(r["npub"])}

    @app.get("/api/account")
    async def account(npub: str = Depends(current)):
        rows = await store.users_for(npub)
        return {"npub": npub, "usernames": [r["username"] for r in rows]}

    @app.post("/api/account")
    async def account_create(request: Request, npub: str = Depends(current)):
        data = await body(request)
        if await store.users_for(npub):
            fail(409, "You already have a username. Change its password instead.")
        username = str(data.get("username", "")).strip()
        try:
            await store.create_user(username, npub, str(data.get("password", "")), created_by=npub)
        except PasswordError as exc:
            fail(400, str(exc))
        await audit(npub, "created own login", username)
        return {"ok": True, "message": f"You can now sign in as {username}."}

    @app.put("/api/account/password")
    async def account_password(request: Request, npub: str = Depends(current)):
        data = await body(request)
        username = str(data.get("username", "")).strip()
        row = await store.user(username)
        if row is None or row["npub"] != npub:
            fail(404, "That isn't your username.")
        ok_npub, why = await store.check_login(username, str(data.get("current", "")))
        if ok_npub is None:
            fail(400, "Your current password is wrong." if "Wrong" in why else why)
        try:
            await store.set_password(username, str(data.get("new", "")))
        except PasswordError as exc:
            fail(400, str(exc))
        await audit(npub, "changed password", username)
        return {"ok": True, "message": "Password changed."}

    @app.get("/api/users")
    async def users(npub: str = Depends(owner)):
        return {"users": [user_json(r) for r in await store.users()]}

    @app.post("/api/users")
    async def users_create(request: Request, npub: str = Depends(owner)):
        data = await body(request)
        target_npub = clean_npub(str(data.get("npub", "")))
        if target_npub is None:
            fail(400, "Give the npub this login is for.")
        username = str(data.get("username", "")).strip()
        try:
            await store.create_user(username, target_npub, str(data.get("password", "")), created_by=npub)
        except PasswordError as exc:
            fail(400, str(exc))
        await audit(npub, "created login", f"{username} → {target_npub}")
        warn = "" if access.may_sign_in(target_npub) else (
            " Note: that npub doesn't manage any community here yet, so it can't sign in until it does.")
        return {"ok": True, "message": f"Created {username}.{warn}"}

    @app.post("/api/users/{username}/password")
    async def users_reset(username: str, request: Request, npub: str = Depends(owner)):
        data = await body(request)
        if await store.user(username) is None:
            fail(404, "No such user.")
        try:
            await store.set_password(username, str(data.get("password", "")))
        except PasswordError as exc:
            fail(400, str(exc))
        await audit(npub, "reset password", username)
        return {"ok": True, "message": f"New password set for {username}. It also unlocks the account."}

    @app.delete("/api/users/{username}")
    async def users_delete(username: str, npub: str = Depends(owner)):
        row = await store.user(username)
        if row is None:
            fail(404, "No such user.")
        await store.delete_user(username)
        ended = 0 if row["npub"] == npub else await store.end_all_sessions(row["npub"])
        await audit(npub, "deleted login", f"{username} ({ended} session(s) ended)")
        return {"ok": True, "message": f"Deleted {username} and signed them out."}

    # -- who am I ------------------------------------------------------------------------------------

    @app.get("/api/me")
    async def me(npub: str = Depends(current)):
        actor = access.actor(npub)
        return {
            "user": person(actor, npub) | {"name": str(getattr(actor, "display_name", "") or npub[:12] + "…")},
            "owner": access.is_owner(npub),
            "bot": person(bot.user),
            "prefix": cfg.prefix,
            "modules": {k: bool(v) for k, v in cfg["modules"].items()},
            "panels": [p for p in panels() if access.is_owner(npub) or not p["owner_only"]],
            "communities": [{"id": str(g.id), "name": g.name, "members": len(g.members),
                             "access": access.levels(g, npub), "configure": access.can_configure(g, npub)}
                            for g in access.manageable(npub)],
        }

    # -- module panels: any module (plugins too) can put a page on the dashboard ----------------------

    def panels() -> list[dict]:
        out = []
        for c in getattr(bot, "cogs", {}).values():
            spec = getattr(c, "dashboard_page", None)
            if not spec or not hasattr(c, "dashboard_panel"):
                continue
            name = modules.owner_of(type(c).__module__)
            m = modules.get(name)
            out.append({"module": name, "label": spec.get("label") or (m.label if m else name),
                        "icon": spec.get("icon", "◆"), "scope": spec.get("scope", "community"),
                        "owner_only": bool(spec.get("owner_only", False))})
        return sorted(out, key=lambda p: p["label"].lower())

    def panel_cog(name: str, npub: str, gid: str | None):
        spec = next((p for p in panels() if p["module"] == name), None)
        if spec is None:
            fail(404, "That module has no dashboard page, or it's switched off.")
        if spec["owner_only"] and not access.is_owner(npub):
            fail(403, "Only bot owners can open this page.")
        guild = community(gid, npub) if gid else None
        if guild is not None and not access.allows(guild, npub, "modules", False):
            fail(403, "You don't have access to module pages in this community.")
        if spec["scope"] == "community" and guild is None:
            fail(400, "Pick a community first.")
        c = next(c for c in bot.cogs.values() if modules.owner_of(type(c).__module__) == name
                 and getattr(c, "dashboard_page", None))
        return c, guild

    @app.get("/api/panel/{name}")
    async def panel_get(name: str, gid: str = "", npub: str = Depends(current)):
        c, guild = panel_cog(name, npub, gid or None)
        try:
            data = await c.dashboard_panel(guild, npub)
        except Exception as exc:  # noqa: BLE001 - a plugin's bug shows as a message, not a crash
            fail(500, f"The module couldn't draw its page: {exc}")
        owner = access.is_owner(npub)
        for sec in data.get("sections", []):          # hide owner-only buttons from everyone else
            if sec.get("type") == "actions":
                sec["items"] = [a for a in sec.get("items", []) if owner or not a.get("owner")]
        return data

    @app.post("/api/panel/{name}/action/{action}")
    async def panel_action(name: str, action: str, request: Request, npub: str = Depends(current)):
        data = await body(request)
        c, guild = panel_cog(name, npub, str(data.get("gid") or "") or None)
        panel = await c.dashboard_panel(guild, npub)
        item = next((a for sec in panel.get("sections", []) if sec.get("type") == "actions"
                     for a in sec.get("items", []) if a.get("id") == action), None)
        if item is None:
            fail(404, "That button isn't on this page.")
        if item.get("owner") and not access.is_owner(npub):
            fail(403, "Only bot owners can do that.")
        try:
            message = await c.dashboard_action(action, guild, npub, data.get("data") or {})
        except Exception as exc:  # noqa: BLE001
            fail(400, str(exc))
        await audit(npub, f"{name}: {item.get('label', action)}", "", guild)
        return {"ok": True, "message": message or "Done."}

    # -- community overview --------------------------------------------------------------------------

    @app.get("/api/c/{gid}/overview")
    async def overview(gid: str, npub: str = Depends(current)):
        g = community(gid, npub)
        s = bot.stores
        profiles.want(m.npub for m in g.members)
        days = await s.activity.daily(gid, 30)
        top = await s.activity.top_channels(gid, 6)
        try:
            caps = g.capabilities if not callable(g.capabilities) else g.capabilities()
            caps = dict(caps) if caps else {}
        except Exception:  # noqa: BLE001
            caps = {}
        week_ago = int(time.time()) - 7 * 86400
        recent = await s.moderation.recent(gid, 8)
        return {
            "community": {"id": gid, "name": g.name, "members": len(g.members),
                          "owner": who(g, str(g.owner_id)), "channels": len(g.text_channels), "roles": len(g.roles)},
            "bot_can": caps,
            "stats": {
                "ranked": await s.levels.count(gid),
                "open_tickets": len(await s.tickets.open_tickets(gid)),
                "giveaways": len(await s.giveaways.active(gid)),
                "cases_week": sum(1 for c in await s.moderation.recent(gid, 500) if c.created_at >= week_ago),
                "economy": await s.economy.totals(gid),
                "onboarding": await s.onboarding.counts(gid),
                "role_menus": len(await s.role_menus.menus(gid)),
            },
            "activity": [{"day": r["day"], "messages": r["m"] or 0, "joins": r["j"] or 0, "leaves": r["l"] or 0}
                         for r in reversed(days)],
            "top_channels": [{"id": r["channel_id"], "name": getattr(g.get_channel(r["channel_id"]), "name", None),
                              "messages": r["m"]} for r in top],
            "recent_cases": [case_json(g, c) for c in recent],
        }

    @app.get("/api/c/{gid}/channels")
    async def channels(gid: str, npub: str = Depends(current)):
        g = community(gid, npub)
        return {"channels": [channel_json(c) for c in g.text_channels],
                "roles": [role_json(r) for r in g.roles if not getattr(r, "is_default", lambda: False)()]}

    @app.get("/api/c/{gid}/setup-check")
    async def setup_check(gid: str, npub: str = Depends(current)):
        """What still stops the current settings from working in this community."""
        g = community(gid, npub)
        problems = []
        for path, f in schema.FIELDS.items():
            ref = cfg.get(path)
            if f["type"] == "channel" and ref and cfg.get(f"modules.{path.split('.')[0]}", True) is not False \
                    and bot.find_channel(g, ref) is None:
                problems.append(f"{f['label']}: no channel matches \"{ref}\".")
        cog = bot.get_cog("Verification")
        if cog is not None and hasattr(cog, "warnings"):
            problems += [w.replace("**", "") for w in cog.warnings(g)]
        return {"problems": problems}

    # -- members -------------------------------------------------------------------------------------

    @app.get("/api/c/{gid}/members")
    async def members(gid: str, q: str = "", offset: int = 0, limit: int = 50, filter: str = "",
                      npub: str = Depends(current)):
        g = community(gid, npub)
        needle = q.strip().lower()
        rows = [m for m in g.members if not needle or needle in m.npub.lower()
                or needle in name_of(m, "").lower()]
        warns = await bot.stores.moderation.warning_counts(gid)
        if filter == "warned":
            rows = [m for m in rows if warns.get(m.npub)]
        elif filter == "admins":
            rows = [m for m in rows if _safe(m.is_admin)]
        elif filter == "timed_out":
            rows = [m for m in rows if _safe(m.is_timed_out)]
        elif filter == "bots":
            rows = [m for m in rows if m.bot]
        total = len(rows)
        rows.sort(key=lambda m: name_of(m, m.npub).lower())
        page = rows[max(offset, 0): max(offset, 0) + min(max(limit, 1), 200)]
        ids = [m.npub for m in page]
        profiles.want(ids)
        levels = await bot.stores.levels.many(gid, ids)
        coins = await bot.stores.economy.balances(gid, ids)
        return {"total": total, "members": [
            person(m) | {"bot": bool(m.bot), "admin": _safe(m.is_admin), "timed_out": _safe(m.is_timed_out),
                         "owner": m.npub == str(g.owner_id),
                         "roles": [str(r.id) for r in m.roles if not getattr(r, "is_default", lambda: False)()],
                         "level": levels.get(m.npub, (0, 0))[1], "xp": levels.get(m.npub, (0, 0))[0],
                         "coins": coins.get(m.npub), "warnings": warns.get(m.npub, 0)} for m in page]}

    @app.get("/api/c/{gid}/members/{uid}")
    async def member(gid: str, uid: str, npub: str = Depends(current)):
        g = community(gid, npub)
        m = g.get_member(uid)
        s = bot.stores
        rank = await s.levels.rank(gid, uid)
        wallet = await s.economy.wallet(gid, uid)
        onboarding = await s.onboarding.get(gid, uid)
        return {
            "member": person(m, uid) | {
                "in_community": m is not None, "bot": bool(getattr(m, "bot", False)),
                "admin": _safe(getattr(m, "is_admin", None)), "timed_out": _safe(getattr(m, "is_timed_out", None)),
                "timed_out_until": ts(getattr(m, "timed_out_until", None)), "joined_at": ts(getattr(m, "joined_at", None)),
                "roles": [str(r.id) for r in getattr(m, "roles", []) if not getattr(r, "is_default", lambda: False)()],
                "owner": uid == str(g.owner_id)},
            "rank": {"position": rank.position, "level": rank.level, "xp": rank.xp, "messages": rank.messages,
                     "into": rank.into_level, "span": rank.level_span},
            "wallet": {"cash": wallet.balance, "bank": wallet.bank, "streak": wallet.daily_streak},
            "transactions": [dict(r) for r in await s.economy.history(gid, uid, 15)],
            "inventory": [dict(r) for r in await s.economy.inventory(gid, uid)],
            "cases": [case_json(g, c) for c in await s.moderation.for_user(gid, uid)],
            "games": [dict(r) for r in await s.games.for_user(gid, uid)],
            "onboarding": dict(onboarding) if onboarding else None,
        }

    @app.post("/api/c/{gid}/members/{uid}/action")
    async def member_action(gid: str, uid: str, request: Request, npub: str = Depends(current)):
        g = community(gid, npub)
        data = await body(request)
        action = str(data.get("action", ""))
        reason = str(data.get("reason", ""))[:400]
        mod = cog("Moderation")
        actor = access.actor(npub, g)
        notes: list[str] = []

        async def note(text: str, **_: Any) -> None:
            notes.append(str(text))

        if action == "warn":
            m = target(g, npub, uid)
            case = await mod.record(g, m, actor, "warn", reason)
            count = len(await mod.store.warnings(gid, uid))
            await mod.escalate(g, m, count, actor, note)
            msg = f"Warned {name_of(m)} (case #{case.id}, warning {count})."
        elif action in ("timeout", "tempban"):
            m = target(g, npub, uid)
            try:
                seconds = parse_duration(str(data.get("duration", "")))
            except DurationError as exc:
                fail(400, str(exc))
            if action == "timeout":
                longest = int(cfg.get("moderation.mute_max_days", 28)) * 86400
                if seconds > longest:
                    fail(400, f"The longest timeout is {format_duration(longest)}.")
                import datetime as dt
                await act(m.timeout(dt.timedelta(seconds=seconds), reason=reason or None), "time them out")
            else:
                await act(m.ban(reason=reason or None), "ban them")
            case = await mod.record(g, m, actor, action, reason, expires_at=int(time.time()) + seconds)
            msg = f"{'Timed out' if action == 'timeout' else 'Banned'} {name_of(m)} for {format_duration(seconds)} " \
                  f"(case #{case.id})."
        elif action == "untimeout":
            m = target(g, npub, uid)
            await act(m.timeout(None), "lift the timeout")
            for c in await mod.store.for_user(gid, uid, action="timeout", active_only=True):
                await mod.store.deactivate(gid, c.id)
            msg = f"Lifted the timeout on {name_of(m)}."
        elif action in ("kick", "ban"):
            m = target(g, npub, uid)
            await act(m.kick(reason=reason or None) if action == "kick" else m.ban(reason=reason or None),
                      f"{action} them")
            case = await mod.record(g, m, actor, action, reason)
            msg = f"{'Kicked' if action == 'kick' else 'Banned'} {name_of(m)} (case #{case.id})."
        elif action == "clearwarns":
            n = await mod.store.clear_warnings(gid, uid)
            msg = f"Cleared {n} warning(s)."
        else:
            fail(400, "Unknown action.")
        await audit(npub, action, f"{uid} {reason}".strip(), g)
        return {"ok": True, "message": " ".join([msg, *notes])}

    @app.post("/api/c/{gid}/members/{uid}/xp")
    async def member_xp(gid: str, uid: str, request: Request, npub: str = Depends(current)):
        g = community(gid, npub)
        data = await body(request)
        if data.get("reset"):
            await bot.stores.levels.reset(gid, uid)
            await audit(npub, "reset XP", uid, g)
            return {"ok": True, "message": "XP reset."}
        amount = _int(data.get("amount"), "Amount")
        rank = await bot.stores.levels.add_xp(gid, uid, amount)
        await audit(npub, "changed XP", f"{uid} {amount:+}", g)
        return {"ok": True, "message": f"Now level {rank.level} with {rank.xp:,} XP."}

    @app.post("/api/c/{gid}/members/{uid}/coins")
    async def member_coins(gid: str, uid: str, request: Request, npub: str = Depends(current)):
        g = community(gid, npub)
        data = await body(request)
        amount = _int(data.get("amount"), "Amount")
        reason = str(data.get("reason", "") or "adjusted in the dashboard")[:100]
        try:
            now = await bot.stores.economy.adjust(gid, uid, amount, reason,
                                                  start=int(cfg.get("economy.start_balance", 0)))
        except InsufficientFunds as exc:
            fail(400, f"They only have {exc.have:,} in cash.")
        await audit(npub, "changed coins", f"{uid} {amount:+} {reason}", g)
        return {"ok": True, "message": f"Cash is now {now:,}."}

    @app.post("/api/c/{gid}/members/{uid}/roles")
    async def member_roles(gid: str, uid: str, request: Request, npub: str = Depends(current)):
        g = community(gid, npub)
        data = await body(request)
        m = g.get_member(uid) or fail(404, "That member isn't in this community.")
        role = g.get_role(str(data.get("role", ""))) or fail(400, "Pick a role.")
        add = bool(data.get("add", True))
        await act(m.add_roles(role, reason="dashboard") if add else m.remove_roles(role, reason="dashboard"),
                  "change roles")
        await audit(npub, "gave role" if add else "removed role", f"{role.name} {uid}", g)
        return {"ok": True, "message": f"{'Gave' if add else 'Removed'} {role.name}."}

    # -- channels, categories, roles and permissions (the shared vectiq.manage layer) -------------------

    from ..manage import ManageError, Manager, explain

    manager = Manager(bot)

    async def manage(g: Any, npub: str, what: str, coro, detail: str = ""):
        try:
            out = await coro
        except ManageError as exc:
            fail(400, str(exc))
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - usually a missing permission on Vector's side
            fail(502, f"That didn't work ({what}): {explain(exc)}")
        await audit(npub, what, detail[:480], g)
        return out

    @app.get("/api/c/{gid}/structure")
    async def structure(gid: str, npub: str = Depends(current)):
        return manager.structure(community(gid, npub))

    @app.post("/api/c/{gid}/channels")
    async def channel_new(gid: str, request: Request, npub: str = Depends(current)):
        g, d = community(gid, npub), await body(request)
        ch = await manage(g, npub, "created channel", manager.create_channel(
            g, d.get("name", ""), d.get("kind", "text"), d.get("category", ""), d.get("topic", ""),
            bool(d.get("private"))), str(d.get("name")))
        return {"ok": True, "message": f"Created #{ch['name']}.", "channel": ch}

    @app.patch("/api/c/{gid}/channels/{cid}")
    async def channel_edit(gid: str, cid: str, request: Request, npub: str = Depends(current)):
        g, d = community(gid, npub), await body(request)
        ch = await manage(g, npub, "edited channel", manager.edit_channel(
            g, cid, name=d.get("name"), topic=d.get("topic"), category=d.get("category"), private=d.get("private"),
            read_only=d.get("read_only"), position=d.get("position")), cid)
        return {"ok": True, "message": f"Saved #{ch['name']}.", "channel": ch}

    @app.delete("/api/c/{gid}/channels/{cid}")
    async def channel_delete(gid: str, cid: str, npub: str = Depends(current)):
        g = community(gid, npub)
        name = await manage(g, npub, "deleted channel", manager.delete_channel(g, cid), cid)
        return {"ok": True, "message": f"Deleted #{name}."}

    @app.post("/api/c/{gid}/categories")
    async def category_new(gid: str, request: Request, npub: str = Depends(current)):
        g, d = community(gid, npub), await body(request)
        c = await manage(g, npub, "created category", manager.create_category(g, d.get("name", "")), str(d.get("name")))
        return {"ok": True, "message": f"Created {c['name']}.", "category": c}

    @app.patch("/api/c/{gid}/categories/{cid}")
    async def category_edit(gid: str, cid: str, request: Request, npub: str = Depends(current)):
        g, d = community(gid, npub), await body(request)
        c = await manage(g, npub, "renamed category", manager.rename_category(g, cid, d.get("name", "")), cid)
        return {"ok": True, "message": f"Renamed to {c['name']}."}

    @app.delete("/api/c/{gid}/categories/{cid}")
    async def category_delete(gid: str, cid: str, npub: str = Depends(current)):
        g = community(gid, npub)
        name = await manage(g, npub, "deleted category", manager.delete_category(g, cid), cid)
        return {"ok": True, "message": f"Deleted {name}. Its channels moved out of it."}

    @app.put("/api/c/{gid}/overwrites")
    async def overwrite_set(gid: str, request: Request, npub: str = Depends(current)):
        g, d = community(gid, npub), await body(request)
        r = await manage(g, npub, "changed permissions", manager.set_overwrite(
            g, str(d.get("where", "")), str(d.get("target", "")), d.get("allow") or [], d.get("deny") or []),
            f"{d.get('where')} {d.get('target')}")
        cleared = not r["allow"] and not r["deny"]
        return {"ok": True, "message": f"{'Reset' if cleared else 'Saved'} {r['target']} in {r['where']}."}

    @app.post("/api/c/{gid}/roles")
    async def role_new(gid: str, request: Request, npub: str = Depends(current)):
        g, d = community(gid, npub), await body(request)
        r = await manage(g, npub, "created role", manager.create_role(
            g, d.get("name", ""), permissions=d.get("permissions") or [], colour_hex=d.get("colour", ""),
            hoist=bool(d.get("hoist")), mentionable=bool(d.get("mentionable"))), str(d.get("name")))
        return {"ok": True, "message": f"Created {r['name']}.", "role": r}

    @app.patch("/api/c/{gid}/roles/{rid}")
    async def role_edit(gid: str, rid: str, request: Request, npub: str = Depends(current)):
        g, d = community(gid, npub), await body(request)
        r = await manage(g, npub, "edited role", manager.edit_role(
            g, rid, name=d.get("name"), permissions=d.get("permissions"), colour_hex=d.get("colour"),
            hoist=d.get("hoist"), mentionable=d.get("mentionable")), rid)
        return {"ok": True, "message": f"Saved {r['name']}."}

    @app.delete("/api/c/{gid}/roles/{rid}")
    async def role_delete(gid: str, rid: str, npub: str = Depends(current)):
        g = community(gid, npub)
        name = await manage(g, npub, "deleted role", manager.delete_role(g, rid), rid)
        return {"ok": True, "message": f"Deleted {name}."}

    @app.put("/api/c/{gid}/roles-order")
    async def role_order(gid: str, request: Request, npub: str = Depends(current)):
        g, d = community(gid, npub), await body(request)
        await manage(g, npub, "reordered roles", manager.order_roles(g, [str(x) for x in d.get("order") or []]))
        return {"ok": True, "message": "Role order saved."}

    @app.put("/api/c/{gid}/everyone")
    async def everyone_set(gid: str, request: Request, npub: str = Depends(current)):
        g, d = community(gid, npub), await body(request)
        await manage(g, npub, "changed @everyone", manager.everyone_permissions(g, d.get("permissions") or []))
        return {"ok": True, "message": "Saved what @everyone may do."}

    # -- moderation ----------------------------------------------------------------------------------

    def case_json(g: Any, c: Any) -> dict:
        return {"id": c.id, "user": who(g, c.user_id), "moderator": who(g, c.moderator), "action": c.action,
                "reason": c.reason, "created_at": c.created_at, "expires_at": c.expires_at, "active": c.active}

    @app.get("/api/c/{gid}/cases")
    async def cases(gid: str, action: str = "", limit: int = 100, npub: str = Depends(current)):
        g = community(gid, npub)
        rows = await bot.stores.moderation.recent(gid, min(max(limit, 1), 500), action or None)
        return {"cases": [case_json(g, c) for c in rows]}

    @app.post("/api/c/{gid}/cases/{case_id}/deactivate")
    async def case_off(gid: str, case_id: int, npub: str = Depends(current)):
        g = community(gid, npub)
        if not await bot.stores.moderation.deactivate(gid, case_id):
            fail(404, "No such case.")
        await audit(npub, "removed case", f"#{case_id}", g)
        return {"ok": True, "message": f"Case #{case_id} is no longer active."}

    @app.get("/api/c/{gid}/bans")
    async def bans(gid: str, npub: str = Depends(current)):
        g = community(gid, npub)
        out = []
        try:
            async for entry in g.bans(limit=500):
                user = getattr(entry, "user", entry)
                uid = str(getattr(user, "npub", None) or getattr(user, "id", user))
                out.append(person(user, uid) | {"reason": getattr(entry, "reason", "") or ""})
        except Exception as exc:  # noqa: BLE001
            fail(502, f"Couldn't read the ban list: {exc}")
        return {"bans": out}

    @app.post("/api/c/{gid}/bans/{uid}/unban")
    async def unban(gid: str, uid: str, npub: str = Depends(current)):
        g = community(gid, npub)
        mod = cog("Moderation")
        await act(mod.lift_ban(g, access.actor(uid), access.actor(npub, g), "dashboard"), "unban")
        await audit(npub, "unban", uid, g)
        return {"ok": True, "message": "Unbanned."}

    # -- leveling ------------------------------------------------------------------------------------

    @app.get("/api/c/{gid}/leveling")
    async def leveling(gid: str, page: int = 1, npub: str = Depends(current)):
        g = community(gid, npub)
        page = max(page, 1)
        rows = await bot.stores.levels.leaderboard(gid, 25, (page - 1) * 25)
        rewards = await bot.stores.levels.rewards(gid)
        return {"total": await bot.stores.levels.count(gid), "page": page,
                "leaderboard": [who(g, r.user_id) | {"position": r.position, "level": r.level, "xp": r.xp,
                                                     "messages": r.messages, "into": r.into_level, "span": r.level_span}
                                for r in rows],
                "rewards": [{"level": lv, "role": role_json(g.get_role(rid)) if g.get_role(rid) else
                             {"id": rid, "name": "(deleted role)", "color": None}} for lv, rid in rewards.items()]}

    @app.get("/api/c/{gid}/leaderboard.png")
    async def leaderboard_png(gid: str, page: int = 1, npub: str = Depends(current)):
        g = community(gid, npub)
        page = max(page, 1)
        rows = await bot.stores.levels.leaderboard(gid, 8, (page - 1) * 8)
        members = [g.get_member(r.user_id) for r in rows]
        avatars = await asyncio.gather(*(avatar_bytes(m) if m else asyncio.sleep(0) for m in members))
        entries = [Entry(position=r.position, name=name_of(m) if m else r.user_id[:12] + "…", level=r.level, xp=r.xp,
                         into=r.into_level, span=r.level_span, messages=r.messages, avatar=a, ident=r.user_id)
                   for r, m, a in zip(rows, members, avatars, strict=True)]
        png = await asyncio.to_thread(leaderboard_card, entries, community=g.name, page=page)
        return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=30"})

    @app.post("/api/c/{gid}/rewards")
    async def add_reward(gid: str, request: Request, npub: str = Depends(current)):
        g = community(gid, npub)
        data = await body(request)
        level = _int(data.get("level"), "Level")
        if not 1 <= level <= 500:
            fail(400, "Level must be 1–500.")
        role = g.get_role(str(data.get("role", ""))) or fail(400, "Pick a role.")
        await bot.stores.levels.set_reward(gid, level, str(role.id))
        await audit(npub, "set level reward", f"{level} → {role.name}", g)
        return {"ok": True, "message": f"Level {level} now gives {role.name}."}

    @app.delete("/api/c/{gid}/rewards/{level}")
    async def del_reward(gid: str, level: int, npub: str = Depends(current)):
        g = community(gid, npub)
        if not await bot.stores.levels.remove_reward(gid, level):
            fail(404, "No reward at that level.")
        await audit(npub, "removed level reward", str(level), g)
        return {"ok": True, "message": "Removed."}

    # -- economy -------------------------------------------------------------------------------------

    @app.get("/api/c/{gid}/economy")
    async def economy(gid: str, npub: str = Depends(current)):
        g = community(gid, npub)
        e = bot.stores.economy
        return {"currency": {"name": cfg.get("economy.currency_name"), "symbol": cfg.get("economy.currency_symbol")},
                "totals": await e.totals(gid),
                "richest": [who(g, w.user_id) | {"cash": w.balance, "bank": w.bank} for w in await e.leaderboard(gid, 25)],
                "shop": [{"id": i.id, "name": i.name, "price": i.price, "description": i.description,
                          "role": role_json(g.get_role(i.role_id)) if i.role_id and g.get_role(i.role_id) else None,
                          "stock": i.stock} for i in await e.shop(gid)]}

    @app.post("/api/c/{gid}/shop")
    async def add_item(gid: str, request: Request, npub: str = Depends(current)):
        g = community(gid, npub)
        data = await body(request)
        name = str(data.get("name", "")).strip()[:60]
        if not name:
            fail(400, "Give the item a name.")
        price = _int(data.get("price"), "Price")
        if price < 0:
            fail(400, "Price can't be negative.")
        stock = data.get("stock")
        stock = None if stock in (None, "") else _int(stock, "Stock")
        role_id = str(data.get("role") or "") or None
        if role_id and g.get_role(role_id) is None:
            fail(400, "That role doesn't exist.")
        if await bot.stores.economy.item(gid, name):
            fail(409, "There's already an item with that name.")
        await bot.stores.economy.add_item(gid, name, price, str(data.get("description", ""))[:200], role_id, stock)
        await audit(npub, "added shop item", f"{name} ({price})", g)
        return {"ok": True, "message": f"Added {name}."}

    @app.delete("/api/c/{gid}/shop/{name}")
    async def del_item(gid: str, name: str, npub: str = Depends(current)):
        g = community(gid, npub)
        if not await bot.stores.economy.remove_item(gid, name):
            fail(404, "No such item.")
        await audit(npub, "removed shop item", name, g)
        return {"ok": True, "message": f"Removed {name}."}

    # -- tickets -------------------------------------------------------------------------------------

    def ticket_json(g: Any, t: Any) -> dict:
        ch = g.get_channel(t.channel_id) if t.channel_id else None
        return {"id": t.id, "user": who(g, t.user_id), "subject": t.subject, "status": t.status,
                "claimed_by": who(g, t.claimed_by) if t.claimed_by else None, "created_at": t.created_at,
                "closed_at": t.closed_at, "channel": channel_json(ch) if ch else None}

    @app.get("/api/c/{gid}/tickets")
    async def tickets(gid: str, status: str = "", npub: str = Depends(current)):
        g = community(gid, npub)
        rows = await bot.stores.tickets.recent(gid, status or None, 200)
        return {"tickets": [ticket_json(g, t) | {"messages": await bot.stores.tickets.message_count(t.id)}
                            for t in rows]}

    async def own_ticket(g: Any, ticket_id: int):
        t = await bot.stores.tickets.get(ticket_id)
        if t is None or t.guild_id != str(g.id):
            fail(404, "No such ticket.")
        return t

    @app.get("/api/c/{gid}/tickets/{ticket_id}")
    async def ticket(gid: str, ticket_id: int, npub: str = Depends(current)):
        g = community(gid, npub)
        t = await own_ticket(g, ticket_id)
        lines = await bot.stores.tickets.transcript(t.id)
        return {"ticket": ticket_json(g, t),
                "transcript": [{"author": who(g, r["author_id"]), "content": r["content"], "at": r["sent_at"]}
                               for r in lines]}

    @app.post("/api/c/{gid}/tickets/{ticket_id}/claim")
    async def ticket_claim(gid: str, ticket_id: int, npub: str = Depends(current)):
        g = community(gid, npub)
        t = await own_ticket(g, ticket_id)
        if not await bot.stores.tickets.claim(t.id, npub):
            fail(409, "Already claimed or closed.")
        ch = g.get_channel(t.channel_id) if t.channel_id else None
        if ch is not None:
            await act(ch.send(f"✅ {name_of(access.actor(npub, g))} is handling this ticket."), "post in the ticket")
        await audit(npub, "claimed ticket", f"#{t.id}", g)
        return {"ok": True, "message": f"You're handling ticket #{t.id}."}

    @app.post("/api/c/{gid}/tickets/{ticket_id}/close")
    async def ticket_close(gid: str, ticket_id: int, npub: str = Depends(current)):
        g = community(gid, npub)
        t = await own_ticket(g, ticket_id)
        if t.status != "open":
            fail(409, "Already closed.")
        ch = g.get_channel(t.channel_id) if t.channel_id else None
        tickets_cog = bot.get_cog("Tickets")
        if ch is not None and tickets_cog is not None:
            replies: list[str] = []

            async def reply(text: str, **_: Any) -> None:
                replies.append(str(text))
            await tickets_cog._close(ch, g, access.actor(npub, g), "closed in the dashboard", reply=reply)
            if replies and replies[-1].startswith("❌"):
                fail(409, replies[-1].lstrip("❌ "))
        else:
            await bot.stores.tickets.close(t.id, npub)
        await audit(npub, "closed ticket", f"#{t.id}", g)
        return {"ok": True, "message": f"Ticket #{t.id} closed."}

    # -- role menus ----------------------------------------------------------------------------------

    @app.get("/api/c/{gid}/rolemenus")
    async def rolemenus(gid: str, npub: str = Depends(current)):
        g = community(gid, npub)
        out = []
        for menu in await bot.stores.role_menus.menus(gid):
            ch = g.get_channel(menu.channel_id)
            opts = await bot.stores.role_menus.options(menu.id)
            out.append({"id": menu.id, "title": menu.title, "channel": channel_json(ch) if ch else None,
                        "options": [{"emoji": o["emoji"], "role": role_json(g.get_role(o["role_id"]))
                                     if g.get_role(o["role_id"]) else {"id": o["role_id"], "name": o["label"] or "?",
                                                                       "color": None}} for o in opts]})
        return {"menus": out}

    @app.post("/api/c/{gid}/rolemenus")
    async def rolemenu_new(gid: str, request: Request, npub: str = Depends(current)):
        g = community(gid, npub)
        data = await body(request)
        roles_cog = cog("Roles")
        ch = channel(g, data.get("channel"))
        title = str(data.get("title", "")).strip()[:100] or fail(400, "Give the menu a title.")
        options = [(str(o.get("emoji", "")).strip(), str(o.get("role", "")).strip())
                   for o in data.get("options", []) if isinstance(o, dict)]
        options = [(e, r) for e, r in options if e and r]
        if not options:
            fail(400, "Add at least one emoji and role.")
        if len({e for e, _ in options}) != len(options):
            fail(400, "Each emoji can only be used once.")
        menu = await act(roles_cog.build_menu(g, ch, title, options), "post the menu")
        await audit(npub, "created role menu", f"#{menu.id} {title} in #{ch.name}", g)
        return {"ok": True, "message": f"Menu #{menu.id} is live in #{ch.name}."}

    @app.delete("/api/c/{gid}/rolemenus/{menu_id}")
    async def rolemenu_del(gid: str, menu_id: int, npub: str = Depends(current)):
        g = community(gid, npub)
        if not await bot.stores.role_menus.delete(gid, menu_id):
            fail(404, "No such menu.")
        await audit(npub, "deleted role menu", f"#{menu_id}", g)
        return {"ok": True, "message": "Deleted. The message stays in the channel; reactions on it no longer give roles."}

    # -- giveaways -----------------------------------------------------------------------------------

    @app.get("/api/c/{gid}/giveaways")
    async def giveaways(gid: str, npub: str = Depends(current)):
        g = community(gid, npub)
        out = []
        for gw in await bot.stores.giveaways.recent(gid, 50):
            ch = g.get_channel(gw.channel_id)
            out.append({"id": gw.id, "prize": gw.prize, "winners": gw.winners, "ends_at": gw.ends_at, "ended": gw.ended,
                        "host": who(g, gw.host_id), "channel": channel_json(ch) if ch else None,
                        "entries": await bot.stores.giveaways.entry_count(gw.id)})
        return {"giveaways": out, "max_winners": cfg.get("giveaways.max_winners", 10)}

    @app.post("/api/c/{gid}/giveaways")
    async def giveaway_new(gid: str, request: Request, npub: str = Depends(current)):
        g = community(gid, npub)
        data = await body(request)
        gw_cog = cog("Giveaways")
        ch = channel(g, data.get("channel"))
        prize = str(data.get("prize", "")).strip()[:200] or fail(400, "What's the prize?")
        try:
            seconds = parse_duration(str(data.get("duration", "")))
        except DurationError as exc:
            fail(400, str(exc))
        if seconds < int(cfg.get("giveaways.min_minutes", 1)) * 60:
            fail(400, "That is too short.")
        winners = _int(data.get("winners", 1), "Winners")
        gw = await act(gw_cog.launch(g, ch, access.actor(npub, g), seconds, winners, prize), "start the giveaway")
        await audit(npub, "started giveaway", f"#{gw.id} {prize}", g)
        return {"ok": True, "message": f"Giveaway #{gw.id} is running in #{ch.name}."}

    @app.post("/api/c/{gid}/giveaways/{gw_id}/{op}")
    async def giveaway_op(gid: str, gw_id: int, op: str, npub: str = Depends(current)):
        g = community(gid, npub)
        gw_cog = cog("Giveaways")
        gw = await bot.stores.giveaways.get(gw_id)
        if gw is None or gw.guild_id != gid:
            fail(404, "No such giveaway.")
        if op == "end":
            if gw.ended:
                fail(409, "It has already ended.")
            await act(gw_cog._announce(gw, await bot.stores.giveaways.finish(gw.id)), "announce the winners")
            msg = "Ended. Winners were announced in the channel."
        elif op == "cancel":
            if not await bot.stores.giveaways.cancel(gw.id):
                fail(409, "It has already ended.")
            msg = "Cancelled."
        elif op == "reroll":
            if not gw.ended:
                fail(409, "It hasn't ended yet.")
            pool = await bot.stores.giveaways.entries(gw.id)
            if not pool:
                fail(409, "Nobody entered.")
            winner = random.choice(pool)
            ch = g.get_channel(gw.channel_id)
            if ch is not None:
                await act(ch.send(f"🎉 New winner of **{gw.prize}**: {gw_cog._mention(g, winner)}"), "announce")
            msg = f"New winner: {who(g, winner)['name']}."
        else:
            fail(400, "Unknown action.")
        await audit(npub, f"{op} giveaway", f"#{gw.id}", g)
        return {"ok": True, "message": msg}

    # -- games ---------------------------------------------------------------------------------------

    @app.get("/api/c/{gid}/games")
    async def games(gid: str, npub: str = Depends(current)):
        g = community(gid, npub)
        out = []
        for name, game in GAMES.items():
            rows = await bot.stores.games.leaderboard(gid, name, 10)
            out.append({"id": name, "title": game.title,
                        "top": [who(g, r["user_id"]) | {k: r[k] for k in ("played", "won", "drawn", "score")}
                                for r in rows]})
        return {"games": out, "enabled": bot.get_cog("Games") is not None}

    @app.post("/api/c/{gid}/games")
    async def game_post(gid: str, request: Request, npub: str = Depends(current)):
        g = community(gid, npub)
        data = await body(request)
        games_cog = cog("Games")
        game = str(data.get("game", ""))
        if game not in GAMES:
            fail(400, "Unknown game.")
        ch = channel(g, data.get("channel"))
        await act(games_cog.post_game(ch, game), "post the game")
        await act(ch.send(f"🎮 **{GAMES[game].title}** is ready. Tap the app above to play."), "post")
        await audit(npub, "posted game", f"{game} in #{ch.name}", g)
        return {"ok": True, "message": f"{GAMES[game].title} posted in #{ch.name}."}

    # -- onboarding ----------------------------------------------------------------------------------

    @app.get("/api/c/{gid}/onboarding")
    async def onboarding(gid: str, npub: str = Depends(current)):
        community(gid, npub)
        return {"enabled": bot.get_cog("Onboarding") is not None, "steps": cfg.get("onboarding.steps", []),
                "counts": await bot.stores.onboarding.counts(gid),
                "role_menu": cfg.get("onboarding.role_menu", {}), "channel": cfg.get("onboarding.channel", ""),
                "title": cfg.get("onboarding.title", ""), "required": cfg.get("onboarding.required", False)}

    @app.post("/api/c/{gid}/onboarding/repost")
    async def onboarding_repost(gid: str, npub: str = Depends(current)):
        g = community(gid, npub)
        ob = cog("Onboarding")
        await act(ob.ensure_menu(g), "post the role menu")
        await audit(npub, "reposted onboarding menu", "", g)
        return {"ok": True, "message": "The onboarding role menu is up to date."}

    # -- security cam ------------------------------------------------------------------------------

    @app.get("/api/c/{gid}/securitycam")
    async def securitycam(gid: str, npub: str = Depends(current)):
        g = community(gid, npub)
        sc = bot.get_cog("SecurityCam")
        if sc is None:
            return {"enabled": False}
        cam = await sc.camera(g)
        st = sc.stats.get(gid, {})
        return {"enabled": True, "channel": str(cam.id) if cam else "",
                "channel_name": cam.name if cam else "",
                "ignore": [str(c) for c in await bot.stores.settings.get(gid, "securitycam:ignore", []) or []],
                "config_ignore": [str(c) for c in cfg.get("securitycam.ignore_channels", [])],
                "include_bots": bool(cfg.get("securitycam.include_bots", False)),
                "echoed": st.get("echoed", 0), "last": st["last"].isoformat() if st.get("last") else None}

    @app.put("/api/c/{gid}/securitycam")
    async def securitycam_save(gid: str, request: Request, npub: str = Depends(current)):
        g = community(gid, npub)
        cog("SecurityCam")
        data = await body(request)
        settings = bot.stores.settings
        if "channel" in data:
            if data["channel"]:
                ch = channel(g, data["channel"])
                await settings.set(gid, "securitycam:channel", str(ch.id))
                await audit(npub, "security cam on", f"#{ch.name}", g)
            else:
                await settings.set(gid, "securitycam:channel", "")
                await audit(npub, "security cam off", "", g)
        if "ignore" in data:
            ids = data["ignore"] if isinstance(data["ignore"], list) else []
            known = {str(c.id) for c in g.text_channels}
            ids = [str(i) for i in ids if str(i) in known]
            await settings.set(gid, "securitycam:ignore", ids)
            await audit(npub, "security cam skips", f"{len(ids)} channels", g)
        return {"ok": True, "message": "Security cam saved."}

    @app.post("/api/c/{gid}/securitycam/test")
    async def securitycam_test(gid: str, npub: str = Depends(current)):
        g = community(gid, npub)
        sc = cog("SecurityCam")
        cam = await sc.camera(g)
        if cam is None:
            fail(400, "Pick a camera channel first.")
        await act(cam.send(embed=embed("📹 Security cam test", "If you can read this, echoes will land here.",
                                       timestamp=True)), "send")
        return {"ok": True, "message": f"Test sent to #{cam.name}."}

    # -- command limits -------------------------------------------------------------------------------

    @app.get("/api/c/{gid}/command-limits")
    async def command_limits(gid: str, npub: str = Depends(current)):
        g = community(gid, npub)
        lim = cog("Limits")
        rules = await lim.get(g)
        names = {str(r.id): r.name for r in g.roles}
        return {"limits": [{"target": k, "roles": [{"id": str(i), "name": names.get(str(i), "(deleted role)")} for i in v]}
                           for k, v in sorted(rules.items())],
                "targets": lim.targets(),
                "roles": [{"id": str(r.id), "name": r.name} for r in g.roles if not getattr(r, "is_default", lambda: False)()]}

    @app.put("/api/c/{gid}/command-limits")
    async def command_limits_save(gid: str, request: Request, npub: str = Depends(current)):
        g = community(gid, npub)
        lim = cog("Limits")
        data = await body(request)
        name = lim.known(str(data.get("target", "")))
        if name is None:
            fail(400, "That isn't a command or module I know.")
        known = {str(r.id) for r in g.roles}
        ids = [str(i) for i in data.get("roles", []) if str(i) in known]
        if data.get("roles") and not ids:
            fail(400, "None of those roles exist.")
        await lim.save(g, name, ids)
        await audit(npub, "limited a command" if ids else "opened a command", f"{name}: {lim.role_names(g, ids)}", g)
        return {"ok": True, "message": f"{name} is limited to {lim.role_names(g, ids)}." if ids
                else f"{name} is open to everyone."}

    # -- announcements -------------------------------------------------------------------------------

    @app.post("/api/c/{gid}/announce")
    async def announce(gid: str, request: Request, npub: str = Depends(current)):
        g = community(gid, npub)
        data = await body(request)
        ch = channel(g, data.get("channel"))
        title = str(data.get("title", "")).strip()[:200]
        text = str(data.get("text", "")).strip()[:4000]
        if not text and not title:
            fail(400, "Write something to send.")
        if data.get("embed", True):
            await act(ch.send(embed=embed(title or None, text or None, footer=str(data.get("footer", ""))[:200] or None,
                                          timestamp=bool(data.get("timestamp")))), "send")
        else:
            await act(ch.send("\n".join(x for x in (f"**{title}**" if title else "", text) if x)), "send")
        await audit(npub, "sent announcement", f"#{ch.name}: {title or text[:60]}", g)
        return {"ok": True, "message": f"Sent to #{ch.name}."}

    # -- audit log -----------------------------------------------------------------------------------

    # -- dashboard access by role (the community's owner and bot owners) -------------------------------

    def configurable(gid: str, npub: str):
        g = community(gid, npub)
        if not access.can_configure(g, npub):
            fail(403, "Only the community's owner and bot owners can change who has access.")
        return g

    @app.get("/api/c/{gid}/access")
    async def access_get(gid: str, npub: str = Depends(current)):
        g = configurable(gid, npub)
        rules = access.rules.get(str(g.id)) or access.clean_rules({})
        roles = [{"id": str(r.id), "name": r.name, "color": role_hex(r)}
                 for r in getattr(g, "roles", []) if not (getattr(r, "is_default", lambda: False)())]
        names = {r["id"]: r["name"] for r in roles}
        return {"areas": [{"id": a, "label": label, "help": help_} for a, label, help_ in AREAS],
                "presets": PRESETS, "levels": list(LEVELS), "admins": rules["admins"],
                "rules": [r | {"name": names.get(r["role_id"], r["name"]), "missing": r["role_id"] not in names}
                          for r in rules["roles"]], "roles": roles, "owner": who(g, str(g.owner_id))}

    @app.put("/api/c/{gid}/access")
    async def access_put(gid: str, request: Request, npub: str = Depends(current)):
        g = configurable(gid, npub)
        data = await body(request)
        known = {str(r.id): r.name for r in getattr(g, "roles", [])}
        roles, seen = [], set()
        for r in data.get("rules", []) if isinstance(data.get("rules"), list) else []:
            rid = str((r or {}).get("role_id", ""))
            if rid not in known:
                fail(400, "One of those roles isn't in this community any more. Reload the page.")
            if rid in seen:
                fail(400, f"{known[rid]} is listed twice.")
            seen.add(rid)
            roles.append({"role_id": rid, "name": known[rid], "areas": clean_levels(r.get("areas"))})
        rules = {"admins": clean_levels(data.get("admins", "full")), "roles": roles}
        await store.set_access_rules(str(g.id), rules, npub)
        access.rules[str(g.id)] = access.clean_rules(rules)
        await audit(npub, "changed dashboard access",
                    f"admins: {len(rules['admins'])} areas; " + ", ".join(f"{r['name']}: {len(r['areas'])} areas"
                                                                        for r in roles)[:400], g)
        return {"ok": True, "message": "Saved. It applies straight away, even to people already signed in."}

    @app.get("/api/c/{gid}/audit")
    async def audit_log(gid: str, npub: str = Depends(current)):
        g = community(gid, npub)
        rows = await store.audit_log(gid, 200)
        return {"entries": [{"at": r["at"], "who": who(g, r["npub"]), "action": r["action"], "detail": r["detail"]}
                            for r in rows]}

    # -- webhooks (owners) ---------------------------------------------------------------------------

    def hooks_cog():
        return cog("Webhooks")

    @app.get("/api/webhooks")
    async def webhooks(npub: str = Depends(owner)):
        w = bot.get_cog("Webhooks")
        return {"enabled": w is not None, "hooks": w.status() if w else [],
                "events": ["mod", "joins", "leaves", "levels", "tickets", "giveaways", "games", "onboarding", "events"],
                "server": {k: cfg.get(f"webhooks.server.{k}") for k in ("enabled", "base_url")},
                "overridden": "webhooks.hooks" in cfg.overrides}

    @app.put("/api/webhooks")
    async def webhooks_save(request: Request, npub: str = Depends(owner)):
        data = await body(request)
        hooks = data.get("hooks")
        if not isinstance(hooks, list):
            fail(400, "Send a list of hooks.")
        clean = []
        for h in hooks:
            if not isinstance(h, dict):
                fail(400, "Each hook needs a name and a channel.")
            item = {"name": str(h.get("name", "")).strip(), "channel": str(h.get("channel", "")).strip(),
                    "events": [str(e) for e in h.get("events", []) if isinstance(e, str)],
                    "notify": [str(n) for n in h.get("notify", ["owners"]) if str(n).strip()] or ["owners"]}
            if str(h.get("community", "")).strip():
                item["community"] = str(h["community"]).strip()
            clean.append(item)
        await save_overrides({"webhooks.hooks": clean}, npub)
        report = await hooks_cog().sync()
        await audit(npub, "saved webhooks", f"{len(clean)} hook(s)")
        return {"ok": True, "message": "Saved.", "report": report}

    @app.post("/api/webhooks/sync")
    async def webhooks_sync(npub: str = Depends(owner)):
        try:
            cfg.reload()
        except ConfigError as exc:
            fail(400, str(exc))
        report = await hooks_cog().sync()
        await audit(npub, "synced webhooks")
        return {"ok": True, "report": report}

    @app.post("/api/webhooks/{name}/rotate")
    async def webhooks_rotate(name: str, npub: str = Depends(owner)):
        w = hooks_cog()
        if name not in w._resolved:
            fail(404, "No such hook, or its channel was not found.")
        url = await act(w.rotate_url(name), "make a new URL")
        await audit(npub, "rotated webhook", name)
        return {"ok": True, "url": url, "message": "New URL made. The old one stopped working. It is shown only now."}

    @app.post("/api/webhooks/{name}/test")
    async def webhooks_test(name: str, npub: str = Depends(owner)):
        w = hooks_cog()
        t = w._resolved.get(name) or fail(404, "No such hook.")
        await act(t[1].send(embed=embed("Vectiq webhook test", f"Hook **{name}** is wired up.")), "send")
        return {"ok": True, "message": f"Test posted in #{t[1].name}."}

    # -- settings (owners edit, everyone signed in can read) -------------------------------------------

    async def save_overrides(changes: dict[str, Any], npub: str) -> None:
        merged = dict(cfg.overrides)
        for path, value in changes.items():
            if value is None or (path in schema.FIELDS and value == cfg.from_file(path)):
                merged.pop(path, None)        # same as config.yaml: no need to keep an override
            else:
                merged[path] = value
        try:
            cfg.apply_overrides(merged)
        except ConfigError as exc:
            fail(400, str(exc))
        for path in changes:
            if path in merged:
                await store.set_override(path, merged[path], npub)
            else:
                await store.clear_override(path)
        if "prefix" in changes:
            bot.command_prefix = cfg.prefix
        apply_soon()

    def apply_soon() -> None:
        """Switch modules on/off and tell them about new settings, after this response has been sent
        (the dashboard itself may be one of the modules switched off)."""
        if hasattr(bot, "apply_settings"):
            async def later():
                await asyncio.sleep(0.2)
                await bot.apply_settings()
            asyncio.get_running_loop().create_task(later())

    def module_note(before: dict[str, bool]) -> str:
        on = [modules.BY_NAME[m].label for m in modules.NAMES if cfg.enabled(m) and not before.get(m)]
        off = [modules.BY_NAME[m].label for m in modules.NAMES if not cfg.enabled(m) and before.get(m)]
        missing = [f"{modules.BY_NAME[m].label} ({modules.BY_NAME[m].install_hint()})" for m in modules.NAMES
                   if cfg.enabled(m) and modules.BY_NAME[m].missing()]
        return ((f" Switching on: {', '.join(on)}." if on else "") + (f" Switching off: {', '.join(off)}." if off else "")
                + (f" Not installed: {', '.join(missing)}." if missing else ""))

    @app.get("/api/settings")
    async def settings(npub: str = Depends(current)):
        groups = []
        for grp in schema.GROUPS:
            groups.append({"id": grp["id"], "title": grp["title"], "fields": [
                f | {"value": cfg.get(f["path"]), "file_value": cfg.from_file(f["path"]),
                     "overridden": f["path"] in cfg.overrides} for f in grp["fields"]]})
        return {"editable": access.is_owner(npub), "groups": groups, "config_path": str(cfg.path or "config.yaml"),
                "wizard": schema.WIZARD, "wizard_when": schema.WIZARD_WHEN, "option_help": schema.OPTION_HELP,
                "wizard_ask": schema.WIZARD_ASK, "wizard_text": {"hello": schema.WIZARD_HELLO,
                                                                "ready": schema.WIZARD_READY, "done": schema.WIZARD_DONE}}

    @app.put("/api/settings")
    async def settings_save(request: Request, npub: str = Depends(owner)):
        data = await body(request)
        changes = data.get("changes")
        if not isinstance(changes, dict) or not changes:
            fail(400, "Nothing to save.")
        try:
            coerced = {path: schema.coerce(path, value) for path, value in changes.items()}
        except schema.FieldError as exc:
            fail(400, str(exc))
        if "owners" in coerced and cfg.owners and npub.lower() not in [o.lower() for o in coerced["owners"]]:
            fail(400, "You can't remove yourself from the owners here; edit config.yaml for that.")
        for path, value in list(coerced.items()):       # switching a module on swaps out its rivals
            if path.startswith("modules.") and value is True:
                for rival in modules.same_slot(path.split(".", 1)[1]):
                    coerced.setdefault(f"modules.{rival.name}", False)
        before = {p: cfg.get(p) for p in coerced}
        if data.get("checkpoint") and getattr(bot, "restore_points", None):
            await bot.restore_points.create(str(data["checkpoint"])[:120], "automatic")
        was_on = {m: cfg.enabled(m) for m in modules.NAMES}
        await save_overrides(coerced, npub)
        restart = sorted({schema.FIELDS[p]["label"] for p in coerced if schema.FIELDS[p]["restart"]
                          and before[p] != coerced[p]})
        await audit(npub, "changed settings", ", ".join(sorted(coerced))[:480])
        return {"ok": True, "restart": restart,
                "message": "Saved." + module_note(was_on)
                + (f" Restart the bot to apply: {', '.join(restart)}." if restart else "")}

    from .library_routes import mount as mount_library

    mount_library(app, bot=bot, owner=owner, body=body, audit=audit)

    @app.delete("/api/settings/{path}")
    async def settings_reset(path: str, npub: str = Depends(owner)):
        if path not in cfg.overrides:
            fail(404, "That setting already comes from config.yaml.")
        await save_overrides({path: None}, npub)
        await audit(npub, "reset setting", path)
        return {"ok": True, "message": "Back to the config.yaml value."}

    @app.get("/api/settings/export")
    async def settings_export(npub: str = Depends(owner)):
        from ..config_io import export_yaml

        await audit(npub, "exported settings", "")
        return PlainTextResponse(export_yaml(cfg), headers={"Content-Disposition": "attachment; filename=vectiq-config.yaml"})

    @app.post("/api/settings/import")
    async def settings_import(request: Request, npub: str = Depends(owner)):
        """Preview (apply: false) or apply settings from an exported YAML file."""
        from ..config_io import ImportError_, parse, plan

        data = await body(request)
        try:
            imported = parse(str(data.get("yaml", "")))
        except ImportError_ as exc:
            fail(400, str(exc))

        def coerce(path, value):
            return schema.coerce(path, value)
        p = plan(cfg, imported, editable=schema.FIELDS, coerce=coerce)
        preview = {"changes": [{"path": k, "label": schema.FIELDS[k]["label"], "from": cfg.get(k), "to": v,
                                "restart": schema.FIELDS[k]["restart"]} for k, v in p.changes.items()],
                   "unchanged": p.unchanged, "skipped": p.skipped, "errors": p.errors}
        if not data.get("apply"):
            return preview
        if p.errors:
            fail(400, "Fix these first: " + "; ".join(p.errors))
        if not p.changes:
            return preview | {"ok": True, "message": "Nothing to change."}
        if "owners" in p.changes and cfg.owners and npub.lower() not in [o.lower() for o in p.changes["owners"]]:
            fail(400, "That file would remove you from the owners. Edit config.yaml for that.")
        if getattr(bot, "restore_points", None):
            await bot.restore_points.create("Before importing settings", "automatic")
        was_on = {m: cfg.enabled(m) for m in modules.NAMES}
        await save_overrides(p.changes, npub)
        await audit(npub, "imported settings", ", ".join(sorted(p.changes))[:480])
        restart = sorted({schema.FIELDS[k]["label"] for k in p.changes if schema.FIELDS[k]["restart"]})
        return preview | {"ok": True, "message": f"Imported {len(p.changes)} setting(s)." + module_note(was_on)
                          + (f" Restart the bot to apply: {', '.join(restart)}." if restart else "")}

    # -- restore points (owners) ---------------------------------------------------------------

    def points():
        rp = getattr(bot, "restore_points", None)
        if rp is None:
            fail(503, "Restore points aren't running.")
        return rp

    @app.get("/api/restore-points")
    async def restore_points(npub: str = Depends(owner)):
        rp = points()
        return {"points": [p.as_dict() for p in rp.list()], "dir": str(rp.dir),
                "every_hours": cfg.get("backup.every_hours"), "keep_automatic": cfg.get("backup.keep_automatic"),
                "keep_manual": cfg.get("backup.keep_manual")}

    @app.post("/api/restore-points")
    async def restore_point_create(request: Request, npub: str = Depends(owner)):
        data = await body(request)
        label = str(data.get("label", "")).strip()[:200] or "Made on the dashboard"
        p = await points().create(label, "manual")
        await audit(npub, "made a restore point", label)
        return {"ok": True, "message": f"Made a restore point: {label}.", "point": p.as_dict()}

    @app.post("/api/restore-points/{pid}/rollback")
    async def restore_point_rollback(pid: str, npub: str = Depends(owner)):
        rp = points()
        p = rp.get(pid)
        if p is None or p.id != pid:
            fail(404, "That restore point is gone.")
        try:
            r = await rp.rollback(p)
        except ValueError as exc:
            fail(400, f"Can't roll back: {exc}")
        await audit(npub, "rolled back", f"{p.when} {p.label}")
        bot.command_prefix = cfg.prefix
        apply_soon()
        return {"ok": True, "result": r, "message": f"Rolled back to {p.when}."
                + (" Features that were switched on or off there are being switched back." if r["restart"] else "")}

    @app.delete("/api/restore-points/{pid}")
    async def restore_point_delete(pid: str, npub: str = Depends(owner)):
        rp = points()
        p = rp.get(pid)
        if p is None or p.id != pid:
            fail(404, "That restore point is gone.")
        rp.delete(p)
        await audit(npub, "deleted a restore point", f"{p.when} {p.label}")
        return {"ok": True, "message": "Deleted."}

    @app.get("/api/restore-points/{pid}/download")
    async def restore_point_download(pid: str, npub: str = Depends(owner)):
        rp = points()
        p = rp.get(pid)
        if p is None or p.id != pid:
            fail(404, "That restore point is gone.")
        await audit(npub, "downloaded a restore point", p.id)
        return FileResponse(rp.path(p), media_type="application/zip", filename=f"{p.id}.zip")

    @app.get("/api/health", include_in_schema=False)
    async def health():
        return {"ok": True, "ready": bot.is_ready() if hasattr(bot, "is_ready") else True}

    return app


def _safe(fn: Any) -> bool:
    try:
        return bool(fn()) if callable(fn) else bool(fn)
    except Exception:  # noqa: BLE001
        return False


def _int(value: Any, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        fail(400, f"{label} must be a whole number.")

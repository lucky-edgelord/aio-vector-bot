"""The CAPTCHA verification page (``verification.mode: captcha``).

Served by the dashboard when it's on, or by a small server of its own when it isn't.
The flow is GateBot's (https://gitworkshop.dev/henk.tech/Gatebot, MIT): a personal
one-time link, an optional age, a CAPTCHA, and a device check.
"""


import html
import json
import secrets
from pathlib import Path
from urllib.parse import urlparse

DEVICE_COOKIE = "vq_device"
STATIC = Path(__file__).parent / "static" / "verify"

# Extra hosts each provider loads frames and assets from.
EXTRA = {"www.google.com": "https://www.google.com https://www.gstatic.com",
         "www.recaptcha.net": "https://www.recaptcha.net https://www.gstatic.com",
         "hcaptcha.com": "https://*.hcaptcha.com", "js.hcaptcha.com": "https://*.hcaptcha.com"}

STYLE = """
:root{color-scheme:light dark;--ink:#1d2330;--soft:#5b6476;--bg:#f3f5f8;--card:#fff;--line:#d9dee7;--go:#3b5bdb;--good:#2b8a3e;--bad:#c92a2a}
@media (prefers-color-scheme:dark){:root{--ink:#e8ebf1;--soft:#9aa3b5;--bg:#12151c;--card:#1b2029;--line:#2c3340;--go:#748ffc;--good:#69db7c;--bad:#ff8787}}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);
font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;padding:24px}
main{width:min(420px,100%);background:var(--card);border:1px solid var(--line);border-radius:14px;padding:28px}
h1{font-size:1.35rem;margin:0 0 4px}p{margin:0 0 18px;color:var(--soft)}label{display:block;font-weight:600;margin-bottom:6px}
input{width:100%;font:inherit;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:transparent;color:inherit;margin-bottom:18px}
#captcha{min-height:70px;margin-bottom:18px}
button{width:100%;font:inherit;font-weight:600;padding:11px;border:0;border-radius:8px;background:var(--go);color:#fff;cursor:pointer}
button:disabled{opacity:.45;cursor:default}button:focus-visible,input:focus-visible{outline:3px solid var(--go);outline-offset:2px}
.status{margin:16px 0 0;min-height:1.5em}.good{color:var(--good);font-weight:600}.bad{color:var(--bad)}
small{display:block;margin-top:18px;color:var(--soft);font-size:.82rem}
"""


def page(title: str, body: str, csp: str) -> tuple[str, dict]:
    doc = (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
           f"<meta name=viewport content='width=device-width,initial-scale=1'>"
           f"<meta name=robots content=noindex><title>{html.escape(title)}</title><style>{STYLE}</style></head>"
           f"<body><main>{body}</main></body></html>")
    return doc, {"Content-Security-Policy": csp, "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def csp_for(script_url: str) -> str:
    host = urlparse(script_url).netloc
    origin = f"https://{host}" if host else ""
    extra = EXTRA.get(host, "")
    allowed = f"{origin} {extra}".strip()
    return (f"default-src 'self'; script-src 'self' {allowed}; frame-src {allowed}; connect-src 'self' {allowed}; "
            f"style-src 'self' 'unsafe-inline' {allowed}; img-src 'self' data: {allowed}; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


def add_verify_routes(app, bot) -> None:
    from fastapi import Request
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

    def cog():
        return bot.get_cog("Verification")

    def settings():
        return bot.config.get("verification.captcha", {}) or {}

    def secure() -> bool:
        c = cog()
        return bool(c and c.public_url().startswith("https://"))

    @app.get("/verify-assets/verify.js", include_in_schema=False)
    async def verify_js():
        return FileResponse(STATIC / "verify.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    @app.get("/verify/{token}", include_in_schema=False)
    async def show(token: str, request: Request):
        c, s = cog(), settings()
        csp = csp_for(str(s.get("script_url", "")))
        if c is None or c.mode != "captcha":
            doc, h = page("Verification", "<h1>Verification is off</h1><p>This community doesn't use web verification.</p>", csp)
            return HTMLResponse(doc, 404, headers=h)
        minutes = int(c.v("link_minutes", 10))
        link = await bot.stores.gate.link(token, minutes)
        if link is None or link["used"]:
            what = "already been used" if link is not None else "expired"
            doc, h = page("Link not valid", f"<h1>This link has {what}</h1><p>Type <b>!verify</b> in the community "
                                            "to get a new one by DM.</p>", csp)
            return HTMLResponse(doc, 404 if link is None else 400, headers=h)
        guild = bot.get_guild(link["guild_id"])
        name = html.escape(c.scope(guild).name if guild else "the community")
        min_age = int(c.v("min_age", 0) or 0)
        age = ""
        if c.needs_age():
            hint = f"You must be at least {min_age} to join." if min_age else "Used only to offer the adults-only role."
            age = (f"<label for=age>Your age</label><input id=age name=age type=number inputmode=numeric min=1 max=120 "
                   f"required aria-describedby=agehint><p id=agehint>{hint}</p>")
        privacy = (" To stop one person verifying many accounts, a scrambled marker of this device is kept for "
                   f"{int(c.v('device_check_days', 30))} days. It isn't linked to your account.") \
            if c.v("device_check", True) else ""
        conf = html.escape(json.dumps({"siteKey": s.get("site_key", ""), "scriptUrl": s.get("script_url", "")}))
        body = (f"<div id=verify data-config=\"{conf}\"><h1>Verify for {name}</h1>"
                "<p>Complete the check below to start talking. No sign-in, key or download is needed.</p>"
                f"<form id=form>{age}<div id=captcha></div><button id=go type=submit disabled>Verify</button></form>"
                "<p id=status class=status role=status aria-live=polite></p>"
                f"<small>{html.escape(str(s.get('provider', 'CAPTCHA')))} checks you're human.{privacy}</small></div>"
                "<script src=/verify-assets/verify.js></script>")
        doc, h = page(f"Verify for {name}", body, csp)
        resp = HTMLResponse(doc, headers=h)
        device = request.cookies.get(DEVICE_COOKIE, "")
        if not (len(device) == 32 and all(ch in "0123456789abcdef" for ch in device)):
            device = secrets.token_hex(16)
        resp.set_cookie(DEVICE_COOKIE, device, max_age=400 * 86400, httponly=True, samesite="lax",
                        secure=secure(), path="/verify")
        return resp

    @app.post("/verify/{token}", include_in_schema=False)
    async def submit(token: str, request: Request):
        from ..stores.gate import canonical_fingerprint

        c = cog()
        if c is None or c.mode != "captcha":
            return JSONResponse({"message": "Verification is off."}, 404)
        if "application/json" not in request.headers.get("content-type", ""):
            return JSONResponse({"message": "Send JSON."}, 415)
        try:
            data = await request.json()
        except ValueError:
            return JSONResponse({"message": "Send JSON."}, 400)
        fp = canonical_fingerprint(data.get("fingerprint", ""))
        if fp is None:
            return JSONResponse({"message": "Verification couldn't finish. Reload the page and try again."}, 400)
        age = data.get("age")
        if age is not None:
            if not isinstance(age, int) or not 1 <= age <= 120:
                return JSONResponse({"message": "Enter your age as a number from 1 to 120."}, 400)
        device = request.cookies.get(DEVICE_COOKIE)
        if device and not (len(device) == 32 and all(ch in "0123456789abcdef" for ch in device)):
            device = None
        ip = request.client.host if request.client else None
        code, message = await c.finish(token, captcha=str(data.get("captcha", ""))[:4096], age=age,
                                       ip=ip, cookie=device, fingerprint=fp)
        return JSONResponse({"message": message}, code, headers={"Cache-Control": "no-store"})

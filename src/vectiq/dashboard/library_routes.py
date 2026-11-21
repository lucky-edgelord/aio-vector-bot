"""The Marketplace page's API: JSON modules to browse, check, install, update, remove and export. Owners only, since a
module changes what the bot does in every community."""

from __future__ import annotations

import functools
from collections.abc import Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response

from ..jsonmods import fmt
from ..jsonmods.library import LibraryError
from ..jsonmods.manager import JsonModules
from ..jsonmods.market import MarketError


def fail(status: int, message: str):
    raise HTTPException(status_code=status, detail=message)


def mount(app: FastAPI, *, bot, owner: Callable, body: Callable, audit: Callable) -> JsonModules:
    jm = JsonModules(bot)

    def plain_errors(fn):
        @functools.wraps(fn)                     # keeps the signature, so FastAPI still sees the parameters
        async def run(*a, **kw):
            try:
                return await fn(*a, **kw)
            except (LibraryError, MarketError) as exc:
                fail(400, str(exc))
        return run

    @app.get("/api/library")
    async def library(npub: str = Depends(owner)):
        return {"installed": jm.installed(), "exportable": jm.exportable(), "allow_code": jm.allow_code,
                "repo": bot.config.get("marketplace.repo"), "branch": bot.config.get("marketplace.branch"),
                "template": fmt.dumps(fmt.template()), "prompt": fmt.PROMPT}

    @app.get("/api/library/browse")
    async def browse(fresh: bool = False, npub: str = Depends(owner)):
        return await jm.browse(fresh=fresh)

    @app.post("/api/library/check")
    async def check(request: Request, npub: str = Depends(owner)):
        data = await body(request)
        return jm.check(str(data.get("text", "")))

    @app.post("/api/library/preview")
    @plain_errors
    async def preview(request: Request, npub: str = Depends(owner)):
        """A marketplace module, downloaded and checked but not installed."""
        data = await body(request)
        m, raw, _entry = await jm.marketplace().download(str(data.get("id", "")))
        return jm.check(raw)

    @app.post("/api/library/install")
    @plain_errors
    async def install(request: Request, npub: str = Depends(owner)):
        data = await body(request)
        on = data.get("on") if isinstance(data.get("on"), bool) else None
        if data.get("id"):
            done = await jm.install_from_market(str(data["id"]), on=on, by=npub)
            how = f"from {bot.config.get('marketplace.repo')}"
        elif data.get("text"):
            done = await jm.install_text(str(data["text"]), source="file " + str(data.get("filename") or "pasted")[:120],
                                         on=on, by=npub)
            how = "from a file"
        else:
            fail(400, "Choose a module first.")
        await audit(npub, "installed a module", f"{done['id']} {done['release']} {how}")
        return {"ok": True, **done}

    @app.delete("/api/library/{mid}")
    @plain_errors
    async def remove(mid: str, npub: str = Depends(owner)):
        message = await jm.remove(mid, by=npub)
        await audit(npub, "removed a module", mid)
        return {"ok": True, "message": message}

    @app.get("/api/library/export/{name}")
    @plain_errors
    async def export(name: str, settings: bool = False, npub: str = Depends(owner)):
        m = jm.export(name, with_settings=settings)
        return Response(fmt.dumps(m), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{m["id"]}{fmt.SUFFIX}"'})

    return jm

"""DevelopAid 2.0 account projects: existing Telegram session + existing project store."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse

_ROOT = Path(__file__).resolve().parent
_FRONTEND = _ROOT / "frontend_v2"
_REVALIDATE = {"Cache-Control": "no-cache, must-revalidate"}


def _drop_v2_index(app: FastAPI) -> None:
    app.router.routes[:] = [
        route for route in app.router.routes
        if not (
            getattr(route, "path", None) in {"/v2", "/v2/"}
            and "GET" in set(getattr(route, "methods", ()) or ())
        )
    ]


def install(app: FastAPI) -> None:
    """Load the account bridge before app.js without touching the calculation API."""

    @app.get("/v2/assets/account-projects.js", include_in_schema=False)
    async def account_projects_script() -> FileResponse:
        return FileResponse(
            _FRONTEND / "account_projects.js",
            media_type="application/javascript",
            headers=_REVALIDATE,
        )

    # developaid_v2_upgrade installed the final /v2 page immediately before us.
    # Replace only that page so script order is deterministic:
    # auth/photo hook -> saved-project hook -> stock v2 application.
    _drop_v2_index(app)

    @app.get("/v2", include_in_schema=False)
    @app.get("/v2/", include_in_schema=False)
    async def account_projects_index() -> HTMLResponse:
        source = (_FRONTEND / "index.html").read_text(encoding="utf-8")
        marker = '<script src="/v2/assets/app.js" defer></script>'
        if marker not in source:
            raise RuntimeError("В index.html /v2 не найден app.js")
        injected = (
            '<script src="/v2/assets/upgrade.js" defer></script>\n  '
            '<script src="/v2/assets/account-projects.js" defer></script>\n  '
            + marker
        )
        return HTMLResponse(source.replace(marker, injected, 1), headers=_REVALIDATE)

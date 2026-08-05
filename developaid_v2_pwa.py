"""Installable PWA shell for the isolated DevelopAid 2.0 interface.

This module does not import or modify the financial engine. It only injects
PWA metadata into the existing /v2 HTML and serves static application assets.
Calculation APIs remain network-only and are never cached by the service
worker.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse

_ROOT = Path(__file__).resolve().parent
_FRONTEND = _ROOT / "frontend_v2"

_PWA_HEAD = """
  <meta name="application-name" content="DevelopAid">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="DevelopAid">
  <link rel="manifest" href="/v2/manifest.webmanifest">
  <link rel="icon" href="/v2/assets/icon.svg" type="image/svg+xml">
  <link rel="apple-touch-icon" href="/v2/assets/icon-192.png">
  <link rel="stylesheet" href="/v2/assets/pwa.css">
  <script src="/v2/assets/pwa.js" defer></script>
""".strip()


def _inject_pwa_shell(html: str) -> str:
    """Add PWA resources idempotently without editing the current v2 page."""

    if "/v2/manifest.webmanifest" in html:
        return html
    return html.replace("</head>", f"{_PWA_HEAD}\n</head>", 1)


def install(app: FastAPI) -> None:
    """Register PWA assets and inject metadata only for /v2."""

    @app.middleware("http")
    async def developaid_v2_pwa_shell(request: Request, call_next):
        if request.method in {"GET", "HEAD"} and request.url.path in {"/v2", "/v2/"}:
            html = (_FRONTEND / "index.html").read_text(encoding="utf-8")
            return HTMLResponse(
                _inject_pwa_shell(html),
                headers={"Cache-Control": "no-cache"},
            )
        return await call_next(request)

    @app.get("/v2/manifest.webmanifest", include_in_schema=False)
    async def developaid_v2_manifest() -> FileResponse:
        return FileResponse(
            _FRONTEND / "manifest.webmanifest",
            media_type="application/manifest+json",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/v2/service-worker.js", include_in_schema=False)
    async def developaid_v2_service_worker() -> FileResponse:
        return FileResponse(
            _FRONTEND / "service-worker.js",
            media_type="application/javascript",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Service-Worker-Allowed": "/v2/",
            },
        )

    @app.get("/v2/assets/pwa.js", include_in_schema=False)
    async def developaid_v2_pwa_script() -> FileResponse:
        return FileResponse(_FRONTEND / "pwa.js", media_type="application/javascript")

    @app.get("/v2/assets/pwa.css", include_in_schema=False)
    async def developaid_v2_pwa_styles() -> FileResponse:
        return FileResponse(_FRONTEND / "pwa.css", media_type="text/css")

    @app.get("/v2/assets/icon.svg", include_in_schema=False)
    async def developaid_v2_icon() -> FileResponse:
        return FileResponse(_FRONTEND / "icon.svg", media_type="image/svg+xml")

    @app.get("/v2/assets/icon-maskable.svg", include_in_schema=False)
    async def developaid_v2_maskable_icon() -> FileResponse:
        return FileResponse(_FRONTEND / "icon-maskable.svg", media_type="image/svg+xml")

    @app.get("/v2/assets/icon-192.png", include_in_schema=False)
    async def developaid_v2_icon_192() -> FileResponse:
        return FileResponse(_FRONTEND / "icon-192.png", media_type="image/png")

    @app.get("/v2/assets/icon-512.png", include_in_schema=False)
    async def developaid_v2_icon_512() -> FileResponse:
        return FileResponse(_FRONTEND / "icon-512.png", media_type="image/png")

"""PWA assets for the DevelopAid 2.0 interface.

The module is isolated from the calculation engine.  It only exposes the
manifest, service worker, installation helper and application icons under the
/v2 scope.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

_ROOT = Path(__file__).resolve().parent
_FRONTEND = _ROOT / "frontend_v2"


def install(app: FastAPI) -> None:
    """Register PWA resources without changing existing application routes."""

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

"""Commercial beta mounted into the normal DevelopAid.ru root interface."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.responses import FileResponse

import developaid_commercial as commercial

_ROOT = Path(__file__).resolve().parent


def install(core: Any, app: Any) -> None:
    commercial.install(app)

    @app.get("/commercial-beta.js", include_in_schema=False)
    def commercial_beta_script() -> FileResponse:
        return FileResponse(
            _ROOT / "commercial_site.js",
            media_type="application/javascript",
            headers={"Cache-Control": "no-store"},
        )

    page = str(core.PAGE)
    tab_anchor = (
        '<button class="tab" data-tab="finance" '
        'onclick="openTab(\'finance\',this)">Финансирование</button>'
    )
    tab = (
        '<button class="tab" data-tab="commercial" '
        'onclick="openTab(\'commercial\',this);commercialEnsureInit()">'
        'Нежилая экономика β</button>'
    )
    if 'data-tab="commercial"' not in page:
        if tab_anchor not in page:
            raise RuntimeError("commercial beta: finance tab anchor not found")
        page = page.replace(tab_anchor, tab_anchor + tab, 1)

    if 'id="commercial" class="panel"' not in page:
        panel = (_ROOT / "commercial_site_panel.html").read_text(encoding="utf-8")
        anchor = '<div id="report" class="panel">'
        if anchor not in page:
            raise RuntimeError("commercial beta: report panel anchor not found")
        page = page.replace(anchor, panel + "\n" + anchor, 1)

    if "/commercial-beta.js" not in page:
        page = page.replace(
            "</body>",
            '<script src="/commercial-beta.js"></script></body>',
            1,
        )
    core.PAGE = page

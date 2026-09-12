"""DevelopAid 2.0 account projects and new-project entry bridges."""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

import document_intake

_ROOT = Path(__file__).resolve().parent
_FRONTEND = _ROOT / "frontend_v2"
_REVALIDATE = {"Cache-Control": "no-cache, must-revalidate"}
_NO_STORE = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
_MAX_TEASER_BYTES = 20 * 1024 * 1024
_CADASTRAL = re.compile(r"\b\d{2}:\d{2}:\d{5,8}:\d+\b")


class TeaserFallbackRequest(BaseModel):
    filename: str = ""
    content_b64: str = ""


def _drop_v2_index(app: FastAPI) -> None:
    app.router.routes[:] = [
        route for route in app.router.routes
        if not (
            getattr(route, "path", None) in {"/v2", "/v2/"}
            and "GET" in set(getattr(route, "methods", ()) or ())
        )
    ]


def _teaser_payload(raw: str) -> bytes:
    try:
        payload = base64.b64decode(str(raw or ""), validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Файл не прочитался: {exc}") from exc
    if not payload:
        raise HTTPException(400, "Пустой файл")
    if len(payload) > _MAX_TEASER_BYTES:
        raise HTTPException(413, "Тизер больше 20 МБ. Пришлите нужные страницы отдельно.")
    return payload


def _field(key: str, label: str, value: Any, unit: str, quote: str) -> dict[str, Any]:
    return {"key": key, "label": label, "value": value, "unit": unit, "quote": quote}


def _quick_teaser_intake(payload: bytes, filename: str) -> dict[str, Any]:
    """Read common broker-teaser fields without depending on the LLM provider.

    This is deliberately narrow: it only copies values that have an explicit
    label and a source line. Ambiguous obligations stay in notes for a human to
    classify. The normal /agent/document path remains primary; this parser is a
    resilience path for provider/JSON failures and therefore must never invent
    missing economics.
    """
    document = document_intake.extract_text(payload, filename)
    text = str(document.get("text") or "")
    if not text:
        raise HTTPException(422, document.get("reason") or "В документе нет читаемого текста")

    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    fields: list[dict[str, Any]] = []
    notes: list[str] = []
    seen: set[str] = set()

    def add(item: dict[str, Any]) -> None:
        key = str(item.get("key") or "")
        if key and key not in seen:
            seen.add(key)
            fields.append(item)

    for line in lines:
        cadastres = _CADASTRAL.findall(line)
        if cadastres:
            add(_field(
                "cadastral_numbers", "Кадастровые номера участков",
                ", ".join(dict.fromkeys(cadastres)), "список", line,
            ))

        area = re.search(
            r"(?i)\bПлощадь(?:\s+участка)?\s+([0-9]+(?:[.,][0-9]+)?)\s*(?:га|гектар(?:а|ов)?)\b",
            line,
        )
        if area:
            add(_field("site_area_ha", "Площадь участка", area.group(1), "га", line))

        price = re.search(
            r"(?i)\bСтоимость\s+([0-9][0-9\s\u00a0\u202f]*)\s*(₽|руб(?:\.|лей|ля)?)",
            line,
        )
        if price:
            add(_field(
                "purchase_price_mln", "Цена сделки / цена входа",
                " ".join(price.group(1).split()), price.group(2), line,
            ))

        gns = re.search(
            r"(?i)\bСПП\s+в\s+ГНС\b.*?([0-9][0-9\s\u00a0\u202f]*)\s*м\s*[²2]",
            line,
        )
        if gns:
            add(_field(
                "apartments_gns_sqm", "СПП / ГНС жилой части",
                " ".join(gns.group(1).split()), "м²", line,
            ))

        if re.search(r"(?i)\bпередач[аи]\b", line) and re.search(r"\d", line):
            notes.append(
                "Обязательство не подставлено автоматически: «" + line[:240] +
                "». Нужно определить, что именно и кому передаётся."
            )

    if not fields:
        raise HTTPException(
            422,
            document.get("reason") or
            "PDF прочитан, но стандартные поля тизера (КН, площадь, стоимость, СПП/ГНС) не найдены.",
        )

    metadata = {key: value for key, value in document.items() if key != "text"}
    metadata["read_chars"] = len(text)
    metadata["total_chars"] = len(text)
    return {
        "document": metadata,
        "fields": fields,
        "questions": [],
        "not_asked": [],
        "notes": notes,
        "reason": "",
        "fallback": "local-labelled-fields",
    }


def install(app: FastAPI) -> None:
    """Load account/start bridges before app.js without touching calculation APIs."""

    @app.get("/v2/assets/account-projects.js", include_in_schema=False)
    async def account_projects_script() -> FileResponse:
        return FileResponse(
            _FRONTEND / "account_projects.js",
            media_type="application/javascript",
            headers=_REVALIDATE,
        )

    @app.get("/v2/assets/start-imports.js", include_in_schema=False)
    async def start_imports_script() -> FileResponse:
        return FileResponse(
            _FRONTEND / "start_imports.js",
            media_type="application/javascript",
            headers=_REVALIDATE,
        )

    @app.get("/v2/assets/entry-layout.js", include_in_schema=False)
    async def entry_layout_script() -> FileResponse:
        return FileResponse(
            _FRONTEND / "entry_layout.js",
            media_type="application/javascript",
            headers=_REVALIDATE,
        )

    @app.get("/v2/assets/teaser-fallback.js", include_in_schema=False)
    async def teaser_fallback_script() -> FileResponse:
        return FileResponse(
            _FRONTEND / "teaser_fallback.js",
            media_type="application/javascript",
            headers=_REVALIDATE,
        )

    @app.post("/api/v2/teaser-fallback", include_in_schema=False)
    async def teaser_fallback(req: TeaserFallbackRequest) -> JSONResponse:
        return JSONResponse(
            _quick_teaser_intake(_teaser_payload(req.content_b64), req.filename),
            headers=_NO_STORE,
        )

    # developaid_v2_upgrade installed the final /v2 page immediately before us.
    # Replace only that page so script order is deterministic:
    # auth/photo hook -> teaser resilience -> saved-project hook -> start/import
    # -> layout hook -> stock v2 application.
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
            '<script src="/v2/assets/teaser-fallback.js" defer></script>\n  '
            '<script src="/v2/assets/account-projects.js" defer></script>\n  '
            '<script src="/v2/assets/start-imports.js" defer></script>\n  '
            '<script src="/v2/assets/entry-layout.js" defer></script>\n  '
            + marker
        )
        return HTMLResponse(source.replace(marker, injected, 1), headers=_REVALIDATE)

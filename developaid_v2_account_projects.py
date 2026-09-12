"""DevelopAid 2.0 account projects and new-project entry bridges."""

from __future__ import annotations

import base64
import copy
import math
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


class TepSyncRequest(BaseModel):
    inputs: dict[str, Any] = {}
    tep: dict[str, dict[str, Any]] = {}
    row_key: str = ""
    field_key: str = ""
    value: float | int | None = None


def _core() -> Any:
    # `main` is the wrapper that owns the single live `main_legacy` module.
    # Importing main_legacy directly here would create a second set of globals.
    import main as wrapper

    return wrapper.core


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


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _round_area(value: float) -> float:
    return round(float(value or 0.0), 1)


def _tep_ratio(core: Any, inputs: dict[str, Any], key: str) -> dict[str, Any] | None:
    """The same ratio table as the main page, including a user's override."""
    custom, _warnings = core.tep_ratios_applied(inputs.get("tep_ratios_custom"))
    return copy.deepcopy(custom.get(key) or core.TEP_RATIOS.get(key))


def _apartments_units(core: Any, inputs: dict[str, Any], saleable: float) -> tuple[int, str]:
    # A GlavAPU file brings a city-provided apartment count. Replacing it with
    # our market divisor would create a second answer to the same question.
    if inputs.get("_glavapu_import"):
        return 0, ""
    source = "mo" if str(inputs.get("vri_region") or "") == "mo" else "manual"
    sqm, basis = core.average_flat_sqm(source)
    return (int(math.ceil(saleable / sqm)) if saleable > 0 and sqm > 0 else 0), basis


def _sync_tep(core: Any, req: TepSyncRequest) -> dict[str, Any]:
    """One edited TEP cell -> the dependent cells, using live engine rules.

    The stock web page already treats GNS / total / saleable as one linked row.
    V2 used to keep the other cells from the previous project, which is how a
    teaser with 31,000 m² GNS ended up next to 117,647 m² total and 80,000 m²
    saleable. This endpoint makes V2 use the same source constants instead of
    hard-coding another set of ratios in JavaScript.
    """
    inputs = copy.deepcopy(req.inputs or {})
    tep = copy.deepcopy(req.tep or {})
    key = str(req.row_key or "")
    field = str(req.field_key or "")
    if key not in core.TEP_DEFAULT:
        raise HTTPException(400, "Неизвестная строка ТЭП")

    row = {**copy.deepcopy(core.TEP_DEFAULT.get(key) or {}), **copy.deepcopy(tep.get(key) or {})}
    old_value = _number(row.get(field))
    value = _number(req.value)
    row[field] = value
    derived: dict[str, str] = {}
    ratio = _tep_ratio(core, inputs, key)

    if ratio and field in {"gns", "total_area", "saleable"}:
        total_of_gns = _number(ratio.get("total_of_gns"))
        saleable_of_gns = _number(ratio.get("saleable_of_gns"))
        if value <= 0 or total_of_gns <= 0 or saleable_of_gns <= 0:
            gns = total = saleable = 0.0
        elif field == "gns":
            gns = value
            total = gns * total_of_gns
            saleable = gns * saleable_of_gns
        elif field == "total_area":
            total = value
            gns = total / total_of_gns
            saleable = gns * saleable_of_gns
        else:
            saleable = value
            gns = saleable / saleable_of_gns
            total = gns * total_of_gns
        row["gns"] = _round_area(gns)
        row["total_area"] = _round_area(total)
        row["saleable"] = _round_area(saleable)
        row["useful"] = row["saleable"]
        derived.update({
            "gns": "связано с площадями строки",
            "total_area": f"{total_of_gns * 100:g}% ГНС",
            "saleable": f"{saleable_of_gns * 100:g}% ГНС",
            "useful": "равна продаваемой",
        })
        if key == "apartments":
            units, basis = _apartments_units(core, inputs, row["saleable"])
            if basis:
                row["units"] = units
                derived["units"] = basis

    elif ratio and field == "transfer":
        delta = value - old_value
        row["saleable"] = _round_area(max(0.0, _number(row.get("saleable")) - delta))
        row["useful"] = row["saleable"]
        derived["saleable"] = "уменьшена на передаваемую площадь"
        derived["useful"] = "равна продаваемой"
        if key == "apartments":
            units, basis = _apartments_units(core, inputs, row["saleable"])
            if basis:
                row["units"] = units
                derived["units"] = basis

    elif key == "underground_parking" and field in {"units", "gns", "total_area"}:
        per = _number(inputs.get("underground_area_per_space_sqm")) or 35.0
        if field == "units":
            area = value * per
            row["gns"] = _round_area(area)
            row["total_area"] = row["gns"]
            derived["gns"] = f"{per:g} м² на машино-место"
            derived["total_area"] = "равна ГНС"
        else:
            area = value
            row["gns"] = _round_area(area)
            row["total_area"] = row["gns"]
            row["units"] = int(round(area / per)) if per > 0 else 0
            derived["total_area"] = "равна ГНС"
            derived["units"] = f"ГНС / {per:g} м²"
        row["useful"] = 0
        row["saleable"] = 0
        row["transfer"] = 0

    elif key == "above_parking" and field in {"units", "gns", "total_area"}:
        per = _number(inputs.get("above_parking_area_per_space_sqm")) or 25.0
        if field == "units":
            area = value * per
            row["gns"] = _round_area(area)
            row["total_area"] = row["gns"]
            derived["gns"] = f"{per:g} м² на машино-место"
            derived["total_area"] = "равна ГНС"
        else:
            area = value
            row["gns"] = _round_area(area)
            row["total_area"] = row["gns"]
            row["units"] = int(round(area / per)) if per > 0 else 0
            derived["total_area"] = "равна ГНС"
            derived["units"] = f"ГНС / {per:g} м²"

    tep[key] = row
    return {
        "tep": tep,
        "inputs": inputs,
        "row_key": key,
        "changed_field": field,
        "derived": derived,
        "ratio_source": (ratio or {}).get("source") if ratio else "",
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

    @app.get("/v2/assets/tep-sync.js", include_in_schema=False)
    async def tep_sync_script() -> FileResponse:
        return FileResponse(
            _FRONTEND / "tep_sync.js",
            media_type="application/javascript",
            headers=_REVALIDATE,
        )

    @app.post("/api/v2/teaser-fallback", include_in_schema=False)
    async def teaser_fallback(req: TeaserFallbackRequest) -> JSONResponse:
        return JSONResponse(
            _quick_teaser_intake(_teaser_payload(req.content_b64), req.filename),
            headers=_NO_STORE,
        )

    @app.post("/api/v2/tep-sync", include_in_schema=False)
    async def tep_sync(req: TepSyncRequest) -> JSONResponse:
        return JSONResponse(_sync_tep(_core(), req), headers=_NO_STORE)

    # developaid_v2_upgrade installed the final /v2 page immediately before us.
    # Replace only that page so script order is deterministic:
    # auth/photo hook -> teaser resilience -> saved-project hook -> start/import
    # -> layout hook -> stock v2 application -> dependent TEP synchronizer.
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
            + '\n  <script src="/v2/assets/tep-sync.js" defer></script>'
        )
        return HTMLResponse(source.replace(marker, injected, 1), headers=_REVALIDATE)

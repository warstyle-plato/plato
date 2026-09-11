"""DevelopAid 2.0: neutral start, Telegram UI hook and TEP photo OCR."""

from __future__ import annotations

import base64
import io
import re
import shutil
import subprocess
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

import developaid_v2_demo as demo
import developaid_v2_form as form
import developaid_v2_result as project_result

_ROOT = Path(__file__).resolve().parent
_FRONTEND = _ROOT / "frontend_v2"
_NO_STORE = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
             "Pragma": "no-cache"}
_REVALIDATE = {"Cache-Control": "no-cache, must-revalidate"}
_MAX_IMAGE_BYTES = 12 * 1024 * 1024
_OCR_TIMEOUT_SECONDS = 75
_SIMPLE_NUMBER = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
_CELL_NUMBER = re.compile(
    r"[-+]?(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,]\d+)?"
)


class TepPhotoRequest(BaseModel):
    image_base64: str
    content_type: str = ""
    filename: str = ""


def _new_project(core: Any, sensitivity: bool = True) -> dict[str, Any]:
    """Default engine inputs, never a demo preset."""
    defaults = form.form_description(core)["defaults"]
    result = project_result.build_project_result(
        core,
        inputs=defaults["inputs"],
        tep=defaults["tep"],
        rates=[],
        phasing=defaults["phasing"],
        project_name="Новый проект",
        region="",
        cadastral_numbers=[],
        source_label="Новый проект · умолчания движка",
        scenario="base",
        sensitivity=bool(sensitivity),
    )
    result.setdefault("project", {})["slug"] = "new"
    result["project"]["demo_inputs"] = False
    return result


def _decode_image(raw: str) -> bytes:
    value = str(raw or "").strip()
    if value.lower().startswith("data:") and "," in value:
        value = value.split(",", 1)[1]
    try:
        payload = base64.b64decode(value, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, "Фотография повреждена: не удалось прочитать base64.") from exc
    if not payload:
        raise HTTPException(400, "Фотография пустая.")
    if len(payload) > _MAX_IMAGE_BYTES:
        raise HTTPException(413, "Фотография больше 12 МБ. Снимите таблицу ближе.")
    return payload


def _prepare_image(payload: bytes) -> bytes:
    """Respect iPhone EXIF orientation and feed Tesseract a contrast PNG."""
    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(payload)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            if max(image.size) > 3200:
                image.thumbnail((3200, 3200))
            image = ImageOps.autocontrast(ImageOps.grayscale(image))
            out = io.BytesIO()
            image.save(out, format="PNG", optimize=True)
            return out.getvalue()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            415,
            "Не удалось открыть фото. Снимок из камеры iPhone поддерживается; "
            "HEIC из медиатеки при необходимости сохраните как JPEG/PNG.",
        ) from exc


def _ocr_image(payload: bytes) -> str:
    if not shutil.which("tesseract"):
        raise HTTPException(503, "OCR недоступен: на сервере нет tesseract.")
    png = _prepare_image(payload)

    def run(language: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", language, "--psm", "6",
             "-c", "preserve_interword_spaces=1"],
            input=png, capture_output=True, timeout=_OCR_TIMEOUT_SECONDS, check=False,
        )

    done = run("rus+eng")
    if done.returncode:
        done = run("rus")
    if done.returncode:
        error = done.stderr.decode("utf-8", errors="replace").strip()
        raise HTTPException(503, f"OCR не прочитал фотографию: {error[:240]}")
    return done.stdout.decode("utf-8", errors="replace").strip()


def _norm(text: str) -> str:
    value = str(text or "").lower().replace("ё", "е")
    value = re.sub(r"[^0-9a-zа-я]+", " ", value)
    return " ".join(value.split())


def _label_score(label: str, line: str) -> float:
    target, source = _norm(label), _norm(line)
    if not target or not source:
        return 0.0
    if target in source:
        return 0.99
    t_words = {x for x in target.split() if not x.isdigit()}
    s_words = {x for x in source.split() if not x.isdigit()}
    overlap = len(t_words & s_words) / max(1, len(t_words))
    clipped = source[: max(len(target) + 12, len(target) * 2)]
    return max(overlap * 0.9, SequenceMatcher(None, target, clipped).ratio())


def _parse_number(raw: str) -> float | None:
    value = str(raw or "").strip().replace("\u00a0", " ").replace("\u202f", " ")
    value = value.replace("'", "")
    compact = value.replace(" ", "")
    if not compact:
        return None
    if "," in compact and "." in compact:
        decimal = "," if compact.rfind(",") > compact.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        compact = compact.replace(thousands, "").replace(decimal, ".")
    elif "," in compact:
        tail = compact.rsplit(",", 1)[1]
        compact = compact.replace(",", "." if len(tail) != 3 else "")
    elif "." in compact:
        left, right = compact.rsplit(".", 1)
        if len(right) == 3:
            compact = left + right
    try:
        return float(compact)
    except ValueError:
        return None


def _numbers(line: str, label: str) -> list[float]:
    """2+ spaces/tabs separate columns; one space may be a thousands separator."""
    cells = [cell.strip() for cell in re.split(r"\t+| {2,}", line) if cell.strip()]
    values: list[float] = []
    if len(cells) > 1:
        for cell in cells:
            matches = list(_CELL_NUMBER.finditer(cell))
            if len(matches) == 1:
                number = _parse_number(matches[0].group(0))
                if number is not None:
                    values.append(number)
    else:
        values = [
            number for number in (_parse_number(m.group(0)) for m in _SIMPLE_NUMBER.finditer(line))
            if number is not None
        ]

    label_numbers = [
        number for number in (_parse_number(m.group(0)) for m in _SIMPLE_NUMBER.finditer(label))
        if number is not None
    ]
    while label_numbers and values and abs(values[0] - label_numbers[0]) < 1e-9:
        values.pop(0)
        label_numbers.pop(0)
    return values


def _header_fields(lines: list[str], fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aliases = {
        "gns": ("гнс",),
        "total_area": ("общая площадь", "общая"),
        "useful": ("полезная", "полезн"),
        "saleable": ("продаваемая", "продаваем", "продаж"),
        "transfer": ("передается", "передаётся", "передач"),
        "units": ("количество", "кол во", "шт"),
    }
    best: list[tuple[int, dict[str, Any]]] = []
    for line in lines:
        normalized = _norm(line)
        found: list[tuple[int, dict[str, Any]]] = []
        for field in fields:
            variants = aliases.get(str(field.get("key")), (_norm(field.get("label", "")),))
            positions = [normalized.find(_norm(v)) for v in variants if _norm(v)]
            positions = [p for p in positions if p >= 0]
            if positions:
                found.append((min(positions), field))
        if len(found) > len(best):
            best = found
    return [field for _, field in sorted(best)] if len(best) >= 2 else fields


def parse_tep_text(text: str, tep_block: dict[str, Any]) -> dict[str, Any]:
    """OCR text -> suggestions. It never mutates the calculation."""
    lines = [line.rstrip() for line in str(text or "").splitlines() if line.strip()]
    rows = list(tep_block.get("rows") or [])
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        for field in row.get("fields") or []:
            key = str(field.get("key") or "")
            if key and key not in seen:
                seen.add(key)
                fields.append(field)
    order = _header_fields(lines, fields)

    best: dict[str, tuple[float, str]] = {}
    for line in lines:
        ranked = sorted(
            ((_label_score(str(row.get("label") or ""), line), row) for row in rows),
            key=lambda item: item[0], reverse=True,
        )
        if not ranked or ranked[0][0] < 0.53:
            continue
        score, row = ranked[0]
        key = str(row.get("key") or "")
        if key not in best or score > best[key][0]:
            best[key] = (score, line)

    suggestions: list[dict[str, Any]] = []
    recognized_rows = 0
    for row in rows:
        row_key = str(row.get("key") or "")
        if row_key not in best:
            continue
        score, line = best[row_key]
        values = _numbers(line, str(row.get("label") or ""))
        row_fields = {str(f.get("key")): f for f in row.get("fields") or []}
        ordered = [f for f in order if str(f.get("key")) in row_fields] or list(row.get("fields") or [])
        if not values:
            continue
        if len(values) > len(ordered):
            values = values[-len(ordered):]
        recognized_rows += 1
        for field, value in zip(ordered, values):
            suggestions.append({
                "row_key": row_key,
                "row_label": str(row.get("label") or row_key),
                "field_key": str(field.get("key") or ""),
                "field_label": str(field.get("label") or field.get("key") or ""),
                "value": value,
                "confidence": round(score, 3),
                "source_line": line,
            })
    return {
        "text": text,
        "suggestions": suggestions,
        "recognized_rows": recognized_rows,
        "total_rows": len(rows),
        "field_order": [str(f.get("key") or "") for f in order],
    }


def _drop_get_routes(app: FastAPI, paths: set[str]) -> None:
    """Replace only the GET surfaces extended by v2, without middleware.

    FastAPI forbids adding middleware after the ASGI application has started.
    Some integration tests intentionally import ``main_registry`` after a
    TestClient has already started the shared app, so route replacement is the
    late-install-safe mechanism here. The router itself supports adding and
    removing routes at that point.
    """
    app.router.routes[:] = [
        route for route in app.router.routes
        if not (
            getattr(route, "path", None) in paths
            and "GET" in set(getattr(route, "methods", ()) or ())
        )
    ]


def _promote_exact_get(app: FastAPI, exact_path: str, before_path: str) -> None:
    """Put an exact route before an earlier dynamic route that would catch it."""
    exact_index = next(
        (i for i, route in enumerate(app.router.routes)
         if getattr(route, "path", None) == exact_path
         and "GET" in set(getattr(route, "methods", ()) or ())),
        None,
    )
    before_index = next(
        (i for i, route in enumerate(app.router.routes)
         if getattr(route, "path", None) == before_path
         and "GET" in set(getattr(route, "methods", ()) or ())),
        None,
    )
    if exact_index is None or before_index is None or exact_index < before_index:
        return
    route = app.router.routes.pop(exact_index)
    before_index = next(
        i for i, candidate in enumerate(app.router.routes)
        if getattr(candidate, "path", None) == before_path
        and "GET" in set(getattr(candidate, "methods", ()) or ())
    )
    app.router.routes.insert(before_index, route)


def install(app: FastAPI, core: Any) -> None:
    @app.get("/v2/assets/upgrade.js", include_in_schema=False)
    async def upgrade_script() -> FileResponse:
        return FileResponse(_FRONTEND / "upgrade.js",
                            media_type="application/javascript", headers=_REVALIDATE)

    @app.post("/api/v2/tep-photo")
    def tep_photo(req: TepPhotoRequest) -> JSONResponse:
        try:
            text = _ocr_image(_decode_image(req.image_base64))
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(
                504, "OCR не успел прочитать снимок. Снимите таблицу ближе и без лишнего фона."
            ) from exc
        tep_block = next(
            (b for b in form.form_description(core)["blocks"] if b.get("kind") == "tep"), None
        )
        if not tep_block:
            raise HTTPException(500, "Описание блока ТЭП не найдено.")
        parsed = parse_tep_text(text, tep_block)
        parsed["filename"] = req.filename
        if not parsed["suggestions"]:
            parsed["warning"] = (
                "Текст прочитан, но строки ТЭП не сопоставились. "
                "Снимите таблицу ровнее: названия строк и цифры должны быть видны целиком."
            )
        return JSONResponse(parsed, headers=_NO_STORE)

    # The stock v2 routes were installed immediately before this extension.
    # Replace only the three GET surfaces we need; no application-wide
    # middleware is involved, so late imports in the integration suite remain
    # valid and unrelated pages are untouched.
    _drop_get_routes(app, {"/v2", "/v2/", "/api/v2/projects"})

    @app.get("/v2", include_in_schema=False)
    @app.get("/v2/", include_in_schema=False)
    async def upgraded_index() -> HTMLResponse:
        source = (_FRONTEND / "index.html").read_text(encoding="utf-8")
        marker = '<script src="/v2/assets/app.js" defer></script>'
        if marker not in source:
            raise RuntimeError("В index.html /v2 не найден app.js")
        injected = '<script src="/v2/assets/upgrade.js" defer></script>\n  ' + marker
        return HTMLResponse(source.replace(marker, injected, 1), headers=_REVALIDATE)

    @app.get("/api/v2/projects")
    def upgraded_projects() -> JSONResponse:
        catalog = [{
            "slug": "new", "name": "Новый проект", "region": "",
            "subtitle": "Умолчания движка · без демонстрационной предустановки",
            "demo": False,
        }]
        catalog.extend(demo.list_scenarios())
        return JSONResponse(catalog, headers=_NO_STORE)

    @app.get("/api/v2/projects/new")
    def upgraded_new_project(sensitivity: bool = True) -> JSONResponse:
        try:
            result = _new_project(core, sensitivity)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            locate = getattr(core, "_error_location", lambda error: str(error))
            raise HTTPException(500, str(locate(exc))[:300]) from exc
        return JSONResponse(result, headers=_NO_STORE)

    # `/api/v2/projects/{slug}` was registered by the stock module first and
    # would otherwise treat `new` as a demo slug. Exact path wins by order.
    _promote_exact_get(app, "/api/v2/projects/new", "/api/v2/projects/{slug}")

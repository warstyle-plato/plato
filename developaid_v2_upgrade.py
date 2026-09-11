"""DevelopAid 2.0: кабинет Telegram, нейтральный старт и фото-ТЭП.

Расширение ставится поверх ``developaid_v2``: расчётный движок и существующие
API не дублируются. Здесь только три вещи интерфейса: новый проект вместо
автоматической демонстрации «Мишина»; вход той же Telegram-сессией, что
использует основной сайт; OCR фотографии ТЭП с подтверждением перед подстановкой.
"""

from __future__ import annotations

import base64
import io
import re
import shutil
import subprocess
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

import developaid_v2_demo as demo
import developaid_v2_form as form
import developaid_v2_result as project_result

_ROOT = Path(__file__).resolve().parent
_FRONTEND = _ROOT / "frontend_v2"
_NO_STORE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
}
_REVALIDATE = {"Cache-Control": "no-cache, must-revalidate"}
_MAX_IMAGE_BYTES = 12 * 1024 * 1024
_OCR_TIMEOUT_SECONDS = 75
_NUMBER_RE = re.compile(r"(?<![\w])[-+]?\d(?:[\d\s\u00a0\u202f.,']*\d)?(?![\w])")


class TepPhotoRequest(BaseModel):
    image_base64: str
    content_type: str = ""
    filename: str = ""


def _new_project(core: Any, sensitivity: bool = True) -> dict[str, Any]:
    """Нейтральный старт /v2: умолчания движка, не демонстрационный preset."""
    description = form.form_description(core)
    defaults = description["defaults"]
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
    if "," in value and value.lower().startswith("data:"):
        value = value.split(",", 1)[1]
    try:
        payload = base64.b64decode(value, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Фотография повреждена: не удалось прочитать base64.") from exc
    if not payload:
        raise HTTPException(status_code=400, detail="Фотография пустая.")
    if len(payload) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Фотография больше 12 МБ. Сделайте снимок меньшего размера.")
    return payload


def _prepare_image(payload: bytes) -> bytes:
    """Повернуть iPhone-снимок по EXIF и дать OCR контрастный PNG."""
    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(payload)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            if max(image.size) > 3200:
                image.thumbnail((3200, 3200))
            gray = ImageOps.autocontrast(ImageOps.grayscale(image))
            out = io.BytesIO()
            gray.save(out, format="PNG", optimize=True)
            return out.getvalue()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=415,
            detail="Не удалось открыть фото. На iPhone снимайте камерой в форме; если выбрали HEIC из «Фото», сохраните его как JPEG/PNG.",
        ) from exc


def _ocr_image(payload: bytes) -> str:
    if not shutil.which("tesseract"):
        raise HTTPException(status_code=503, detail="OCR недоступен: на сервере нет tesseract.")
    png = _prepare_image(payload)
    done = subprocess.run(
        ["tesseract", "stdin", "stdout", "-l", "rus+eng", "--psm", "6"],
        input=png,
        capture_output=True,
        timeout=_OCR_TIMEOUT_SECONDS,
        check=False,
    )
    if done.returncode != 0:
        done = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", "rus", "--psm", "6"],
            input=png,
            capture_output=True,
            timeout=_OCR_TIMEOUT_SECONDS,
            check=False,
        )
    if done.returncode != 0:
        error = done.stderr.decode("utf-8", errors="replace").strip()
        raise HTTPException(status_code=503, detail=f"OCR не прочитал фотографию: {error[:240]}")
    return done.stdout.decode("utf-8", errors="replace").strip()


def _norm(text: str) -> str:
    value = str(text or "").lower().replace("ё", "е")
    value = re.sub(r"[^0-9a-zа-я]+", " ", value)
    return " ".join(value.split())


def _label_score(label: str, line: str) -> float:
    target = _norm(label)
    source = _norm(line)
    if not target or not source:
        return 0.0
    if target in source:
        return 0.99
    target_words = {item for item in target.split() if not item.isdigit()}
    source_words = {item for item in source.split() if not item.isdigit()}
    overlap = len(target_words & source_words) / max(1, len(target_words))
    clipped = source[: max(len(target) + 12, len(target) * 2)]
    return max(overlap * 0.9, SequenceMatcher(None, target, clipped).ratio())


def _parse_number(token: str) -> float | None:
    raw = str(token or "").strip().replace("\u00a0", " ").replace("\u202f", " ").replace("'", "")
    if not raw:
        return None
    compact = raw.replace(" ", "")
    if "," in compact and "." in compact:
        decimal = "," if compact.rfind(",") > compact.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        compact = compact.replace(thousands, "").replace(decimal, ".")
    elif "," in compact:
        tail = compact.rsplit(",", 1)[1]
        compact = compact.replace(",", "." if len(tail) != 3 else "")
    elif "." in compact:
        parts = compact.split(".")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3):
            compact = "".join(parts)
    try:
        return float(compact)
    except ValueError:
        return None


def _numbers(line: str, label: str) -> list[float]:
    values = [
        value
        for value in (_parse_number(match.group(0)) for match in _NUMBER_RE.finditer(line))
        if value is not None
    ]
    label_numbers = [
        value
        for value in (_parse_number(match.group(0)) for match in _NUMBER_RE.finditer(label))
        if value is not None
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
            positions = [normalized.find(_norm(alias)) for alias in variants if _norm(alias)]
            positions = [position for position in positions if position >= 0]
            if positions:
                found.append((min(positions), field))
        if len(found) > len(best):
            best = found
    if len(best) >= 2:
        return [field for _, field in sorted(best, key=lambda item: item[0])]
    return fields


def parse_tep_text(text: str, tep_block: dict[str, Any]) -> dict[str, Any]:
    """Текст OCR → предложения для формы. Ничего в проекте не меняет."""
    lines = [" ".join(line.split()) for line in str(text or "").splitlines() if line.strip()]
    rows = list(tep_block.get("rows") or [])
    all_fields: list[dict[str, Any]] = []
    seen_fields: set[str] = set()
    for row in rows:
        for field in row.get("fields") or []:
            key = str(field.get("key") or "")
            if key and key not in seen_fields:
                seen_fields.add(key)
                all_fields.append(field)
    field_order = _header_fields(lines, all_fields)

    best_for_row: dict[str, tuple[float, str]] = {}
    for line in lines:
        winner: tuple[float, dict[str, Any]] | None = None
        for row in rows:
            score = _label_score(str(row.get("label") or ""), line)
            if winner is None or score > winner[0]:
                winner = (score, row)
        if winner is None or winner[0] < 0.53:
            continue
        row = winner[1]
        key = str(row.get("key") or "")
        previous = best_for_row.get(key)
        if previous is None or winner[0] > previous[0]:
            best_for_row[key] = (winner[0], line)

    suggestions: list[dict[str, Any]] = []
    recognized_rows = 0
    for row in rows:
        row_key = str(row.get("key") or "")
        matched = best_for_row.get(row_key)
        if not matched:
            continue
        score, line = matched
        values = _numbers(line, str(row.get("label") or ""))
        row_fields = {str(field.get("key")): field for field in row.get("fields") or []}
        ordered = [field for field in field_order if str(field.get("key")) in row_fields]
        if not ordered:
            ordered = list(row.get("fields") or [])
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
        "field_order": [str(field.get("key") or "") for field in field_order],
    }


def install(app: FastAPI, core: Any) -> None:
    """Поставить UI-расширение после штатного ``developaid_v2.install``."""

    @app.get("/v2/assets/upgrade.js", include_in_schema=False)
    async def developaid_v2_upgrade_script() -> FileResponse:
        return FileResponse(
            _FRONTEND / "upgrade.js",
            media_type="application/javascript",
            headers=_REVALIDATE,
        )

    @app.post("/api/v2/tep-photo")
    def developaid_v2_tep_photo(req: TepPhotoRequest) -> JSONResponse:
        payload = _decode_image(req.image_base64)
        try:
            text = _ocr_image(payload)
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(
                status_code=504,
                detail="OCR не успел прочитать снимок. Снимите таблицу ближе и без лишнего фона.",
            ) from exc
        tep_block = next(
            (block for block in form.form_description(core)["blocks"] if block.get("kind") == "tep"),
            None,
        )
        if not tep_block:
            raise HTTPException(status_code=500, detail="Описание блока ТЭП не найдено.")
        parsed = parse_tep_text(text, tep_block)
        parsed["filename"] = req.filename
        if not parsed["suggestions"]:
            parsed["warning"] = (
                "Таблица распознана как текст, но строки ТЭП не сопоставились. "
                "Проверьте снимок: названия строк и цифры должны быть видны целиком."
            )
        return JSONResponse(parsed, headers=_NO_STORE)

    @app.middleware("http")
    async def developaid_v2_upgrade_middleware(request: Request, call_next):
        path = request.url.path
        if request.method == "GET" and path in {"/v2", "/v2/"}:
            source = (_FRONTEND / "index.html").read_text(encoding="utf-8")
            marker = '<script src="/v2/assets/app.js" defer></script>'
            injected = '<script src="/v2/assets/upgrade.js" defer></script>\n  ' + marker
            if marker not in source:
                raise RuntimeError("В index.html /v2 не найден app.js: нельзя безопасно вставить upgrade.js")
            return HTMLResponse(source.replace(marker, injected, 1), headers=_REVALIDATE)

        if request.method == "GET" and path == "/api/v2/projects":
            catalog = [{
                "slug": "new",
                "name": "Новый проект",
                "region": "",
                "subtitle": "Умолчания движка · без демонстрационной предустановки",
                "demo": False,
            }]
            catalog.extend(demo.list_scenarios())
            return JSONResponse(catalog, headers=_NO_STORE)

        if request.method == "GET" and path == "/api/v2/projects/new":
            raw = str(request.query_params.get("sensitivity", "true")).strip().lower()
            sensitivity = raw not in {"0", "false", "no", "off"}
            try:
                result = _new_project(core, sensitivity=sensitivity)
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001
                detail = getattr(core, "_error_location", lambda error: str(error))(exc)
                raise HTTPException(status_code=500, detail=str(detail)[:300]) from exc
            return JSONResponse(result, headers=_NO_STORE)

        return await call_next(request)

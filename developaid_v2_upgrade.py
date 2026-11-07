"""DevelopAid 2.0: neutral start, Telegram UI hook and TEP photo OCR."""

from __future__ import annotations

import base64
import copy
import io
import math
import re
import shutil
import subprocess
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

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


class TepPhotoApplyRequest(BaseModel):
    inputs: dict[str, Any] = {}
    tep: dict[str, dict[str, Any]] = {}
    selected: list[dict[str, Any]] = []


def apply_photo_values(core: Any, req: TepPhotoApplyRequest) -> dict[str, Any]:
    """Apply one reviewed table packet; derive only cells absent from it.

    The engine's existing TEP writer owns the reverse mapping to inputs. All
    source cells of a row are restored after deriving its missing neighbours;
    a later asynchronous single-cell request cannot erase another source cell.
    """
    from developaid_v2_account_projects import (
        TepSyncRequest, _row_to_inputs, _sync_tep, _underground_guests_follow,
    )

    block = next((item for item in form.form_description(core)["blocks"]
                  if item.get("kind") == "tep"), {})
    schema = {str(row["key"]): {str(field["key"]) for field in row.get("fields") or []}
              for row in block.get("rows") or []}
    if not req.selected or len(req.selected) > 200:
        raise HTTPException(400, "Отметьте от одного до 200 значений фотографии.")
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for item in req.selected:
        row, field = str(item.get("row_key") or ""), str(item.get("field_key") or "")
        value = item.get("value")
        if row not in schema or field not in schema[row]:
            raise HTTPException(400, "Поле фотографии не найдено в ТЭП проекта.")
        try:
            finite = math.isfinite(value)
        except (OverflowError, TypeError):
            finite = False
        if (isinstance(value, bool) or not isinstance(value, (float, int))
                or not finite or value < 0
                or (field == "units" and value != int(value))):
            raise HTTPException(400, "В фотографии есть недопустимое число; проверьте выбранные значения.")
        previous = grouped.setdefault(row, {}).get(field)
        if previous is not None and previous["value"] != value:
            raise HTTPException(409, "Для одной ячейки выбраны разные числа фотографии.")
        grouped[row][field] = {"value": value, "source_line": str(item.get("source_line") or "")[:1000]}
    inputs, tep = copy.deepcopy(req.inputs), copy.deepcopy(req.tep)
    if "_field_origin" in inputs and not isinstance(inputs["_field_origin"], dict):
        raise HTTPException(400, "Происхождение полей проекта повреждено. Откройте проект заново.")
    applied, notes = [], []
    for row_key, cells in grouped.items():
        anchor = next((field for field in ("gns", "total_area", "saleable", "units", "transfer", "useful")
                       if field in cells), next(iter(cells)))
        got = _sync_tep(core, TepSyncRequest(inputs=inputs, tep=tep, row_key=row_key,
                                            field_key=anchor, value=cells[anchor]["value"]))
        inputs, tep = got["inputs"], got["tep"]
        origins = inputs.setdefault("_field_origin", {})
        for field, rule in got["derived"].items():
            origins[f"tep.{row_key}.{field}"] = {"source": "document",
                                                  "text": f"По данным фотографии: {rule}"}
        for field, item in cells.items():
            tep[row_key][field] = item["value"]
            origins[f"tep.{row_key}.{field}"] = {
                "source": "document", "text": "Из фотографии таблицы ТЭП: " + item["source_line"],
            }
            applied.append({"row_key": row_key, "field_key": field, "value": item["value"]})
        notes.extend(_row_to_inputs(core, inputs, row_key, tep[row_key]))
        if row_key == "underground_parking":
            _underground_guests_follow(core, inputs, tep, {})
        for field, input_key in core.tep_row_inputs(row_key).items():
            if field in tep[row_key]:
                origins[f"inputs.{input_key}"] = dict(origins.get(f"tep.{row_key}.{field}") or {
                    "source": "document", "text": "По данным фотографии таблицы ТЭП"})
    for row_key, cells in grouped.items():
        switch = next((obj.enabled_key for obj in core.STANDALONE_OBJECTS if obj.key == row_key), "")
        if switch and not inputs.get(switch) and any(item["value"] > 0 for item in cells.values()):
            raise HTTPException(409, "Объект из фотографии выключен в проекте. "
                                "Включите его во вводных и повторите применение фотографии.")
        if row_key in core.SOCIAL_TEP_FIELDS:
            effective = core.social_tep_row(inputs, row_key)
            if any(field in effective and not math.isclose(item["value"], effective[field], abs_tol=0.01)
                   for field, item in cells.items()):
                raise HTTPException(409, "Настройки социальной нагрузки меняют числа фотографии. "
                                    "Проверьте нормативный или ручной режим площадей и повторите применение.")
    return {"inputs": inputs, "tep": tep, "applied": applied, "notes": list(dict.fromkeys(notes))}


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


def _numbers(line: str, label: str) -> list[float | None]:
    """Keep explicit empty cells; never infer a column from a numeric tail.

    Tesseract's preserved whitespace is only usable when all column boundaries
    survive. A collapsed row is refused, rather than silently zipped left.
    """
    del label  # Row identity was matched separately, not by a digit in its name.
    cells = [cell.strip() for cell in re.split(r"\t| {2,}", line.strip())]
    if len(cells) < 2:
        return []
    values: list[float | None] = []
    for cell in cells[1:]:
        if cell in {"", "-", "—", "–"}:
            values.append(None)
            continue
        match = re.fullmatch(
            rf"({_CELL_NUMBER.pattern})\s*(?:м[²2]|шт\.?|мест(?:а|о)?|пос\.?/смену)?", cell)
        if match is None:
            return []
        if re.fullmatch(r"[-+]?\d+[.,]\d{3}", match.group(1)):
            # A lone three-digit suffix can mean a decimal or a thousands
            # group. Label similarity gives no evidence to resolve that.
            return []
        number = _parse_number(match.group(1))
        if number is None or not math.isfinite(number) or number < 0:
            return []
        values.append(number)
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
    # No header means no source evidence for column order. The order of fields
    # in the form is not a substitute for the source table's schema.
    return [field for _, field in sorted(best, key=lambda item: item[0])] if len(best) >= 2 else []


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
    conflicting: set[str] = set()
    for line in lines:
        ranked = sorted(
            ((_label_score(str(row.get("label") or ""), line), row) for row in rows),
            key=lambda item: item[0], reverse=True,
        )
        if (not ranked or ranked[0][0] < 0.53
                or (len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.08)):
            continue
        score, row = ranked[0]
        key = str(row.get("key") or "")
        if key in best and score == best[key][0]:
            previous = _numbers(best[key][1], str(row.get("label") or ""))
            current = _numbers(line, str(row.get("label") or ""))
            if previous and current and previous != current:
                conflicting.add(key)
        if key not in best or score > best[key][0]:
            best[key] = (score, line)

    suggestions: list[dict[str, Any]] = []
    warnings: list[str] = []
    recognized_rows = 0
    for row in rows:
        row_key = str(row.get("key") or "")
        if row_key not in best:
            continue
        score, line = best[row_key]
        if row_key in conflicting:
            warnings.append(f"{row.get('label') or row_key}: найдены разные строки с одной подписью; "
                            "значения не перенесены, выберите одну таблицу на фотографии.")
            continue
        values = _numbers(line, str(row.get("label") or ""))
        row_fields = {str(f.get("key")): f for f in row.get("fields") or []}
        ordered = [f for f in order if str(f.get("key")) in row_fields]
        if not ordered or len(values) != len(ordered):
            warnings.append(f"{row.get('label') or row_key}: столбцы не определены однозначно; "
                            "значения не перенесены. Нужен снимок с заголовками и границами ячеек.")
            continue
        wrote = False
        for field, value in zip(ordered, values):
            if value is None:
                continue
            if str(field.get("key")) == "units" and value != int(value):
                warnings.append(f"{row.get('label') or row_key}: количество не целое; проверьте снимок.")
                continue
            suggestions.append({
                "row_key": row_key,
                "row_label": str(row.get("label") or row_key),
                "field_key": str(field.get("key") or ""),
                "field_label": str(field.get("label") or field.get("key") or ""),
                "value": value,
                "label_similarity": round(score, 3),
                "source_line": line,
            })
            wrote = True
        recognized_rows += int(wrote)
    return {
        "text": text,
        "suggestions": suggestions,
        "recognized_rows": recognized_rows,
        "total_rows": len(rows),
        "field_order": [str(f.get("key") or "") for f in order],
        "warnings": warnings,
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


def install(app: FastAPI, core: Any) -> None:
    @app.post("/api/v2/tep-photo/apply")
    def tep_photo_apply(req: TepPhotoApplyRequest) -> JSONResponse:
        return JSONResponse(apply_photo_values(core, req), headers=_NO_STORE)

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


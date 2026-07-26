from __future__ import annotations

import copy
import io
import math
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime
from typing import Any

from plato_template_mapping import (
    ACTIVE_SCENARIO_CELL,
    ACTIVE_SCENARIO_VALUE,
    DERIVED_WEB_INPUTS,
    DIRECT_CELL_MAP,
    INPUT_CELL_MAP,
    TEP_CELL_MAP,
)

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
ET.register_namespace("", _MAIN_NS)
ET.register_namespace("r", _DOC_REL_NS)


class PlatoTemplateError(RuntimeError):
    pass


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value not in (None, "") else default)
    except Exception:
        return float(default)


def _excel_serial(value: Any) -> float:
    if isinstance(value, str):
        value = datetime.strptime(value[:10], "%Y-%m-%d")
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day)
    if not isinstance(value, datetime):
        raise PlatoTemplateError(f"Invalid Excel date: {value!r}")
    return (value - datetime(1899, 12, 30)).total_seconds() / 86400.0


def _transform(value: Any, transform: str) -> tuple[Any, str]:
    if transform == "pct":
        return _number(value) / 100.0, "number"
    if transform == "date":
        return value, "date"
    if transform == "bool_ru":
        if isinstance(value, str):
            enabled = value.strip().lower() in {"1", "true", "да", "yes", "on"}
        else:
            enabled = bool(value)
        return ("Да" if enabled else "Нет"), "string"
    if transform == "social_mode":
        text = str(value or "").strip().lower()
        construction = "стро" in text or text in {"construction", "build"}
        return ("Строительство" if construction else "Денежная компенсация"), "string"
    if transform == "string":
        return str(value or ""), "string"
    return _number(value), "number"


def _split_address(address: str) -> tuple[str, str]:
    if "!" not in address:
        raise PlatoTemplateError(f"Workbook address must contain sheet name: {address}")
    sheet, cell = address.rsplit("!", 1)
    return sheet.strip("'"), cell.upper()


def _sheet_paths(files: dict[str, bytes]) -> dict[str, str]:
    workbook = ET.fromstring(files["xl/workbook.xml"])
    relationships = ET.fromstring(files["xl/_rels/workbook.xml.rels"])
    rel_map = {item.attrib["Id"]: item.attrib["Target"] for item in relationships}
    sheets = workbook.find(f"{{{_MAIN_NS}}}sheets")
    if sheets is None:
        raise PlatoTemplateError("Master workbook has no sheets")
    result: dict[str, str] = {}
    for sheet in sheets:
        relation_id = sheet.attrib[f"{{{_DOC_REL_NS}}}id"]
        target = rel_map.get(relation_id)
        if not target:
            continue
        result[sheet.attrib["name"]] = "xl/" + target.lstrip("/")
    return result


def _row_number(cell_reference: str) -> int:
    match = re.fullmatch(r"[A-Z]+([0-9]+)", cell_reference)
    if not match:
        raise PlatoTemplateError(f"Invalid cell reference: {cell_reference}")
    return int(match.group(1))


def _column_number(cell_reference: str) -> int:
    match = re.fullmatch(r"([A-Z]+)[0-9]+", cell_reference)
    if not match:
        raise PlatoTemplateError(f"Invalid cell reference: {cell_reference}")
    value = 0
    for char in match.group(1):
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value


def _find_or_create_cell(root: ET.Element, reference: str) -> ET.Element:
    sheet_data = root.find(f"{{{_MAIN_NS}}}sheetData")
    if sheet_data is None:
        sheet_data = ET.SubElement(root, f"{{{_MAIN_NS}}}sheetData")
    row_index = _row_number(reference)
    row = next((item for item in sheet_data if int(item.attrib.get("r", "0")) == row_index), None)
    if row is None:
        row = ET.Element(f"{{{_MAIN_NS}}}row", {"r": str(row_index)})
        inserted = False
        for position, candidate in enumerate(list(sheet_data)):
            if int(candidate.attrib.get("r", "0")) > row_index:
                sheet_data.insert(position, row)
                inserted = True
                break
        if not inserted:
            sheet_data.append(row)
    cell = next((item for item in row if item.attrib.get("r") == reference), None)
    if cell is None:
        cell = ET.Element(f"{{{_MAIN_NS}}}c", {"r": reference})
        column_index = _column_number(reference)
        inserted = False
        for position, candidate in enumerate(list(row)):
            candidate_ref = candidate.attrib.get("r", "A1")
            if _column_number(candidate_ref) > column_index:
                row.insert(position, cell)
                inserted = True
                break
        if not inserted:
            row.append(cell)
    return cell


def _set_cell(root: ET.Element, reference: str, value: Any, kind: str) -> None:
    cell = _find_or_create_cell(root, reference)
    for child in list(cell):
        if child.tag in {
            f"{{{_MAIN_NS}}}f",
            f"{{{_MAIN_NS}}}v",
            f"{{{_MAIN_NS}}}is",
        }:
            cell.remove(child)
    cell.attrib.pop("t", None)
    if kind == "string":
        cell.attrib["t"] = "inlineStr"
        inline = ET.SubElement(cell, f"{{{_MAIN_NS}}}is")
        text = ET.SubElement(inline, f"{{{_MAIN_NS}}}t")
        text.text = str(value or "")
        return
    numeric = _excel_serial(value) if kind == "date" else _number(value)
    node = ET.SubElement(cell, f"{{{_MAIN_NS}}}v")
    node.text = format(numeric, ".15g")


def _target_growth(inputs: dict[str, Any]) -> float | None:
    if "monthly_growth_pre_pct" not in inputs:
        return None
    months = max(
        1,
        int(round(_number(inputs.get("construction_months"), 24)))
        - int(round(_number(inputs.get("sales_lag_months"), 0))),
    )
    monthly = _number(inputs.get("monthly_growth_pre_pct")) / 100.0
    return (1.0 + monthly) ** months - 1.0


def _weighted_main_rate(inputs: dict[str, Any], tep: dict[str, dict[str, Any]]) -> float | None:
    above = _number(inputs.get("main_above_th_per_sqm"))
    under = _number(inputs.get("main_under_th_per_sqm"), above)
    above_gns = sum(
        _number((tep.get(key) or {}).get("gns"))
        for key in (
            "apartments",
            "ground_commercial",
            "standalone_retail",
            "offices",
            "above_parking",
        )
    )
    under_gns = _number((tep.get("underground_parking") or {}).get("gns")) + _number(
        (tep.get("storage") or {}).get("gns")
    )
    total = above_gns + under_gns
    if total <= 0:
        return above or under or None
    return (above * above_gns + under * under_gns) / total


def _derived_writes(inputs: dict[str, Any], tep: dict[str, dict[str, Any]]) -> dict[str, tuple[Any, str]]:
    writes: dict[str, tuple[Any, str]] = {}
    growth = _target_growth(inputs)
    if growth is not None:
        writes["Вводные!E52"] = (growth, "number")
    weighted_rate = _weighted_main_rate(inputs, tep)
    if weighted_rate is not None:
        writes["Вводные!E27"] = (weighted_rate, "number")
    spaces = _number(inputs.get("above_parking_spaces"))
    area_per_space = _number(inputs.get("above_parking_area_per_space_sqm"), 25.0)
    if spaces > 0:
        writes["Вводные!E144"] = (spaces * area_per_space, "number")
    for places_key, gba_key, norm_cell in (
        ("kindergarten_places", "social_dou_gba_sqm", "Вводные!I148"),
        ("school_places", "social_school_gba_sqm", "Вводные!I149"),
        ("clinic_capacity", "social_clinic_gba_sqm", "Вводные!I150"),
    ):
        places = _number(inputs.get(places_key))
        gba = _number(inputs.get(gba_key))
        if places > 0 and gba > 0:
            writes[norm_cell] = (gba / places, "number")
    return writes


def _rate_writes(rates: list[dict[str, Any]]) -> dict[str, tuple[Any, str]]:
    if not rates:
        return {}
    normalized = []
    for item in rates:
        raw_date = item.get("date") or item.get("month")
        raw_rate = item.get("rate")
        if raw_rate is None:
            raw_rate = item.get("key_rate")
        if not raw_date or raw_rate is None:
            continue
        try:
            parsed = datetime.strptime(str(raw_date)[:10], "%Y-%m-%d")
        except Exception:
            continue
        rate = _number(raw_rate)
        if abs(rate) > 1.0:
            rate /= 100.0
        normalized.append((parsed, rate))
    if not normalized:
        return {}
    normalized.sort(key=lambda item: item[0])
    first_date, first_rate = normalized[0]
    last_date, last_rate = normalized[-1]
    months = max(0, (last_date.year - first_date.year) * 12 + last_date.month - first_date.month)
    return {
        "Вводные!C54": ("Базовая", "string"),
        "Вводные!E54": (first_rate, "number"),
        "Вводные!G54": (months, "number"),
        "Вводные!J54": (first_date, "date"),
        "Вводные!E55": (last_rate, "number"),
    }


def build_formula_workbook(
    template_bytes: bytes,
    inputs: dict[str, Any],
    tep: dict[str, dict[str, Any]],
    rates: list[dict[str, Any]] | None = None,
) -> bytes:
    """Fill the user-approved PLATO template without rebuilding its formulas.

    The function edits only selected hardcoded cells in the OOXML package.  All
    existing formulas, styles, charts, drawings, names and hidden service sheets
    are retained.  Excel is instructed to perform a full recalculation on open.
    """
    if not template_bytes.startswith(b"PK"):
        raise PlatoTemplateError("PLATO master template is not a valid .xlsx package")
    with zipfile.ZipFile(io.BytesIO(template_bytes), "r") as source:
        files = {name: source.read(name) for name in source.namelist()}
    paths = _sheet_paths(files)
    writes: dict[str, tuple[Any, str]] = {
        ACTIVE_SCENARIO_CELL: (ACTIVE_SCENARIO_VALUE, "string")
    }
    for key, (address, transform) in INPUT_CELL_MAP.items():
        if key not in inputs or key in DERIVED_WEB_INPUTS:
            continue
        writes[address] = _transform(inputs.get(key), transform)
    for key, (address, transform) in DIRECT_CELL_MAP.items():
        if key in inputs:
            writes[address] = _transform(inputs.get(key), transform)
    for product_key, cell_map in TEP_CELL_MAP.items():
        product = tep.get(product_key) or {}
        for field, (address, transform) in cell_map.items():
            if field in product:
                writes[address] = _transform(product.get(field), transform)
    writes.update(_derived_writes(inputs, tep))
    writes.update(_rate_writes(rates or []))

    by_sheet: dict[str, dict[str, tuple[Any, str]]] = {}
    for address, payload in writes.items():
        sheet, cell = _split_address(address)
        by_sheet.setdefault(sheet, {})[cell] = payload
    for sheet_name, cells in by_sheet.items():
        path = paths.get(sheet_name)
        if not path or path not in files:
            raise PlatoTemplateError(f"Master template sheet not found: {sheet_name}")
        root = ET.fromstring(files[path])
        for reference, (value, kind) in cells.items():
            _set_cell(root, reference, value, kind)
        files[path] = ET.tostring(root, encoding="utf-8", xml_declaration=True)

    workbook = ET.fromstring(files["xl/workbook.xml"])
    calc = workbook.find(f"{{{_MAIN_NS}}}calcPr")
    if calc is None:
        calc = ET.SubElement(workbook, f"{{{_MAIN_NS}}}calcPr")
    calc.set("calcMode", "auto")
    calc.set("fullCalcOnLoad", "1")
    calc.set("forceFullCalc", "1")
    calc.set("calcId", "0")
    files["xl/workbook.xml"] = ET.tostring(
        workbook, encoding="utf-8", xml_declaration=True
    )

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as target:
        for name, content in files.items():
            target.writestr(name, content)
    return output.getvalue()

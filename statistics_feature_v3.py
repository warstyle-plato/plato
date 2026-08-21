from __future__ import annotations

import html
from datetime import date, datetime
from typing import Any

from fastapi import Query
from fastapi.responses import HTMLResponse

from developaid_cost_structure import CLASS_LABELS, UNIT_LABELS, build_cost_structure_matrix
from statistics_feature_v2 import PROJECT_PRESETS, _correct_matrix, _parse_area, _remove_route, install as install_v2

# Working preview assumption confirmed in discussion: total building area is
# roughly 7–10% below GNS. Use the midpoint transparently; no extra user field.
BUILDING_TOTAL_TO_GBA = 0.915

GRADE_WEIGHT = {"A": 1.0, "B": 0.8, "C": 0.5}
SOURCE_WEIGHT = {
    "internal_project": 1.0,
    "official_normative": 0.95,
    "industry_benchmark": 0.8,
    "industry_case": 0.65,
}

ROW_SPECS = [
    {"key": "preparation", "label": "Подготовка площадки", "unit": "gba", "kind": "component"},
    {"key": "design", "label": "ПИР / РД / экспертиза", "unit": "gba", "kind": "component"},
    {"key": "main_above", "label": "Основное строительство — наземная часть", "unit": "above_ground", "kind": "component"},
    {"key": "main_under", "label": "Подземная часть / паркинг", "unit": "underground", "kind": "component"},
    {"key": "main_building_smr", "label": "СМР здания — опубликованный блок", "unit": "gba", "kind": "component"},
    {"key": "internal_engineering", "label": "Внутренние инженерные системы", "unit": "gba", "kind": "component"},
    {"key": "external_utilities", "label": "Наружные / внутриплощадочные сети", "unit": "gba", "kind": "component"},
    {"key": "landscaping", "label": "Благоустройство", "unit": "gba", "kind": "component"},
    {"key": "networks_landscaping", "label": "Наружные сети + благоустройство (совместно)", "unit": "gba", "kind": "combined"},
    {"key": "technical_connection", "label": "ТУ / технологическое присоединение", "unit": "gba", "kind": "component"},
    {"key": "commissioning", "label": "Сдача и ввод", "unit": "gba", "kind": "component"},
    {"key": "site_maintenance", "label": "Содержание стройплощадки", "unit": "gba", "kind": "component"},
    {"key": "tech_customer", "label": "Техзаказчик / стройконтроль", "unit": "gba", "kind": "component"},
    {"key": "project_management", "label": "Управление проектом", "unit": "gba", "kind": "component"},
    {"key": "reserve", "label": "Резерв", "unit": "gba", "kind": "component"},
    {"key": "construction_capex", "label": "Строительный CAPEX / контрольный итог", "unit": "gba", "kind": "construction_total"},
    {"key": "land", "label": "Земля в полной стоимости застройщика", "unit": "gba", "kind": "component"},
    {"key": "full_development_cost", "label": "Полная стоимость застройщика", "unit": "gba", "kind": "full_total"},
]

AREA_KEYS = {
    "gba": "gba_sqm",
    "above_ground": "above_ground_gns_sqm",
    "underground": "underground_gns_sqm",
    "sellable": "sellable_sqm",
    "apartments": "apartments_sqm",
    "building_total": "building_total_sqm",
}

FRIENDLY_GROUPS = {
    "developaid-grodnenskaya-2026-07": "Гродненская",
    "core-xp-moscow-cost-stack-2024-09": "CORE.XP",
    "mke-ncsm-2025-09": "Москомэкспертиза / НЦСМ",
    "ac-moscow-declared-2025-06": "АЦ Москвы / декларации",
    "sis-erz-moscow-2026-04": "СИС / ЕРЗ",
}

CONSTRUCTION_CONTROL_SCOPES = {
    "construction_capex",
    "core_xp_construction_stack",
    "building_normative",
    "declared_project_construction",
}


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _fmt(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value / 1000:,.1f}".replace(",", " ").replace(".", ",")


def _fmt_area(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.1f}".replace(",", " ").replace(".", ",")


def _areas(
    gba: Any,
    sellable: Any,
    apartments: Any = None,
    underground: Any = None,
    above: Any = None,
    building_total: Any = None,
) -> tuple[dict[str, float], bool]:
    """Normalize project TEP without asking for duplicate building-area inputs.

    The user-facing form has one sellable-housing field. Legacy query args are
    still accepted for old links, but building_total is always derived from GNS.
    """
    result: dict[str, float] = {}
    g = _parse_area(gba)
    s = _parse_area(sellable)
    legacy_apartments = _parse_area(apartments)
    u = _parse_area(underground)
    a = _parse_area(above)

    if g is not None:
        result["gba_sqm"] = g
        result["building_total_sqm"] = g * BUILDING_TOTAL_TO_GBA
    if s is not None:
        result["sellable_sqm"] = s
        result["apartments_sqm"] = s
    elif legacy_apartments is not None:
        result["sellable_sqm"] = legacy_apartments
        result["apartments_sqm"] = legacy_apartments
    if u is not None:
        result["underground_gns_sqm"] = u
    if a is not None:
        result["above_ground_gns_sqm"] = a
    elif g is not None and u is not None and g > u:
        result["above_ground_gns_sqm"] = g - u
    return result, False


def _default_areas_if_blank(gba: Any, sellable: Any, underground: Any, above: Any) -> tuple[dict[str, float], bool]:
    if any(_parse_area(x) is not None for x in (gba, sellable, underground, above)):
        areas, _ = _areas(gba, sellable, None, underground, above, None)
        return areas, False
    p = PROJECT_PRESETS["grodno"]
    areas, _ = _areas(p["gba_sqm"], p["sellable_sqm"], None, p["underground_gns_sqm"], None, None)
    return areas, True


def _area(unit: str | None, areas: dict[str, float]) -> float | None:
    return areas.get(AREA_KEYS.get(unit or "", ""))


def _convert(value: float | None, source_unit: str | None, target_unit: str, areas: dict[str, float]) -> tuple[float | None, bool]:
    if value is None or source_unit is None:
        return None, False
    if source_unit == target_unit:
        return float(value), False
    source_area = _area(source_unit, areas)
    target_area = _area(target_unit, areas)
    if not source_area or not target_area:
        return None, False
    return float(value) * source_area / target_area, True


def _source_value(source: dict[str, Any]) -> float | None:
    value = source.get("published_adjusted_value_rub_m2")
    if value is None:
        value = source.get("published", {}).get("value_rub_m2")
    return None if value is None else float(value)


def _source_range(source: dict[str, Any]) -> tuple[float | None, float | None]:
    published = source.get("published", {})
    ratio = float(source.get("published_adjustment_ratio", 1) or 1)
    low = published.get("value_low_rub_m2")
    high = published.get("value_high_rub_m2")
    return (
        None if low is None else float(low) * ratio,
        None if high is None else float(high) * ratio,
    )


def _direct_cell(source: dict[str, Any], key: str, target_unit: str, areas: dict[str, float]) -> dict[str, Any] | None:
    cell = source.get("cells", {}).get(key, {})
    status = cell.get("status")

    if status == "share":
        parent = _source_value(source)
        share = cell.get("share_pct")
        if parent is None or share is None:
            return None
        value, _ = _convert(parent * float(share) / 100, source.get("published", {}).get("unit"), target_unit, areas)
        if value is None:
            return None
        return {"value": value, "low": value, "high": value, "grade": "C"}

    if status == "share_range":
        parent = _source_value(source)
        lo_pct = cell.get("share_low_pct")
        hi_pct = cell.get("share_high_pct")
        if parent is None or lo_pct is None or hi_pct is None:
            return None
        low, _ = _convert(parent * float(lo_pct) / 100, source.get("published", {}).get("unit"), target_unit, areas)
        high, _ = _convert(parent * float(hi_pct) / 100, source.get("published", {}).get("unit"), target_unit, areas)
        if low is None or high is None:
            return None
        return {"value": (low + high) / 2, "low": low, "high": high, "grade": "C"}

    if status not in {"value", "separate_denominator"}:
        return None

    raw = cell.get("adjusted_value_rub_m2", cell.get("value_rub_m2"))
    if raw is None or float(raw) <= 0:
        return None
    low_raw = cell.get("adjusted_value_low_rub_m2", cell.get("value_low_rub_m2", raw))
    high_raw = cell.get("adjusted_value_high_rub_m2", cell.get("value_high_rub_m2", raw))
    source_unit = cell.get("unit")
    value, converted = _convert(float(raw), source_unit, target_unit, areas)
    low, _ = _convert(float(low_raw), source_unit, target_unit, areas)
    high, _ = _convert(float(high_raw), source_unit, target_unit, areas)
    if value is None:
        return None
    grade = "B" if converted or cell.get("class_adjusted") else "A"
    return {"value": value, "low": low or value, "high": high or value, "grade": grade}


def _combined_cell(source: dict[str, Any], target_unit: str, areas: dict[str, float]) -> dict[str, Any] | None:
    cell = source.get("cells", {}).get("external_utilities", {})
    if cell.get("status") != "combined_share" or cell.get("group") != "networks_landscaping":
        return None
    parent = _source_value(source)
    lo_pct = cell.get("share_low_pct")
    hi_pct = cell.get("share_high_pct")
    if parent is None or lo_pct is None or hi_pct is None:
        return None
    low, _ = _convert(parent * float(lo_pct) / 100, source.get("published", {}).get("unit"), target_unit, areas)
    high, _ = _convert(parent * float(hi_pct) / 100, source.get("published", {}).get("unit"), target_unit, areas)
    if low is None or high is None:
        return None
    return {"value": (low + high) / 2, "low": low, "high": high, "grade": "C"}


def _published_total(source: dict[str, Any], target_unit: str, areas: dict[str, float], allowed_scopes: set[str]) -> dict[str, Any] | None:
    published = source.get("published", {})
    if published.get("scope") not in allowed_scopes:
        return None
    raw = _source_value(source)
    if raw is None or raw <= 0:
        return None
    value, converted = _convert(raw, published.get("unit"), target_unit, areas)
    if value is None:
        return None
    raw_low, raw_high = _source_range(source)
    low, _ = _convert(raw_low if raw_low is not None else raw, published.get("unit"), target_unit, areas)
    high, _ = _convert(raw_high if raw_high is not None else raw, published.get("unit"), target_unit, areas)

    exact = published.get("scope") == "construction_capex"
    if exact:
        grade = "B" if converted or source.get("published_class_adjusted") else "A"
    else:
        # Normalized and visible, but lower confidence because scope differs.
        grade = "C"
    return {"value": value, "low": low or value, "high": high or value, "grade": grade}


def _candidate(source: dict[str, Any], row: dict[str, Any], areas: dict[str, float]) -> dict[str, Any] | None:
    if row["kind"] == "combined":
        return _combined_cell(source, row["unit"], areas)
    if row["kind"] == "construction_total":
        direct = _direct_cell(source, "construction_capex", row["unit"], areas)
        if direct is not None:
            return direct
        return _published_total(source, row["unit"], areas, CONSTRUCTION_CONTROL_SCOPES)
    if row["kind"] == "full_total":
        return _published_total(source, row["unit"], areas, {"developer_full_cost"})
    return _direct_cell(source, row["key"], row["unit"], areas)


def _group_id(source: dict[str, Any]) -> str:
    return str(source.get("source_group") or source.get("source_id") or source.get("source"))


def _group_label(group: str, rows: list[dict[str, Any]]) -> str:
    if group in FRIENDLY_GROUPS:
        return FRIENDLY_GROUPS[group]
    return str(rows[0].get("source") or group)


def _source_groups(matrix: dict[str, Any]) -> list[tuple[str, str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for source in matrix.get("sources", []):
        grouped.setdefault(_group_id(source), []).append(source)
    return [(group, _group_label(group, rows), rows) for group, rows in grouped.items()]


def _class_distance(source: dict[str, Any], target_class: str) -> int:
    rank = {"standard": 0, "comfort": 1, "business": 2, "premium": 3, "elite": 4}
    base = source.get("base_class")
    if base not in rank or target_class not in rank:
        return 99
    return abs(rank[base] - rank[target_class])


def _best_group_candidate(rows: list[dict[str, Any]], row: dict[str, Any], areas: dict[str, float], target_class: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    candidates = []
    for source in rows:
        cell = _candidate(source, row, areas)
        if cell is not None:
            candidates.append((source, cell))
    if not candidates:
        return None, None
    rank = {"A": 0, "B": 1, "C": 2}
    candidates.sort(key=lambda item: (
        rank.get(item[1]["grade"], 9),
        0 if item[0].get("base_class") == target_class else 1,
        _class_distance(item[0], target_class),
    ))
    return candidates[0]


def _freshness(source: dict[str, Any]) -> float:
    try:
        observed = datetime.strptime(str(source.get("reference_date")), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return 0.5
    months = max(0, (date.today() - observed).days / 30.4375)
    if months <= 12:
        return 1.0
    if months <= 24:
        return 0.85
    if months <= 36:
        return 0.65
    return 0.4


def _weight(source: dict[str, Any], cell: dict[str, Any]) -> float:
    return GRADE_WEIGHT.get(cell.get("grade"), 0) * SOURCE_WEIGHT.get(source.get("source_kind"), 0.65) * _freshness(source)


def build_normalized_matrix(matrix: dict[str, Any], areas: dict[str, float], apartments_fallback: bool = False) -> dict[str, Any]:
    groups = _source_groups(matrix)
    target_class = matrix.get("housing_class", "business")
    rows = []
    for spec in ROW_SPECS:
        values = []
        aggregate_points = []
        for group, label, sources in groups:
            source, cell = _best_group_candidate(sources, spec, areas, target_class)
            item = {"group": group, "label": label, "value": None, "low": None, "high": None, "grade": None}
            if source and cell:
                item.update({"value": cell["value"], "low": cell["low"], "high": cell["high"], "grade": cell["grade"], "source_id": source.get("source_id")})
                w = _weight(source, cell)
                if w > 0:
                    aggregate_points.append((cell["value"], w))
            values.append(item)
        total_weight = sum(w for _, w in aggregate_points)
        aggregate = sum(v * w for v, w in aggregate_points) / total_weight if total_weight else None
        rows.append({
            "key": spec["key"],
            "label": spec["label"],
            "unit": spec["unit"],
            "unit_label": UNIT_LABELS.get(spec["unit"], spec["unit"]),
            "values": values,
            "aggregate": aggregate,
            "n": len(aggregate_points),
        })
    return {"groups": [{"group": g, "label": label} for g, label, _ in groups], "rows": rows}


def _render_matrix(payload: dict[str, Any]) -> str:
    headers = ["Параметр DevelopAid", "Единая база"] + [g["label"] for g in payload["groups"]] + ["Агрегат", "N"]
    head = "".join(f"<th>{_esc(x)}</th>" for x in headers)
    body = []
    for row in payload["rows"]:
        cells = [f'<td class="rowname"><b>{_esc(row["label"])}</b></td>', f'<td class="base">{_esc(row["unit_label"])}</td>']
        for item in row["values"]:
            if item["value"] is None:
                cells.append('<td class="num blank"></td>')
                continue
            range_html = ""
            if item["low"] is not None and item["high"] is not None and abs(item["high"] - item["low"]) > 0.5:
                range_html = f'<div class="small">{_fmt(item["low"])}–{_fmt(item["high"])}</div>'
            cells.append(f'<td class="num">{_fmt(item["value"])} <span class="grade">{_esc(item["grade"])}</span>{range_html}</td>')
        one = '<div class="small">1 источник</div>' if row["aggregate"] is not None and row["n"] == 1 else ""
        cells.append(f'<td class="num aggregate">{_fmt(row["aggregate"])}{one}</td>')
        cells.append(f'<td class="n">{row["n"]}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    return '<div class="tablewrap"><table><thead><tr>' + head + '</tr></thead><tbody>' + "".join(body) + '</tbody></table></div>'


def install(app):
    install_v2(app)
    _remove_route(app, "/statistics")
    _remove_route(app, "/api/statistics/normalized-matrix")

    @app.get("/api/statistics/normalized-matrix")
    def normalized_matrix(
        region: str = "Москва",
        housing_class: str = Query("business", alias="class"),
        gba_sqm: str | None = None,
        sellable_sqm: str | None = None,
        apartments_sqm: str | None = None,
        underground_gns_sqm: str | None = None,
        above_ground_gns_sqm: str | None = None,
        building_total_sqm: str | None = None,
    ):
        areas, defaulted = _default_areas_if_blank(gba_sqm, sellable_sqm or apartments_sqm, underground_gns_sqm, above_ground_gns_sqm)
        matrix = _correct_matrix(build_cost_structure_matrix(region=region, housing_class=housing_class))
        return {
            "areas": areas,
            "default_project": "grodno" if defaulted else None,
            "building_total_estimate_ratio": BUILDING_TOTAL_TO_GBA,
            **build_normalized_matrix(matrix, areas),
        }

    @app.get("/statistics", response_class=HTMLResponse)
    def statistics_page(
        region: str = "Москва",
        housing_class: str = Query("business", alias="class"),
        gba_sqm: str | None = None,
        sellable_sqm: str | None = None,
        apartments_sqm: str | None = None,
        underground_gns_sqm: str | None = None,
        above_ground_gns_sqm: str | None = None,
        building_total_sqm: str | None = None,
    ):
        areas, defaulted = _default_areas_if_blank(gba_sqm, sellable_sqm or apartments_sqm, underground_gns_sqm, above_ground_gns_sqm)
        matrix = _correct_matrix(build_cost_structure_matrix(region=region, housing_class=housing_class))
        normalized = build_normalized_matrix(matrix, areas)
        norm_html = _render_matrix(normalized)

        classes = [("standard", "Стандарт"), ("comfort", "Комфорт"), ("business", "Бизнес"), ("premium", "Премиум"), ("elite", "Элитный")]
        class_opts = "".join(f'<option value="{k}" {"selected" if housing_class == k else ""}>{v}</option>' for k, v in classes)
        preset_links = []
        for p in PROJECT_PRESETS.values():
            parts = [f'region={p["region"]}', f'class={p["housing_class"]}', f'gba_sqm={p["gba_sqm"]}', f'sellable_sqm={p["sellable_sqm"]}', f'underground_gns_sqm={p["underground_gns_sqm"]}']
            preset_links.append(f'<a href="/statistics?{"&".join(parts)}">{_esc(p["label"])}</a>')

        def iv(key: str) -> str:
            value = areas.get(key)
            return "" if value is None else f"{value:g}"

        default_html = '<div class="info">На первом открытии подставлен тестовый пример «Гродненская, 18», чтобы форма и нормализованная таблица не были пустыми.</div>' if defaulted else ""
        method_html = (
            '<div class="method"><b>Автонормализация Москвы:</b> отдельную «общую площадь здания» вводить не надо. '
            f'Для АЦ Москвы/НЦСМ она оценивается как {BUILDING_TOTAL_TO_GBA*100:.1f}% ГНС (середина рабочего диапазона ГНС −7…10%) и поэтому имеет grade C. '
            'Для источников на площадь квартир используется введённая продаваемая площадь жилья.</div>'
        )

        css = """
        *{box-sizing:border-box}body{margin:0;background:#f4f5f7;color:#202833;font:14px -apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif}.wrap{max-width:1600px;margin:auto;padding:28px 22px 70px}.top{display:flex;justify-content:space-between}.brand{font-size:20px;font-weight:800}.tag{font-size:11px;border:1px solid #d8dde5;background:#fff;padding:6px 10px;border-radius:999px}h1{font-size:34px;margin:26px 0 8px}h2{font-size:20px;margin:0 0 7px}.sub,.note,.small{color:#737d8d}.note{line-height:1.5;margin-bottom:12px}.presets{margin:10px 0}.presets a{color:#185d94}.filters{display:grid;grid-template-columns:1.1fr .9fr repeat(4,1fr) auto;gap:8px;background:#fff;border:1px solid #dfe4ea;border-radius:14px;padding:14px;margin:16px 0 18px}.field label{display:block;font-size:10px;color:#788291;margin-bottom:5px}.field .hint{font-size:9px;color:#98a0ab;margin-top:3px}input,select,button{width:100%;height:42px;border:1px solid #d5dae2;border-radius:8px;background:#fff;padding:0 9px;font:inherit}button{background:#192231;color:#fff;border-color:#192231;cursor:pointer}.tablewrap{overflow:auto;background:#fff;border:1px solid #dfe4ea;border-radius:12px}table{width:100%;border-collapse:collapse;font-size:12px;min-width:1250px}th,td{padding:9px;border-bottom:1px solid #edf0f4;border-right:1px solid #f0f2f5;vertical-align:top}th{background:#fafbfc;color:#717b89;font-size:10px;text-transform:uppercase;text-align:left}.rowname{min-width:255px}.base{min-width:150px;color:#667080}.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums;min-width:120px}.blank{background:#fbfcfd}.aggregate{background:#edf3f7;font-weight:800}.n{text-align:center;background:#f7f8fa;font-weight:700}.grade{font-size:9px;color:#758090}.small{font-size:9px;margin-top:3px}.section{margin-top:26px}.info{background:#eef4f8;border:1px solid #d4e0e8;color:#566b7b;padding:10px 13px;border-radius:10px;margin:8px 0}.method{background:#fff8e6;border:1px solid #eedca3;color:#6d581e;padding:10px 13px;border-radius:10px;margin:8px 0}@media(max-width:1100px){.filters{grid-template-columns:repeat(3,1fr)}}@media(max-width:700px){.filters{grid-template-columns:1fr}.wrap{padding:18px 10px 50px}h1{font-size:29px}}
        """
        body = f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DevelopAid — Себестоимость</title><style>{css}</style></head><body><div class="wrap">
        <div class="top"><div class="brand">DevelopAid</div><div class="tag">COST BENCHMARK · NORMALIZED v3.1</div></div>
        <h1>Себестоимость строительства</h1>
        <div class="sub">Строки — параметры DevelopAid, столбцы — источники. Москва, СИС/ЕРЗ и CORE.XP не исчезают из-за другого знаменателя: раскрытые данные сначала приводятся к ГНС/наземной/подземной базе, потом агрегируются.</div>
        {default_html}
        <div class="presets">Быстрая проверка: {" · ".join(preset_links)}</div>
        <form class="filters" method="get">
          <div class="field"><label>Регион</label><input name="region" value="{_esc(region)}"></div>
          <div class="field"><label>Класс</label><select name="class">{class_opts}</select></div>
          <div class="field"><label>Общая ГНС, м²</label><input name="gba_sqm" value="{iv('gba_sqm')}"></div>
          <div class="field"><label>Продаваемая площадь жилья, м²</label><input name="sellable_sqm" value="{iv('sellable_sqm')}"></div>
          <div class="field"><label>Подземная ГНС, м²</label><input name="underground_gns_sqm" value="{iv('underground_gns_sqm')}"></div>
          <div class="field"><label>Наземная ГНС, м²</label><input name="above_ground_gns_sqm" value="{iv('above_ground_gns_sqm')}"><div class="hint">авто = общая − подземная</div></div>
          <button>Пересчитать</button>
        </form>
        {method_html}
        <div class="section"><h2>Нормализованная таблица · {_esc(CLASS_LABELS.get(housing_class, housing_class))}</h2>
        <div class="note">Все значения — <b>тыс. ₽/м²</b> уже на базе строки. A — прямое число; B — механический пересчёт базы/класса; C — расчёт из явно раскрытой доли или контрольный итог с отличающимся scope. СИС «сети + благо» остаётся одной строкой и не делится искусственно.</div>{norm_html}</div>
        <div class="section"><div class="note">ТЭП: ГНС {_fmt_area(areas.get('gba_sqm'))} · продаваемая жилья {_fmt_area(areas.get('sellable_sqm'))} · подземная {_fmt_area(areas.get('underground_gns_sqm'))} · наземная {_fmt_area(areas.get('above_ground_gns_sqm'))} м². Расчётная общая площадь здания для АЦ/НЦСМ {_fmt_area(areas.get('building_total_sqm'))} м².</div></div>
        </div></body></html>'''
        return HTMLResponse(body)

    return app

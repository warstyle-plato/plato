"""Свод источников себестоимости: страница `/statistics` и её API.

Экран отвечает на один вопрос — **откуда взялось число**, которым DevelopAid
считает себестоимость. Строки — параметры движка, столбцы — источники,
последние две колонки — агрегат и число независимых источников. У источника
берётся только то, что содержит его методика: чего в ней нет, то остаётся
пустой ячейкой, а не подставляется оценкой.

Слоёв было три: `statistics_feature` рисовал первую страницу, `_v2` снимал её с
маршрута и вешал свою, `_v3` снимал вторую и вешал третью. Живой набор
приходилось выводить из порядка установки, а два мёртвых рендерера выглядели
ровно так же настояще, как живой. Здесь один модуль и восемь маршрутов; снимать
с приложения нечего, потому что лишнего не ставится.
"""

from __future__ import annotations

import html
from datetime import date, datetime
from functools import lru_cache
from typing import Any

from fastapi import Query
from fastapi.responses import HTMLResponse

from developaid_cost_aggregation import build_cost_recommendation
from developaid_cost_structure import (
    CLASS_LABELS,
    UNIT_LABELS,
    build_cost_structure_matrix,
    class_adjustment_catalog,
    load_class_adjustments,
)
from developaid_statistics import (
    build_benchmark,
    index_source_catalog,
    load_external_benchmarks,
    load_normalized_benchmarks,
    load_observations,
    result_to_dict,
    source_catalog,
)

import management_contour as _contour

LEGAL_FOOTER_PLACEHOLDER = "__DEVELOPAID_LEGAL_FOOTER__"

# Условный пример: страница без ТЭП показала бы пустую таблицу — привести
# источники к одной базе не из чего. Прежде для этого подставлялся реальный
# проект владельца, названный в форме по имени; демонстрационные числа не
# обязаны быть ничьими, поэтому здесь круглые.
EXAMPLE_AREAS = {"gba_sqm": 60000.0, "sellable_sqm": 32000.0,
                 "underground_gns_sqm": 13000.0}
EXAMPLE_LABEL = "условный пример: 60 000 м² ГНС"

# Разброс печатается от полутора раз, красным — от двух: ниже этого
# расхождение источников уже не спор о величине.
_SPREAD_VISIBLE = 1.5
_SPREAD_WIDE = 2.0

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
    "developaid-grodnenskaya-2026-07": "ФМ проекта DevelopAid",
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


def building_total_ratio(core) -> float:
    """Общая площадь здания как доля ГНС — то же число, что у движка.

    Источники Москомэкспертизы и АЦ публикуют ставку на общую площадь здания,
    а строки таблицы стоят на ГНС; перевод требует их отношения. Модуль знал
    своё 0,915 «середина рабочего диапазона», а движок — 0,90 из двух выгрузок
    ГлавАПУ. Два числа под одним смыслом расходятся молча, и правило тут то же,
    что с `VERSION`: копию негде обновлять, потому что копии нет.
    """
    ratios = getattr(core, "TEP_RATIOS", None) or {}
    value = (ratios.get("apartments") or {}).get("total_of_gns")
    return float(value) if value else 0.9


def class_options(core) -> list[tuple[str, str]]:
    """Классы — те, что есть у движка, и в его порядке.

    Своего списка страница не держит: класс, показанный в своде, но не
    существующий в расчёте, обещает настройку, которой нет. «Стандарт» ушёл
    вместе с решением владельца, «Премиум» появится здесь сам, как только у
    него будут названы ставки.
    """
    presets = getattr(core, "PROJECT_CLASS_PRESETS", None) or {}
    return [(key, str(value.get("label") or key)) for key, value in presets.items()]


@lru_cache(maxsize=1)
def _class_rank() -> dict[str, int]:
    """Ступени классов — из справочника нормализации, где они и объявлены.

    Справочник едет с образом и за время работы не меняется, а спрашивают
    ступень внутри сортировки на каждой ячейке таблицы: без памяти это
    чтение файла на каждое сравнение.
    """
    classes = load_class_adjustments().get("classes") or []
    return {name: index for index, name in enumerate(classes)}


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _fmt(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{float(value) / 1000:,.1f}".replace(",", " ").replace(".", ",")


def _fmt_area(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{float(value):,.1f}".replace(",", " ").replace(".", ",")


def _parse_area(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) or None
    text = str(value).strip().replace(" ", "").replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed or None


def _areas(core, gba: Any, sellable: Any, underground: Any, above: Any) -> tuple[dict[str, float], bool]:
    """ТЭП формы. Пусто во всех полях — подставляется условный пример."""
    given = {key: _parse_area(value) for key, value in
             (("gba_sqm", gba), ("sellable_sqm", sellable),
              ("underground_gns_sqm", underground), ("above_ground_gns_sqm", above))}
    example = not any(value is not None for value in given.values())
    if example:
        given = dict(EXAMPLE_AREAS)
    result: dict[str, float] = {}
    if given.get("gba_sqm") is not None:
        result["gba_sqm"] = float(given["gba_sqm"])
        result["building_total_sqm"] = result["gba_sqm"] * building_total_ratio(core)
    if given.get("sellable_sqm") is not None:
        result["sellable_sqm"] = float(given["sellable_sqm"])
        result["apartments_sqm"] = result["sellable_sqm"]
    if given.get("underground_gns_sqm") is not None:
        result["underground_gns_sqm"] = float(given["underground_gns_sqm"])
    if given.get("above_ground_gns_sqm") is not None:
        result["above_ground_gns_sqm"] = float(given["above_ground_gns_sqm"])
    elif result.get("gba_sqm") and result.get("underground_gns_sqm") \
            and result["gba_sqm"] > result["underground_gns_sqm"]:
        result["above_ground_gns_sqm"] = result["gba_sqm"] - result["underground_gns_sqm"]
    return result, example


def _area(unit: str | None, areas: dict[str, float]) -> float | None:
    return areas.get(AREA_KEYS.get(unit or "", ""))


def _convert(value: float | None, source_unit: str | None, target_unit: str,
             areas: dict[str, float]) -> tuple[float | None, bool]:
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
    return (None if low is None else float(low) * ratio,
            None if high is None else float(high) * ratio)


def _direct_cell(source: dict[str, Any], key: str, target_unit: str,
                 areas: dict[str, float]) -> dict[str, Any] | None:
    cell = source.get("cells", {}).get(key, {})
    status = cell.get("status")

    if status == "share":
        parent = _source_value(source)
        share = cell.get("share_pct")
        if parent is None or share is None:
            return None
        value, _ = _convert(parent * float(share) / 100,
                            source.get("published", {}).get("unit"), target_unit, areas)
        if value is None:
            return None
        return {"value": value, "low": value, "high": value, "grade": "C"}

    if status == "share_range":
        parent = _source_value(source)
        lo_pct, hi_pct = cell.get("share_low_pct"), cell.get("share_high_pct")
        if parent is None or lo_pct is None or hi_pct is None:
            return None
        unit = source.get("published", {}).get("unit")
        low, _ = _convert(parent * float(lo_pct) / 100, unit, target_unit, areas)
        high, _ = _convert(parent * float(hi_pct) / 100, unit, target_unit, areas)
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


def _combined_cell(source: dict[str, Any], target_unit: str,
                   areas: dict[str, float]) -> dict[str, Any] | None:
    cell = source.get("cells", {}).get("external_utilities", {})
    if cell.get("status") != "combined_share" or cell.get("group") != "networks_landscaping":
        return None
    parent = _source_value(source)
    lo_pct, hi_pct = cell.get("share_low_pct"), cell.get("share_high_pct")
    if parent is None or lo_pct is None or hi_pct is None:
        return None
    unit = source.get("published", {}).get("unit")
    low, _ = _convert(parent * float(lo_pct) / 100, unit, target_unit, areas)
    high, _ = _convert(parent * float(hi_pct) / 100, unit, target_unit, areas)
    if low is None or high is None:
        return None
    return {"value": (low + high) / 2, "low": low, "high": high, "grade": "C"}


def _published_total(source: dict[str, Any], target_unit: str, areas: dict[str, float],
                     allowed_scopes: set[str]) -> dict[str, Any] | None:
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
    if published.get("scope") == "construction_capex":
        grade = "B" if converted or source.get("published_class_adjusted") else "A"
    else:
        # Приведено и видно, но scope у источника другой — уверенность ниже.
        grade = "C"
    return {"value": value, "low": low or value, "high": high or value, "grade": grade}


def _candidate(source: dict[str, Any], row: dict[str, Any],
               areas: dict[str, float]) -> dict[str, Any] | None:
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


def _source_groups(matrix: dict[str, Any]) -> list[tuple[str, str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for source in matrix.get("sources", []):
        grouped.setdefault(_group_id(source), []).append(source)
    return [(group, FRIENDLY_GROUPS.get(group, str(rows[0].get("source") or group)), rows)
            for group, rows in grouped.items()]


def _class_distance(source: dict[str, Any], target_class: str) -> int:
    rank = _class_rank()
    base = source.get("base_class")
    if base not in rank or target_class not in rank:
        return 99
    return abs(rank[base] - rank[target_class])


def _best_group_candidate(rows: list[dict[str, Any]], row: dict[str, Any],
                          areas: dict[str, float], target_class: str):
    candidates = []
    for source in rows:
        cell = _candidate(source, row, areas)
        if cell is not None:
            candidates.append((source, cell))
    if not candidates:
        return None, None
    grade_rank = {"A": 0, "B": 1, "C": 2}
    candidates.sort(key=lambda item: (
        grade_rank.get(item[1]["grade"], 9),
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
    return (GRADE_WEIGHT.get(cell.get("grade"), 0)
            * SOURCE_WEIGHT.get(source.get("source_kind"), 0.65)
            * _freshness(source))


def build_normalized_matrix(matrix: dict[str, Any], areas: dict[str, float]) -> dict[str, Any]:
    groups = _source_groups(matrix)
    target_class = matrix.get("housing_class", "business")
    rows = []
    for spec in ROW_SPECS:
        values, aggregate_points = [], []
        for group, label, sources in groups:
            source, cell = _best_group_candidate(sources, spec, areas, target_class)
            item = {"group": group, "label": label, "value": None,
                    "low": None, "high": None, "grade": None}
            if source and cell:
                item.update({"value": cell["value"], "low": cell["low"], "high": cell["high"],
                             "grade": cell["grade"], "source_id": source.get("source_id")})
                weight = _weight(source, cell)
                if weight > 0:
                    aggregate_points.append((cell["value"], weight))
            values.append(item)
        total_weight = sum(weight for _, weight in aggregate_points)
        aggregate = (sum(value * weight for value, weight in aggregate_points) / total_weight
                     if total_weight else None)
        # Разброс входящих чисел — часть ответа, а не подробность. «Агрегат 192,0
        # · N 4» читается как согласие четырёх источников, а под ним лежали
        # 90,7 и 265,8: втрое, и все четыре в ответе. Веса тут ни при чём —
        # видно должно быть то, из чего среднее получилось.
        contributing = [value for value, _ in aggregate_points]
        low = min(contributing) if contributing else None
        high = max(contributing) if contributing else None
        rows.append({
            "key": spec["key"], "label": spec["label"], "unit": spec["unit"],
            "unit_label": UNIT_LABELS.get(spec["unit"], spec["unit"]),
            "values": values, "aggregate": aggregate, "n": len(aggregate_points),
            "spread_low": low, "spread_high": high,
            "spread_ratio": (high / low if low and high and low > 0 else None),
        })
    return {"groups": [{"group": group, "label": label} for group, label, _ in groups],
            "rows": rows}


def _aggregate_note(row: dict[str, Any]) -> str:
    """Подпись под агрегатом: один источник или разброс тех, что вошли."""
    if row["aggregate"] is None:
        return ""
    if row["n"] == 1:
        return '<div class="small">1 источник</div>'
    low, high = row.get("spread_low"), row.get("spread_high")
    ratio = row.get("spread_ratio")
    if low is None or high is None or not ratio or ratio < _SPREAD_VISIBLE:
        return ""
    wide = ' wide' if ratio >= _SPREAD_WIDE else ''
    return f'<div class="small spread{wide}">{_fmt(low)}–{_fmt(high)}</div>'


def _render_matrix(payload: dict[str, Any]) -> str:
    headers = ["Параметр DevelopAid", "Единая база"] \
        + [group["label"] for group in payload["groups"]] + ["Агрегат", "N"]
    head = "".join(f"<th>{_esc(x)}</th>" for x in headers)
    body = []
    for row in payload["rows"]:
        cells = [f'<td class="rowname"><b>{_esc(row["label"])}</b></td>',
                 f'<td class="base">{_esc(row["unit_label"])}</td>']
        for item in row["values"]:
            if item["value"] is None:
                cells.append('<td class="num blank"></td>')
                continue
            span = ""
            if item["low"] is not None and item["high"] is not None \
                    and abs(item["high"] - item["low"]) > 0.5:
                span = f'<div class="small">{_fmt(item["low"])}–{_fmt(item["high"])}</div>'
            cells.append(f'<td class="num">{_fmt(item["value"])} '
                         f'<span class="grade">{_esc(item["grade"])}</span>{span}</td>')
        cells.append(f'<td class="num aggregate">{_fmt(row["aggregate"])}'
                     f'{_aggregate_note(row)}</td>')
        cells.append(f'<td class="n">{row["n"]}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    return ('<div class="tablewrap"><table><thead><tr>' + head
            + '</tr></thead><tbody>' + "".join(body) + '</tbody></table></div>')


_CSS = """
*{box-sizing:border-box}body{margin:0;background:#f4f5f7;color:#202833;font:14px -apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif}
.wrap{max-width:1600px;margin:auto;padding:0 22px 40px}/* Эмблема — чёрное на белом, без прозрачности: она одна на все поверхности и лежит в `PAGE`, а копии с альфой негде обновлять. На светлой странице белый прямоугольник вокруг букв виден цветом (владелец, 31.08.2026), поэтому фон снимается наложением: multiply оставляет буквы и растворяет белое в любой светлой подложке. */
.brandbar{padding:22px 0 0}.brandbar img{display:block;width:min(360px,58vw);height:auto;mix-blend-mode:multiply}.brandline{height:8px;background:#050505;margin-top:12px}
h1{font-size:34px;margin:26px 0 8px}h2{font-size:20px;margin:0 0 7px}.sub,.note,.small{color:#737d8d}.note{line-height:1.5;margin-bottom:12px}
.filters{display:grid;grid-template-columns:1.1fr .9fr repeat(4,1fr) auto;gap:8px;background:#fff;border:1px solid #dfe4ea;border-radius:14px;padding:14px;margin:16px 0 18px}
.field label{display:block;font-size:10px;color:#788291;margin-bottom:5px}.field .hint{font-size:9px;color:#98a0ab;margin-top:3px}
input,select,button{width:100%;height:42px;border:1px solid #d5dae2;border-radius:8px;background:#fff;padding:0 9px;font:inherit}
button{background:#192231;color:#fff;border-color:#192231;cursor:pointer}
.tablewrap{overflow:auto;background:#fff;border:1px solid #dfe4ea;border-radius:12px}
table{width:100%;border-collapse:collapse;font-size:12px;min-width:1250px}
th,td{padding:9px;border-bottom:1px solid #edf0f4;border-right:1px solid #f0f2f5;vertical-align:top}
th{background:#fafbfc;color:#717b89;font-size:10px;text-transform:uppercase;text-align:left}
.rowname{min-width:255px}.base{min-width:150px;color:#667080}
.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums;min-width:120px}
.blank{background:#fbfcfd}.aggregate{background:#edf3f7;font-weight:800}.n{text-align:center;background:#f7f8fa;font-weight:700}
.grade{font-size:9px;color:#758090}.small{font-size:9px;margin-top:3px}.spread{font-weight:600;color:#6b7684}.spread.wide{color:#a4451f}.section{margin-top:26px}
.info{background:#eef4f8;border:1px solid #d4e0e8;color:#566b7b;padding:10px 13px;border-radius:10px;margin:8px 0}
.method{background:#fff8e6;border:1px solid #eedca3;color:#6d581e;padding:10px 13px;border-radius:10px;margin:8px 0}
.legal-footer{display:flex;gap:18px;flex-wrap:wrap;padding:16px 0 24px;margin-top:26px;font-size:11px;color:#737d8d;border-top:1px solid #dfe4ea}
.legal-footer a{color:#737d8d}
@media(max-width:1100px){.filters{grid-template-columns:repeat(3,1fr)}}
@media(max-width:700px){.filters{grid-template-columns:1fr}.wrap{padding:0 10px 30px}h1{font-size:29px}}
"""


def _page(core, region: str, housing_class: str, areas: dict[str, float],
          example: bool, normalized: dict[str, Any]) -> str:
    from guide import legal_footer_html

    options = class_options(core)
    if housing_class not in dict(options) and options:
        housing_class = options[0][0]
    class_opts = "".join(
        f'<option value="{_esc(key)}"{" selected" if housing_class == key else ""}>{_esc(label)}</option>'
        for key, label in options)

    def field(key: str) -> str:
        value = areas.get(key)
        return "" if value is None else f"{value:g}"

    ratio = building_total_ratio(core)
    example_html = (f'<div class="info">Полей ТЭП нет — подставлен {EXAMPLE_LABEL}, '
                    'иначе приводить источники к одной базе не из чего. '
                    'Впишите свои площади и нажмите «Пересчитать».</div>') if example else ""
    method_html = (
        '<div class="method"><b>Приведение к одной базе.</b> Отдельную «общую площадь здания» '
        f'вводить не надо: для источников, публикующих ставку на неё, она берётся как {ratio * 100:.0f}% ГНС — '
        'то же отношение, что у расчёта DevelopAid (две выгрузки ГлавАПУ), — и такая ячейка помечается grade C. '
        'Для источников на площадь квартир используется введённая продаваемая площадь жилья.</div>')

    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DevelopAid — Свод источников себестоимости</title>
<style>{_CSS}{_contour.STYLE}</style></head>
<body><div class="wrap">
<div class="brandbar"><a href="/" title="DevelopAid"><img src="/guide/assets/logo.webp" alt="ПЛАТО"></a><div class="brandline"></div></div>
{_contour.markup("/statistics")}
<h1>Себестоимость: свод источников</h1>
<div class="sub">Строки — параметры DevelopAid, столбцы — источники. У источника берётся только то,
что содержит его методика: чего в ней нет, то остаётся пустой ячейкой, а не подставляется оценкой.
Раскрытые данные сначала приводятся к базе строки (ГНС, наземная, подземная), потом агрегируются.</div>
{example_html}
<form class="filters" method="get">
  <div class="field"><label>Регион</label><input name="region" value="{_esc(region)}"></div>
  <div class="field"><label>Класс</label><select name="class">{class_opts}</select></div>
  <div class="field"><label>Общая ГНС, м²</label><input name="gba_sqm" inputmode="decimal" value="{field('gba_sqm')}"></div>
  <div class="field"><label>Продаваемая площадь жилья, м²</label><input name="sellable_sqm" inputmode="decimal" value="{field('sellable_sqm')}"></div>
  <div class="field"><label>Подземная ГНС, м²</label><input name="underground_gns_sqm" inputmode="decimal" value="{field('underground_gns_sqm')}"></div>
  <div class="field"><label>Наземная ГНС, м²</label><input name="above_ground_gns_sqm" inputmode="decimal" value="{field('above_ground_gns_sqm')}"><div class="hint">авто = общая − подземная</div></div>
  <button>Пересчитать</button>
</form>
{method_html}
<div class="section"><h2>Приведённая таблица · {_esc(CLASS_LABELS.get(housing_class, housing_class))}</h2>
<div class="note">Все значения — <b>тыс. ₽/м²</b> на базе строки. A — прямое число источника;
B — механический пересчёт базы или класса; C — расчёт из явно раскрытой доли либо контрольный итог
с другим scope. «Сети + благоустройство» СИС остаётся одной строкой и не делится искусственно.
Под агрегатом стоит разброс вошедших чисел, если они расходятся больше чем в полтора раза:
<b>N — это сколько источников ответило, а не насколько они согласны</b>.</div>
{_render_matrix(normalized)}</div>
<div class="section"><div class="note">ТЭП: ГНС {_fmt_area(areas.get('gba_sqm'))} ·
продаваемая жилья {_fmt_area(areas.get('sellable_sqm'))} ·
подземная {_fmt_area(areas.get('underground_gns_sqm'))} ·
наземная {_fmt_area(areas.get('above_ground_gns_sqm'))} м².
Расчётная общая площадь здания {_fmt_area(areas.get('building_total_sqm'))} м².</div></div>
{LEGAL_FOOTER_PLACEHOLDER}
</div></body></html>'''.replace(LEGAL_FOOTER_PLACEHOLDER, legal_footer_html(core))


def install(app, core):
    """Восемь маршрутов свода. Ставится один раз, снимать нечего."""

    @app.get("/api/statistics/construction-cost")
    def construction_cost(
        region: str = Query(...), housing_class: str = Query("comfort", alias="class"),
        city: str | None = None, unit: str = "gba",
        metric_type: str = "main_construction", cost_scope: str | None = None,
        floors_min: int | None = None, floors_max: int | None = None,
        construction_type: str | None = None, underground_parking: bool | None = None,
    ):
        result = build_benchmark(
            load_observations(), load_external_benchmarks(),
            normalized=load_normalized_benchmarks(),
            region=region, housing_class=housing_class, city=city, unit=unit,
            metric_type=metric_type, cost_scope=cost_scope,
            floors_min=floors_min, floors_max=floors_max,
            construction_type=construction_type, underground_parking=underground_parking,
        )
        return result_to_dict(result)

    @app.get("/api/statistics/sources")
    def statistics_sources(region: str | None = None):
        rows = source_catalog()
        if region:
            rows = [row for row in rows if row.get("region") == region]
        return {"count": len(rows), "sources": rows, "methodology_version": "2.1"}

    @app.get("/api/statistics/index-sources")
    def statistics_index_sources():
        rows = index_source_catalog()
        return {"count": len(rows), "sources": rows, "methodology_version": "2.1"}

    @app.get("/api/statistics/class-adjustments")
    def statistics_class_adjustments():
        return class_adjustment_catalog()

    @app.get("/api/statistics/cost-structure")
    def statistics_cost_structure(region: str = "Москва",
                                  housing_class: str = Query("business", alias="class")):
        return build_cost_structure_matrix(region=region, housing_class=housing_class)

    @app.get("/api/statistics/cost-recommendation")
    def statistics_cost_recommendation(
        region: str = "Москва", housing_class: str = Query("business", alias="class"),
        gba_sqm: str | None = None, sellable_sqm: str | None = None,
        underground_gns_sqm: str | None = None, above_ground_gns_sqm: str | None = None,
    ):
        areas, _ = _areas(core, gba_sqm, sellable_sqm, underground_gns_sqm, above_ground_gns_sqm)
        return build_cost_recommendation(region=region, housing_class=housing_class,
                                         target_areas=areas)

    @app.get("/api/statistics/normalized-matrix")
    def normalized_matrix(
        region: str = "Москва", housing_class: str = Query("business", alias="class"),
        gba_sqm: str | None = None, sellable_sqm: str | None = None,
        underground_gns_sqm: str | None = None, above_ground_gns_sqm: str | None = None,
    ):
        areas, example = _areas(core, gba_sqm, sellable_sqm, underground_gns_sqm, above_ground_gns_sqm)
        matrix = build_cost_structure_matrix(region=region, housing_class=housing_class)
        return {
            "areas": areas,
            "example_areas": example,
            "building_total_ratio": building_total_ratio(core),
            **build_normalized_matrix(matrix, areas),
        }

    @app.get("/statistics", response_class=HTMLResponse)
    def statistics_page(
        region: str = "Москва", housing_class: str = Query("business", alias="class"),
        gba_sqm: str | None = None, sellable_sqm: str | None = None,
        underground_gns_sqm: str | None = None, above_ground_gns_sqm: str | None = None,
    ):
        areas, example = _areas(core, gba_sqm, sellable_sqm, underground_gns_sqm, above_ground_gns_sqm)
        matrix = build_cost_structure_matrix(region=region, housing_class=housing_class)
        normalized = build_normalized_matrix(matrix, areas)
        return HTMLResponse(_page(core, region, housing_class, areas, example, normalized))

    return app

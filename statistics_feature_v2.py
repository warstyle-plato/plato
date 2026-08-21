from __future__ import annotations

import html
import json
from typing import Any

from fastapi import Query
from fastapi.responses import HTMLResponse

from developaid_cost_aggregation import build_cost_recommendation
from developaid_cost_structure import CLASS_LABELS, UNIT_LABELS, build_cost_structure_matrix
from statistics_feature import install as install_legacy


GRODNO_SOURCE_ID = "developaid-grodnenskaya-structure-2026-07"
GRODNO_UNDERGROUND_RUB_M2 = 210_000.0

PROJECT_PRESETS = {
    "grodno": {
        "label": "Гродненская, 18",
        "region": "Москва",
        "housing_class": "business",
        "gba_sqm": 22032.9,
        "sellable_sqm": 13710.0,
        "underground_gns_sqm": 3629.0,
    },
    "profsoyuznaya": {
        "label": "Профсоюзная",
        "region": "Москва",
        "housing_class": "business",
        "gba_sqm": 60322.0,
        "sellable_sqm": 31526.0,
        "underground_gns_sqm": 12915.0,
    },
}

DISPLAY_COMPONENTS = [
    "preparation",
    "design",
    "main_above",
    "main_under",
    "external_utilities",
    "landscaping",
    "technical_connection",
    "commissioning",
    "site_maintenance",
    "tech_customer",
    "project_management",
    "reserve",
    "construction_capex",
]


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _parse_area(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if float(value) > 0 else None
    cleaned = str(value).strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
    if not cleaned:
        return None
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return number if number > 0 else None


def _fmt_input(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:g}"


def _fmt_money(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value / 1000:,.1f}".replace(",", " ").replace(".", ",")


def _fmt_area(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.1f}".replace(",", " ").replace(".", ",")


def _remove_route(app, path: str) -> None:
    app.router.routes[:] = [route for route in app.router.routes if getattr(route, "path", None) != path]


def _correct_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    """Temporary source correction until the curated JSON is regenerated.

    The earlier 592.5k/m² value came from an intermediate control workbook and
    used the wrong denominator. The underlying FM has ~762m RUB of underground
    cost and 3,629 m² underground GNS, i.e. about 210k RUB/m².
    """
    for source in matrix.get("sources", []):
        if source.get("source_id") != GRODNO_SOURCE_ID:
            continue
        cell = source.get("cells", {}).get("main_under")
        if not cell:
            continue
        cell["value_rub_m2"] = GRODNO_UNDERGROUND_RUB_M2
        cell["adjusted_value_rub_m2"] = GRODNO_UNDERGROUND_RUB_M2
        cell["source_value_rub_m2"] = GRODNO_UNDERGROUND_RUB_M2
        cell["note"] = "По исходной ФМ: ~762 млн ₽ / 3 629 м² подземной ГНС ≈ 210 тыс. ₽/м²."
    return matrix


def _weighted_mean(rows: list[dict[str, Any]], key: str) -> float | None:
    valid = [r for r in rows if r.get("included") and r.get("weight", 0) > 0 and r.get(key) is not None]
    if not valid:
        return None
    total_weight = sum(float(r["weight"]) for r in valid)
    return sum(float(r[key]) * float(r["weight"]) for r in valid) / total_weight


def _correct_recommendation(payload: dict[str, Any]) -> dict[str, Any]:
    for row in payload.get("recommendations", []):
        if row.get("key") != "main_under":
            continue
        sources = row.get("included_sources", []) + row.get("excluded_sources", [])
        for source in sources:
            if source.get("source_id") == GRODNO_SOURCE_ID:
                source["value_rub_m2"] = GRODNO_UNDERGROUND_RUB_M2
                source["low_rub_m2"] = GRODNO_UNDERGROUND_RUB_M2
                source["high_rub_m2"] = GRODNO_UNDERGROUND_RUB_M2
                source["reason"] = "Исправлено по исходной ФМ: ~762 млн ₽ / 3 629 м² подземной ГНС."
        included = [s for s in row.get("included_sources", []) if s.get("included")]
        recommended = _weighted_mean(included, "value_rub_m2")
        low = _weighted_mean(included, "low_rub_m2")
        high = _weighted_mean(included, "high_rub_m2")
        row["recommended_rub_m2"] = round(recommended, 2) if recommended is not None else None
        row["range_low_rub_m2"] = round(low, 2) if low is not None else None
        row["range_high_rub_m2"] = round(high, 2) if high is not None else None
        baseline = next((s.get("value_rub_m2") for s in included if s.get("source_kind") == "internal_project"), None)
        row["baseline_rub_m2"] = baseline
        if baseline and recommended:
            row["delta_to_baseline_pct"] = round((recommended / baseline - 1) * 100, 1)
    params = payload.get("model_parameters_th_rub_m2", {})
    row = next((r for r in payload.get("recommendations", []) if r.get("key") == "main_under"), None)
    if row and row.get("recommended_rub_m2") is not None:
        params["main_under_th_per_sqm"] = round(float(row["recommended_rub_m2"]) / 1000, 3)
    return payload


def _areas_from_query(gba: Any, sellable: Any, underground: Any, above: Any) -> dict[str, float]:
    clean: dict[str, float] = {}
    g = _parse_area(gba)
    s = _parse_area(sellable)
    u = _parse_area(underground)
    a = _parse_area(above)
    if g is not None:
        clean["gba_sqm"] = g
    if s is not None:
        clean["sellable_sqm"] = s
    if u is not None:
        clean["underground_gns_sqm"] = u
    if a is not None:
        clean["above_ground_gns_sqm"] = a
    elif g is not None and u is not None and g > u:
        clean["above_ground_gns_sqm"] = g - u
    return clean


def _source_groups(payload: dict[str, Any]) -> list[dict[str, str]]:
    seen: dict[str, dict[str, str]] = {}
    for article in payload.get("recommendations", []):
        for source in article.get("included_sources", []) + article.get("excluded_sources", []):
            group = str(source.get("source_group") or source.get("source_id") or source.get("source"))
            current = seen.get(group)
            candidate = {"group": group, "label": str(source.get("source") or group)}
            # Prefer the exact target-class slice, otherwise keep the first title.
            if current is None or source.get("base_class") == payload.get("housing_class"):
                seen[group] = candidate
    return list(seen.values())


def _pick_source(article: dict[str, Any], group: str, target_class: str) -> dict[str, Any] | None:
    matches = [
        s for s in article.get("included_sources", []) + article.get("excluded_sources", [])
        if str(s.get("source_group") or s.get("source_id") or s.get("source")) == group
    ]
    if not matches:
        return None
    matches.sort(key=lambda s: (0 if s.get("included") else 1, 0 if s.get("base_class") == target_class else 1))
    return matches[0]


def _normalized_matrix(payload: dict[str, Any]) -> str:
    groups = _source_groups(payload)
    rec_by_key = {r.get("key"): r for r in payload.get("recommendations", [])}
    headers = ["Параметр DevelopAid", "Единая база"] + [g["label"] for g in groups] + ["Агрегат", "N"]
    head = "".join(f"<th>{_esc(x)}</th>" for x in headers)
    rows: list[str] = []
    for key in DISPLAY_COMPONENTS:
        article = rec_by_key.get(key)
        if not article:
            continue
        cells = [
            f'<td class="rowname"><b>{_esc(article.get("label"))}</b></td>',
            f'<td class="base">{_esc(article.get("unit_label"))}</td>',
        ]
        for group in groups:
            source = _pick_source(article, group["group"], payload.get("housing_class", ""))
            value = None
            grade = None
            if source and source.get("value_rub_m2") is not None and source.get("grade") != "D":
                value = float(source["value_rub_m2"])
                grade = source.get("grade")
            if value is None:
                cells.append('<td class="num blank"></td>')
            else:
                grade_html = f'<span class="grade">{_esc(grade)}</span>' if grade else ""
                cells.append(f'<td class="num">{_fmt_money(value)} {grade_html}</td>')
        aggregate = article.get("recommended_rub_m2")
        n = int(article.get("source_count", 0) or 0)
        agg_note = ""
        if aggregate is not None and n == 1:
            agg_note = '<div class="small">1 источник</div>'
        cells.append(f'<td class="num aggregate">{_fmt_money(aggregate)}{agg_note}</td>')
        cells.append(f'<td class="n">{n}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return '<div class="tablewrap"><table class="norm"><thead><tr>' + head + '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>'


def _raw_matrix(matrix: dict[str, Any]) -> str:
    sources = matrix.get("sources", [])
    headers = ["Статья"] + [str(s.get("source")) for s in sources]
    head = "".join(f"<th>{_esc(x)}</th>" for x in headers)
    rows = []
    component_by_key = {c.get("key"): c for c in matrix.get("components", [])}
    for key in DISPLAY_COMPONENTS:
        component = component_by_key.get(key)
        if not component:
            continue
        cells = [f'<td class="rowname"><b>{_esc(component.get("label"))}</b></td>']
        for source in sources:
            cell = source.get("cells", {}).get(key, {})
            value = cell.get("adjusted_value_rub_m2", cell.get("value_rub_m2"))
            if value is None or cell.get("status") not in {"value", "separate_denominator", "source_aggregate"}:
                cells.append('<td class="num blank"></td>')
            else:
                cells.append(f'<td class="num">{_fmt_money(float(value))}<div class="small">{_esc(cell.get("unit_label") or UNIT_LABELS.get(cell.get("unit"), ""))}</div></td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return '<div class="tablewrap"><table><thead><tr>' + head + '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>'


def install(app):
    # Keep the legacy APIs, but replace the two user-facing endpoints below.
    install_legacy(app)
    _remove_route(app, "/statistics")
    _remove_route(app, "/api/statistics/cost-recommendation")
    _remove_route(app, "/api/statistics/cost-structure")

    @app.get("/api/statistics/cost-structure")
    def cost_structure(region: str = "Москва", housing_class: str = Query("business", alias="class")):
        return _correct_matrix(build_cost_structure_matrix(region=region, housing_class=housing_class))

    @app.get("/api/statistics/cost-recommendation")
    def cost_recommendation(
        region: str = "Москва",
        housing_class: str = Query("business", alias="class"),
        gba_sqm: str | None = None,
        sellable_sqm: str | None = None,
        underground_gns_sqm: str | None = None,
        above_ground_gns_sqm: str | None = None,
    ):
        areas = _areas_from_query(gba_sqm, sellable_sqm, underground_gns_sqm, above_ground_gns_sqm)
        return _correct_recommendation(build_cost_recommendation(region=region, housing_class=housing_class, target_areas=areas))

    @app.get("/statistics", response_class=HTMLResponse)
    def statistics_page(
        region: str = "Москва",
        housing_class: str = Query("business", alias="class"),
        gba_sqm: str | None = None,
        sellable_sqm: str | None = None,
        underground_gns_sqm: str | None = None,
        above_ground_gns_sqm: str | None = None,
    ):
        areas = _areas_from_query(gba_sqm, sellable_sqm, underground_gns_sqm, above_ground_gns_sqm)
        recommendation = _correct_recommendation(build_cost_recommendation(region=region, housing_class=housing_class, target_areas=areas))
        matrix = _correct_matrix(build_cost_structure_matrix(region=region, housing_class=housing_class))
        norm_html = _normalized_matrix(recommendation)
        raw_html = _raw_matrix(matrix)
        classes = [("standard", "Стандарт"), ("comfort", "Комфорт"), ("business", "Бизнес"), ("premium", "Премиум"), ("elite", "Элитный")]
        class_opts = "".join(f'<option value="{key}" {"selected" if housing_class == key else ""}>{label}</option>' for key, label in classes)
        g = areas.get("gba_sqm")
        s = areas.get("sellable_sqm")
        u = areas.get("underground_gns_sqm")
        a = areas.get("above_ground_gns_sqm")
        preset_links = " · ".join(
            f'<a href="/statistics?region={_esc(p["region"])}&class={p["housing_class"]}&gba_sqm={p["gba_sqm"]}&sellable_sqm={p["sellable_sqm"]}&underground_gns_sqm={p["underground_gns_sqm"]}">{_esc(p["label"])}</a>'
            for p in PROJECT_PRESETS.values()
        )
        preset_json = json.dumps(recommendation.get("model_parameters_th_rub_m2", {}), ensure_ascii=False).replace("</", "<\\/")
        css = """
        *{box-sizing:border-box}body{margin:0;background:#f4f5f7;color:#202833;font:14px -apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif}.wrap{max-width:1550px;margin:auto;padding:28px 22px 70px}.top{display:flex;justify-content:space-between;align-items:center}.brand{font-weight:800;font-size:20px}.tag{font-size:11px;border:1px solid #d8dde5;background:#fff;padding:6px 10px;border-radius:999px}h1{font-size:34px;margin:26px 0 8px}h2{font-size:20px;margin:0 0 7px}.sub,.note,.small{color:#737d8d}.note{line-height:1.5;margin-bottom:12px}.presets{margin:10px 0}.presets a{color:#185d94}.filters{display:grid;grid-template-columns:1.2fr 1fr repeat(4,1fr) auto;gap:9px;background:#fff;border:1px solid #dfe4ea;border-radius:14px;padding:14px;margin:16px 0 22px}.field label{display:block;font-size:10px;color:#788291;margin-bottom:5px}.field .hint{font-size:9px;color:#98a0ab;margin-top:4px}input,select,button{width:100%;height:42px;border:1px solid #d5dae2;border-radius:8px;background:#fff;padding:0 10px;font:inherit}button{background:#192231;color:#fff;border-color:#192231;cursor:pointer}.tablewrap{overflow:auto;background:#fff;border:1px solid #dfe4ea;border-radius:12px}table{width:100%;border-collapse:collapse;font-size:12px;min-width:1050px}th,td{padding:10px;border-bottom:1px solid #edf0f4;border-right:1px solid #f0f2f5;vertical-align:top}th{background:#fafbfc;color:#717b89;font-size:10px;text-transform:uppercase;text-align:left}.rowname{min-width:230px}.base{min-width:145px;color:#667080}.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums;min-width:115px}.blank{background:#fbfcfd}.aggregate{background:#f1f5f8;font-weight:800}.n{text-align:center;background:#f7f8fa;font-weight:700}.grade{font-size:9px;color:#667080;margin-left:3px}.small{font-size:9px;margin-top:3px}.section{margin-top:28px}.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:11px;color:#6c7684;margin:8px 0 12px}.action{display:flex;gap:10px;align-items:center;margin:12px 0}.action button{width:auto}.details{margin-top:28px}.details summary{cursor:pointer;font-weight:700;padding:10px 0}.warning{background:#fff8e6;border:1px solid #eedca3;color:#6d581e;padding:12px 14px;border-radius:12px;margin:10px 0}@media(max-width:900px){.filters{grid-template-columns:1fr}.wrap{padding:18px 10px 50px}h1{font-size:29px}}
        """
        missing = []
        for key, label in (("gba_sqm", "общая ГНС"), ("sellable_sqm", "продаваемая площадь"), ("underground_gns_sqm", "подземная ГНС")):
            if key not in areas:
                missing.append(label)
        warning = ""
        if missing:
            warning = '<div class="warning"><b>Для нормализации не хватает:</b> ' + _esc(", ".join(missing)) + ". Наземную ГНС можно не вводить: она считается как общая ГНС − подземная.</div>"
        body = f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DevelopAid — Себестоимость</title><style>{css}</style></head><body><div class="wrap">
        <div class="top"><div class="brand">DevelopAid</div><div class="tag">COST BENCHMARK · NORMALIZED</div></div>
        <h1>Себестоимость строительства</h1>
        <div class="sub">Все источники приводятся к одним статьям DevelopAid и к одной базе площади. Если источник статью не раскрывает — ячейка остаётся пустой.</div>
        <div class="presets">Быстрая проверка: {preset_links}</div>
        <form class="filters" method="get">
          <div class="field"><label>Регион</label><input name="region" value="{_esc(region)}"></div>
          <div class="field"><label>Класс</label><select name="class">{class_opts}</select></div>
          <div class="field"><label>Общая ГНС, м²</label><input name="gba_sqm" inputmode="decimal" value="{_fmt_input(g)}"></div>
          <div class="field"><label>Продаваемая площадь, м²</label><input name="sellable_sqm" inputmode="decimal" value="{_fmt_input(s)}"></div>
          <div class="field"><label>Подземная ГНС, м²</label><input name="underground_gns_sqm" inputmode="decimal" value="{_fmt_input(u)}"></div>
          <div class="field"><label>Наземная ГНС, м²</label><input name="above_ground_gns_sqm" inputmode="decimal" value="{_fmt_input(a)}"><div class="hint">можно оставить пустым — посчитается автоматически</div></div>
          <button>Пересчитать</button>
        </form>
        {warning}
        <div class="section"><h2>Нормализованная таблица · {_esc(CLASS_LABELS.get(housing_class, housing_class))}</h2>
        <div class="note">Все числа ниже — <b>тыс. ₽/м²</b> уже после приведения к базе в колонке «Единая база». Пусто = у источника нет сопоставимой статьи. Последние две колонки — агрегированный ориентир DevelopAid и количество независимых источников.</div>
        <div class="legend"><span>A — прямое совпадение</span><span>B — механический пересчёт базы/класса</span><span>C — оценочная декомпозиция</span></div>
        {norm_html}
        <div class="action"><button id="copyPreset" type="button">Скопировать агрегированные параметры</button><span class="small" id="copyState"></span></div></div>
        <details class="details"><summary>Показать исходную таблицу до нормализации</summary><div class="note">Это контрольный слой: исходные значения и исходные знаменатели. Он не используется как основная рабочая таблица.</div>{raw_html}</details>
        <div class="section"><div class="note">ТЭП: общая ГНС {_fmt_area(g)} м² · продаваемая {_fmt_area(s)} м² · подземная {_fmt_area(u)} м² · наземная {_fmt_area(a)} м².</div></div>
        </div><script>const preset={preset_json};document.getElementById('copyPreset').addEventListener('click',async function(){{try{{await navigator.clipboard.writeText(JSON.stringify(preset,null,2));document.getElementById('copyState').textContent='Скопировано'}}catch(e){{document.getElementById('copyState').textContent='Не удалось скопировать'}}}});</script></body></html>'''
        return HTMLResponse(body)

    return app

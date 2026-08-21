from __future__ import annotations

import html
import json

from fastapi import Query
from fastapi.responses import HTMLResponse

from developaid_cost_aggregation import build_cost_recommendation
from developaid_cost_structure import (
    CLASS_LABELS,
    UNIT_LABELS as STRUCTURE_UNIT_LABELS,
    build_cost_structure_matrix,
    class_adjustment_catalog,
)
from developaid_statistics import (
    METRIC_LABELS,
    UNIT_LABELS,
    build_benchmark,
    index_source_catalog,
    load_external_benchmarks,
    load_normalized_benchmarks,
    load_observations,
    result_to_dict,
    source_catalog,
)

CONF_LABELS = {
    "high": "Высокая",
    "medium": "Средняя",
    "limited": "Ограниченная",
    "pilot": "Пилотная",
    "insufficient": "Недостаточно данных",
}


def _esc(value) -> str:
    return html.escape(str(value or ""))


def _fmt(value) -> str:
    if value is None:
        return "—"
    return f"{float(value) / 1000:,.1f}".replace(",", " ").replace(".", ",") + " тыс. ₽/м²"


def _fmt_pct(value) -> str:
    if value is None:
        return "—"
    sign = "+" if float(value) > 0 else ""
    return (f"{sign}{float(value):.1f}%").replace(".", ",")


def _fmt_sqm(value) -> str:
    if value in (None, ""):
        return ""
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return ""


def _fmt_range(low, high, value=None) -> str:
    if low is not None and high is not None and float(low) != float(high):
        return f"{_fmt(low)} — {_fmt(high)}"
    return _fmt(value if value is not None else low)


def _matrix_cell(cell: dict) -> str:
    status = cell.get("status", "not_disclosed")
    note = cell.get("note")
    title = f' title="{_esc(note)}"' if note else ""
    if status in {"value", "source_aggregate"}:
        value = cell.get("adjusted_value_rub_m2", cell.get("value_rub_m2"))
        low = cell.get("adjusted_value_low_rub_m2", cell.get("value_low_rub_m2"))
        high = cell.get("adjusted_value_high_rub_m2", cell.get("value_high_rub_m2"))
        source_value = cell.get("source_value_rub_m2", cell.get("value_rub_m2"))
        unit_label = cell.get("unit_label") or STRUCTURE_UNIT_LABELS.get(cell.get("unit"), cell.get("unit", ""))
        badge = ""
        detail = f'<div class="tiny">{_esc(unit_label)}</div>' if unit_label else ""
        if cell.get("class_adjusted"):
            ratio = float(cell.get("class_adjustment_ratio", 1))
            badge = '<span class="badge b">B</span>'
            detail = f'<div class="tiny">из {_fmt(source_value)} · ×{ratio:.2f} по классу<br>{_esc(unit_label)}</div>'
        return f'<div class="value"{title}>{_fmt_range(low, high, value)} {badge}</div>{detail}'
    if status == "share":
        return f'<span{title}>{cell.get("share_pct")}%</span>'
    if status == "share_range":
        return f'<span{title}>{cell.get("share_low_pct")}–{cell.get("share_high_pct")}%</span>'
    if status == "combined_share":
        return f'<span{title}>{cell.get("share_low_pct")}–{cell.get("share_high_pct")}% вместе*</span>'
    if status == "unallocated_remainder":
        return f'<span class="muted"{title}>остаток {cell.get("share_low_pct")}–{cell.get("share_high_pct")}%*</span>'
    if status == "separate_denominator":
        unit_label = cell.get("unit_label") or STRUCTURE_UNIT_LABELS.get(cell.get("unit"), cell.get("unit", ""))
        return f'<div class="muted"{title}>{_fmt(cell.get("value_rub_m2"))}<div class="tiny">{_esc(unit_label)}</div></div>'
    labels = {
        "included_in_aggregate": "входит в агрегат",
        "included_in_broader_total": "входит в более широкий итог",
        "included_residual": "входит в нераскрытый остаток",
        "outside_scope": "вне scope",
    }
    return f'<span class="muted"{title}>{labels.get(status, "н/д")}</span>'


def _cost_structure_table(matrix: dict) -> str:
    sources = matrix.get("sources", [])
    if not sources:
        return '<div class="box">Нет источников для выбранного региона.</div>'
    headers = ['<th class="sticky">Статья DevelopAid</th>']
    for source in sources:
        published = source.get("published", {})
        name = _esc(source.get("source"))
        if source.get("source_url"):
            name = f'<a href="{_esc(source.get("source_url"))}" target="_blank" rel="noopener">{name}</a>'
        unit = source.get("published_unit_label") or STRUCTURE_UNIT_LABELS.get(published.get("unit"), published.get("unit", ""))
        line = _fmt_range(published.get("value_low_rub_m2"), published.get("value_high_rub_m2"), published.get("value_rub_m2"))
        vat = "с НДС" if source.get("vat_included") is True else "НДС: н/д"
        headers.append(
            '<th class="source">'
            f'<div>{name}</div><div class="headvalue">{line}</div>'
            f'<div class="tiny">{_esc(unit)}<br>класс: {_esc(source.get("base_class_label"))}'
            f'<br>цены: {_esc(source.get("price_basis_date") or source.get("reference_date"))} · {vat}</div>'
            '</th>'
        )
    body = []
    for component in matrix.get("components", []):
        key = component.get("key")
        total = " total" if key in {"construction_capex", "full_development_cost"} else ""
        cells = [f'<td class="sticky row{total}">{_esc(component.get("label"))}</td>']
        for source in sources:
            cells.append(f'<td class="cell{total}">{_matrix_cell(source.get("cells", {}).get(key, {}))}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    return '<div class="scroll"><table class="matrix"><thead><tr>' + "".join(headers) + '</tr></thead><tbody>' + "".join(body) + '</tbody></table></div>'


def _recommendation_table(payload: dict) -> str:
    rows = []
    for row in payload.get("recommendations", []):
        if row.get("recommended_rub_m2") is None and row.get("key") != "construction_capex":
            continue
        grades = row.get("grade_counts", {})
        grade_mix = " · ".join(f"{g}:{grades.get(g, 0)}" for g in ("A", "B", "C") if grades.get(g, 0)) or "—"
        model_key = row.get("model_key")
        key_note = f"→ {model_key}" if model_key else "аналитическая статья"
        rows.append(
            "<tr>"
            f'<td><b>{_esc(row.get("label"))}</b><div class="tiny">{_esc(row.get("unit_label"))}<br>{_esc(key_note)}</div></td>'
            f'<td class="num">{_fmt(row.get("baseline_rub_m2"))}</td>'
            f'<td class="num strong">{_fmt(row.get("recommended_rub_m2"))}</td>'
            f'<td class="num">{_fmt_range(row.get("range_low_rub_m2"), row.get("range_high_rub_m2"))}</td>'
            f'<td class="num">{_fmt_pct(row.get("delta_to_baseline_pct"))}</td>'
            f'<td>{row.get("source_count", 0)}<div class="tiny">{_esc(grade_mix)}</div></td>'
            f'<td>{_esc(CONF_LABELS.get(row.get("confidence"), row.get("confidence")))}</td>'
            "</tr>"
        )
    if not rows:
        return '<div class="box">Сопоставимых значений пока недостаточно.</div>'
    return (
        '<div class="scroll"><table><thead><tr><th>Параметр</th><th>Baseline DA</th><th>Consensus</th>'
        '<th>Диапазон источников</th><th>Δ</th><th>N / grade</th><th>Достоверность</th></tr></thead><tbody>'
        + "".join(rows) + '</tbody></table></div>'
    )


def _normalization_table(payload: dict) -> str:
    rows = []
    for article in payload.get("recommendations", []):
        sources = article.get("included_sources", []) + article.get("excluded_sources", [])
        for source in sources:
            included = source.get("included")
            status = '<span class="yes">участвует</span>' if included else '<span class="no">не участвует</span>'
            rows.append(
                "<tr>"
                f'<td>{_esc(article.get("label"))}</td>'
                f'<td>{_esc(source.get("source"))}<div class="tiny">цены {_esc(source.get("price_basis_date"))}</div></td>'
                f'<td><span class="badge {str(source.get("grade", "D")).lower()}">{_esc(source.get("grade"))}</span> {_esc(source.get("grade_label"))}</td>'
                f'<td>{_esc(source.get("source_unit_label"))}<div class="tiny">{_esc(source.get("normalization"))}</div></td>'
                f'<td class="num">{_fmt(source.get("value_rub_m2"))}<div class="tiny">{_esc(source.get("unit_label"))}</div></td>'
                f'<td class="num">{float(source.get("weight", 0)):.3f}</td>'
                f'<td>{status}</td><td>{_esc(source.get("reason"))}</td>'
                "</tr>"
            )
    return (
        '<div class="scroll"><table><thead><tr><th>Статья</th><th>Источник</th><th>Grade</th><th>Исходная база / преобразование</th>'
        '<th>Нормализовано</th><th>Вес</th><th>Агрегат</th><th>Причина</th></tr></thead><tbody>'
        + "".join(rows) + '</tbody></table></div>'
    )


def _class_table(catalog: dict, active_class: str) -> str:
    components = [
        ("main_above", "Основное строительство"),
        ("design", "ПИР / РД"),
        ("main_under", "Подземная часть"),
        ("external_utilities", "Наружные сети"),
        ("landscaping", "Благоустройство"),
        ("site_maintenance", "Содержание площадки"),
        ("tech_customer", "Техзаказчик"),
        ("project_management", "Управление проектом"),
    ]
    classes = catalog.get("classes", [])
    headers = '<th>Статья</th>' + ''.join(
        f'<th class="{"active" if c.get("key") == active_class else ""}">{_esc(c.get("label"))}</th>' for c in classes
    )
    rows = []
    cfg = catalog.get("components", {})
    for key, label in components:
        values = cfg.get(key, {})
        cells = ''.join(
            f'<td class="{"active" if c.get("key") == active_class else ""}">×{float(values.get(c.get("key"), 1)):.2f}</td>' for c in classes
        )
        rows.append(f'<tr><td>{_esc(label)}</td>{cells}</tr>')
    return f'<div class="scroll"><table class="coeff"><thead><tr>{headers}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def _source_rows(rows: list[dict]) -> str:
    result, seen = [], set()
    for row in rows:
        key = row.get("external_id") or (row.get("source"), row.get("reference_date"), row.get("metric_type"), row.get("unit"))
        if key in seen:
            continue
        seen.add(key)
        source = _esc(row.get("source"))
        if row.get("source_url"):
            source = f'<a href="{_esc(row.get("source_url"))}" target="_blank" rel="noopener">{source}</a>'
        result.append(
            f'<tr><td>{source}</td><td>{_esc(row.get("housing_class"))}</td><td>{_fmt(row.get("value_rub_m2"))}</td>'
            f'<td>{_esc(row.get("unit_label"))}</td><td>{_esc(row.get("metric_label"))}</td>'
            f'<td>{_esc(row.get("scope_label"))}</td><td>{_esc(row.get("reference_date"))}</td></tr>'
        )
    return "".join(result) or '<tr><td colspan="7">Нет источников.</td></tr>'


def _target_areas(gba_sqm, sellable_sqm, underground_gns_sqm, above_ground_gns_sqm, apartments_sqm, building_total_sqm):
    return {
        "gba_sqm": gba_sqm,
        "sellable_sqm": sellable_sqm,
        "underground_gns_sqm": underground_gns_sqm,
        "above_ground_gns_sqm": above_ground_gns_sqm,
        "apartments_sqm": apartments_sqm,
        "building_total_sqm": building_total_sqm,
    }


def install(app):
    @app.get("/api/statistics/construction-cost")
    def construction_cost(
        region: str = Query(...), housing_class: str = Query("comfort", alias="class"), city: str | None = None,
        unit: str = "gba", metric_type: str = "main_construction", cost_scope: str | None = None,
        floors_min: int | None = None, floors_max: int | None = None, construction_type: str | None = None,
        underground_parking: bool | None = None,
    ):
        result = build_benchmark(
            load_observations(), load_external_benchmarks(), normalized=load_normalized_benchmarks(),
            region=region, housing_class=housing_class, city=city, unit=unit, metric_type=metric_type,
            cost_scope=cost_scope, floors_min=floors_min, floors_max=floors_max,
            construction_type=construction_type, underground_parking=underground_parking,
        )
        return result_to_dict(result)

    @app.get("/api/statistics/cost-recommendation")
    def statistics_cost_recommendation(
        region: str = "Москва", housing_class: str = Query("business", alias="class"),
        gba_sqm: float | None = None, sellable_sqm: float | None = None,
        underground_gns_sqm: float | None = None, above_ground_gns_sqm: float | None = None,
        apartments_sqm: float | None = None, building_total_sqm: float | None = None,
    ):
        areas = _target_areas(gba_sqm, sellable_sqm, underground_gns_sqm, above_ground_gns_sqm, apartments_sqm, building_total_sqm)
        return build_cost_recommendation(region=region, housing_class=housing_class, target_areas=areas)

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

    @app.get("/api/statistics/cost-structure")
    def statistics_cost_structure(region: str = "Москва", housing_class: str = Query("business", alias="class")):
        return build_cost_structure_matrix(region=region, housing_class=housing_class)

    @app.get("/api/statistics/class-adjustments")
    def statistics_class_adjustments():
        return class_adjustment_catalog()

    @app.get("/statistics", response_class=HTMLResponse)
    def statistics_page(
        region: str = "Москва", housing_class: str = Query("business", alias="class"), city: str | None = None,
        unit: str = "gba", metric_type: str = "main_construction",
        gba_sqm: float | None = None, sellable_sqm: float | None = None,
        underground_gns_sqm: float | None = None, above_ground_gns_sqm: float | None = None,
        apartments_sqm: float | None = None, building_total_sqm: float | None = None,
    ):
        old = result_to_dict(build_benchmark(
            load_observations(), load_external_benchmarks(), normalized=load_normalized_benchmarks(),
            region=region, housing_class=housing_class, city=city, unit=unit, metric_type=metric_type,
        ))
        areas = _target_areas(gba_sqm, sellable_sqm, underground_gns_sqm, above_ground_gns_sqm, apartments_sqm, building_total_sqm)
        matrix = build_cost_structure_matrix(region=region, housing_class=housing_class)
        recommendation = build_cost_recommendation(region=region, housing_class=housing_class, target_areas=areas)
        coeffs = class_adjustment_catalog()
        matrix_html = _cost_structure_table(matrix)
        recommendation_html = _recommendation_table(recommendation)
        normalization_html = _normalization_table(recommendation)
        coeff_html = _class_table(coeffs, housing_class)

        class_opts = [("standard", "Стандарт"), ("comfort", "Комфорт"), ("business", "Бизнес"), ("premium", "Премиум"), ("elite", "Элитный")]
        opts = "".join(f'<option value="{v}" {"selected" if housing_class == v else ""}>{n}</option>' for v, n in class_opts)
        unit_opts = "".join(f'<option value="{v}" {"selected" if unit == v else ""}>{_esc(label)}</option>' for v, label in UNIT_LABELS.items())
        metric_opts = "".join(f'<option value="{v}" {"selected" if metric_type == v else ""}>{_esc(label)}</option>' for v, label in METRIC_LABELS.items())
        reg = _esc(region)
        cls_label = _esc(CLASS_LABELS.get(housing_class, housing_class))

        missing = recommendation.get("missing_area_inputs", [])
        if missing:
            quality_note = "Для полной нормализации заполните ТЭП: " + ", ".join(missing)
            warning_html = (
                '<div class="warning"><b>Не хватает ТЭП для полной нормализации:</b> '
                + _esc(", ".join(missing))
                + ". Внешние ставки на продаваемую/другую площадь пока видны, но не усредняются с ГНС.</div>"
            )
        else:
            weak = sum(1 for row in recommendation.get("applyable_recommendations", []) if row.get("confidence") in {"pilot", "insufficient"})
            quality_note = f"{weak} из {recommendation.get('applyable_count', 0)} применимых статей пока имеют пилотную базу."
            warning_html = ""

        preset_json = json.dumps(recommendation.get("model_parameters_th_rub_m2", {}), ensure_ascii=False).replace("</", "<\\/")
        all_rows = [x for x in source_catalog() if x.get("region") == region]
        source_rows = _source_rows((old.get("comparable_points") or []) + (old.get("external_benchmarks") or []) + all_rows)
        index_cards = "".join(
            f'<div class="box"><b>{_esc(x.get("source"))}</b><div class="tiny">{_esc(x.get("dataset"))}<br>публикация {_esc(x.get("published_at"))}</div></div>'
            for x in index_source_catalog()
        )

        css = """
        *{box-sizing:border-box}body{margin:0;background:#f4f5f7;color:#1d2530;font:14px -apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif}
        .wrap{max-width:1500px;margin:auto;padding:30px 22px 70px}.top{display:flex;justify-content:space-between}.brand{font-size:20px;font-weight:800}.tag{font-size:11px;border:1px solid #d8dde5;background:#fff;padding:6px 10px;border-radius:999px}
        h1{font-size:34px;margin:26px 0 7px}h2{font-size:20px;margin:0 0 6px}.sub,.note,.tiny{color:#737d8d;line-height:1.45}.section{margin-top:28px}
        form.filters{display:grid;grid-template-columns:1.4fr 1fr repeat(4,1fr) auto;gap:9px;background:#fff;border:1px solid #dfe4ea;border-radius:14px;padding:14px;margin:18px 0}.field label{display:block;font-size:10px;color:#788291;margin-bottom:5px}
        input,select,button{width:100%;height:42px;border:1px solid #d5dae2;border-radius:8px;background:#fff;padding:0 10px;font:inherit}button{background:#192231;color:#fff;border-color:#192231;cursor:pointer}.tabs{display:flex;gap:7px;margin:18px 0 10px}.tab{width:auto;background:#fff;color:#4b5665}.tab.on{background:#192231;color:#fff}.panel{display:none}.panel.on{display:block}
        .scroll{overflow:auto;background:#fff;border:1px solid #dfe4ea;border-radius:12px}table{width:100%;border-collapse:collapse;font-size:12px}th,td{text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid #edf0f4}th{background:#fafbfc;color:#727d8d;font-size:10px;text-transform:uppercase}.num{text-align:right;font-variant-numeric:tabular-nums}.strong,.value{font-weight:800}.matrix{min-width:2100px}.matrix th,.matrix td{border-right:1px solid #edf0f4}.sticky{position:sticky;left:0;z-index:2;background:#fff;min-width:250px}.matrix th.sticky{z-index:3;background:#fafbfc}.source{min-width:225px;max-width:270px;text-transform:none;font-size:11px;color:#283241}.headvalue{font-size:13px;font-weight:800;margin:6px 0}.cell{min-width:200px}.total{background:#f6f8fa!important;font-weight:800;border-top:2px solid #dce2e8}
        .badge{display:inline-block;border-radius:999px;padding:2px 6px;font-size:9px;font-weight:800;background:#eef0f2;color:#69727e}.badge.a{background:#e8f5ee;color:#236642}.badge.b{background:#edf3fa;color:#285c89}.badge.c{background:#fff2c9;color:#735b16}.yes{color:#236642;font-weight:700}.no{color:#9a555e}.muted{color:#8a929e}.warning,.method{background:#fff8e6;border:1px solid #eedca3;border-radius:12px;padding:13px 15px;color:#6d581e;margin:12px 0}.box{background:#fff;border:1px solid #dfe4ea;border-radius:12px;padding:14px}.action{display:flex;gap:10px;align-items:center;margin:12px 0}.action button{width:auto}.indices{display:grid;grid-template-columns:repeat(2,1fr);gap:9px}.coeff td,.coeff th{text-align:center}.coeff td:first-child,.coeff th:first-child{text-align:left}.active{background:#eef3f8!important;font-weight:800}a{color:#1c5d91;text-decoration:none}
        @media(max-width:900px){.wrap{padding:20px 10px 50px}form.filters{grid-template-columns:1fr}.indices{grid-template-columns:1fr}h1{font-size:29px}}
        """

        body = f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DevelopAid — Себестоимость</title><style>{css}</style></head><body><div class="wrap">
        <div class="top"><div class="brand">DevelopAid</div><div class="tag">COST BENCHMARK · METHOD v3.2</div></div>
        <h1>Себестоимость строительства</h1>
        <div class="sub">Не витрина источников, а нормализующий контур: <b>как опубликовано → статья → класс → база площади → вес → агрегированный consensus → параметры модели.</b></div>
        <form class="filters" method="get">
          <div class="field"><label>Регион</label><input name="region" value="{reg}"></div>
          <div class="field"><label>Класс</label><select name="class">{opts}</select></div>
          <div class="field"><label>Общая ГНС, м²</label><input type="number" step=".01" name="gba_sqm" value="{_fmt_sqm(gba_sqm)}"></div>
          <div class="field"><label>Продаваемая, м²</label><input type="number" step=".01" name="sellable_sqm" value="{_fmt_sqm(sellable_sqm)}"></div>
          <div class="field"><label>Подземная ГНС, м²</label><input type="number" step=".01" name="underground_gns_sqm" value="{_fmt_sqm(underground_gns_sqm)}"></div>
          <div class="field"><label>Наземная ГНС, м²</label><input type="number" step=".01" name="above_ground_gns_sqm" value="{_fmt_sqm(above_ground_gns_sqm)}" placeholder="авто = общая − подземная"></div>
          <button>Нормализовать</button>
          <input type="hidden" name="unit" value="{_esc(unit)}"><input type="hidden" name="metric_type" value="{_esc(metric_type)}">
        </form>
        {warning_html}
        <div class="tabs"><button class="tab on" type="button" data-panel="rec">Рекомендация DevelopAid</button><button class="tab" type="button" data-panel="src">Источники и нормализация</button></div>
        <div class="panel on" id="rec"><div class="section"><h2>Агрегированное предложение · {reg} · {cls_label}</h2><div class="note">Наземное СМР нормализуется на наземную ГНС, подземное — на подземную ГНС, общепроектные статьи — на общую ГНС. Consensus считается по статьям, а не по красивым итоговым цифрам разных scope.</div>{recommendation_html}<div class="action"><button id="copyPreset" type="button">Скопировать параметры модели</button><span class="tiny" id="copyState">{_esc(quality_note)}</span></div></div>
        <div class="section"><h2>Корректировка класса</h2><div class="method">Если источник имеет прямой срез выбранного класса, используется он. Экспертный коэффициент класса применяется только когда прямого среза нет и маркируется как B.</div>{coeff_html}</div></div>
        <div class="panel" id="src"><div class="section"><h2>1. Как опубликовано</h2><div class="note">Сохранены исходная статья, диапазон, знаменатель площади, дата цен и scope. CORE.XP не переименовывается из «на м² полезной площади» в «на м² ГНС» без пересчёта через ТЭП.</div>{matrix_html}</div>
        <div class="section"><h2>2. Нормализация и допуск</h2><div class="note">A — прямое совпадение; B — прозрачный пересчёт класса/базы; C — оценочная декомпозиция; D — только справочно. D имеет нулевой вес.</div>{normalization_html}</div>
        <div class="section"><h2>3. Индексация даты</h2><div class="indices">{index_cards}</div><div class="note" style="margin-top:8px">Автоматическая временная индексация пока не применяется: дата влияет на вес свежести и видна пользователю. Для пересчёта цен к одной дате нужен проверенный ряд индекса цен строительной продукции Мосстата; случайный CPI сюда не подставляется.</div></div>
        <div class="section"><h2>4. Реестр источников</h2><div class="scroll"><table><thead><tr><th>Источник</th><th>Класс</th><th>Значение</th><th>База</th><th>Метрика</th><th>Scope</th><th>Дата</th></tr></thead><tbody>{source_rows}</tbody></table></div></div></div>
        <div class="section"><h2>Диагностический explorer</h2><div class="note">Старый срез оставлен только для проверки отдельной метрики. Он не является агрегированным пресетом.</div><form class="filters" method="get"><div class="field"><label>Регион</label><input name="region" value="{reg}"></div><div class="field"><label>Класс</label><select name="class">{opts}</select></div><div class="field"><label>База</label><select name="unit">{unit_opts}</select></div><div class="field"><label>Метрика</label><select name="metric_type">{metric_opts}</select></div><button>Показать</button></form><div class="box"><b>{_fmt(old.get('recommended'))}</b><div class="tiny">N={old.get('n')} · {CONF_LABELS.get(old.get('confidence'), old.get('confidence'))}</div></div></div>
        </div><script>const preset={preset_json};document.querySelectorAll('.tab').forEach(function(b){{b.addEventListener('click',function(){{document.querySelectorAll('.tab,.panel').forEach(function(x){{x.classList.remove('on')}});b.classList.add('on');document.getElementById(b.dataset.panel).classList.add('on')}})}});document.getElementById('copyPreset').addEventListener('click',async function(){{try{{await navigator.clipboard.writeText(JSON.stringify(preset,null,2));document.getElementById('copyState').textContent='Параметры скопированы: ключ API → тыс. ₽/м².'}}catch(e){{document.getElementById('copyState').textContent='Не удалось скопировать автоматически.'}}}});</script></body></html>'''
        return HTMLResponse(body)

    return app

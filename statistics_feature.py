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


def _fmt(value):
    return "—" if value is None else f"{round(value / 1000):,}".replace(",", " ") + " тыс. ₽/м²"


def _fmt_precise(value):
    if value is None:
        return "—"
    return f"{value / 1000:,.1f}".replace(",", " ").replace(".", ",") + " тыс."


def _fmt_pct(value):
    if value is None:
        return "—"
    sign = "+" if float(value) > 0 else ""
    return f"{sign}{float(value):.1f}%".replace(".", ",")


def _fmt_row(row: dict | None) -> str:
    if not row:
        return "—"
    lo = row.get("value_low_rub_m2")
    hi = row.get("value_high_rub_m2")
    if lo is not None and hi is not None:
        return f"{round(lo / 1000):,}–{round(hi / 1000):,}".replace(",", " ") + " тыс. ₽/м²"
    return _fmt(row.get("value_rub_m2"))


def _esc(value) -> str:
    return html.escape(str(value or ""))


def _source_rows(rows: list[dict]) -> str:
    if not rows:
        return '<tr><td colspan="7">Нет источников для выбранного региона.</td></tr>'
    result = []
    seen = set()
    for row in rows:
        key = row.get("external_id") or (
            row.get("source"), row.get("reference_date"), row.get("metric_type"), row.get("unit")
        )
        if key in seen:
            continue
        seen.add(key)
        source = _esc(row.get("source"))
        if row.get("source_url"):
            source = f'<a href="{_esc(row.get("source_url"))}" target="_blank" rel="noopener">{source}</a>'
        result.append(
            "<tr>"
            f"<td>{source}</td>"
            f"<td>{_esc(row.get('housing_class'))}</td>"
            f"<td><b>{_fmt_row(row)}</b></td>"
            f"<td>{_esc(row.get('unit_label'))}</td>"
            f"<td>{_esc(row.get('metric_label'))}</td>"
            f"<td>{_esc(row.get('scope_label'))}</td>"
            f"<td>{_esc(row.get('reference_date'))}</td>"
            "</tr>"
        )
    return "".join(result)


def _reference_cards(region: str) -> str:
    rows = [x for x in source_catalog() if x.get("region") == region]
    by_id = {x.get("external_id"): x for x in rows}
    specs = [
        ("developaid-grodnenskaya-main-above-2026-07", "Бизнес · основной СМР", "Фактический бюджет DevelopAid"),
        ("mke-ncsm-20-1-001-apartments-2025-09", "НЦСМ · площадь квартир", "Официальный московский норматив"),
        ("mke-ncsm-20-1-001-building-total-2025-09", "НЦСМ · общая площадь здания", "Отдельный знаменатель, не ГНС"),
        ("ac-moscow-eiszh-declared-cost-2025-06", "Проектные декларации", "Медиана по Москве"),
        ("sis-erz-2026-04-moscow", "Полная стоимость застройщика", "Массовое жильё, СИС / ЕРЗ"),
    ]
    cards = []
    for external_id, title, subtitle in specs:
        row = by_id.get(external_id)
        if not row:
            continue
        cards.append(
            '<div class="refcard">'
            f'<div class="label">{_esc(title)}</div>'
            f'<div class="refvalue">{_fmt_row(row)}</div>'
            f'<div class="refmeta">{_esc(row.get("unit_label"))}<br>{_esc(subtitle)}</div>'
            '</div>'
        )
    return "".join(cards) if cards else '<div class="empty">Нет подключенных ориентиров.</div>'


def _index_cards() -> str:
    cards = []
    for row in index_source_catalog():
        status = "Источник подключен; автоиндексация пока выключена" if not row.get("automatic") else "Автоиндексация включена"
        cards.append(
            '<div class="indexcard">'
            f'<div><b>{_esc(row.get("source"))}</b> · {_esc(row.get("region"))}</div>'
            f'<div class="indexdataset">{_esc(row.get("dataset"))}</div>'
            f'<div class="indexstatus">{_esc(status)} · публикация {_esc(row.get("published_at"))}</div>'
            '</div>'
        )
    return "".join(cards)


def _matrix_cell(cell: dict) -> str:
    status = cell.get("status", "not_disclosed")
    note = cell.get("note")
    title = f' title="{_esc(note)}"' if note else ""
    if status in {"value", "source_aggregate"}:
        adjusted = cell.get("adjusted_value_rub_m2")
        source_value = cell.get("source_value_rub_m2", cell.get("value_rub_m2"))
        value = adjusted if adjusted is not None else cell.get("value_rub_m2")
        unit_label = cell.get("unit_label") or STRUCTURE_UNIT_LABELS.get(cell.get("unit"), cell.get("unit", ""))
        detail = ""
        if cell.get("class_adjusted"):
            ratio = cell.get("class_adjustment_ratio")
            detail = f'<div class="cellnote">из {_fmt_precise(source_value)} · ×{ratio:.2f} по классу</div>'
        elif unit_label:
            detail = f'<div class="cellnote">{_esc(unit_label)}</div>'
        badge = '<span class="estimate">B · нормализовано</span>' if cell.get("class_adjusted") else ""
        return f'<div class="cellvalue"{title}>{_fmt_precise(value)} {badge}</div>{detail}'
    if status == "share":
        return f'<div class="share"{title}>{cell.get("share_pct")}%</div>'
    if status == "share_range":
        return f'<div class="share"{title}>{cell.get("share_low_pct")}–{cell.get("share_high_pct")}%</div>'
    if status == "combined_share":
        return f'<div class="share"{title}>{cell.get("share_low_pct")}–{cell.get("share_high_pct")}% вместе*</div>'
    if status == "unallocated_remainder":
        return f'<div class="muted"{title}>остаток {cell.get("share_low_pct")}–{cell.get("share_high_pct")}%*</div>'
    if status == "separate_denominator":
        value = cell.get("value_rub_m2")
        unit_label = cell.get("unit_label") or STRUCTURE_UNIT_LABELS.get(cell.get("unit"), cell.get("unit", ""))
        return f'<div class="muted"{title}>{_fmt_precise(value)}<div class="cellnote">{_esc(unit_label)}</div></div>'
    labels = {
        "included_in_aggregate": "входит в агрегат",
        "included_in_broader_total": "входит в более широкий итог",
        "included_residual": "входит в нераскрытый остаток",
        "outside_scope": "вне scope",
    }
    if status in labels:
        return f'<div class="included"{title}>{labels[status]}</div>'
    return f'<div class="muted"{title}>н/д</div>'


def _cost_structure_table(matrix: dict) -> str:
    sources = matrix.get("sources", [])
    if not sources:
        return '<div class="empty">Для выбранного региона нет источников структуры себестоимости.</div>'
    heads = ['<th class="sticky">Статья DevelopAid</th>']
    for source in sources:
        published = source.get("published", {})
        raw_value = published.get("value_rub_m2")
        adjusted = source.get("published_adjusted_value_rub_m2")
        unit_label = source.get("published_unit_label") or STRUCTURE_UNIT_LABELS.get(published.get("unit"), published.get("unit", ""))
        name = _esc(source.get("source"))
        if source.get("source_url"):
            name = f'<a href="{_esc(source.get("source_url"))}" target="_blank" rel="noopener">{name}</a>'
        if source.get("published_class_adjusted") and adjusted is not None:
            published_line = f'{_fmt_precise(raw_value)} → <b>{_fmt_precise(adjusted)}</b> <span class="estimate">B</span>'
        else:
            published_line = _fmt_precise(raw_value)
        heads.append(
            '<th class="sourcehead">'
            f'<div>{name}</div><div class="headvalue">{published_line}</div>'
            f'<div class="headmeta">{_esc(unit_label)}<br>База класса: {_esc(source.get("base_class_label"))}<br>{_esc(source.get("reference_date"))}</div>'
            '</th>'
        )
    body = []
    for component in matrix.get("components", []):
        key = component.get("key")
        cls = " totalrow" if key in {"construction_capex", "full_development_cost"} else ""
        row = [f'<td class="rowlabel{cls}">{_esc(component.get("label"))}</td>']
        for source in sources:
            row.append(f'<td class="matrixcell{cls}">{_matrix_cell(source.get("cells", {}).get(key, {}))}</td>')
        body.append("<tr>" + "".join(row) + "</tr>")
    return '<div class="matrixwrap"><table class="matrix"><thead><tr>' + "".join(heads) + '</tr></thead><tbody>' + "".join(body) + '</tbody></table></div>'


def _recommendation_table(payload: dict) -> str:
    rows = []
    for row in payload.get("recommendations", []):
        if row.get("key") == "construction_capex" or row.get("recommended_rub_m2") is not None or row.get("source_count"):
            grades = row.get("grade_counts", {})
            grade_text = " · ".join(f"{g}:{grades.get(g, 0)}" for g in ("A", "B", "C") if grades.get(g, 0)) or "—"
            rows.append(
                "<tr>"
                f"<td><b>{_esc(row.get('label'))}</b><div class='tiny'>{_esc(row.get('unit_label'))}</div></td>"
                f"<td class='number'>{_fmt_precise(row.get('baseline_rub_m2'))}</td>"
                f"<td class='number strong'>{_fmt_precise(row.get('recommended_rub_m2'))}</td>"
                f"<td class='number'>{_fmt_precise(row.get('p25_rub_m2'))} — {_fmt_precise(row.get('p75_rub_m2'))}</td>"
                f"<td class='number'>{_fmt_pct(row.get('delta_to_baseline_pct'))}</td>"
                f"<td>{row.get('source_count', 0)}<div class='tiny'>{_esc(grade_text)}</div></td>"
                f"<td>{_esc(CONF_LABELS.get(row.get('confidence'), row.get('confidence')))}</td>"
                "</tr>"
            )
    if not rows:
        return '<div class="empty">Пока нет ни одной статьи с сопоставимой базой для агрегирования.</div>'
    return (
        '<div class="tablewrap"><table class="recommend"><thead><tr>'
        '<th>Параметр DevelopAid</th><th>Baseline DA</th><th>Рекомендация</th><th>Коридор P25–P75</th>'
        '<th>Δ к baseline</th><th>Источники</th><th>Достоверность</th></tr></thead><tbody>'
        + "".join(rows) + '</tbody></table></div>'
    )


def _normalization_table(payload: dict) -> str:
    rows = []
    for item in payload.get("recommendations", []):
        for source in item.get("included_sources", []) + item.get("excluded_sources", []):
            included = source.get("included")
            status = '<span class="ok">участвует</span>' if included else '<span class="no">не участвует</span>'
            rows.append(
                "<tr>"
                f"<td>{_esc(item.get('label'))}</td>"
                f"<td>{_esc(source.get('source'))}<div class='tiny'>{_esc(source.get('reference_date'))}</div></td>"
                f"<td><span class='grade g{_esc(source.get('grade'))}'>{_esc(source.get('grade'))}</span> {_esc(source.get('grade_label'))}</td>"
                f"<td class='number'>{_fmt_precise(source.get('value_rub_m2'))}<div class='tiny'>{_esc(source.get('unit_label'))}</div></td>"
                f"<td class='number'>{source.get('weight', 0):.3f}</td>"
                f"<td>{status}</td>"
                f"<td>{_esc(source.get('reason'))}</td>"
                "</tr>"
            )
    return (
        '<div class="tablewrap"><table><thead><tr><th>Статья</th><th>Источник</th><th>Качество нормализации</th>'
        '<th>Нормализовано</th><th>Вес</th><th>Агрегат</th><th>Почему</th></tr></thead><tbody>'
        + "".join(rows) + '</tbody></table></div>'
    )


def _class_adjustment_table(catalog: dict, active_class: str) -> str:
    components = [
        ("main_above", "Основное строительство"), ("design", "ПИР / РД"),
        ("main_under", "Подземная часть"), ("external_utilities", "Наружные сети"),
        ("landscaping", "Благоустройство"), ("site_maintenance", "Содержание площадки"),
        ("tech_customer", "Техзаказчик"), ("project_management", "Управление проектом"),
    ]
    classes = catalog.get("classes", [])
    head = '<th>Статья</th>' + ''.join(
        f'<th class="{"activeclass" if c.get("key") == active_class else ""}">{_esc(c.get("label"))}</th>' for c in classes
    )
    rows = []
    cfg = catalog.get("components", {})
    for key, label in components:
        values = cfg.get(key, {})
        cells = ''.join(
            f'<td class="{"activeclass" if c.get("key") == active_class else ""}">×{float(values.get(c.get("key"), 1)):.2f}</td>' for c in classes
        )
        rows.append(f'<tr><td>{_esc(label)}</td>{cells}</tr>')
    return '<div class="coeffwrap"><table class="coeff"><thead><tr>' + head + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'


def install(app):
    @app.get("/api/statistics/construction-cost")
    def construction_cost(
        region: str = Query(...), housing_class: str = Query("comfort", alias="class"), city: str | None = None,
        unit: str = "gba", metric_type: str = "main_construction", cost_scope: str | None = None,
        floors_min: int | None = None, floors_max: int | None = None, construction_type: str | None = None,
        underground_parking: bool | None = None,
    ):
        return result_to_dict(build_benchmark(
            load_observations(), load_external_benchmarks(), normalized=load_normalized_benchmarks(),
            region=region, housing_class=housing_class, city=city, unit=unit, metric_type=metric_type,
            cost_scope=cost_scope, floors_min=floors_min, floors_max=floors_max,
            construction_type=construction_type, underground_parking=underground_parking,
        ))

    @app.get("/api/statistics/cost-recommendation")
    def statistics_cost_recommendation(
        region: str = "Москва", housing_class: str = Query("business", alias="class")
    ):
        return build_cost_recommendation(region=region, housing_class=housing_class)

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
    ):
        r = result_to_dict(build_benchmark(
            load_observations(), load_external_benchmarks(), normalized=load_normalized_benchmarks(),
            region=region, housing_class=housing_class, city=city, unit=unit, metric_type=metric_type,
        ))
        matrix = build_cost_structure_matrix(region=region, housing_class=housing_class)
        recommendation = build_cost_recommendation(region=region, housing_class=housing_class)
        coeffs = class_adjustment_catalog()
        matrix_html = _cost_structure_table(matrix)
        recommendation_html = _recommendation_table(recommendation)
        normalization_html = _normalization_table(recommendation)
        coeff_html = _class_adjustment_table(coeffs, housing_class)

        reg, cls = html.escape(region), html.escape(housing_class)
        cls_label = CLASS_LABELS.get(housing_class, housing_class)
        refs = r.get("external_benchmarks") or []
        comparable = r.get("comparable_points") or []
        all_region_rows = [x for x in source_catalog() if x.get("region") == region]
        source_rows = _source_rows(comparable + refs + all_region_rows)
        reference_cards = _reference_cards(region)
        index_cards = _index_cards()
        conf = CONF_LABELS.get(r["confidence"], r["confidence"])

        class_opts = [("standard", "Стандарт"), ("comfort", "Комфорт"), ("business", "Бизнес"), ("premium", "Премиум"), ("elite", "Элитный")]
        opts = "".join(f'<option value="{v}" {"selected" if housing_class == v else ""}>{n}</option>' for v, n in class_opts)
        unit_opts = "".join(f'<option value="{v}" {"selected" if unit == v else ""}>{_esc(label)}</option>' for v, label in UNIT_LABELS.items())
        metric_opts = "".join(f'<option value="{v}" {"selected" if metric_type == v else ""}>{_esc(label)}</option>' for v, label in METRIC_LABELS.items())

        preset = {
            row["key"]: {"value_rub_m2": row["recommended_rub_m2"], "unit": row["unit"]}
            for row in recommendation.get("applyable_recommendations", [])
        }
        preset_json = json.dumps(preset, ensure_ascii=False).replace("</", "<\\/")
        weak = sum(1 for row in recommendation.get("applyable_recommendations", []) if row.get("confidence") in {"pilot", "insufficient"})
        quality_note = (
            f"Сейчас {weak} из {recommendation.get('applyable_count', 0)} применимых статей имеют пилотную базу. "
            "Это не прячется: при добавлении сопоставимых источников агрегат пересчитается автоматически."
            if recommendation.get("applyable_count") else "Пока нет статей, которые можно безопасно предложить модели."
        )

        return HTMLResponse(f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DevelopAid — Себестоимость</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f4f5f7;color:#1c2430;font:15px -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}}.wrap{{max-width:1500px;margin:auto;padding:32px 24px 70px}}.top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:26px}}.brand{{font-weight:800;font-size:20px}}.tag{{font-size:12px;padding:6px 10px;border:1px solid #d8dde5;border-radius:999px;background:#fff}}h1{{font-size:36px;margin:0 0 8px}}h2{{font-size:20px;margin:0 0 7px}}.sub,.sectionnote{{color:#697386;line-height:1.45}}.section{{margin-top:28px}}.primaryfilters{{display:flex;gap:10px;align-items:center;background:#fff;padding:14px;border:1px solid #e0e4ea;border-radius:14px;margin:18px 0}}.primaryfilters input{{flex:1}}.primaryfilters select{{min-width:180px}}input,select,button{{height:44px;border-radius:9px;border:1px solid #d5dae2;padding:0 12px;background:#fff;font:inherit;min-width:0}}button{{background:#182131;color:#fff;border-color:#182131;padding:0 20px;cursor:pointer}}button.secondary{{background:#fff;color:#182131}}.actionbar{{display:flex;gap:10px;align-items:center;margin:12px 0}}.hint{{font-size:12px;color:#6d7685}}table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e0e4ea;font-size:13px}}td,th{{padding:11px;text-align:left;border-bottom:1px solid #edf0f4;vertical-align:top}}th{{font-size:11px;color:#747d8d;background:#fafbfc;text-transform:uppercase;letter-spacing:.03em}}.number{{text-align:right;font-variant-numeric:tabular-nums}}.strong{{font-weight:800;font-size:14px}}.tiny{{font-size:10px;color:#818a98;margin-top:3px}}.tablewrap,.matrixwrap,.coeffwrap{{overflow:auto;border:1px solid #dfe4ea;border-radius:14px;background:#fff}}.tablewrap table,.matrix,.coeff{{border:0}}.matrix{{min-width:1320px}}.matrix th,.matrix td{{border-right:1px solid #edf0f4}}.matrix .sticky{{position:sticky;left:0;z-index:3;min-width:240px;background:#fafbfc}}.rowlabel{{position:sticky;left:0;z-index:2;background:#fff;font-weight:650;min-width:240px}}.matrixcell{{min-width:205px;max-width:250px}}.sourcehead{{min-width:220px;max-width:260px;text-transform:none;letter-spacing:0;font-size:12px;color:#283241}}.headvalue{{font-size:14px;margin-top:7px;font-weight:600}}.headmeta,.cellnote{{font-size:10px;color:#778091;margin-top:5px;line-height:1.35;font-weight:400}}.cellvalue{{font-weight:750;font-size:14px}}.muted,.included{{color:#7f8896;font-size:12px}}.share{{font-weight:650;color:#475364}}.estimate,.grade{{display:inline-block;font-size:9px;font-weight:800;padding:2px 6px;border-radius:999px;background:#fff2c9;color:#735b16}}.gA{{background:#e8f5ee;color:#236642}}.gB{{background:#edf3fa;color:#285c89}}.gC{{background:#fff2c9;color:#735b16}}.gD{{background:#eef0f2;color:#727a85}}.ok{{color:#236642;font-weight:700}}.no{{color:#8d5860}}.totalrow{{background:#f6f8fa!important;font-weight:800;border-top:2px solid #dce2e8}}.callout{{background:#fff;border:1px solid #dce2e8;border-radius:16px;padding:20px}}.callout b{{font-size:17px}}.refs{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}}.refcard,.indexcard{{background:#fff;border:1px solid #e0e4ea;border-radius:12px;padding:14px}}.refvalue{{font-size:21px;font-weight:800;margin:7px 0}}.refmeta,.indexstatus{{font-size:11px;color:#758090;line-height:1.4}}.indices{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}}.filters{{display:grid;grid-template-columns:1.4fr 1fr 1.25fr 1.5fr auto;gap:10px}}.hero{{margin-top:10px;background:#fff;border:1px solid #e0e4ea;border-radius:14px;padding:18px}}.hero .value{{font-size:32px;font-weight:800}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:10px}}.card{{background:#fff;border:1px solid #e0e4ea;border-radius:12px;padding:14px}}.label{{font-size:11px;color:#778091}}.num{{font-size:18px;font-weight:750;margin-top:5px}}.expertbox,.method{{background:#fff8e6;border:1px solid #eedca3;border-radius:12px;padding:14px 16px;color:#68551c;line-height:1.45}}.coeff td,.coeff th{{text-align:center}}.coeff td:first-child,.coeff th:first-child{{text-align:left}}.activeclass{{background:#eef3f8!important;font-weight:800}}a{{color:#1e5a8a;text-decoration:none}}.tabs{{display:flex;gap:6px;margin:20px 0 10px}}.tab{{background:#fff;color:#485363;border-color:#d5dae2}}.tab.on{{background:#182131;color:#fff;border-color:#182131}}.panel{{display:none}}.panel.on{{display:block}}@media(max-width:900px){{.primaryfilters,.filters,.grid,.refs,.indices{{display:grid;grid-template-columns:1fr}}.wrap{{padding:22px 12px 50px}}h1{{font-size:30px}}}}
</style></head><body><div class="wrap"><div class="top"><div class="brand">DevelopAid</div><div class="tag">COST BENCHMARK · METHOD v3.1</div></div><h1>Себестоимость строительства</h1><div class="sub">Цепочка расчёта теперь явная: <b>как опубликовано → нормализация к статье и базе DevelopAid → вес источника → агрегированная рекомендация</b>. Несопоставимый источник остаётся виден, но не портит среднее.</div><form class="primaryfilters" method="get"><input name="region" value="{reg}" placeholder="Регион"><select name="class">{opts}</select><input type="hidden" name="unit" value="{_esc(unit)}"><input type="hidden" name="metric_type" value="{_esc(metric_type)}"><button>Пересчитать</button></form>
<div class="tabs"><button class="tab on" type="button" data-panel="recommendation">Рекомендация DevelopAid</button><button class="tab" type="button" data-panel="sources">Источники и нормализация</button></div>
<div id="recommendation" class="panel on"><div class="section"><h2>Агрегированное предложение · {reg} · {_esc(cls_label)}</h2><div class="sectionnote">Не простое среднее. По каждой статье считаются только сопоставимые значения; веса учитывают качество нормализации, свежесть, тип и методологическую сопоставимость источника.</div>{recommendation_html}<div class="actionbar"><button type="button" id="copyPreset">Скопировать пресет</button><span class="hint" id="copyState">{_esc(quality_note)}</span></div><div class="callout"><b>Что можно применять в модель сейчас: {recommendation.get('applyable_count', 0)} статей.</b><div class="sectionnote" style="margin-top:6px">Полный construction budget не складывается из несопоставимых знаменателей. Он считается уже на ТЭП проекта после применения ставок наземной части, подземной части и общепроектных статей.</div></div></div><div class="section"><h2>Экспертная индексация по классу</h2><div class="expertbox"><b>Комфорт = 1,00.</b> Коэффициент класса — отдельный слой нормализации, а не статистика. Поэтому такая точка получает B, а не A.</div>{coeff_html}</div></div>
<div id="sources" class="panel"><div class="section"><h2>1. Как опубликовано</h2><div class="sectionnote">Строки — наша структура; колонки — источники. Исходный scope, знаменатель площади и опубликованная цифра не переписываются задним числом.</div>{matrix_html}<div class="sectionnote">* Совместные доли не размазываются по статьям. Пусто означает «не раскрыто», а не ноль.</div></div><div class="section"><h2>2. Нормализация и допуск в агрегат</h2><div class="sectionnote">A — прямое совпадение; B — прозрачная нормализация; C — оценочная декомпозиция; D — только справочно. D имеет нулевой вес.</div>{normalization_html}</div><div class="section"><h2>3. Контрольные ориентиры</h2><div class="refs">{reference_cards}</div></div><div class="section"><h2>Индексация даты</h2><div class="indices">{index_cards}</div></div><div class="section"><h2>Реестр исходных источников</h2><div class="tablewrap"><table><thead><tr><th>Источник</th><th>Класс</th><th>Значение</th><th>База площади</th><th>Метрика</th><th>Scope</th><th>Дата</th></tr></thead><tbody>{source_rows}</tbody></table></div></div></div>
<div class="section"><h2>Статистический explorer</h2><div class="sectionnote">Ниже сохранён старый срез для проверки конкретной метрики/единицы. Он не заменяет агрегатор по статьям.</div><form class="filters" method="get"><input name="region" value="{reg}"><select name="class">{opts}</select><select name="unit">{unit_opts}</select><select name="metric_type">{metric_opts}</select><button>Показать</button></form><div class="hero"><div class="label">Статистический ориентир · {reg} · {cls}</div><div class="value">{_fmt(r['recommended'])}</div><div>P25–P75: {_fmt(r['p25'])} — {_fmt(r['p75'])}</div></div><div class="grid"><div class="card"><div class="label">Медиана</div><div class="num">{_fmt(r['median'])}</div></div><div class="card"><div class="label">N</div><div class="num">{r['n']}</div></div><div class="card"><div class="label">Достоверность</div><div class="num">{_esc(conf)}</div></div><div class="card"><div class="label">Версия</div><div class="num">v{_esc(r['methodology_version'])}</div></div></div></div><div class="method">Метод v3.1: агрегирование выполняется по статье после нормализации; несопоставимые unit/scope не усредняются. При недостатке данных система показывает ограниченность вместо фиктивной точности.</div></div>
<script>const preset={preset_json};document.querySelectorAll('.tab').forEach(b=>b.addEventListener('click',()=>{{document.querySelectorAll('.tab,.panel').forEach(x=>x.classList.remove('on'));b.classList.add('on');document.getElementById(b.dataset.panel).classList.add('on')}}));document.getElementById('copyPreset').addEventListener('click',async()=>{{const text=JSON.stringify(preset,null,2);try{{await navigator.clipboard.writeText(text);document.getElementById('copyState').textContent='Пресет скопирован. Следующий шаг — применить его к вводным модели.'}}catch(e){{document.getElementById('copyState').textContent='Не удалось скопировать автоматически.'}}}});</script></body></html>''')

    return app

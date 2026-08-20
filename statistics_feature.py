from __future__ import annotations

import html

from fastapi import Query
from fastapi.responses import HTMLResponse

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


def _fmt(value):
    return "—" if value is None else f"{round(value / 1000):,}".replace(",", " ") + " тыс. ₽/м²"


def _fmt_precise(value):
    if value is None:
        return "—"
    return f"{value / 1000:,.1f}".replace(",", " ").replace(".", ",") + " тыс."


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
        key = row.get("external_id") or (row.get("source"), row.get("reference_date"), row.get("metric_type"), row.get("unit"))
        if key in seen:
            continue
        seen.add(key)
        value = _fmt_row(row)
        source = _esc(row.get("source"))
        source_url = row.get("source_url")
        if source_url:
            source = f'<a href="{_esc(source_url)}" target="_blank" rel="noopener">{source}</a>'
        result.append(
            "<tr>"
            f"<td>{source}</td>"
            f"<td>{_esc(row.get('housing_class'))}</td>"
            f"<td><b>{value}</b></td>"
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
    if not cards:
        return '<div class="empty">Для региона пока нет подключенных контрольных ориентиров.</div>'
    return "".join(cards)


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
        badge = '<span class="estimate">экспертно</span>' if cell.get("class_adjusted") else ""
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
        value_html = _fmt_precise(value) if value is not None else "отдельная база"
        return f'<div class="muted"{title}>{value_html}<div class="cellnote">{_esc(unit_label)}</div></div>'
    if status == "included_in_aggregate":
        return f'<div class="included"{title}>входит в агрегат</div>'
    if status == "included_in_broader_total":
        return f'<div class="included"{title}>входит в более широкий итог</div>'
    if status == "included_residual":
        return f'<div class="included"{title}>входит в нераскрытый остаток</div>'
    if status == "outside_scope":
        return f'<div class="outside"{title}>вне scope</div>'
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
        source_name = _esc(source.get("source"))
        if source.get("source_url"):
            source_name = f'<a href="{_esc(source.get("source_url"))}" target="_blank" rel="noopener">{source_name}</a>'
        class_line = f'База: {_esc(source.get("base_class_label"))}'
        if source.get("published_class_adjusted") and adjusted is not None:
            published_line = f'{_fmt_precise(raw_value)} → <b>{_fmt_precise(adjusted)}</b> <span class="estimate">экспертно</span>'
        else:
            published_line = _fmt_precise(raw_value)
        heads.append(
            '<th class="sourcehead">'
            f'<div>{source_name}</div>'
            f'<div class="headvalue">{published_line}</div>'
            f'<div class="headmeta">{_esc(unit_label)}<br>{class_line}<br>{_esc(source.get("reference_date"))}</div>'
            '</th>'
        )

    body = []
    for component in matrix.get("components", []):
        key = component.get("key")
        cls = " totalrow" if key in {"construction_capex", "full_development_cost"} else ""
        row = [f'<td class="rowlabel{cls}">{_esc(component.get("label"))}</td>']
        for source in sources:
            row.append(f'<td class="matrixcell{cls}">{_matrix_cell(source.get("cells", {}).get(key, {"status": "not_disclosed"}))}</td>')
        body.append("<tr>" + "".join(row) + "</tr>")

    return (
        '<div class="matrixwrap"><table class="matrix"><thead><tr>'
        + "".join(heads)
        + '</tr></thead><tbody>'
        + "".join(body)
        + '</tbody></table></div>'
    )


def _class_adjustment_table(catalog: dict, active_class: str) -> str:
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
    head = '<th>Статья</th>' + ''.join(
        f'<th class="{"activeclass" if c.get("key") == active_class else ""}">{_esc(c.get("label"))}</th>'
        for c in classes
    )
    rows = []
    cfg = catalog.get("components", {})
    for key, label in components:
        values = cfg.get(key, {})
        cells = ''.join(
            f'<td class="{"activeclass" if c.get("key") == active_class else ""}">×{float(values.get(c.get("key"), 1)):.2f}</td>'
            for c in classes
        )
        rows.append(f'<tr><td>{_esc(label)}</td>{cells}</tr>')
    return '<div class="coeffwrap"><table class="coeff"><thead><tr>' + head + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'


def install(app):
    @app.get("/api/statistics/construction-cost")
    def construction_cost(
        region: str = Query(...),
        housing_class: str = Query("comfort", alias="class"),
        city: str | None = None,
        unit: str = "gba",
        metric_type: str = "main_construction",
        cost_scope: str | None = None,
        floors_min: int | None = None,
        floors_max: int | None = None,
        construction_type: str | None = None,
        underground_parking: bool | None = None,
    ):
        result = build_benchmark(
            load_observations(),
            load_external_benchmarks(),
            normalized=load_normalized_benchmarks(),
            region=region,
            housing_class=housing_class,
            city=city,
            unit=unit,
            metric_type=metric_type,
            cost_scope=cost_scope,
            floors_min=floors_min,
            floors_max=floors_max,
            construction_type=construction_type,
            underground_parking=underground_parking,
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

    @app.get("/api/statistics/cost-structure")
    def statistics_cost_structure(
        region: str = "Москва",
        housing_class: str = Query("business", alias="class"),
    ):
        return build_cost_structure_matrix(region=region, housing_class=housing_class)

    @app.get("/api/statistics/class-adjustments")
    def statistics_class_adjustments():
        return class_adjustment_catalog()

    @app.get("/statistics", response_class=HTMLResponse)
    def statistics_page(
        region: str = "Москва",
        housing_class: str = Query("business", alias="class"),
        city: str | None = None,
        unit: str = "gba",
        metric_type: str = "main_construction",
    ):
        r = result_to_dict(
            build_benchmark(
                load_observations(),
                load_external_benchmarks(),
                normalized=load_normalized_benchmarks(),
                region=region,
                housing_class=housing_class,
                city=city,
                unit=unit,
                metric_type=metric_type,
            )
        )
        matrix = build_cost_structure_matrix(region=region, housing_class=housing_class)
        coeffs = class_adjustment_catalog()
        matrix_html = _cost_structure_table(matrix)
        coeff_html = _class_adjustment_table(coeffs, housing_class)

        reg, cls = html.escape(region), html.escape(housing_class)
        cls_label = CLASS_LABELS.get(housing_class, housing_class)
        conf = {
            "high": "Высокая",
            "medium": "Средняя",
            "limited": "Ограниченная",
            "pilot": "Пилотная",
            "insufficient": "Недостаточно данных",
        }.get(r["confidence"], r["confidence"])
        refs = r.get("external_benchmarks") or []
        comparable = r.get("comparable_points") or []
        all_region_rows = [x for x in source_catalog() if x.get("region") == region]
        source_rows = _source_rows(comparable + refs + all_region_rows)
        reference_cards = _reference_cards(region)
        index_cards = _index_cards()

        class_opts = [
            ("standard", "Стандарт"),
            ("comfort", "Комфорт"),
            ("business", "Бизнес"),
            ("premium", "Премиум"),
            ("elite", "Элитный"),
        ]
        opts = "".join(
            f'<option value="{v}" {"selected" if housing_class == v else ""}>{n}</option>'
            for v, n in class_opts
        )
        unit_opts = "".join(
            f'<option value="{v}" {"selected" if unit == v else ""}>{_esc(label)}</option>'
            for v, label in UNIT_LABELS.items()
        )
        metric_opts = "".join(
            f'<option value="{v}" {"selected" if metric_type == v else ""}>{_esc(label)}</option>'
            for v, label in METRIC_LABELS.items()
        )

        if r["n"] == 0:
            warn = (
                '<div class="warn"><b>Статистическая рекомендация не подставлена.</b> '
                "Для выбранных класса, метрики и единицы пока нет сопоставимой выборки. "
                "Экспертная индексация класса в матрице выше при этом остаётся доступной и явно помечается как экспертная.</div>"
            )
        elif r["n"] < 5:
            warn = (
                f'<div class="warn"><b>Пилотный benchmark: N={r["n"]}.</b> '
                "Это контрольная точка, а не рыночная медиана. Для P25–P75 нужна выборка реальных проектов.</div>"
            )
        else:
            warn = ""

        methodology = (
            "Главная таблица использует строки CAPEX DevelopAid: внешняя терминология мэппится на нашу структуру. "
            "Пустая ячейка означает отсутствие раскрытия, а не нулевую стоимость. Разные знаменатели площади не конвертируются автоматически. "
            "Комфорт принят экспертной базой класса = 1,00; переход к бизнесу/премиуму/элите выполняется отдельными коэффициентами по статьям и не считается статистикой. "
            "Росстат и Мосстат используются только для временной индексации после загрузки проверенного числового ряда."
        )

        return HTMLResponse(
            f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DevelopAid — Статистика себестоимости</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f4f5f7;color:#1c2430;font:15px -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}}.wrap{{max-width:1500px;margin:auto;padding:32px 24px 70px}}.top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:26px}}.brand{{font-weight:800;font-size:20px}}.tag{{font-size:12px;padding:6px 10px;border:1px solid #d8dde5;border-radius:999px;background:#fff}}h1{{font-size:36px;margin:0 0 8px}}.sub{{color:#697386;margin-bottom:18px;max-width:1000px;line-height:1.45}}.primaryfilters{{display:flex;gap:10px;align-items:center;background:#fff;padding:14px;border:1px solid #e0e4ea;border-radius:14px;margin:18px 0}}.primaryfilters input{{flex:1}}.primaryfilters select{{min-width:180px}}.filters{{display:grid;grid-template-columns:1.4fr 1fr 1.25fr 1.5fr auto;gap:10px;background:#fff;padding:14px;border:1px solid #e0e4ea;border-radius:14px}}input,select,button{{height:44px;border-radius:9px;border:1px solid #d5dae2;padding:0 12px;background:#fff;font:inherit;min-width:0}}button{{background:#182131;color:#fff;border-color:#182131;padding:0 20px}}.hero{{margin-top:16px;background:#fff;border:1px solid #e0e4ea;border-radius:16px;padding:26px}}.eyebrow{{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#7b8492}}.value{{font-size:44px;font-weight:800;margin:7px 0}}.range{{color:#596273;font-size:17px}}.scope{{margin-top:8px;color:#7b8492;font-size:13px}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:14px}}.card{{background:#fff;border:1px solid #e0e4ea;border-radius:14px;padding:18px}}.label{{font-size:12px;color:#778091;margin-bottom:7px}}.num{{font-size:21px;font-weight:750}}.section{{margin-top:28px}}h2{{font-size:20px;margin-bottom:7px}}.sectionnote{{color:#6d7685;font-size:13px;margin-bottom:12px;line-height:1.45}}.refs{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}}.refcard{{background:#fff;border:1px solid #e0e4ea;border-radius:14px;padding:16px;min-height:138px}}.refvalue{{font-size:22px;font-weight:800;margin:8px 0}}.refmeta{{font-size:12px;line-height:1.4;color:#6c7584}}.indices{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}}.indexcard{{background:#fff;border:1px solid #e0e4ea;border-radius:12px;padding:14px;line-height:1.4}}.indexdataset{{margin-top:4px;color:#596273}}.indexstatus{{margin-top:7px;color:#8a691a;font-size:12px}}table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e0e4ea;font-size:13px}}td,th{{padding:12px 11px;text-align:left;border-bottom:1px solid #edf0f4;vertical-align:top}}th{{font-size:11px;color:#747d8d;background:#fafbfc;text-transform:uppercase;letter-spacing:.03em}}a{{color:#1e5a8a;text-decoration:none}}a:hover{{text-decoration:underline}}.warn{{padding:14px 16px;background:#fff8e6;border:1px solid #eedca3;border-radius:12px;color:#68551c;margin-top:16px;line-height:1.45}}.method{{margin-top:18px;color:#667080;font-size:13px;line-height:1.55;background:#fff;border:1px solid #e0e4ea;border-radius:12px;padding:15px}}.pill{{display:inline-block;margin:0 6px 6px 0;padding:5px 8px;border-radius:999px;background:#eef1f4;font-size:11px;color:#596273}}.empty{{background:#fff;padding:16px;border:1px solid #e0e4ea;border-radius:12px}}.matrixwrap{{overflow:auto;border:1px solid #dfe4ea;border-radius:14px;background:#fff}}.matrix{{border:0;min-width:1320px}}.matrix th,.matrix td{{border-right:1px solid #edf0f4}}.matrix .sticky{{position:sticky;left:0;z-index:3;min-width:240px;background:#fafbfc}}.rowlabel{{position:sticky;left:0;z-index:2;background:#fff;font-weight:650;min-width:240px}}.matrixcell{{min-width:205px;max-width:250px}}.sourcehead{{min-width:220px;max-width:260px;text-transform:none;letter-spacing:0;font-size:12px;color:#283241}}.headvalue{{font-size:14px;margin-top:7px;font-weight:600}}.headmeta{{font-size:10px;color:#778091;margin-top:6px;line-height:1.35;font-weight:400}}.cellvalue{{font-weight:750;font-size:14px}}.cellnote{{font-size:10px;color:#7c8593;margin-top:4px;line-height:1.3}}.muted{{color:#9aa2ae;font-size:12px}}.included{{color:#596273;font-size:12px}}.outside{{color:#a0a7b1;font-size:11px}}.share{{font-weight:650;color:#475364}}.estimate{{display:inline-block;font-size:9px;font-weight:700;padding:2px 5px;margin-left:3px;border-radius:999px;background:#fff2c9;color:#735b16;vertical-align:middle}}.totalrow{{background:#f6f8fa!important;font-weight:800;border-top:2px solid #dce2e8}}.coeffwrap{{overflow:auto;border:1px solid #e0e4ea;border-radius:12px}}.coeff{{border:0;min-width:760px}}.coeff td,.coeff th{{text-align:center}}.coeff td:first-child,.coeff th:first-child{{text-align:left}}.activeclass{{background:#eef3f8!important;font-weight:800}}.expertbox{{background:#fff8e6;border:1px solid #eedca3;border-radius:12px;padding:14px 16px;margin-bottom:12px;color:#68551c;line-height:1.45}}@media(max-width:1000px){{.refs{{grid-template-columns:repeat(2,1fr)}}}}@media(max-width:900px){{.grid,.filters,.indices,.refs{{grid-template-columns:1fr}}.primaryfilters{{display:grid}}.value{{font-size:34px}}table:not(.matrix):not(.coeff){{display:block;overflow:auto}}}}
</style></head><body><div class="wrap"><div class="top"><div class="brand">DevelopAid</div><div class="tag">STATISTICS · METHOD v3.0</div></div><h1>Себестоимость по методике DevelopAid</h1><div class="sub">Главный экран — не набор несопоставимых «цен за метр», а мэппинг источников на одну структуру CAPEX DevelopAid. Исходная база площади и исходный scope всегда сохраняются.</div><form class="primaryfilters" method="get"><input name="region" value="{reg}" placeholder="Регион"><select name="class">{opts}</select><input type="hidden" name="unit" value="{_esc(unit)}"><input type="hidden" name="metric_type" value="{_esc(metric_type)}"><button>Применить класс</button></form><div class="section"><h2>Матрица себестоимости · {reg} · { _esc(cls_label) }</h2><div class="sectionnote">Строки — статьи DevelopAid. Значение после стрелки или с меткой «экспертно» — индексация от базового класса источника к выбранному классу; единица площади при этом не меняется.</div>{matrix_html}<div class="sectionnote" style="margin-top:10px">* СИС/ЕРЗ раскрывает наружные сети и благоустройство совместно 8–12%; эти две ячейки показывают один и тот же агрегат и не суммируются. «Остаток» также не считается основным СМР.</div></div><div class="section"><h2>Экспертная индексация по классу</h2><div class="expertbox"><b>Комфорт = 1,00.</b> Это отдельный экспертный слой DevelopAid, а не статистика Росстата/Москомэкспертизы. Коэффициент применяется по статьям: класс сильнее влияет на основной СМР, ПИР и благоустройство и почти не влияет на сети и ТУ. При появлении достаточной выборки реальных проектов коэффициенты должны быть перекалиброваны.</div>{coeff_html}</div><div class="section"><h2>Контрольные ориентиры · {reg}</h2><div class="sectionnote">Исходные опубликованные показатели — для аудита. Они не складываются между собой и не становятся ГНС без исходных площадей.</div><div class="refs">{reference_cards}</div></div><div class="section"><h2>Индексация даты</h2><div class="sectionnote">Росстат и Мосстат отвечают только за приведение даты. Класс и временная индексация — две разные операции.</div><div class="indices">{index_cards}</div></div><div class="section"><h2>Статистическая выборка</h2><form class="filters" method="get"><input name="region" value="{reg}" placeholder="Регион"><select name="class">{opts}</select><select name="unit">{unit_opts}</select><select name="metric_type">{metric_opts}</select><button>Показать</button></form><div class="hero"><div class="eyebrow">Статистический ориентир · {reg} · {cls}</div><div class="value">{_fmt(r['recommended'])}</div><div class="range">P25–P75: {_fmt(r['p25'])} — {_fmt(r['p75'])}</div><div class="scope">{_esc(r.get('metric_label'))} · {_esc(r.get('unit_label'))}{(' · ' + _esc(r.get('scope_label'))) if r.get('scope_label') else ''}</div></div><div class="grid"><div class="card"><div class="label">Медиана</div><div class="num">{_fmt(r['median'])}</div></div><div class="card"><div class="label">Сопоставимых наблюдений</div><div class="num">{r['n']}</div></div><div class="card"><div class="label">Достоверность</div><div class="num">{conf}</div></div><div class="card"><div class="label">Статистика</div><div class="num">v{r['methodology_version']}</div></div></div>{warn}</div><div class="section"><h2>Реестр исходных источников</h2><table><thead><tr><th>Источник</th><th>Класс</th><th>Значение</th><th>База площади</th><th>Метрика</th><th>Scope</th><th>Дата</th></tr></thead><tbody>{source_rows}</tbody></table></div><div class="method"><span class="pill">Raw</span><span class="pill">DevelopAid mapping</span><span class="pill">Class adjustment</span><span class="pill">Comparable stats</span><br>{_esc(methodology)}</div></div></body></html>'''
        )

    return app

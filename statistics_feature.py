from __future__ import annotations

import html

from fastapi import Query
from fastapi.responses import HTMLResponse

from developaid_statistics import (
    METRIC_LABELS,
    SCOPE_LABELS,
    UNIT_LABELS,
    build_benchmark,
    load_external_benchmarks,
    load_normalized_benchmarks,
    load_observations,
    result_to_dict,
    source_catalog,
)


def _fmt(value):
    return "—" if value is None else f"{round(value / 1000):,}".replace(",", " ") + " тыс. ₽/м²"


def _esc(value) -> str:
    return html.escape(str(value or ""))


def _source_rows(rows: list[dict]) -> str:
    if not rows:
        return '<tr><td colspan="7">Нет сопоставимых источников для выбранного региона.</td></tr>'
    result = []
    for row in rows:
        value = _fmt(row.get("value_rub_m2"))
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
        return {"count": len(rows), "sources": rows, "methodology_version": "2.0"}

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
        reg, cls = html.escape(region), html.escape(housing_class)
        conf = {
            "high": "Высокая",
            "medium": "Средняя",
            "limited": "Ограниченная",
            "pilot": "Пилотная",
            "insufficient": "Недостаточно данных",
        }.get(r["confidence"], r["confidence"])
        refs = r.get("external_benchmarks") or []
        comparable = r.get("comparable_points") or []
        all_rows = comparable + refs
        source_rows = _source_rows(all_rows)

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
                '<div class="warn"><b>Рекомендация не подставлена.</b> '
                "Для выбранных класса, метрики и единицы пока нет сопоставимой выборки. "
                "Другие источники показаны ниже, но не усредняются с другим scope или знаменателем площади.</div>"
            )
        elif r["n"] < 5:
            warn = (
                f'<div class="warn"><b>Пилотный benchmark: N={r["n"]}.</b> '
                "Значение можно использовать как контрольную точку, но не как рыночную медиану. "
                "Для P25–P75 нужна выборка реальных проектов.</div>"
            )
        else:
            warn = ""

        methodology = (
            "Сначала сравниваются только одинаковые метрики: регион + класс + единица площади + scope затрат. "
            "СИС/ЕРЗ, внутренние бюджеты и отраслевые кейсы хранятся раздельно и не усредняются автоматически. "
            "Росстат будет использоваться как индексатор даты, а не как источник абсолютной себестоимости."
        )

        return HTMLResponse(
            f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DevelopAid — Статистика себестоимости</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f4f5f7;color:#1c2430;font:15px -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}}.wrap{{max-width:1240px;margin:auto;padding:32px 24px 70px}}.top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:30px}}.brand{{font-weight:800;font-size:20px}}.tag{{font-size:12px;padding:6px 10px;border:1px solid #d8dde5;border-radius:999px;background:#fff}}h1{{font-size:36px;margin:0 0 8px}}.sub{{color:#697386;margin-bottom:22px;max-width:850px;line-height:1.45}}.filters{{display:grid;grid-template-columns:1.4fr 1fr 1.25fr 1.5fr auto;gap:10px;background:#fff;padding:14px;border:1px solid #e0e4ea;border-radius:14px}}input,select,button{{height:44px;border-radius:9px;border:1px solid #d5dae2;padding:0 12px;background:#fff;font:inherit;min-width:0}}button{{background:#182131;color:#fff;border-color:#182131;padding:0 20px}}.hero{{margin-top:16px;background:#fff;border:1px solid #e0e4ea;border-radius:16px;padding:26px}}.eyebrow{{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#7b8492}}.value{{font-size:44px;font-weight:800;margin:7px 0}}.range{{color:#596273;font-size:17px}}.scope{{margin-top:8px;color:#7b8492;font-size:13px}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:14px}}.card{{background:#fff;border:1px solid #e0e4ea;border-radius:14px;padding:18px}}.label{{font-size:12px;color:#778091;margin-bottom:7px}}.num{{font-size:21px;font-weight:750}}.section{{margin-top:24px}}h2{{font-size:20px}}table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e0e4ea;font-size:13px}}td,th{{padding:12px 11px;text-align:left;border-bottom:1px solid #edf0f4;vertical-align:top}}th{{font-size:11px;color:#747d8d;background:#fafbfc;text-transform:uppercase;letter-spacing:.03em}}a{{color:#1e5a8a;text-decoration:none}}a:hover{{text-decoration:underline}}.warn{{padding:14px 16px;background:#fff8e6;border:1px solid #eedca3;border-radius:12px;color:#68551c;margin-top:16px;line-height:1.45}}.method{{margin-top:18px;color:#667080;font-size:13px;line-height:1.55;background:#fff;border:1px solid #e0e4ea;border-radius:12px;padding:15px}}.pill{{display:inline-block;margin:0 6px 6px 0;padding:5px 8px;border-radius:999px;background:#eef1f4;font-size:11px;color:#596273}}@media(max-width:900px){{.grid,.filters{{grid-template-columns:1fr}}.value{{font-size:34px}}table{{display:block;overflow:auto}}}}
</style></head><body><div class="wrap"><div class="top"><div class="brand">DevelopAid</div><div class="tag">STATISTICS · PILOT</div></div><h1>Статистика себестоимости</h1><div class="sub">Не одна «цена за метр», а сопоставимые слои затрат. Модуль различает основной СМР, СМР + благоустройство и полную стоимость застройщика, а также не смешивает ГНС, площадь квартир и продаваемую площадь.</div><form class="filters" method="get"><input name="region" value="{reg}" placeholder="Регион"><select name="class">{opts}</select><select name="unit">{unit_opts}</select><select name="metric_type">{metric_opts}</select><button>Показать</button></form><div class="hero"><div class="eyebrow">DevelopAid recommended · {reg} · {cls}</div><div class="value">{_fmt(r['recommended'])}</div><div class="range">P25–P75: {_fmt(r['p25'])} — {_fmt(r['p75'])}</div><div class="scope">{_esc(r.get('metric_label'))} · {_esc(r.get('unit_label'))}{(' · ' + _esc(r.get('scope_label'))) if r.get('scope_label') else ''}</div></div><div class="grid"><div class="card"><div class="label">Медиана</div><div class="num">{_fmt(r['median'])}</div></div><div class="card"><div class="label">Сопоставимых наблюдений</div><div class="num">{r['n']}</div></div><div class="card"><div class="label">Достоверность</div><div class="num">{conf}</div></div><div class="card"><div class="label">Методология</div><div class="num">v{r['methodology_version']}</div></div></div>{warn}<div class="section"><h2>Источники и слои</h2><table><thead><tr><th>Источник</th><th>Класс</th><th>Значение</th><th>База площади</th><th>Метрика</th><th>Scope</th><th>Дата</th></tr></thead><tbody>{source_rows}</tbody></table></div><div class="method"><span class="pill">Raw</span><span class="pill">Normalized</span><span class="pill">Recommended</span><br>{_esc(methodology)}</div></div></body></html>'''
        )

    return app

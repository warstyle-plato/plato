from __future__ import annotations

import html
from fastapi import Query
from fastapi.responses import HTMLResponse

from developaid_statistics import build_benchmark, load_external_benchmarks, load_observations, result_to_dict


def _fmt(value):
    return "—" if value is None else f"{round(value/1000):,}".replace(",", " ") + " тыс. ₽/м²"


def install(app):
    @app.get("/api/statistics/construction-cost")
    def construction_cost(region: str = Query(...), housing_class: str = Query("comfort", alias="class"), city: str | None = None, unit: str = "gba", floors_min: int | None = None, floors_max: int | None = None, construction_type: str | None = None, underground_parking: bool | None = None):
        result = build_benchmark(load_observations(), load_external_benchmarks(), region=region, housing_class=housing_class, city=city, unit=unit, floors_min=floors_min, floors_max=floors_max, construction_type=construction_type, underground_parking=underground_parking)
        return result_to_dict(result)

    @app.get("/statistics", response_class=HTMLResponse)
    def statistics_page(region: str = "Москва", housing_class: str = Query("business", alias="class"), city: str | None = None, unit: str = "gba"):
        r = result_to_dict(build_benchmark(load_observations(), load_external_benchmarks(), region=region, housing_class=housing_class, city=city, unit=unit))
        reg, cls = html.escape(region), html.escape(housing_class)
        conf = {"high":"Высокая", "medium":"Средняя", "limited":"Ограниченная", "insufficient":"Недостаточно данных"}.get(r["confidence"], r["confidence"])
        refs = r.get("external_benchmarks") or []
        ref_rows = "".join(f"<tr><td>{html.escape(x.get('source',''))}</td><td>{_fmt(x.get('value_rub_m2'))}</td><td>{html.escape(x.get('scope',''))}</td><td>{html.escape(x.get('reference_date',''))}</td></tr>" for x in refs) or '<tr><td colspan="4">Пока нет загруженных внешних ориентиров</td></tr>'
        class_opts = [("standard","Стандарт"),("comfort","Комфорт"),("business","Бизнес"),("premium","Премиум"),("elite","Элитный")]
        opts = "".join(f'<option value="{v}" {"selected" if housing_class==v else ""}>{n}</option>' for v,n in class_opts)
        warn = '<div class="warn">В тестовой базе пока нет достаточной объектной выборки для этого фильтра. Значение намеренно не подставляется до синхронизации официальных источников.</div>' if r['n'] < 5 else ''
        return HTMLResponse(f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DevelopAid — Статистика себестоимости</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f4f5f7;color:#1c2430;font:15px -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}}.wrap{{max-width:1180px;margin:auto;padding:32px 24px 70px}}.top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:30px}}.brand{{font-weight:800;font-size:20px}}.tag{{font-size:12px;padding:6px 10px;border:1px solid #d8dde5;border-radius:999px;background:#fff}}h1{{font-size:36px;margin:0 0 8px}}.sub{{color:#697386;margin-bottom:22px}}.filters{{display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:10px;background:#fff;padding:14px;border:1px solid #e0e4ea;border-radius:14px}}input,select,button{{height:44px;border-radius:9px;border:1px solid #d5dae2;padding:0 12px;background:#fff;font:inherit}}button{{background:#182131;color:#fff;border-color:#182131;padding:0 20px}}.hero{{margin-top:16px;background:#fff;border:1px solid #e0e4ea;border-radius:16px;padding:26px}}.eyebrow{{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#7b8492}}.value{{font-size:44px;font-weight:800;margin:7px 0}}.range{{color:#596273;font-size:17px}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:14px}}.card{{background:#fff;border:1px solid #e0e4ea;border-radius:14px;padding:18px}}.label{{font-size:12px;color:#778091;margin-bottom:7px}}.num{{font-size:21px;font-weight:750}}.section{{margin-top:24px}}h2{{font-size:20px}}table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e0e4ea}}td,th{{padding:13px 14px;text-align:left;border-bottom:1px solid #edf0f4}}th{{font-size:12px;color:#747d8d;background:#fafbfc}}.warn{{padding:14px 16px;background:#fff8e6;border:1px solid #eedca3;border-radius:12px;color:#68551c;margin-top:16px}}.method{{margin-top:18px;color:#667080;font-size:13px;line-height:1.5}}@media(max-width:800px){{.grid,.filters{{grid-template-columns:1fr}}}}
</style></head><body><div class="wrap"><div class="top"><div class="brand">DevelopAid</div><div class="tag">TEST · рядом с Рынком</div></div><h1>Статистика себестоимости</h1><div class="sub">Ориентиры по регионам и классам жилья. Объектная выборка, внешние benchmark и прозрачная достоверность.</div><form class="filters" method="get"><input name="region" value="{reg}" placeholder="Регион"><select name="class">{opts}</select><select name="unit"><option value="gba">₽/м² GBA</option><option value="apartments">₽/м² квартир</option><option value="sellable">₽/м² продаваемой</option></select><button>Показать</button></form><div class="hero"><div class="eyebrow">DevelopAid recommended · {reg} · {cls}</div><div class="value">{_fmt(r['recommended'])}</div><div class="range">P25–P75: {_fmt(r['p25'])} — {_fmt(r['p75'])}</div></div><div class="grid"><div class="card"><div class="label">Медиана</div><div class="num">{_fmt(r['median'])}</div></div><div class="card"><div class="label">Объектов</div><div class="num">{r['n']}</div></div><div class="card"><div class="label">Достоверность</div><div class="num">{conf}</div></div><div class="card"><div class="label">Методология</div><div class="num">v{r['methodology_version']}</div></div></div>{warn}<div class="section"><h2>Внешние ориентиры</h2><table><thead><tr><th>Источник</th><th>Значение</th><th>Методология</th><th>Дата</th></tr></thead><tbody>{ref_rows}</tbody></table></div><div class="method">ЕИСЖС — основная объектная выборка. Росстат — только индексация во времени. СИС/ЕРЗ — отдельный внешний benchmark. Разные знаменатели м² автоматически не смешиваются.</div></div></body></html>''')
    return app

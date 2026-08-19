from __future__ import annotations

import html
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from developaid_statistics import (
    build_benchmark,
    load_external_benchmarks,
    load_observations,
    result_to_dict,
)

app = FastAPI(title="DevelopAid Statistics Preview", version="0.1")


def _fmt(value):
    return "—" if value is None else f"{round(value/1000):,}".replace(",", " ") + " тыс. ₽/м²"


@app.get("/health")
def health():
    return {"ok": True, "service": "developaid-statistics-preview"}


@app.get("/api/statistics/construction-cost")
def construction_cost(
    region: str = Query(...),
    housing_class: str = Query("comfort", alias="class"),
    city: str | None = None,
    unit: str = "gba",
    floors_min: int | None = None,
    floors_max: int | None = None,
    construction_type: str | None = None,
    underground_parking: bool | None = None,
):
    result = build_benchmark(
        load_observations(),
        load_external_benchmarks(),
        region=region,
        housing_class=housing_class,
        city=city,
        unit=unit,
        floors_min=floors_min,
        floors_max=floors_max,
        construction_type=construction_type,
        underground_parking=underground_parking,
    )
    return result_to_dict(result)


@app.get("/statistics", response_class=HTMLResponse)
def statistics_page(
    region: str = "Москва",
    housing_class: str = Query("business", alias="class"),
    city: str | None = None,
    unit: str = "gba",
):
    result = build_benchmark(
        load_observations(),
        load_external_benchmarks(),
        region=region,
        housing_class=housing_class,
        city=city,
        unit=unit,
    )
    r = result_to_dict(result)
    cls = html.escape(housing_class)
    reg = html.escape(region)
    conf = {"high":"Высокая", "medium":"Средняя", "limited":"Ограниченная", "insufficient":"Недостаточно данных"}.get(r["confidence"], r["confidence"])
    relaxed = ", ".join(r["filters_relaxed"]) or "нет"
    return HTMLResponse(f"""
<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DevelopAid — Статистика себестоимости</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f5f6f8;color:#1d2433;font:15px Inter,Arial,sans-serif}}.wrap{{max-width:1180px;margin:auto;padding:34px 24px 70px}}
.top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:28px}}.brand{{font-weight:800;font-size:20px}}.tag{{font-size:12px;padding:6px 10px;border:1px solid #d9dde5;border-radius:999px;background:white}}
h1{{font-size:34px;line-height:1.1;margin:0 0 8px}}.sub{{color:#697386;margin-bottom:24px}}.filters{{display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:10px;background:white;padding:14px;border:1px solid #e2e5ea;border-radius:14px}}
input,select,button{{height:44px;border-radius:9px;border:1px solid #d6dae2;padding:0 12px;background:#fff;font:inherit}}button{{background:#172033;color:white;border-color:#172033;padding:0 20px;cursor:pointer}}
.hero{{margin-top:16px;background:white;border:1px solid #e2e5ea;border-radius:16px;padding:26px}}.eyebrow{{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#7c8493}}.value{{font-size:42px;font-weight:800;margin:7px 0 5px}}.range{{font-size:17px;color:#596273}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:16px}}
.card{{background:white;border:1px solid #e2e5ea;border-radius:14px;padding:18px}}.label{{font-size:12px;color:#778091;margin-bottom:7px}}.num{{font-size:21px;font-weight:750}}.note{{font-size:13px;color:#697386;margin-top:7px;line-height:1.45}}
.section{{margin-top:24px}}h2{{font-size:20px;margin:0 0 12px}}table{{width:100%;border-collapse:collapse;background:white;border:1px solid #e2e5ea;border-radius:14px;overflow:hidden}}td,th{{padding:13px 14px;text-align:left;border-bottom:1px solid #edf0f4}}th{{font-size:12px;color:#747d8d;font-weight:600;background:#fafbfc}}
.warn{{padding:14px 16px;background:#fff9e9;border:1px solid #f0dfaa;border-radius:12px;color:#67551f;margin-top:16px}}@media(max-width:800px){{.grid,.filters{{grid-template-columns:1fr}}}}
</style></head><body><div class="wrap">
<div class="top"><div class="brand">DevelopAid</div><div class="tag">TEST · статистический контур</div></div>
<h1>Статистика себестоимости</h1><div class="sub">Рыночные ориентиры по регионам и классам жилья с прозрачной методологией источников.</div>
<form class="filters" method="get"><input name="region" value="{reg}" placeholder="Регион"><select name="class"><option value="standard">Стандарт</option><option value="comfort">Комфорт</option><option value="business" {'selected' if housing_class=='business' else ''}>Бизнес</option><option value="premium">Премиум</option><option value="elite">Элитный</option></select><select name="unit"><option value="gba">₽/м² GBA</option><option value="apartments">₽/м² квартир</option><option value="sellable">₽/м² продаваемой</option></select><button>Показать</button></form>
<div class="hero"><div class="eyebrow">DevelopAid recommended · {reg} · {cls}</div><div class="value">{_fmt(r['recommended'])}</div><div class="range">P25–P75: {_fmt(r['p25'])} — {_fmt(r['p75'])}</div></div>
<div class="grid"><div class="card"><div class="label">Медиана выборки</div><div class="num">{_fmt(r['median'])}</div></div><div class="card"><div class="label">Объектов в выборке</div><div class="num">{r['n']}</div></div><div class="card"><div class="label">Достоверность</div><div class="num">{conf}</div></div><div class="card"><div class="label">Ослаблены фильтры</div><div class="num">{relaxed}</div></div></div>
<div class="section"><h2>Источники</h2><table><thead><tr><th>Источник</th><th>Роль</th><th>Что используем</th><th>Не смешиваем автоматически</th></tr></thead><tbody><tr><td>ЕИСЖС / наш.дом.рф</td><td>Основная объектная выборка</td><td>ПД, стоимость, площади, класс, характеристики дома</td><td>С разными знаменателями м²</td></tr><tr><td>Росстат</td><td>Индексация</td><td>Индексы цен строительной продукции</td><td>Не является себестоимостью проекта</td></tr><tr><td>СИС / ЕРЗ</td><td>Внешний benchmark</td><td>Региональная полная стоимость строительства</td><td>Отдельная методология и состав затрат</td></tr><tr><td>DevelopAid plan/fact</td><td>Будущий фактический слой</td><td>Бюджет, контрактование, факт, EAC</td><td>Только после обезличивания</td></tr></tbody></table></div>
{('<div class="warn">В тестовой базе пока нет достаточной объектной выборки для этого фильтра. Интерфейс намеренно не подставляет выдуманное значение: после синхронизации источников здесь появится статистика.</div>' if r['n'] < 5 else '')}
</div></body></html>""")

"""Isolated 12-lot KRT comparison page from the user-supplied KRT.pdf.

Route: /krt-12-preview
This page is intentionally separate from the production KRT catalogue.  It is
an audit/comparison surface for the twelve lots from the supplied comparison
sheet.  Missing rating components stay missing: the page never manufactures a
full 0..100 investment rating from partial source data.
"""
from __future__ import annotations

from fastapi.responses import HTMLResponse, JSONResponse

DEFAULT_PRICE_TARGET_RUB_SQM = 600_000.0


def price_score(market_rub_sqm, target_rub_sqm=DEFAULT_PRICE_TARGET_RUB_SQM):
    try:
        market = float(market_rub_sqm)
        target = float(target_rub_sqm)
    except (TypeError, ValueError):
        return None
    if target <= 0:
        return None
    ratio = market / target
    stops = [(0.70, 0.0), (0.85, 50.0), (1.00, 100.0)]
    if ratio <= stops[0][0]:
        return 0.0
    for (x1, y1), (x2, y2) in zip(stops, stops[1:]):
        if ratio <= x2:
            return y1 + (ratio - x1) / (x2 - x1) * (y2 - y1)
    return 100.0


LOTS = [
    {
        "lot": 2, "okrug": "САО", "name": "Дмитровское ш., влд. 60",
        "area_ha": 4.10, "start_price_mln": 178.36, "seizure_mln": 3680.0,
        "total_gfa_sqm": 94400, "housing_gfa_sqm": 94400, "nonres_gfa_sqm": 0,
        "load_housing_rub_sqm": 40872.46, "load_total_rub_sqm": 40872.46,
        "market_rub_sqm": 376832,
        "note": "ЛОС + инфраструктурный договор. Ближайшие ориентиры около 375–377 тыс. ₽/м²; в записке проект имеет смысл только при ожидании 475–500 тыс. ₽/м².",
    },
    {
        "lot": 6, "okrug": "СВАО", "name": "Алтуфьевское шоссе, проект 2, территория 1",
        "area_ha": 11.19, "start_price_mln": 170.0, "seizure_mln": 4830.0,
        "total_gfa_sqm": 219300, "housing_gfa_sqm": 146720, "nonres_gfa_sqm": 72580,
        "load_housing_rub_sqm": 34078.52, "load_total_rub_sqm": 22799.82,
        "market_rub_sqm": 486000,
        "note": "Инфраструктурный договор, школа/ДОО на 825 мест, 5 000 м² помещений для городских нужд. В записке реальная нагрузка с учётом школы оценивается около 60–65 тыс. ₽/м² жилья или выше.",
    },
    {
        "lot": 10, "okrug": "ЮАО", "name": "Шипиловский пр-д, влд. 55",
        "area_ha": 6.61, "start_price_mln": 410.0, "seizure_mln": 1000.0,
        "total_gfa_sqm": 55760, "housing_gfa_sqm": 0, "nonres_gfa_sqm": 55760,
        "load_housing_rub_sqm": None, "load_total_rub_sqm": 25286.94,
        "market_rub_sqm": None, "live_tender_start_mln": 4.11334042,
        "note": "50 090 м² спортивный кластер + 5 670 м² ФОК с бассейном. В сравнительном файле отдельно отмечен текущий повторный аукцион со стартом около 4,11 млн ₽.",
    },
    {
        "lot": 11, "okrug": "ВАО", "name": "ул. Рубцовско-Дворцовая, влд. 1/3",
        "area_ha": 6.93, "start_price_mln": 114.29, "seizure_mln": 2040.0,
        "total_gfa_sqm": 58020, "housing_gfa_sqm": 28350, "nonres_gfa_sqm": 29670,
        "load_housing_rub_sqm": 75989.07, "load_total_rub_sqm": 37130.13,
        "market_rub_sqm": 533154,
        "note": "Инфраструктурный договор + реставрация 5 ОКН площадью 6 550 м². Ориентир Stone Сокольники — 533 154 ₽/м².",
    },
    {
        "lot": 12, "okrug": "ЮАО", "name": "ул. Красного Маяка, влд. 16",
        "area_ha": 13.56, "start_price_mln": 730.0, "seizure_mln": 4020.0,
        "total_gfa_sqm": 241670, "housing_gfa_sqm": 194340, "nonres_gfa_sqm": 47330,
        "load_housing_rub_sqm": 24441.70, "load_total_rub_sqm": 19654.90,
        "market_rub_sqm": 380000,
        "note": "7 территориально разрозненных зон. ОДЦ/ФОК, помещения для ВОИ и молочно-раздаточного пункта, перебазирование ГБУ. Рыночный ориентир около 380 тыс. ₽/м².",
    },
    {
        "lot": 14, "okrug": "ЮАО", "name": "Харьковский пр-д, влд. 1–9",
        "area_ha": 22.79, "start_price_mln": 2190.0, "seizure_mln": 2060.0,
        "total_gfa_sqm": 441570, "housing_gfa_sqm": 201850, "nonres_gfa_sqm": 239720,
        "load_housing_rub_sqm": 35843.81, "load_total_rub_sqm": 9624.75,
        "market_rub_sqm": None,
        "note": "Из 239 720 м² нежилой застройки 193 680 м² — административно-деловая функция. Инфраструктурный договор + перенос ВЛ в кабель.",
    },
    {
        "lot": 16, "okrug": "ЮАО", "name": "МКАД, 26 км; ул. Липецкая, влд. 27",
        "area_ha": 11.15, "start_price_mln": 4800.0, "seizure_mln": 100.0,
        "total_gfa_sqm": 255270, "housing_gfa_sqm": 181560, "nonres_gfa_sqm": 73710,
        "load_housing_rub_sqm": 20514.11, "load_total_rub_sqm": 19195.36,
        "market_rub_sqm": None,
        "note": "Эконом-класс; 16 410 м² реновации, перехватывающий паркинг на 300 м/м и подстанция медпомощи. В записке отдельно отмечена фактическая удалённость от м. Тютчевская.",
    },
    {
        "lot": 18, "okrug": "ЮАО", "name": "Производственная зона Ленино",
        "area_ha": 31.32, "start_price_mln": 5200.0, "seizure_mln": 6600.0,
        "total_gfa_sqm": 504670, "housing_gfa_sqm": 381150, "nonres_gfa_sqm": 123520,
        "load_housing_rub_sqm": 34106.02, "load_total_rub_sqm": 23381.62,
        "market_rub_sqm": 390046,
        "note": "35 170 м² реновации, 3 ДОУ, очистные, каток, тяговая подстанция метро, перебазирование ГБУ, ЦОД и инфраструктурный договор. Срок КРТ 8 лет.",
    },
    {
        "lot": 21, "okrug": "ЮЗАО", "name": "ул. Архитектора Власова, влд. 59",
        "area_ha": 3.66, "start_price_mln": 810.11, "seizure_mln": 83.22,
        "total_gfa_sqm": 27915, "housing_gfa_sqm": 26260, "nonres_gfa_sqm": 1655,
        "load_housing_rub_sqm": 34018.66, "load_total_rub_sqm": 32001.79,
        "market_rub_sqm": 594548,
        "note": "Инфраструктурный договор, 800 м² для ГБУ Жилищника, парк не менее 1,57 га, сокращение СЗЗ. Ориентир Secret Garden — 594 548 ₽/м².",
    },
    {
        "lot": 28, "okrug": "ТиНАО", "name": "п. Знамя Октября, мкр. Родники, территория 1",
        "area_ha": 14.49, "start_price_mln": 1120.0, "seizure_mln": 1360.0,
        "total_gfa_sqm": 233430, "housing_gfa_sqm": 166880, "nonres_gfa_sqm": 66550,
        "load_housing_rub_sqm": 14860.98, "load_total_rub_sqm": 10624.17,
        "market_rub_sqm": None,
        "note": "В сравнительном файле дана краткая оценка «нецелесообразно» без дополнительной детализации.",
    },
    {
        "lot": 31, "okrug": "ЮАО", "name": "ул. Каспийская, влд. 22",
        "area_ha": 1.10, "start_price_mln": 24.09, "seizure_mln": 676.16,
        "total_gfa_sqm": 22890, "housing_gfa_sqm": 6890, "nonres_gfa_sqm": 16000,
        "load_housing_rub_sqm": 101632.80, "load_total_rub_sqm": 30591.96,
        "market_rub_sqm": 390046,
        "note": "Всего около 6,9 тыс. м² жилья и 16 тыс. м² общественной функции. Метро Царицыно около 750 м, береговая линия; ориентир Кавказский бульвар 51 — 390 046 ₽/м².",
    },
    {
        "lot": 42, "okrug": "ЮЗАО", "name": "Новоясеневский пр-кт, влд. 42, стр. 9",
        "area_ha": 0.69, "start_price_mln": 4.36, "seizure_mln": 606.16,
        "total_gfa_sqm": 10380, "housing_gfa_sqm": 0, "nonres_gfa_sqm": 10380,
        "load_housing_rub_sqm": None, "load_total_rub_sqm": 58816.96,
        "market_rub_sqm": None,
        "note": "5 860 м² МФК со спортивным объектом + 4 060 м² торгово-бытовой комплекс. В записке рассматривается только как арендный бизнес.",
    },
]


def _row(row: dict, target: float = DEFAULT_PRICE_TARGET_RUB_SQM) -> dict:
    item = dict(row)
    item["acquisition_mln"] = round(float(row["start_price_mln"]) + float(row["seizure_mln"]), 3)
    item["price_target_rub_sqm"] = target
    item["price_score"] = price_score(row.get("market_rub_sqm"), target)
    item["coverage_pct"] = 25 if item["price_score"] is not None else 0
    item["rating"] = None
    item["rating_reason"] = (
        "Экспресс-источник даёт цену рынка, но не authoritative LLCR, поглощение м²/мес. "
        "и burden/ordinary CAPEX. Итоговый рейтинг не присваивается."
        if item["price_score"] is not None else
        "Нет полного набора из четырёх компонентов рейтинга."
    )
    return item


PAGE = r'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>12 КРТ · DevelopAid</title><style>
:root{--bg:#f2f2ef;--line:#dedede;--muted:#6c6c6c;--soft:#f7f7f4}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#171717;font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial}
.shell{max-width:1480px;margin:auto;background:#fff;min-height:100vh}.head{padding:22px 28px 16px;border-bottom:7px solid #111}.head h1{margin:0;font-size:29px}.sub{color:var(--muted);margin-top:5px}
.content{padding:18px 28px 40px}.filters{display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:8px;margin-bottom:12px}.filters input,.filters select{height:42px;border:1px solid var(--line);background:#fff;padding:0 10px;font:inherit}
.summary{display:flex;justify-content:space-between;gap:10px;margin:10px 0 14px;color:var(--muted)}.cards{display:grid;gap:10px}
.card{border:1px solid var(--line);background:#fff}.top{display:grid;grid-template-columns:86px minmax(250px,1.3fr) minmax(560px,2.6fr);align-items:stretch}
.lot{display:flex;align-items:center;justify-content:center;border-right:1px solid var(--line);font-size:26px;font-weight:800;background:var(--soft)}
.id{padding:14px}.id b{font-size:17px}.tag{display:inline-block;border:1px solid var(--line);padding:3px 6px;font-size:10px;margin-bottom:7px}.muted{color:var(--muted)}
.metrics{display:grid;grid-template-columns:repeat(5,1fr);border-left:1px solid var(--line)}.m{padding:11px;border-right:1px solid var(--line)}.m b{display:block;font-size:15px}.m small{display:block;color:var(--muted);font-size:10px;margin-top:4px}
details{border-top:1px solid var(--line)}summary{cursor:pointer;padding:10px 14px;font-weight:650}.detail{padding:0 14px 14px;display:grid;grid-template-columns:1fr 1fr;gap:12px}.box{background:var(--soft);border:1px solid var(--line);padding:10px}.score{font-size:22px;font-weight:800}
@media(max-width:900px){.content{padding:14px}.filters{grid-template-columns:1fr 1fr}.top{grid-template-columns:64px 1fr}.metrics{grid-column:1/-1;grid-template-columns:repeat(2,1fr);border-left:0;border-top:1px solid var(--line)}.detail{grid-template-columns:1fr}}
</style></head><body><div class="shell"><header class="head"><h1>12 тестовых площадок КРТ</h1><div class="sub">Отдельный сравнительный экран по объектам из КРТ.pdf · не production-каталог</div></header><main class="content">
<div class="filters"><input id="q" placeholder="Лот, адрес, округ"><select id="okrug"><option value="">Все округа</option></select><select id="kind"><option value="">Жильё и нежильё</option><option value="housing">Есть жильё</option><option value="nonhousing">Только нежилое</option></select><select id="sort"><option value="lot">По номеру лота</option><option value="price_score">По баллу цены</option><option value="load_housing">По нагрузке на жильё</option><option value="acquisition">По сумме входа</option></select></div>
<div class="summary"><b id="found">Загружаю…</b><span>Итоговый рейтинг намеренно не рассчитывается по неполным данным</span></div><section class="cards" id="list"></section>
</main></div><script>
const $=id=>document.getElementById(id),n=v=>v===null||v===undefined||v===''?null:Number(v),fmt=(v,d=0)=>n(v)===null?'—':Number(v).toLocaleString('ru-RU',{maximumFractionDigits:d}),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let rows=[];
function card(x){return '<article class="card"><div class="top"><div class="lot">'+x.lot+'</div><div class="id"><span class="tag">'+esc(x.okrug)+'</span><br><b>'+esc(x.name)+'</b><div class="muted">'+fmt(x.area_ha,2)+' га · ГНС '+fmt(x.total_gfa_sqm)+' м²</div></div><div class="metrics">'+
[['Старт',fmt(x.start_price_mln,2)+' млн ₽'],['Изъятие',fmt(x.seizure_mln,2)+' млн ₽'],['Старт + изъятие',fmt(x.acquisition_mln,2)+' млн ₽'],['Нагрузка / м² жилья',x.load_housing_rub_sqm==null?'—':fmt(x.load_housing_rub_sqm)+' ₽'],['Цена рынка',x.market_rub_sqm==null?'—':fmt(x.market_rub_sqm)+' ₽/м²']].map(a=>'<div class="m"><b>'+esc(a[1])+'</b><small>'+esc(a[0])+'</small></div>').join('')+
'</div></div><details><summary>Расшифровка и наш текущий балл</summary><div class="detail"><div class="box"><b>Исходные ТЭП</b><p>Жильё: '+fmt(x.housing_gfa_sqm)+' м²<br>Нежильё: '+fmt(x.nonres_gfa_sqm)+' м²<br>Нагрузка на весь ГНС: '+fmt(x.load_total_rub_sqm)+' ₽/м²</p><p>'+esc(x.note)+'</p></div><div class="box"><b>Наша система 4×100</b><p class="score">Цена: '+(x.price_score==null?'—':fmt(x.price_score,1)+'/100')+'</p><p>Ценовой ориентир: '+fmt(x.price_target_rub_sqm)+' ₽/м²<br>Покрытие рейтинга: '+fmt(x.coverage_pct)+'%</p><p>LLCR: —<br>Поглощение: —<br>Нагрузка КРТ / ordinary CAPEX: —</p><p class="muted">'+esc(x.rating_reason)+'</p></div></div></details></article>'}
function render(){let q=$('q').value.trim().toLowerCase(),o=$('okrug').value,k=$('kind').value,s=$('sort').value;let v=rows.filter(x=>(!q||[x.lot,x.name,x.okrug].join(' ').toLowerCase().includes(q))&&(!o||x.okrug===o)&&(!k||(k==='housing'?x.housing_gfa_sqm>0:x.housing_gfa_sqm===0)));v.sort((a,b)=>{if(s==='price_score')return (b.price_score??-1)-(a.price_score??-1);if(s==='load_housing')return (a.load_housing_rub_sqm??Infinity)-(b.load_housing_rub_sqm??Infinity);if(s==='acquisition')return a.acquisition_mln-b.acquisition_mln;return a.lot-b.lot});$('found').textContent='Площадок: '+v.length+' из '+rows.length;$('list').innerHTML=v.map(card).join('')}
fetch('/krt-12-preview/data').then(r=>r.json()).then(d=>{rows=d.rows||[];$('okrug').innerHTML+=[...new Set(rows.map(x=>x.okrug))].sort().map(x=>'<option>'+esc(x)+'</option>').join('');render()});
['q','okrug','kind','sort'].forEach(id=>$(id).addEventListener(id==='q'?'input':'change',render));
</script></body></html>'''


def install(app):
    @app.get("/krt-12-preview/data", include_in_schema=False)
    async def krt_12_preview_data(price_target: float = DEFAULT_PRICE_TARGET_RUB_SQM):
        target = float(price_target or DEFAULT_PRICE_TARGET_RUB_SQM)
        return JSONResponse({
            "source": "user-supplied KRT.pdf, 2026-09-23",
            "method": "partial issue-485 rating; missing components remain missing",
            "rows": [_row(row, target) for row in LOTS],
        }, headers={"Cache-Control": "no-store"})

    @app.get("/krt-12-preview", response_class=HTMLResponse, include_in_schema=False)
    async def krt_12_preview():
        return HTMLResponse(PAGE, headers={"Cache-Control": "no-store, must-revalidate"})

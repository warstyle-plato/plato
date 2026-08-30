"""Вкладка «Тестовый отчёт bnMAP» в кабинете рынка.

Отдельный блок рядом с отчётом, а не внутри него — решение владельца
(30.08.2026): «можно на рыночном отчёте вкладку сделать типа тестовый отчёт bn,
для сравнения». Пока два источника не сверены на живых числах, действующий
отчёт не трогается: он собирает «Пульс», bnMAP стоит рядом и подписан тестовым.

Разметка живёт здесь, а не в `cabinet.py`, по той же причине, что контур и
подвал: в шаблоне кабинета стоит плейсхолдер, копии нет. В самом кабинете от
этой вкладки ровно две строки — место и подстановка.

**Числа не считаются нигде.** Сервер отдаёт готовую разметку по ответу bnMAP,
страница её показывает. Второй счёт той же величины однажды разошёлся бы с
первым, и обе поверхности выглядели бы верными — так уже расходились бот с
сайтом и книга с движком.

Опознавать объект приходится по идентификатору bnMAP, и это не лень: справочник
проектов у них за региональной лицензией (`layers.data` отвечает
`403 NO_REGION_ACCESS`), а метода поиска по адресу в каталоге нет вовсе. Пока
лицензии нет, адрес в идентификатор превратить нечем, и притворяться, что можем,
хуже, чем спросить номер.


Блоки клона рисует `blockCard` кабинета — тот же рендерер, которым показан
отчёт по «Пульсу». Своей вёрстки для них здесь нет: две вёрстки одного отчёта
разошлись бы, и обе выглядели бы верными. Здесь остаётся то, для чего блока в
отчёте не существует.
"""

from __future__ import annotations

from html import escape
from typing import Any

PLACEHOLDER = "__DEVELOPAID_BNMAP__"

# Колонки карточки соседа. Имена полей — из живого ответа `analytics.reportNearBy`
# (30.08.2026), а не из головы: у карточки 29 полей, здесь взяты те, что отвечают
# на те же вопросы, что наш отчёт задаёт «Пульсу».
# Оценке нужен не ряд за десять лет, а сегодняшняя цена, скидка с неё и то,
# как быстро уходит остаток (владелец, 30.08.2026: «история цены мало
# интересна для оценки»). Поэтому рядом с ценой метра стоят скидка и прогноз
# распродажи, а помесячный ряд bnMAP не показывается вовсе: он приходит в том
# же ответе и просто не выводится.
#
# Прогноз проверен арифметикой: 585 остатка при темпе 14 дают 41 месяц,
# 907 при 27 — 33, 1623 при 11 — 147. Значит подпись верна.
#
# Поле `price_dynamics` из той же карточки НЕ показывается: у соседей оно
# равно 5, 45, 624 и 298, процентами не читается, и чем является — неизвестно.
# Число под выдуманной подписью хуже отсутствующего числа.
# Ключи — те, что остаются после разбора строки: приставку `metrprice_avg_`
# снимает `_metric_row`, и таблица обязана знать имя ПОСЛЕ разбора, а не до.
_ROOMS: tuple[tuple[str, str], ...] = (
    ("st", "Студии"),
    ("1", "1к"),
    ("2", "2к"),
    ("3", "3к"),
    ("4", "4к+"),
)


def markup() -> str:
    """Свёрнутый блок кабинета. Открывается по нажатию, сам ничего не грузит."""
    return f"""
<details class="salesreport" id="bnmap"><summary>
  <b>Тестовый отчёт bnMAP</b>
  <span class="muted">второй источник — для сравнения; действующий отчёт считает «Пульс»</span>
</summary>
<div class="card">
  <div class="muted" style="font-size:13px;margin-bottom:10px">
    Числа показаны так, как их отдал bnMAP: здесь ничего не пересчитывается.
    Объект ищется в справочнике службы отчётов bnMAP — 1869 проектов Москвы и
    области с адресами и координатами; он открыт без подписки на платформу.
    Можно и номером, если он известен.
  </div>
  <div class="row">
    <div><label class="f">Объект: название, адрес, координаты или номер bnMAP</label>
      <input type="text" id="bnid" placeholder="Прайм Парк · Викторенко 16 · 55.79, 37.52 · 1"
             style="max-width:320px"></div>
    <div><label class="f">Регион</label>
      <select id="bnbase"><option value="msk" selected>Москва и область</option></select></div>
  </div>
  <button class="go alt" id="bngo" style="margin-top:10px">Собрать тестовый свод</button>
  <span id="bnstate" class="muted" style="margin-left:10px"></span>
  <div id="bnout" style="margin-top:12px"></div>
</div>
</details>
<script>
(function(){{
  const $=id=>document.getElementById(id);
  const go=$('bngo'); if(!go) return;
  go.addEventListener('click', async function(){{
    const q=($('bnid').value||'').trim();
    $('bnstate').textContent='спрашиваю bnMAP…'; $('bnout').innerHTML='';
    try{{
      const r=await fetch('/market/bnmap/report?object_id='+encodeURIComponent(q)
        +'&base='+encodeURIComponent($('bnbase').value));
      const text=await r.text();
      let data=null;
      try{{ data=JSON.parse(text); }}catch(e){{
        // Ответ разбирают, зная, что он может быть не ответом: шлюз отдаёт свою
        // страницу, и «The string did not match the expected pattern» вместо
        // причины отказа — это поломка разбора, а не сообщение сервиса.
        $('bnstate').textContent='ответ не разобрался ('+r.status+'): '
          +text.slice(0,120); return;
      }}
      if(!r.ok){{ $('bnstate').textContent=data.detail||('отказ '+r.status); return; }}
      $('bnstate').textContent='';
      // Блоки рисует рендерер отчёта — тот же `blockCard`. Пустые ряды для
      // графиков передаются намеренно: истории у этого источника мы не берём,
      // а функция графика на пустом ряду говорит об этом сама.
      const ctx={{peers:data.peers||[], subjectMetrics:data.subject||{{}},
        subjectName:(data.subject||{{}}).name||'', subjectSegment:(data.subject||{{}}).segment||'',
        series:[], sales:[], analysis:null}};
      const blocks=(data.blocks||[]).map(b=>{{
        try{{ return blockCard(b,ctx); }}
        catch(e){{ return '<div class="card"><h2>'+(b.title||'')+'</h2>'
          +'<div class="err">блок не нарисовался: '+e+'</div></div>'; }}
      }}).join('');
      $('bnout').innerHTML=blocks+'<div class="card">'+(data.html||'')+'</div>';
    }}catch(e){{ $('bnstate').textContent='не дошло до сервера: '+e; }}
  }});
}})();
</script>
"""


def render(report: dict[str, Any]) -> str:
    """То, чего в отчёте нет. Сами блоки рисует рендерер кабинета.

    Клон отчёта показывается ТЕМ ЖЕ `blockCard`, которым показан отчёт по
    «Пульсу»: иначе сравнение источников превратилось бы в сравнение двух
    наших вёрсток. Здесь остаётся то, для чего блока в отчёте не существует, —
    комнатность, скидки, городские зоны, — и оговорки: чего источник не дал и
    почему блок пуст.
    """
    out: list[str] = []
    account = report.get("account") or {}
    tools = account.get("tools") or []
    out.append('<div class="muted" style="font-size:12.5px;margin-bottom:10px">'
               + "Инструменты аккаунта bnMAP: "
               + (escape(", ".join(tools)) if tools else "не назвались")
               + " · срез " + escape(str(report.get("asked_date") or "—"))
               + " · числа показаны как пришли, считают их блоки нашего отчёта.</div>")
    for line in report.get("errors") or []:
        out.append('<div class="err" style="margin-bottom:8px">' + escape(str(line)) + "</div>")
    if report.get("reason"):
        out.append('<div class="err">' + escape(str(report["reason"])) + "</div>")
    out.append(_subject(report.get("found")))
    out.append(_rooms(report.get("peers"), report.get("subject")))
    out.append(_discounts(report.get("peers"), report.get("subject")))
    out.append(_rooms_balance(report.get("rooms_balance")))
    out.append(_deal_prices(report.get("deal_prices")))
    out.append(_indicators(report.get("indicators")))
    out.append(_gaps(report))
    return "".join(part for part in out if part)


def _gaps(report: dict[str, Any]) -> str:
    """Чего источник не дал. Пустой блок без причины читается как «этого нет»."""
    lines = list(report.get("gaps") or [])
    missing = report.get("unnamed_peers") or []
    if missing:
        lines.append("bnMAP назвал соседей, но карточек по ним не дал: "
                     + ", ".join(str(name) for name in missing))
    if not lines:
        return ""
    return ('<h3 style="margin-top:16px">Чего bnMAP не дал</h3><ul style="margin:0;'
            'padding-left:20px;color:#5b6b7d;font-size:13.5px">'
            + "".join("<li>" + escape(str(line)) + "</li>" for line in lines) + "</ul>")


def _subject(found: Any) -> str:
    """Чем опознан объект — часть ответа, а не подробность.

    Номер, найденный по слову в справочнике, и номер, введённый руками, на
    экране выглядят одинаково, а доверия к ним разное. Кандидаты показываются
    рядом: совпадение по адресу бывает не одно.
    """
    if not isinstance(found, dict) or not found.get("how"):
        return ""
    rows = found.get("candidates") or []
    names = ", ".join(
        escape(str(row.get("name") or row.get("address") or row.get("object_id")))
        + (f' ({row["distance_km"]} км)' if row.get("distance_km") is not None else "")
        for row in rows[:5])
    return ('<div class="muted" style="font-size:12.5px;margin-bottom:8px">'
            + "Объект опознан: " + escape(str(found["how"]))
            + " · номер " + escape(str(found.get("object_id") or "не найден"))
            + (" · рядом: " + names if names else "") + "</div>")


def _rooms_balance(rows: Any) -> str:
    """Квартирография объекта с остатком — по типам квартир.

    То же, что у нас в своде продаж считается по книге финмодели, но здесь по
    любому проекту и без файла. Отвечает на вопрос оценки прямо: какая полоса
    вымылась, а какая стоит.
    """
    if not isinstance(rows, list) or not rows:
        return ""
    body = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        body.append("<tr><td>" + escape(_room_name(row.get("type"))) + "</td>"
                    + _num({"val": row.get("pboCount")}) + _num({"val": row.get("pdoCount")})
                    + _num({"val": row.get("pboLeft")})
                    + '<td class="num">' + escape(str(row.get("pboLeftShare", "—"))) + " %</td></tr>")
    if not body:
        return ""
    return ('<h3 style="margin-top:16px">Квартирография и вымывание</h3>'
            '<div class="tablescroll"><table class="peers"><tr><th>Тип</th>'
            '<th class="num">В продаже</th><th class="num">Продано ДДУ</th>'
            '<th class="num">Остаток</th><th class="num">Доля остатка</th></tr>'
            + "".join(body) + "</table></div>")


def _deal_prices(data: Any) -> str:
    """Цена В СДЕЛКАХ по годам — не прайс.

    Прайс это витрина, сделка — факт, и разрыв между ними у нас до сих пор был
    виден только через скидки со слов застройщика. Разрез по комнатности тот же,
    что и у прайса, поэтому две таблицы читаются рядом.
    """
    years = (data or {}).get("years") if isinstance(data, dict) else None
    if not isinstance(years, list) or not years:
        return ""
    body = []
    for row in years:
        if not isinstance(row, dict):
            continue
        cells = "".join(_num({"val": row.get(key) or None}) for key, _ in _ROOMS)
        body.append("<tr><td>" + escape(str(row.get("year", "—"))) + "</td>" + cells + "</tr>")
    if not body:
        return ""
    head = "".join(f'<th class="num">{escape(title)}</th>' for _, title in _ROOMS)
    return ('<h3 style="margin-top:16px">Цена в сделках по годам, ₽/м²</h3>'
            '<div class="tablescroll"><table class="peers"><tr><th>Год</th>'
            + head + "</tr>" + "".join(body) + "</table></div>")


def _room_name(value: Any) -> str:
    """Подпись типа — та, что дал источник; «ст» разворачиваем в «студии»."""
    text = str(value or "").strip()
    return "Студии" if text.lower() in ("ст", "st") else (text + "к" if text.isdigit() else text or "—")


def _indicators(data: Any) -> str:
    """Рынок по зонам. Зоны и товары называет сам ответ, своего списка нет."""
    if not isinstance(data, dict) or not isinstance(data.get("short"), dict):
        return ""
    names = {"Kva": "Квартиры", "Ap": "Апартаменты"}
    zones = {"M": "Москва", "NewM": "Новая Москва", "MO": "Московская область"}
    rows = []
    for product, by_zone in data["short"].items():
        if not isinstance(by_zone, dict):
            continue
        for zone, vals in by_zone.items():
            if not isinstance(vals, dict):
                continue
            price = vals.get("Avgm2") or {}
            rows.append(
                "<tr><td>" + escape(names.get(product, product)) + "</td>"
                + "<td>" + escape(zones.get(zone, zone)) + "</td>"
                + _num(vals.get("KolProj")) + _num(vals.get("Kol")) + _num(price)
                + "<td class=\"num\">" + escape(str(price.get("percent", "—"))) + "%</td></tr>")
    if not rows:
        return ""
    return ('<h3>Рынок по зонам</h3><div class="muted" style="font-size:12.5px">'
            + f'срез {escape(str(data.get("date") or "—"))}, предыдущий '
            + f'{escape(str(data.get("pre_date") or "—"))}</div>'
            + '<div class="tablescroll"><table class="peers"><tr>'
            + "<th>Товар</th><th>Зона</th><th class=\"num\">Проектов</th>"
            + "<th class=\"num\">Лотов</th><th class=\"num\">₽/м²</th>"
            + "<th class=\"num\">Δ</th></tr>" + "".join(rows) + "</table></div>")


def _rooms(peers: Any, subject: Any) -> str:
    """Цена метра по комнатности — блока с таким вопросом в отчёте нет.

    Для оценки это работает там, где общая средняя врёт: у соседа с
    однокомнатным ядром и у соседа с крупными лотами один и тот же «средний
    метр» означает разные товары. Разбивку bnMAP отдаёт готовой, считать нечего.
    """
    rows = [row for row in ([subject] + list(peers or [])) if isinstance(row, dict) and row.get("rooms")]
    if not rows:
        return ""
    body = []
    for row in rows:
        rooms = row.get("rooms") or {}
        cells = "".join(_num({"val": rooms.get(key) or None}) for key, _ in _ROOMS)
        body.append("<tr><td>" + escape(str(row.get("name") or row.get("object_id")))
                    + (' <span class="self">— объект</span>' if row is rows[0] and row is subject else "")
                    + "</td>" + cells + "</tr>")
    head = "".join(f'<th class="num">{escape(title)}</th>' for _, title in _ROOMS)
    return ('<h3 style="margin-top:16px">Цена метра по комнатности</h3>'
            '<div class="tablescroll"><table class="peers"><tr><th>Проект</th>'
            + head + "</tr>" + "".join(body) + "</table></div>")


def _discounts(peers: Any, subject: Any) -> str:
    """Скидки и условия покупки. Прайс — не цена сделки, и разрыв виден числом."""
    rows = [row for row in ([subject] + list(peers or []))
            if isinstance(row, dict) and (row.get("discount") or row.get("discount_terms"))]
    if not rows:
        return ""
    body = []
    for row in rows:
        body.append("<tr><td>" + escape(str(row.get("name") or "")) + "</td>"
                    + _num({"val": row.get("price_per_sqm")})
                    + "<td>" + escape(str(row.get("discount") or "—")) + "</td>"
                    + '<td style="white-space:normal;max-width:420px">'
                    # Условия у застройщиков бывают на полтора экрана: акции,
                    # партнёрские карты, скидки льготным категориям. В таблицу
                    # идёт начало, целиком оно живёт в подсказке.
                    + f'<span title="{escape(str(row.get("discount_terms") or ""))}">'
                    + escape(_short(row.get("discount_terms"))) + "</span></td></tr>")
    return ('<h3 style="margin-top:16px">Скидки и условия покупки</h3>'
            '<div class="tablescroll"><table class="peers"><tr><th>Проект</th>'
            '<th class="num">Прайс, ₽/м²</th><th>Скидка</th><th>Условия</th></tr>'
            + "".join(body) + "</table></div>")


def _num(value: Any) -> str:
    raw = value.get("val") if isinstance(value, dict) else value
    if raw in (None, ""):
        return '<td class="num">—</td>'
    try:
        return '<td class="num">' + f"{float(raw):,.0f}".replace(",", " ") + "</td>"
    except (TypeError, ValueError):
        return '<td class="num">' + escape(str(raw)) + "</td>"


def _short(text: Any, limit: int = 150) -> str:
    """Начало условий. Обрезаем по слову: обрубок посреди числа читается как другое число."""
    words = " ".join(str(text or "").split())
    if len(words) <= limit:
        return words or "—"
    cut = words[:limit].rsplit(" ", 1)[0]
    return cut + "…"

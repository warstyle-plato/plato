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
"""

from __future__ import annotations

from html import escape
from typing import Any

PLACEHOLDER = "__DEVELOPAID_BNMAP__"

# Колонки карточки соседа. Имена полей — из живого ответа `analytics.reportNearBy`
# (30.08.2026), а не из головы: у карточки 29 полей, здесь взяты те, что отвечают
# на те же вопросы, что наш отчёт задаёт «Пульсу».
_PEER_COLUMNS: tuple[tuple[str, str], ...] = (
    ("distance", "Дист., км"),
    ("project", "Проект"),
    ("class", "Класс"),
    ("agreement", "Договор"),
    ("start_sales_date", "Старт продаж"),
    ("date_state_commission", "Ввод"),
    ("interior", "Отделка"),
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
    Объект задаётся его идентификатором — справочник проектов у bnMAP за
    региональной лицензией, и превратить адрес в номер пока нечем.
    Номер виден в адресе их кабинета: <code>platform.bnmap.pro/object/details/<b>2600</b></code>.
  </div>
  <div class="row">
    <div><label class="f">Идентификатор объекта bnMAP</label>
      <input type="text" id="bnid" placeholder="1" style="max-width:180px"></div>
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
    const id=($('bnid').value||'').trim();
    $('bnstate').textContent='спрашиваю bnMAP…'; $('bnout').innerHTML='';
    try{{
      const r=await fetch('/market/bnmap/report?object_id='+encodeURIComponent(id)
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
      $('bnout').innerHTML=data.html||'';
    }}catch(e){{ $('bnstate').textContent='не дошло до сервера: '+e; }}
  }});
}})();
</script>
"""


def render(report: dict[str, Any]) -> str:
    """Разметка по ответу bnMAP. Ни одного вычисления — только показ."""
    out: list[str] = []
    account = report.get("account") or {}
    tools = account.get("tools") or []
    expires = account.get("expires") or []
    out.append('<div class="muted" style="font-size:12.5px;margin-bottom:10px">'
               + "Инструменты аккаунта: "
               + (escape(", ".join(tools)) if tools else "не назвались")
               + (f" · доступ до {escape(expires[0])}" if expires else "")
               + " · " + escape(str(report.get("note") or "")) + "</div>")
    for line in report.get("errors") or []:
        out.append('<div class="err" style="margin-bottom:8px">' + escape(str(line)) + "</div>")

    out.append(_indicators(report.get("indicators")))
    out.append(_peers(report.get("nearby")))
    out.append(_location(report.get("nearby")))
    return "".join(part for part in out if part)


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


def _peers(data: Any) -> str:
    """Соседи так, как их подобрал сам bnMAP: расстояние он считает у себя."""
    if not isinstance(data, dict):
        return ""
    cards = {str(row.get("object_id")): row for row in data.get("nearby") or []
             if isinstance(row, dict)}
    rows = []
    for item in data.get("radius") or []:
        if not isinstance(item, dict):
            continue
        card = cards.get(str(item.get("id"))) or {}
        price = card.get("metrprice_avg") or {}
        total = card.get("apart_total") or {}
        cells = []
        for key, _ in _PEER_COLUMNS:
            if key == "distance":
                value = item.get("distance")
            elif key == "project":
                # Имя соседа лежит в строке радиуса под `name`, а в карточке —
                # под `project`. Ответ несёт оба; берём первое, что есть, иначе
                # сосед без карточки остаётся строкой из прочерков и читается
                # как пустая находка, хотя bnMAP его назвал.
                value = item.get("name") or card.get("project")
            else:
                value = card.get(key)
            cells.append("<td>" + escape(str(value if value not in (None, "") else "—")) + "</td>")
        cells.append(_num({"val": price.get("metrprice_avg_total")}))
        cells.append(_num({"val": total.get("expo")}))
        cells.append(_num({"val": card.get("pace_lots")}))
        cells.append(_num({"val": card.get("unrealized_count")}))
        rows.append("<tr>" + "".join(cells) + "</tr>")
    if not rows:
        return ('<h3>Соседи</h3><div class="muted">bnMAP соседей не вернул — '
                'либо не задан объект, либо у аккаунта нет инструмента.</div>')
    head = "".join(f"<th>{escape(title)}</th>" for _, title in _PEER_COLUMNS)
    return ('<h3 style="margin-top:16px">Соседи по версии bnMAP</h3>'
            '<div class="tablescroll"><table class="peers"><tr>' + head
            + '<th class="num">₽/м²</th><th class="num">Экспозиция</th>'
              '<th class="num">Темп, лотов</th><th class="num">Остаток</th></tr>'
            + "".join(rows) + "</table></div>")


def _location(data: Any) -> str:
    """Ряд цены по локации. Показываются края и длина — весь ряд не таблица."""
    if not isinstance(data, dict) or not isinstance(data.get("location"), dict):
        return ""
    series = data["location"]
    months = sorted(series)
    if not months:
        return ""
    last = series[months[-1]] or {}
    near = last.get("location_buildings") or {}
    return ('<h3 style="margin-top:16px">История цены по локации</h3>'
            '<div class="muted" style="font-size:12.5px">'
            + f'{len(months)} месячных точек, с {escape(months[0][:7])} по {escape(months[-1][:7])}. '
            + "На последней точке: проект "
            + escape(_money(last.get("current_project_metrprice_avg")))
            + ", пять ближайших "
            + escape(_money(last.get("five_projects_metrprice_avg")))
            + ", локация " + escape(_money(near.get("metrprice_avg")))
            + " при экспозиции " + escape(str(near.get("expo_num", "—")))
            + " лотов.</div>")


def _num(value: Any) -> str:
    raw = value.get("val") if isinstance(value, dict) else value
    if raw in (None, ""):
        return '<td class="num">—</td>'
    try:
        return '<td class="num">' + f"{float(raw):,.0f}".replace(",", " ") + "</td>"
    except (TypeError, ValueError):
        return '<td class="num">' + escape(str(raw)) + "</td>"


def _money(raw: Any) -> str:
    try:
        return f"{float(raw):,.0f}".replace(",", " ") + " ₽/м²"
    except (TypeError, ValueError):
        return "—"

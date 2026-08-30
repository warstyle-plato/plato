"""Управленческий контур: один вход и разделы по ролям.

«Кабинет надо объединить и сделать внутренним управленческим контуром. В
котором есть ссылки для строителя — монитор, коммерции — отчёт о продажах и
маркетинговый инструментарий для отчётов по рынку, инвестиций — КРТ и торги»
(владелец, 29.08.2026).

Это перестановка входов, а не переписывание модулей: страницы остаются свои,
контур становится их оглавлением. Объявлен он ОДИН раз — здесь, — и
подставляется на поверхности плейсхолдером, как подвал документов и версия.
Копии нет по той же причине: копию негде обновлять, а поверхность, добавленная
позже, иначе останется без входа в контур и найти её будет нельзя.

Ссылка на страницу, где человек уже стоит, не ссылка: она подсвечена и никуда
не ведёт. Иначе «Монитор» на мониторе выглядит как переход, который не
произошёл.
"""

from __future__ import annotations

PLACEHOLDER = "__DEVELOPAID_CONTOUR__"

# Роль — не отдел, а вопрос, с которым человек пришёл. Порядок тот же, что у
# владельца: стройка, продажи, покупки. Статистика себестоимости стояла у
# коммерции и стояла неверно: «статистика строительства — это аналитический
# блок, а не маркетинг» (владелец, 30.08.2026). Она обосновывает наши ставки, а
# не помогает продавать, и роль у неё своя.
# Три кабинета — решение владельца (30.08.2026): аналитика уходит в
# инвестиции. Роль тут не украшение: у каждой свой вход и свой Платон.
# «Роли и функции берём из твоей памяти» — состав входов наш, с макета взяты
# только карточки и портреты.
ROLES: tuple[dict[str, object], ...] = (
    {
        "role": "Строителю",
        "room": "Кабинет строительства",
        "face": "plato-build",
        "note": "ход стройки, деньги и сроки",
        "links": (
            {"href": "/monitor", "name": "Монитор проекта",
             "note": "ГПР и КС, платежи, прогноз ввода и дефицит"},
        ),
    },
    {
        "role": "Коммерции",
        "room": "Кабинет маркетинга",
        "face": "plato-market",
        "note": "продажи и рынок",
        "links": (
            {"href": "/cabinet/sales", "name": "Отчёт о продажах",
             "note": "договоры, темп, каналы, эскроу; PDF и презентация"},
            {"href": "/cabinet/market", "name": "Отчёт о рынке",
             "note": "соседи, цена метра, темп продаж, класс"},
        ),
    },
    {
        "role": "Инвестициям",
        "room": "Инвестиционный кабинет",
        "face": "plato-invest",
        "note": "что покупать и на чём стоят наши числа",
        "links": (
            {"href": "/auctions", "name": "Торги и КРТ",
             "note": "лоты и площадки, балл соответствия профилю"},
            {"href": "/", "name": "Расчёт проекта",
             "note": "участок, ТЭП, экономика, финансирование"},
            {"href": "/statistics", "name": "Статистика строительства",
             "note": "себестоимость по классам, свод источников и их методики"},
        ),
    },
)

def rooms(assets: str = "/cabinet/assets") -> str:
    """Титульная кабинета: три карточки с портретом, именем и входами.

    Карточки строятся из тех же `ROLES`, что и полоска контура: два списка
    входов однажды разошлись бы, и человек получил бы разное меню на титуле и
    на странице раздела. Портрета может не быть — тогда на его месте сказано,
    чего не хватает, а не пустой круг: пустое место читается как «так и надо».
    """
    cards = []
    for role in ROLES:
        links = "".join(
            f'<a href="{link["href"]}">{link["name"]}<span>{link["note"]}</span></a>'
            for link in role["links"]  # type: ignore[index]
        )
        face = str(role["face"])
        cards.append(
            f'<div class="room">'
            f'<img src="{assets}/{face}.webp" alt="{role["room"]}"'
            f' onerror="this.outerHTML=\'<div class=&quot;noface&quot;>портрет'
            f' {face} ещё не загружен</div>\'">'
            f'<b>{role["room"]}</b>'
            f'<div class="what">{role["note"]}</div>{links}</div>'
        )
    return "".join(cards)


STYLE = """
.contour{background:#fff;border:1px solid #dde5ed;border-radius:0;padding:12px 14px;
margin:0 0 16px;display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.contour .role{border-left:3px solid #1367AE;padding-left:10px}
.contour .role b{display:block;font-size:13px;color:#16202b}
.contour .role i{display:block;font-style:normal;font-size:11.5px;color:#5b6b7d;margin-bottom:5px}
.contour a{display:block;font-size:13px;color:#1367AE;text-decoration:none;margin-top:4px}
.contour a:hover{text-decoration:underline}
.contour a span{display:block;font-size:11px;color:#5b6b7d}
.contour .here{color:#16202b;font-weight:600;cursor:default}
.contour .here:hover{text-decoration:none}
@media print{.contour{display:none !important}}
"""


def markup(current: str = "") -> str:
    """Оглавление контура. `current` — адрес страницы, на которой человек стоит."""
    here = str(current or "").rstrip("/") or "/"
    blocks = []
    for role in ROLES:
        items = []
        for link in role["links"]:  # type: ignore[index]
            href = str(link["href"])
            name, note = str(link["name"]), str(link["note"])
            if (href.rstrip("/") or "/") == here:
                items.append(f'<a class="here" aria-current="page">{name}'
                             f'<span>{note}</span></a>')
            else:
                items.append(f'<a href="{href}">{name}<span>{note}</span></a>')
        blocks.append(f'<div class="role"><b>{role["role"]}</b>'
                      f'<i>{role["note"]}</i>{"".join(items)}</div>')
    return ('<nav class="contour" aria-label="Управленческий контур">'
            + "".join(blocks) + "</nav>")


def apply(page: str, current: str = "") -> str:
    """Подставить контур на поверхность.

    Плейсхолдера нет — страница отдаётся как была: контур это оглавление, а не
    условие работы страницы, и ронять из-за него поверхность нельзя.
    """
    if PLACEHOLDER not in page:
        return page
    return page.replace(PLACEHOLDER, markup(current))

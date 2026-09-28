"""Переданные метры стоят в своей колонке, а не внутри «продаваемой».

«Якобы продаются якобы метры школы и садика» (владелец, 26.09.2026). Он прав
буквально: у ДОУ в колонке «Продаваемая площадь» стоял ноль, а под ним
припиской — «передано 5 670,3 м²». То есть метры школы напечатаны ВНУТРИ
колонки, озаглавленной «продаваемая», и читаются её заголовком.

Приписку завели, чтобы не забыть про переданное («в отчёте вообще нет указания
на передаваемую», владелец 10.09.2026) — намерение верное, место неверное.
Число отвечает на заголовок своей колонки, а не на приписку под собой.

Ноль в продаваемой при этом остаётся нулём: «0 тоже сойдут» (владелец,
26.09.2026) — прочерк не заводим.

Проверка гоняет НАСТОЯЩИЙ кусок страницы через node, а не копию разметки:
копия разошлась бы со страницей молча и осталась бы зелёной.

Запуск: python3 -m pytest tests/test_the_given_metres_have_their_own_column.py -q
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(Path(__file__).resolve().parent))

import main_legacy as core  # noqa: E402
import page_blocks  # noqa: E402

# «шт.» из заголовков ушло 27.09.2026: мера у каждой строки своя и стоит при
# числе — у ДОО это места, у паркинга машино-места, у квартир квартиры.
HEADERS = ("Продукт", "ГНС наземная, м²", "Подземная, м²",
           "Продаваемая площадь, м²", "Передаётся, м²",
           "Построено", "Продаётся")


def _const(name: str) -> str:
    """Объявление-стрелка со страницы. Разрешитель ищет `function`, а форматом
    объявления проверка не занимается — берём саму строку, а не копию."""
    for line in core.PAGE.split("\n"):
        if line.startswith(f"const {name}="):
            return line
    raise AssertionError(f"на странице нет объявления const {name}=")


def _piece() -> str:
    """Кусок отрисовки — по своим границам, как его берёт соседняя проверка."""
    # Начало — у первого объявления блока (`soldUnits`), а не у `underGns`:
    # соседняя проверка берёт кусок текстом и до этого ей дела нет, а стенду
    # нужен исполнимый блок целиком.
    start = core.PAGE.index(" const soldUnits=x=>Number(")
    end = core.PAGE.index("const REPORT_SECTIONS", start)
    piece = core.PAGE[start:end]
    # Кусок лежит ВНУТРИ функции, и его хвост несёт её закрывающую скобку:
    # без обрезки node падает «Unexpected token }», то есть на стенде, а не на
    # том, что стенд проверяет.
    return piece[:piece.rindex("}")]


def _render() -> str:
    """Отрисовать таблицу на школе и садике — тех самых строках со скрина."""
    # Списки и слова берутся у движка, а не переписываются в стенд: копия
    # разошлась бы с объявлением молча. На странице они стоят плейсхолдерами,
    # и разрешитель их не найдёт — значит подставляем тем же значением.
    declared = ("const UNDERGROUND_PRODUCTS=" + json.dumps(list(core.UNDERGROUND_PRODUCTS))
                + ";\nconst TRANSFER_NOTE_WORD=" + json.dumps(core.TRANSFER_NOTE_WORD) + ";\n"
                # Мера счёта продукта — такой же подставленный плейсхолдером
                # список, как и соседние: разрешитель их не находит.
                + "const TEP_COUNT_MEASURE="
                + json.dumps(core.TEP_COUNT_MEASURE, ensure_ascii=False) + ";\n"
                + "const COUNT_PARKING=" + json.dumps(core.COUNT_PARKING, ensure_ascii=False)
                + ";\n"
                + _const("num") + "\n")
    stand = declared + """
const reportTep={innerHTML:''};
const document={getElementById:()=>null};
const r={summary:{underground_gns_sqm:60690,construction_volume_sqm:270690},
 tep:{core_under_gns:60690,
  total:{gns:270690,saleable:153600,units:3150,transfer:25668.5},
  rows:[
   {key:'apartments',label:'Квартиры',gns:210000,saleable:136500,transfer:0,
    units:1800,saleable_units:1800,guest_units:0,transfer_units:0},
   {key:'underground_parking',label:'Подземный паркинг',gns:60690,saleable:0,
    transfer:0,units:2376,saleable_units:2267,guest_units:109,transfer_units:0},
   {key:'kindergarten',label:'ДОУ',gns:6300.3,saleable:0,transfer:5670.3,
    units:350,saleable_units:0,guest_units:0,transfer_units:350},
   {key:'school',label:'СОШ',gns:22220.2,saleable:0,transfer:19998.2,
    units:1000,saleable_units:0,guest_units:0,transfer_units:1000}]}};
"""
    tail = "console.log(reportTep.innerHTML);"
    out, _taken = page_blocks.run(stand + _piece(), tail)
    return out


def _cells(html: str, label: str) -> list[str]:
    """Ячейки строки продукта — так, как их видит человек."""
    rows = re.findall(r"<tr>(.*?)</tr>", html, re.S)
    for row in rows:
        if f"<td>{label}</td>" in row:
            return [re.sub(r"<[^>]+>", " ", cell).strip()
                    for cell in re.findall(r"<td>(.*?)</td>", row, re.S)]
    raise AssertionError(f"строки {label} в таблице нет:\n{html}")


def test_the_table_has_a_column_for_the_given_metres() -> None:
    """Колонка объявлена, и порядок заголовков — тот, что видит человек."""
    html = _render()
    heads = [re.sub(r"<[^>]+>", "", one).strip()
             for one in re.findall(r"<th>(.*?)</th>", html[:html.index("</thead>")], re.S)]
    assert heads == list(HEADERS), heads


def test_the_metres_of_a_school_are_not_inside_the_saleable_column() -> None:
    """То, что видно на скрине: 19 998,2 м² школы под заголовком «продаваемая»."""
    html = _render()
    saleable, given = _cells(html, "СОШ")[3], _cells(html, "СОШ")[4]
    assert saleable.replace("\xa0", " ").strip() == "0", (
        f"в продаваемой школы стоит не ноль: {saleable!r}")
    assert "19" in given and "998" in given, f"переданных метров нет в своей колонке: {given!r}"
    assert "998" not in saleable, "переданные метры всё ещё внутри продаваемой"


def test_a_sold_product_leaves_the_given_column_at_zero() -> None:
    """У квартир передавать нечего, и это ноль, а не пустая ячейка."""
    cells = _cells(_render(), "Квартиры")
    assert cells[4].strip() == "0", cells


def test_the_total_of_the_given_metres_stands_in_its_own_column() -> None:
    """Итог переданного — колонка, а не приписка под итогом продаваемой."""
    html = _render()
    foot = html[html.index("<tfoot>"):]
    cells = [re.sub(r"<[^>]+>", " ", one).strip()
             for one in re.findall(r"<th>(.*?)</th>", foot, re.S)]
    assert len(cells) == len(HEADERS), cells
    given = cells[4].replace("\xa0", "").replace(" ", "").replace(",", ".")
    assert abs(float(given) - 25668.5) < 0.6, cells
    assert "передан" not in cells[3].lower(), "приписка вернулась в продаваемую"


def test_the_built_column_still_says_what_is_not_sold() -> None:
    """Приписка про гостевые и переданные ШТУКИ остаётся у построенного.

    Её место верное: она объясняет разницу между двумя соседними колонками
    штук, а не подписывает чужую величину.
    """
    html = _render()
    assert "из них гостевых" in html
    assert core.TRANSFER_NOTE_WORD in html

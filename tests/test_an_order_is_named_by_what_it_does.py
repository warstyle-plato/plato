"""Распоряжение города решает ДЕЙСТВИЕМ, а не подписью.

Замер прода 15.09.2026 (`POST /auctions/krt/tenders`): распоряжений 55, к
площадкам привязано 25 — 22 действующих, 1 отмена и ДВА, которые страница
выбрасывала молча. Гейт стоял по номеру (`if(!order||!order.number)`), а у этих
двух номер пуст:

  Рубцовская наб., влд. 3          — начальная цена     23 808 328 ₽
  Задонский пр-д, Ясеневая ул.     — начальная цена  1 574 787 939 ₽

Обе — «О проведении торгов», обе с адресом, распознанным в самом документе, и
обе не доезжали ни до оси отбора, ни до шага воронки, ни до цены входа модели.

Номер у них при этом ЕСТЬ и стоит в заголовке карточки mos.ru: «№ ДГП-Р 58/26».
Город пишет разделитель между буквенной частью и числом то дефисом, то
пробелом, а образец требовал цифру сразу за буквами. Та же семья, что
ASCII-дефис в именах ЖК и номер владения, написанный диапазоном.

Отсюда две половины, и обе нужны: разбор читает вторую форму записи (замер по
55 заголовкам — прибавилось 2, потеряно 0, изменилось 0), а гейт перестаёт
требовать подпись вовсе — непрочитанный номер это НАШ пробел, а не отсутствие
документа, и следующий такой выпал бы так же молча.

Запуск: python3 -m pytest tests/test_an_order_is_named_by_what_it_does.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import json  # noqa: E402

import page_blocks  # noqa: E402
from auction_search import ui  # noqa: E402
from market_search import krt_decisions  # noqa: E402
from test_a_cancelled_order_is_not_a_tender import CANCEL, HOLD, _answers  # noqa: E402

# Снимок заголовков прода от 15.09.2026. Живые публичные заголовки mos.ru:
# собранный руками пример подтвердил бы только себя, а форма записи у города и
# есть предмет проверки.
SPACED = ("Распоряжение Департамента градостроительной политики города Москвы "
          "по основной деятельности № ДГП-Р 58/26 от 03.09.2026 О проведении "
          "торгов в форме аукциона на право заключения договора о комплексном "
          "развитии территории нежилой застройки")
HYPHEN = ("Распоряжение Департамента градостроительной политики города Москвы "
          "от 14.08.2026 № ДГП-Р-54/26 О проведении торгов в форме аукциона на "
          "право заключения договора о комплексном развитии территории "
          "нежилой застройки")


def _number(title: str) -> str:
    return krt_decisions.parse_tender_order(
        {"id": "1", "title": title, "url": "u", "date": 1})["number"]


def test_the_number_is_read_in_both_forms_the_city_writes():
    assert _number(SPACED) == "ДГП-Р 58/26", "номер через пробел не прочитан"
    assert _number(HYPHEN) == "ДГП-Р-54/26", "дефисная форма читалась и должна читаться"
    # Буквы только заглавные и без флага регистронезависимости: иначе строчное
    # слово перед числом становится частью номера, и «№ от 03.09.2026» даёт
    # уверенное «от 03.09» — выдуманная подпись хуже её отсутствия.
    assert _number("Распоряжение № от 03.09.2026 о проведении аукциона "
                   "по комплексному развитию") == ""


def test_an_order_without_a_read_number_is_still_a_tender():
    """Подпись не прочитана — документ от этого не исчезает.

    Проверяется тем, что видно: ось отбора, шаг воронки и цена входа. Строковый
    тест тут зелен на обоих — гейт живёт одной строкой.
    """
    said = _answers(
        {"rubtsovskaya": {}},
        {"rubtsovskaya": {"number": "", "title": SPACED, "action": "hold",
                          "published_at": 1788382800, "start_price_rub": 23_808_328}},
    )
    row = said["rubtsovskaya"]
    assert row["order"], "распоряжение выброшено по отсутствию подписи"
    assert row["announced"] and row["on_tender"]
    assert row["stage"] == "upcoming"
    assert row["price"], "объявленная цена входа не доехала до модели"
    # Внутренний идентификатор mos.ru читателю немой — как «dipp» в адресе
    # публикации: вместо него сказано, что номер не прочитан.
    assert "без прочитанного номера" in row["price"], row["price"]


def test_a_cancelled_order_without_a_number_is_still_not_a_tender():
    """Предохранитель: гейт ослаблен по подписи, но не по действию.

    Без этой проверки соседняя зеленела бы и на коде, который пускает всё
    подряд, — то есть вернула бы отменённый аукцион в цену входа.
    """
    said = _answers(
        {"volgogradskiy": {}},
        {"volgogradskiy": {"number": "", "title": CANCEL, "action": "cancel",
                           "published_at": 1691653557, "start_price_rub": 1_000_000_000}},
    )
    row = said["volgogradskiy"]
    assert not row["order"] and not row["announced"]
    assert not row["price"], "начальная цена отменённого аукциона в модель не идёт"


def test_the_order_is_named_once_for_every_reader():
    """Имя распоряжения одно на всех читателей, а не «номер или id» пятью копиями.

    Проверяется поведением: на одном и том же документе строка воронки и цена
    входа обязаны сказать одно и то же. Пересказ имени здесь закрепил бы ту
    копию, из-за которой правило и заведено.
    """
    said = _answers(
        {"named": {}, "unnamed": {}},
        {"named": {"number": "ДГП-Р 58/26", "title": SPACED, "action": "hold",
                   "published_at": 1788382800, "start_price_rub": 23_808_328},
         "unnamed": {"id": "349133220", "number": "", "title": SPACED, "action": "hold",
                     "published_at": 1788382800, "start_price_rub": 23_808_328}},
    )
    assert "№ ДГП-Р 58/26" in said["named"]["price"], said["named"]["price"]
    assert "без прочитанного номера" in said["unnamed"]["price"]
    assert "349133220" not in said["unnamed"]["price"], "внутренний id mos.ru на экране"


def _card(order: dict | None, mark: dict | None, catalogue: bool = True) -> str:
    """Что карточка ГОВОРИТ про распоряжение — её же функцией, текстом без разметки."""
    page = ui.auctions_page(None)
    prelude = (page_blocks.page_const("state", page)
               + "\nstate.krtOrderBySite=" + json.dumps({"s": order} if order else {}, ensure_ascii=False) + ";"
               + "\nstate.krtOrders=" + json.dumps(
                   [order] if order else ([FOUND] if catalogue else []), ensure_ascii=False) + ";"
               + "\nstate.krtTenderLinks=" + json.dumps({"s": mark} if mark else {}, ensure_ascii=False) + ";")
    tail = """
const html=krtOrderBlock({slug:'s'});
console.log(JSON.stringify({text:html.replace(/<[^>]+>/g,' ').replace(/\\s+/g,' ').trim()}));
"""
    return page_blocks.run_json(prelude, tail, page=page)["text"]


FOUND = {"id": "349133220", "number": "ДГП-Р-54/26", "title": SPACED, "action": "hold",
         "url": "https://www.mos.ru/dgp/documents/view/349133220/", "published_at": 1788382800,
         "start_price_rub": 23_808_328, "deposit_rub": 4_761_665, "step_rub": 476_166,
         "address": "г. Москва, Рубцовская наб., влд. 3", "ocr_notes": []}


def test_the_card_prints_what_the_machine_found():
    """Найденное машиной печаталось НИКОГДА, а карточка при этом падала.

    Условие было собрано как `found||krtMarked(mark) ? <ветка про mark> : …`,
    то есть `(found||mark) ? …`: при найденном распоряжении и без ручной
    отметки ветка читала `mark.number` у null — `selectKrt` бросал TypeError,
    и карточка не открывалась вовсе. На проде 15.09.2026 это 22 площадки из 25
    привязанных, в том числе Варшавское ш., вл. 37.
    """
    said = _card(FOUND, None)
    assert "Объявлены торги" in said
    assert "ДГП-Р-54/26" in said, said[:160]
    assert "23 808 328" in said, "начальная цена из распоряжения не показана"
    assert "Рубцовская наб." in said, "адрес, распознанный в документе, не показан"
    assert "не нашлось" not in said


def test_the_hand_mark_is_shown_when_the_machine_found_nothing():
    """Предохранитель: ветка ручной отметки не потеряна вместе с починкой."""
    said = _card(None, {"order_id": "349133220", "number": "ДГП-Р-57/26",
                        "url": "u", "published_at": 1788382800, "marked_at": 1788382900})
    assert "Отмечено вручную" in said and "ДГП-Р-57/26" in said, said[:160]
    # Город публикует распоряжения, а к этой площадке ни одно не привязалось —
    # это названный ответ, а не пустое место: молча снятое читается как «город
    # об этой площадке ничего не публиковал».
    assert "не нашлось" in _card(None, None)
    # А когда и публиковать нечего, и отметки нет, блока нет ВОВСЕ: постоянная
    # приписка ни о чём перестаёт читаться.
    assert _card(None, None, catalogue=False) == ""

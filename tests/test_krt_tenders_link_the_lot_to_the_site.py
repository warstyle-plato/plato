"""Торги по КРТ связаны с площадками каталога.

«У нас не отработана система поиска информации о торгах по КРТ» (владелец,
31.08.2026). Два модуля жили рядом и не разговаривали: торги знали про лоты,
каталог — про площадки, а вопрос «эту площадку уже выставили?» не задавался
нигде — при том что ИнвестМосква ищется в том числе по словам «комплексное
развитие территории», то есть лоты КРТ в выдаче есть с самого начала.

Измерено на живых ответах mos.ru (31.08.2026): город объявляет такие торги
распоряжением ДГП, их 53. Но АДРЕСА в распоряжении нет — ни в заголовке, ни в
карточке документа, а PDF оказался сканом: извлекается только регистрационный
штамп. Поэтому распоряжение показывается фактом со ссылкой и датой, а к
площадке не привязывается. Привязывается лот: у него есть адрес и кадастры.

Запуск: python3 -m pytest tests/test_krt_tenders_link_the_lot_to_the_site.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.krt_tenders import looks_like_krt, match  # noqa: E402
from market_search.krt_decisions import parse_tender_order  # noqa: E402

SITES = [
    {"slug": "vyatskaya", "name": "Вятская ул., вл. 41А", "okrug": "САО"},
    {"slug": "svetly", "name": "Светлый проезд, вл. 4", "okrug": "САО"},
]
KRT_LOT = {
    "title": "Право на заключение договора о комплексном развитии территории "
             "нежилой застройки по адресу: г. Москва, Вятская ул., вл. 41А",
    "address": "г. Москва, Вятская ул., вл. 41А",
    "cadastral_numbers": [],
    "current_price_rub": 1_200_000_000,
    "application_deadline": "2026-09-30",
    "source": {"catalogue": "ИнвестМосква", "lot_url": "https://investmoscow.ru/tenders/1"},
}
PLAIN_LOT = {
    "title": "Продажа земельного участка по адресу: г. Москва, Вятская ул., вл. 41А",
    "address": "г. Москва, Вятская ул., вл. 41А",
    "cadastral_numbers": [],
    "source": {"catalogue": "ИнвестМосква", "lot_url": "https://investmoscow.ru/tenders/2"},
}
FAR_LOT = {
    "title": "Право на заключение договора о комплексном развитии территории "
             "по адресу: г. Москва, Вятская ул., вл. 12",
    "address": "г. Москва, Вятская ул., вл. 12",
    "cadastral_numbers": [],
    "source": {"catalogue": "ИнвестМосква", "lot_url": "https://investmoscow.ru/tenders/3"},
}


def test_a_krt_lot_finds_its_site() -> None:
    got = match([KRT_LOT], SITES)
    assert list(got["by_site"]) == ["vyatskaya"]
    assert got["by_site"]["vyatskaya"][0]["price_rub"] == 1_200_000_000
    assert got["by_site"]["vyatskaya"][0]["source"] == "ИнвестМосква"
    assert got["krt_lots"] == 1


def test_a_plain_land_sale_is_not_a_krt_tender() -> None:
    """Город продаёт участки сотнями; «право на КРТ» отличают только слова лота."""
    assert looks_like_krt(PLAIN_LOT) is False
    got = match([PLAIN_LOT], SITES)
    assert got["by_site"] == {} and got["krt_lots"] == 0


def test_the_same_street_with_another_holding_is_another_site() -> None:
    """Ложная привязка объявила бы площадку проданной."""
    got = match([FAR_LOT], SITES)
    assert got["by_site"] == {}
    assert len(got["unmatched"]) == 1, "лот про КРТ не пропадает — он находка"


def test_an_unmatched_krt_lot_is_kept_and_named() -> None:
    got = match([KRT_LOT, FAR_LOT], SITES)
    assert len(got["by_site"]["vyatskaya"]) == 1
    assert got["unmatched"][0]["address"].endswith("вл. 12")


def test_the_cadastral_number_beats_the_address() -> None:
    lot = dict(KRT_LOT, address="", title="Право на КРТ, кадастровый номер 77:09:0004014:13",
               cadastral_numbers=["77:09:0004014:13"])
    sites = [{"slug": "by-cad", "name": "Площадка 77:09:0004014:13", "okrug": ""}]
    got = match([lot], sites)
    assert list(got["by_site"]) == ["by-cad"]


def test_the_order_is_read_but_never_tied_to_a_site() -> None:
    """Адреса в распоряжении нет, и придумывать привязку по номеру нельзя."""
    row = {
        "id": "342473220",
        "date": 1778619600,
        "url": "https://www.mos.ru/dgp/documents/view/342473220/",
        "title": ("Распоряжение Департамента от 13.05.2026 № ДГП-Р-28/26 "
                  "\"О проведении торгов в форме аукциона на право заключения договора "
                  "о комплексном развитии территории нежилой застройки города Москвы\""),
    }
    order = parse_tender_order(row)
    assert order is not None
    assert order["number"] == "ДГП-Р-28/26"
    assert order["kind"] == "нежилой застройки"
    assert "address" not in order, "адреса в распоряжении нет — поля быть не должно"

    assert parse_tender_order({"id": "1", "title": "О внесении изменений в постановление"}) is None

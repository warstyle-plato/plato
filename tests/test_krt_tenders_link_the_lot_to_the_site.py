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


# --- Отметка о торгах ставится человеком, а не выводится машиной --------------
#
# «Пишем в ячейке КРТ, что согласно постановлению такому-то объявлены торги»
# (владелец, 31.08.2026). Машине привязать нечем: адреса в распоряжении нет ни в
# заголовке, ни в карточке документа, а PDF — скан (семь страниц, 199 картинок
# на первой, текста только регистрационный штамп; текстовых полей у записи
# поиска тоже нет — пустые). Привязка по номеру или по дате объявила бы площадку
# выставленной на торги без единого основания.

def test_the_mark_is_stored_as_a_human_statement(tmp_path) -> None:
    from market_search.krt_registry import KrtRegistry

    registry = KrtRegistry(tmp_path, fetch=lambda url: b"{}")
    assert registry.tender_link("vyatskaya") == {}

    order = {"id": "342473220", "number": "ДГП-Р-28/26",
             "url": "https://www.mos.ru/dgp/documents/view/342473220/",
             "published_at": 1778619600, "kind": "нежилой застройки"}
    saved = registry.mark_tender("vyatskaya", order, who="владелец")
    assert saved["number"] == "ДГП-Р-28/26"
    assert saved["marked_at"] > 0, "отметка обязана нести дату — это утверждение человека"
    assert saved["marked_by"] == "владелец"

    again = KrtRegistry(tmp_path, fetch=lambda url: b"{}")
    assert again.tender_link("vyatskaya")["number"] == "ДГП-Р-28/26", "отметка не пережила перезапуск"
    assert again.mark_tender("vyatskaya", {}) == {}
    assert again.tender_link("vyatskaya") == {}


def test_an_empty_slug_is_refused(tmp_path) -> None:
    from market_search.krt_registry import KrtRegistry

    registry = KrtRegistry(tmp_path, fetch=lambda url: b"{}")
    try:
        registry.mark_tender("", {"number": "x"})
    except ValueError:
        return
    raise AssertionError("площадка без имени не должна отмечаться")


def test_the_card_says_the_mark_is_by_hand() -> None:
    from auction_search import ui

    page = ui.AUCTIONS_PAGE
    body = page[page.index("function krtOrderBlock("):]
    body = body[:body.index("\nfunction ", 1)]
    assert "Отмечено вручную" in body
    assert "адреса в распоряжении нет" in body, "причина ручной отметки названа на экране"
    assert "Согласно распоряжению" in body, "формулировка владельца"


def test_the_route_only_accepts_a_mos_ru_document() -> None:
    """Ссылка на что угодно превратила бы отметку в свободное поле."""
    source = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")
    block = source[source.index('"/auctions/krt/{slug}/tender-order"'):]
    block = block[:block.index('@app.get("/auctions/krt/tender-links")')]
    assert 'startswith("https://www.mos.ru/")' in block
    assert "скан" in block, "причина ручной отметки названа и в маршруте"

"""«Здесь уже продаётся ЖК» — самый громкий ответ на «можно ли войти».

«Почему тут нет даже намёка на то, что это Страна Девелопмент и там по адресу
42 уже ЖК строится» (владелец, 03.09.2026). Ответ лежал в той же выдаче: у
Озёрной, вл. 42-46 восемь страниц продаж «Страны.Озерной» и офис продаж по
адресу «Озёрная ул., 42». Корзины были написаны языком канцелярии — оператор,
договор, городские нужды, — а источники говорят языком продаж, и ни одно
канцелярское слово на странице агрегатора не стоит. Молчание при этом читалось
как «о площадке не пишут».

Документы ниже — настоящие заголовки из хранимого ответа прода (снимок
03.09.2026, slug ozernaya-ul-vld-42-46).

Запуск: python3 -m pytest tests/test_the_site_already_sells_flats.py -q
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search.krt_open_sources import (  # noqa: E402
    FINDING_BUCKETS, _clean_name, read_findings)

OZERNAYA = "Озерная ул., вл. 42-46"
# На той же улице стоит вторая площадка каталога — значит одного названия улицы
# мало, и номер владения обязателен.
NEIGHBOUR = "Озерная ул., вл. 37, Вернадского просп., вл. 62"


@dataclass
class Doc:
    title: str
    snippet: str
    url: str = "https://example.ru/x"
    domain: str = "example.ru"
    rank: int = 1


SELLS = Doc(
    title="ЖК Страна.Озерная — купить квартиру в Москве от застройщика",
    snippet=("ЖК Страна.Озерная, Озёрная ул., вл. 42-46, Очаково-Матвеевское. "
             "Цены и планировки квартир от застройщика."),
    url="https://whitewill.ru/zhk-strana-ozernaya/",
    domain="whitewill.ru")

# Адрес написан по-человечески, диапазоном и без «вл.»: «на Озерной улице, 42-46».
PLAIN_RANGE = Doc(
    title="ЖК Страна. Озерная: АКЦИЯ от официального застройщика ГК Страна Девелопмент",
    snippet=("ЖК Страна. Озерная на Озерной улице, 42-46: акция от официального "
             "застройщика ГК Страна Девелопмент."),
    url="https://www.novostroy-m.ru/zhk_strana_ozernaya",
    domain="www.novostroy-m.ru")

# Сестринский проект того же застройщика: имя бренда общее, площадка другая.
SISTER = Doc(
    title="ЖК Страна.Заречная от застройщика Страна Девелопмент",
    snippet="ЖК Страна.Заречная — купить квартиру от застройщика Страна Девелопмент.",
    url="https://msk.restate.ru/strana-zarechnaya/",
    domain="msk.restate.ru")

# Соседняя площадка каталога — та же улица, чужой номер.
NEXT_DOOR = Doc(
    title="Озерная, 37: старт продаж нового ЖК",
    snippet="Озерная ул., вл. 37 — старт продаж, купить квартиру от застройщика.",
    url="https://www.cian.ru/ozernaya-37/",
    domain="www.cian.ru")

DECISION = Doc(
    title="Проект решения о комплексном развитии территории нежилой застройки",
    snippet=("Озерная ул., вл. 42-46. Проект решения опубликован для сбора мнений "
             "правообладателей."),
    url="https://www.mos.ru/dgp/documents/1/",
    domain="www.mos.ru")


def _read(*docs: Doc) -> dict:
    return read_findings(list(docs), OZERNAYA, [NEIGHBOUR])


def test_a_selling_complex_at_our_address_is_found_and_closes_the_entry() -> None:
    found = _read(SELLS, DECISION)
    assert found["selling_now"], "страница продаж по нашему адресу — находка"
    assert "купить квартиру" in found["selling_now"][0]["quote"].lower()
    assert found["selling_now"][0]["url"] == SELLS.url
    # Продающийся ЖК занимает площадку так же, как заключённый договор.
    assert found["taken"] is True
    assert found["free"] is False


def test_the_address_is_read_as_a_plain_range_too() -> None:
    """«На Озерной улице, 42-46» — тот же адрес, что «вл. 42-46»."""
    found = _read(PLAIN_RANGE)
    assert found["selling_now"], "диапазон без «вл.» — тот же номер владения"


def test_a_sister_project_of_the_same_developer_proves_nothing_here() -> None:
    """Бренд общий, площадка другая: «Страна.Заречная» — не наш адрес."""
    found = _read(SISTER)
    assert found["selling_now"] == []
    assert found["taken"] is False


def test_the_neighbouring_site_on_the_same_street_is_not_ours() -> None:
    found = _read(NEXT_DOOR)
    assert found["selling_now"] == []


def test_the_developer_name_drops_the_headline_tail() -> None:
    """«ГК Страна Девелопмент в Москве и МО - квартиры» — это заголовок, не имя."""
    assert _clean_name("ГК Страна Девелопмент в Москве и МО - квартиры") \
        == "ГК Страна Девелопмент"
    assert _clean_name("ГК Страна Девелопмент — информация") == "ГК Страна Девелопмент"
    # Внутри кавычек хвост не режется: «КРТ «Магистральные улицы» — группа ЕСН»
    # это одно лицо, а не имя и приписка.
    assert _clean_name("«КРТ «Магистральные улицы» — группа ЕСН") \
        == "«КРТ «Магистральные улицы» — группа ЕСН"


def test_every_bucket_is_named_in_the_answer() -> None:
    """Корзины объявлены один раз, и ответ несёт их список.

    Перечисление подводило дважды: в счётчике каналов (0.21.59) и на экране —
    застройщик, торги и роль Фонда приезжали и не рисовались вовсе.
    """
    found = _read(SELLS)
    keys = [bucket["key"] for bucket in found["buckets"]]
    assert keys == [bucket["key"] for bucket in FINDING_BUCKETS]
    for key in keys:
        assert key in found, f"корзина {key} объявлена и не отдана"
    assert all(bucket["title"] for bucket in found["buckets"])


def test_the_card_draws_the_buckets_the_server_names() -> None:
    """Карточка рисует по списку сервера, а не по своему перечислению."""
    from auction_search import ui

    page = ui.auctions_page()
    body = page[page.index("function showKrtPress("):]
    body = body[:body.index("\nfunction ")]
    assert "d.buckets" in body, "список корзин берётся из ответа сервера"
    # Ни одного имени корзины руками: перечисление в двух местах расходится.
    for bucket in FINDING_BUCKETS:
        assert f"d.{bucket['key']}" not in body, \
            f"корзина {bucket['key']} перечислена руками"

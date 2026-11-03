"""Оператор и городские нужды читаются там, где о них пишут.

Проверка на восьми живых проектах решений mos.ru (31.08.2026): «оператор»,
«застройщик», «государственных нужд», «изъятие», «победитель» — ноль раз из
восьми; «реновация» — один раз. Признак, собранный по решению и карточке, не
срабатывал потому, что искать было негде («твой фильтр КРТ не отлавливает ни
операторы, ни городские нужды», владелец, 31.08.2026).

Фразы ниже — настоящие, из ручной таблицы владельца: он выписал их из
публикаций mos.ru и деловой прессы. Разбор написан по ним, а не по догадке о
том, как это могло бы быть сформулировано.

Запуск: python3 -m pytest tests/test_krt_open_sources_read_the_press.py -q
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search.krt_open_sources import queries, read_findings  # noqa: E402


@dataclass
class Doc:
    title: str
    snippet: str
    url: str = "https://www.mos.ru/news/item/1/"
    domain: str = "mos.ru"
    rank: int = 1


MAGISTRAL = Doc(
    title="Магистральные улицы: комплексное развитие территории",
    snippet=("Статус на krt.mos.ru «Планируемый проект», вместе с тем в марте 2026 была "
             "представлена концепция проекта. Оператором выступает компания "
             "«КРТ «Магистральные улицы» - группа ЕСН."))
MOLDAVSKAYA = Doc(
    title="Молдавская улица, владение 3-5",
    snippet=("В течение семи лет на Молдавской улице назначенный городом оператор "
             "проведет редевелопмент неэффективно используемой площадки, на которой "
             "построит современный административно-деловой центр."))
MIRA = Doc(
    title="Проспект Мира, владение 82-92",
    snippet=("Право на редевелопмент участка на проспекте Мира в центре столицы "
             "выставят на торги по программе комплексного развития территорий."))
PUDOVKINA = Doc(
    title="Улица Пудовкина, владение 7А",
    snippet="В марте 2026 на Пудовкина были объявлены торги на поиск генерального подрядчика.")
# Номер владения в цитате стоит намеренно: с 02.09.2026 тяжёлый признак
# (реновация, оператор, договор) ставится только там, где назван НАШ адрес, —
# улица опознаёт квартал, а не площадку.
RENOVATION = Doc(
    title="Квартал реновации на улице Добролюбова",
    snippet=("Площадка на улице Добролюбова, вл. 8 вошла в программы реновации: "
             "переселение жителей начнётся после ввода стартового дома."),
    domain="stroi.mos.ru")
STRANGER = Doc(
    title="Оператором выступает ООО «Чужой Девелопмент»",
    snippet="Оператором комплексного развития другой площадки в Бутове стал ООО «Чужой Девелопмент».",
    domain="example.com")


def test_the_named_operator_is_read_with_its_name() -> None:
    got = read_findings([MAGISTRAL], "Магистральные улицы тер. 4, 5, 6")
    assert got["operator_named"], "имя оператора не найдено"
    name = got["operator_named"][0]["name"]
    assert "ЕСН" in name or "Магистральные" in name, f"имя разобрано как «{name}»"
    assert got["taken"] is True
    assert got["operator_named"][0]["official"] is True, "mos.ru — официальный источник"
    assert "Оператором выступает" in got["operator_named"][0]["quote"]


def test_an_appointed_operator_without_a_name_is_a_separate_answer() -> None:
    got = read_findings([MOLDAVSKAYA], "Молдавская ул., вл. 3-5")
    assert not got["operator_named"], "имени в этой публикации нет — выдумывать нечего"
    assert got["operator_appointed"], "«назначенный городом оператор» — это факт"
    assert got["taken"] is True


def test_a_site_whose_right_is_yet_to_be_auctioned_is_not_taken() -> None:
    got = read_findings([MIRA], "проспект Мира, вл. 82-92")
    assert got["operator_pending"] and not got["taken"]
    assert got["free"] is True, "право ещё выставят — войти можно"


def test_the_stage_is_a_fact_with_a_quote() -> None:
    got = read_findings([PUDOVKINA], "ул. Пудовкина, вл. 7А")
    assert got["stage"] and "торги" in got["stage"][0]["quote"]


def test_city_needs_come_from_the_press_when_the_decision_is_silent() -> None:
    got = read_findings([RENOVATION], "ул. Добролюбова, вл. 8")
    assert got["city_needs"], "реновация в публикации названа прямо"
    assert got["city_needs"][0]["domain"] == "stroi.mos.ru"


def test_a_sentence_about_another_site_is_not_ours() -> None:
    """Сниппет повторяет слова запроса — без якоря площадки сюда попадёт любой."""
    got = read_findings([STRANGER], "Магистральные улицы тер. 4, 5, 6")
    assert not got["operator_named"] and not got["taken"], \
        "чужая площадка приписала бы себе нашего оператора"


def test_nothing_found_is_not_nothing_there() -> None:
    got = read_findings([], "ул. Добролюбова, вл. 8")
    assert got["checked"] == 0
    assert got["taken"] is False and got["free"] is False
    assert got["operator_named"] == [] and got["city_needs"] == []


def test_the_queries_carry_the_address_and_the_district() -> None:
    asked = queries("Молдавская ул., вл. 3-5", okrug="ЗАО", district="Кунцево")
    assert asked and all("Молдавская" in one for one in asked)
    assert any("Кунцево" in one for one in asked)
    assert queries("") == []


# --- Найденное входит в фильтр, а не остаётся на карточке --------------------

def _function(page: str, name: str) -> str:
    start = page.index(f"function {name}(")
    depth, index, seen = 0, page.index("{", start), False
    while index < len(page):
        if page[index] == "{":
            depth, seen = depth + 1, True
        elif page[index] == "}":
            depth -= 1
            if seen and depth == 0:
                return page[start:index + 1]
        index += 1
    raise AssertionError(f"не нашёл конец функции {name}")


def test_the_press_findings_reach_the_filter() -> None:
    """Находка, видная только на карточке, не влияет ни на что."""
    from auction_search import ui

    body = _function(ui.AUCTIONS_PAGE, "krtIntent")
    assert "state.krtPress" in body, "фильтр не знает о публикациях"
    assert "operator_named" in body and "city_needs" in body
    assert "merged.taken" in body


def test_the_press_is_asked_by_hand_not_on_every_card() -> None:
    """Веб-поиск платный и небыстрый: на каждую открытую карточку его не зовут."""
    from auction_search import ui

    assert "id=\"krtPress\"" in ui.AUCTIONS_PAGE
    assert "loadKrtPress" in ui.AUCTIONS_PAGE
    opened = _function(ui.AUCTIONS_PAGE, "selectKrt")
    assert "loadKrtPress(x)" in opened, "кнопка должна быть привязана"
    assert opened.count("loadKrtPress") == 1, "по нажатию, а не при открытии"


def test_a_silent_search_is_not_an_empty_answer() -> None:
    from auction_search import ui

    body = _function(ui.AUCTIONS_PAGE, "loadKrtPress")
    assert "не спрошены" in body and "не значит, что о площадке не пишут" in body


def test_the_reader_uses_the_engine_search_and_not_its_own() -> None:
    """Модуль, идущий наружу мимо общего пути, однажды ответит иначе, чем сервис.

    Здесь стояло `getattr(service, "search", None)` — и проверка искала в
    исходнике ровно ту строку, которая ломала маршрут: имя `service` живёт
    локально внутри маршрута выдачи лотов, снаружи его нет, и кнопка отвечала
    пятисоткой всегда (экран владельца, 01.09.2026). Совпадение текста ничего
    не говорит о том, разрешается ли имя, — поэтому рядом стоит проверка,
    которая маршрут ЗОВЁТ (`test_the_press_button_answers.py`).

    Проверяется РАЗБОР, а не тело маршрута: разбор с 01.09.2026 объявлен один
    раз (`_read_open_sources`) и зовётся и кнопкой, и еженедельным прогоном.
    Прежняя проверка смотрела на строки внутри маршрута и упала бы на любом
    выносе кода, ничего не сказав о том, что сломалось на самом деле.
    """
    source = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")
    block = source[source.index("def _read_open_sources("):]
    block = block[:block.index("\n    def _open_sources_for_run(")]
    assert 'getattr(market, "search", None)' in block
    assert 'getattr(service, "search", None)' not in block
    assert "YandexSearchClient" not in block, "своего клиента поиска здесь быть не должно"
    assert "configured" in block


def test_the_button_and_the_run_share_one_reader() -> None:
    """Два разбора однажды ответят про одну площадку разное, и оба достоверно."""
    source = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")
    assert source.count("def _read_open_sources(") == 1
    route = source[source.index('"/auctions/krt/{slug}/open-sources"'):]
    route = route[:route.index('@app.get("/auctions/krt/{slug}/card-facts")')]
    assert "_read_open_sources" in route, "кнопка пошла мимо общего разбора"

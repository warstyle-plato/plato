"""Ту же компанию называют другими словами — и все они значат одно.

Владелец прислал две публикации о КРТ на Светлом проезде, вл. 4 (01.09.2026),
и фильтр не считал площадку занятой ни по одной из них. Причина не в якоре и не
в поиске: в обоих текстах слова «застройщик» нет вовсе.

    «Компания «КС-Про», на 30% принадлежащая головной организации девелопера
    STONE — АО «Стоунхедж», проводит инженерно-геодезические работы на участке
    по адресу: Светлый проезд, вл. 4.»   (t.me/livesokol)

    «ЖК от STONE на Светлый проезд, 4»   (dzen.ru, 15.12.2025)

Первое — «девелопер», которого не было в наших словах. Второе — другая форма
целиком: имя стоит ПЕРЕД адресом, и хвостовой разбор («что написано после
слова «оператор») его не достаёт вовсе.

Имя при этом берётся только доказанное: «ЖК от застройщика» — это роль, а не
компания, и именем не становится. Регистр здесь значащий, поэтому у имени он не
игнорируется — под общим `(?i)` «застройщика» проходило как имя.

Запуск: python3 -m pytest tests/test_a_developer_is_named_by_other_words_too.py -q
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import krt_open_sources  # noqa: E402

SITE = "Светлый проезд, вл. 4"

LIVESOKOL = ("Компания «КС-Про», на 30% принадлежащая головной организации девелопера "
             "STONE — АО «Стоунхедж», проводит инженерно-геодезические работы "
             "на участке по адресу: Светлый проезд, вл. 4.")
DZEN = "ЖК от STONE на Светлый проезд, 4 — старт продаж ЖК бизнес-класса в САО Москвы"


@dataclass
class Doc:
    title: str
    snippet: str
    url: str = "https://t.me/livesokol/14677"
    domain: str = "t.me"
    rank: int = 1


def test_a_developer_counts_as_an_operator():
    got = krt_open_sources.read_findings(
        [Doc(title="Стройка на Светлом проезде", snippet=LIVESOKOL)], SITE)
    assert got["operator_named"], "«девелопер» не опознан как тот, кто площадку берёт"
    name = got["operator_named"][0]["name"]
    assert "Стоунхедж" in name or "STONE" in name, f"имя разобрано как «{name}»"
    assert got["taken"] is True


def test_the_name_keeps_its_closing_quote():
    """«АО «Стоунхедж» с непарной кавычкой дальше не совпадёт ни с чем."""
    name = krt_open_sources._operator_name(LIVESOKOL)
    assert name.count("«") == name.count("»"), f"непарная кавычка в «{name}»"


def test_a_brand_before_the_address_is_read_too():
    """«ЖК от STONE» — имя стоит перед адресом, хвостовой разбор его не видит."""
    got = krt_open_sources.read_findings(
        [Doc(title=DZEN, snippet="", url="https://dzen.ru/a/x", domain="dzen.ru")], SITE)
    assert got["operator_named"], "имя из заголовка не прочитано"
    assert got["operator_named"][0]["name"] == "STONE"
    assert got["taken"] is True


def test_a_role_after_ot_is_not_a_name():
    for phrase in ("ЖК от застройщика на Светлый проезд",
                   "Проект от Города на Светлый проезд",
                   "Квартал от девелопера на Светлый проезд"):
        assert krt_open_sources._operator_name(phrase) == "", phrase


def test_a_quoted_brand_is_read():
    assert krt_open_sources._operator_name(
        "ЖК от «Донстрой» на Светлый проезд") == "Донстрой"


def test_the_old_wording_still_works():
    """Правка добавляет слова, а не заменяет прежние."""
    name = krt_open_sources._operator_name(
        "Оператором выступает компания «КРТ «Магистральные улицы» - группа ЕСН.")
    assert "ЕСН" in name or "Магистральные" in name


def test_a_stranger_site_still_does_not_borrow_the_name():
    """Якорь не смягчается: имя без адреса площадки — чужое."""
    got = krt_open_sources.read_findings(
        [Doc(title="ЖК от STONE на Бутовской улице", snippet="")], SITE)
    assert not got["operator_named"] and got["taken"] is False


# --- Что поиск принёс, видно на экране ---------------------------------------
#
# Владелец трижды подряд присылал публикацию, которую видно глазами, и каждый
# раз разговор начинался с догадок: карточка показывала только НАХОДКИ, а по
# пустому блоку нельзя сказать, промолчал источник или промолчали мы.


def test_the_findings_carry_what_was_read():
    got = krt_open_sources.read_findings(
        [Doc(title=DZEN, snippet="", url="https://dzen.ru/a/x", domain="dzen.ru"),
         Doc(title="Новости района Сокол", snippet="Про совсем другое место")], SITE)
    docs = got["documents"]
    assert len(docs) == 2, "прочитанные документы до карточки не доезжают"
    assert docs[0]["domain"] == "dzen.ru" and docs[0]["url"]
    assert docs[0]["anchored"] is True, "документ с адресом площадки помечен как чужой"
    assert docs[1]["anchored"] is False, "документ без якоря выдан за подходящий"


def test_an_empty_search_is_not_an_empty_site():
    got = krt_open_sources.read_findings([], SITE)
    assert got["documents"] == []
    assert got["checked"] == 0


def test_the_screen_shows_what_was_read():
    from auction_search import ui

    page = ui.auctions_page(None)
    assert "function krtPressDocs(" in page, "прочитанное на экране не показывается"
    assert "Что прочитано" in page
    assert "без якоря площадки" in page, \
        "отброшенный документ неотличим от непрочитанного"
    assert "Поиск не вернул ни одного документа" in page, \
        "пустая выдача подана как отсутствие фактов о площадке"


# --- Спрашиваем вопросом, а не набором слов ----------------------------------
#
# Владелец (01.09.2026): «даже тупая Алиса от Яндекса находит легко, когда
# задаёшь вопрос, кто оператор или кто строит КРТ по такому адресу».
#
# Прежние запросы были неудачны дважды. Адрес брался в ЖЁСТКИЕ КАВЫЧКИ — точной
# фразой «Светлый проезд, вл. 4», которой в публикациях нет: dzen пишет
# «Светлый проезд, 4». И рядом стояло одно слово «оператор», хотя пишут
# «застройщик», «девелопер», «построит».


def test_the_office_shorthand_is_dropped_from_the_query():
    """«вл.» пишет каталог, а не люди."""
    assert krt_open_sources.search_address("Светлый проезд, вл. 4") == "Светлый проезд 4"
    assert krt_open_sources.search_address("проспект Мира, вл. 82-92") == "проспект Мира 82-92"
    assert krt_open_sources.search_address("") == ""


def test_the_dot_of_the_shorthand_goes_with_it():
    """Между «.» и пробелом границы слова нет: «вл.» оставляло «.» в адресе."""
    for name in ("Светлый проезд, вл. 4", "Магистральные улицы тер. 4, 5, 6"):
        assert " . " not in krt_open_sources.search_address(name)
        assert not krt_open_sources.search_address(name).endswith(".")


def test_the_query_is_a_question():
    asked = krt_open_sources.queries("Светлый проезд, вл. 4", okrug="САО", district="Сокол")
    assert asked, "запросов не осталось"
    assert any("кто оператор и застройщик" in q for q in asked), \
        "вопроса про оператора и застройщика нет"
    # Второй путь к тому же ответу: справочники отвечают именем ЖК, а от имени
    # до компании один шаг — его делает круг по бренду.
    assert any("какой ЖК строится" in q for q in asked), \
        "имя ЖК по адресу не спрашивается вовсе"
    assert all('"' not in q for q in asked), \
        "адрес снова в жёстких кавычках — точной фразы каталога в публикациях нет"
    assert all("вл." not in q for q in asked), "канцелярское сокращение уехало в запрос"


def test_the_query_names_the_other_words_for_the_same_person():
    asked = " ".join(krt_open_sources.queries("Светлый проезд, вл. 4"))
    assert "застройщик" in asked and "девелопер" in asked


def test_the_channel_query_uses_the_human_address_too():
    asked = krt_open_sources.telegram_queries("Светлый проезд, вл. 4", [])
    assert asked == ["site:t.me кто оператор КРТ Светлый проезд 4 застройщик"], asked
    # Имя проекта — наоборот, точной фразой: «Строгино 360» без кавычек
    # рассыпается на «Строгино» и число.
    assert krt_open_sources.telegram_queries("Светлый проезд, вл. 4", ["Строгино 360"]) == [
        'site:t.me "Строгино 360" КРТ застройщик оператор']


def test_the_anchor_survives_the_russian_case():
    """«Светлый» → «на Светлом проезде»: шестая буква у прилагательного — окончание.

    Основа в шесть букв давала «светлы», а публикация пишет «светлом» — якорь
    не срабатывал ровно на той площадке, из-за которой всё и затевалось
    (владелец, 01.09.2026). Это же правило держит «Молдавская» → «Молдавской».
    """
    for sentence, site in (
            ("Застройщиком проекта на Светлом проезде выступает ПАО «ПИК».",
             "Светлый проезд, вл. 4"),
            ("Оператором КРТ на Молдавской улице выступает ООО «Ромашка».",
             "Молдавская ул., вл. 3-5")):
        got = krt_open_sources.read_findings(
            [Doc(title="", snippet=sentence, domain="mos.ru")], site)
        assert got["operator_named"], f"якорь не сработал: {site}"
        assert got["taken"] is True


def test_a_short_stem_does_not_borrow_a_stranger():
    """Пять букв — всё ещё улица, а не любое слово."""
    got = krt_open_sources.read_findings(
        [Doc(title="", snippet="Оператором КРТ на Бутовской улице выступает ООО «Чужой».",
             domain="mos.ru")], "Светлый проезд, вл. 4")
    assert not got["operator_named"] and got["taken"] is False

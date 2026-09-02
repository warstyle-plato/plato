"""Застройщика и реновацию называет сама карточка каталога.

Я измерил восемь проектов решений mos.ru и записал, что об операторе и
городских нуждах официальный источник молчит. Молчало РЕШЕНИЕ. Живой ответ
krt.mos.ru (31.08.2026, 60 карточек) говорит обратное: «Застройщик» назван по
имени на 27 из 30 карточек «В реализации», «реновация» — на 12 из 30, а оборота
«городские нужды» нет вовсе (0 из 60): город называет это Программой реновации.

Отсюда три вещи. Источник официальный и бесплатный — читается в прогоне, а не
по нажатию, иначе фильтр находит оператора только у площадок, открытых руками.
У планируемых карточка честно молчит: инвестора ещё определяют торгами.
И ловушка: слова «жилой застройки» / «нежилой застройки» есть на ВСЕХ
карточках — это названия типовых приложений, а не вид площадки.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_search import krt_card_facts  # noqa: E402
from market_search.krt_registry import KrtRegistry  # noqa: E402
from auction_search import ui  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
RUNNING = (FIXTURES / "krt_card_kuncevo.html").read_text(encoding="utf-8")
PLANNED = (FIXTURES / "krt_card_planned.html").read_text(encoding="utf-8")


def test_the_running_card_names_who_builds_it():
    facts = krt_card_facts.parse(RUNNING)
    assert facts["developers"] == ['АО "Главстрой"', 'АО "Совтрансавто-Москва"']
    assert facts["renovation"] is True
    assert "реноваци" in facts["renovation_quote"].lower()
    assert facts["renovation_quote"].endswith("."), "цитата обрывается на полуслове"


def test_the_planned_card_stays_silent_and_that_is_the_answer():
    facts = krt_card_facts.parse(PLANNED)
    assert facts["developers"] == [], "у планируемой площадки застройщика ещё нет"
    assert facts["renovation"] is False
    # Описание планируемой площадки пусто, и колонка ТЭП описанием не становится.
    assert "Площадь, га" not in facts["description"]


def test_the_kind_is_not_read_from_attachment_names():
    """«Нежилой застройки» стоит в именах типовых приложений у всех карточек."""
    for page in (RUNNING, PLANNED):
        assert "нежилой застройки" in page.lower()
    for facts in (krt_card_facts.parse(RUNNING), krt_card_facts.parse(PLANNED)):
        assert "kind" not in facts, "вид КРТ по именам приложений читать нельзя"


def test_a_city_developer_is_named_as_such():
    """КП «КРТ» и ГБУ «ГлавАПУ» — город строит сам, и это ответ, а не оттенок."""
    page = RUNNING.replace('АО &quot;Главстрой&quot;', 'КП &quot;КРТ&quot;')
    assert krt_card_facts.parse(page)["city_operator"] is True
    assert krt_card_facts.parse(RUNNING)["city_operator"] is False


def test_the_registry_caches_the_parsed_card_not_the_page():
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        return RUNNING.encode("utf-8")

    registry = KrtRegistry(tempfile.mkdtemp(), fetch=fetch)
    first = registry.card_facts("no8-kuncevo")
    assert first["available"] and first["developers"]
    second = registry.card_facts("no8-kuncevo")
    assert second["developers"] == first["developers"]
    assert len(calls) == 1, "разобранное не кэшируется — карточка читается заново"
    stored = (Path(registry.card_facts_dir) / "no8-kuncevo.json").read_text(encoding="utf-8")
    assert "<html" not in stored.lower(), "на диск легла страница, а не разбор"


def test_a_silent_source_is_not_a_negative_answer():
    def fetch(url: str) -> bytes:
        raise OSError("сеть недоступна")

    facts = KrtRegistry(tempfile.mkdtemp(), fetch=fetch).card_facts("no8-kuncevo")
    assert facts["available"] is False and facts["reason"]
    assert "developers" not in facts, "молчание источника выдано за отсутствие застройщика"


def test_the_list_sees_the_card_without_opening_it():
    page = ui.auctions_page(None)
    assert "card_facts" in page, "строка рейтинга не несёт фактов карточки"
    assert "rank.card_facts" in page, "фильтр смотрит только в открытую карточку"
    assert "Программой реновации" in page, \
        "«городские нужды» на карточках не пишут — это надо сказать читателю"


def test_the_table_shows_renovation_and_the_builder():
    """Реновацию и застройщика видно в списке, а не только в открытой карточке.

    «А где поиск публичной информации и реновация в таблице?» (владелец,
    01.09.2026). Признаки читаются прогоном и лежат в строке рейтинга —
    значит и показывать их надо там, где смотрят: в самой таблице.
    """
    page = ui.auctions_page(None)
    assert ">реновация</span>" in page, "метки реновации в строке таблицы нет"
    assert "card.developers" in page, "застройщик в строке не показан"
    # Публикации читаются проходом по ВСЕМ планируемым, а не по одной площадке
    # из карточки и не порциями по 25 из браузера: на каталоге из 263 площадок
    # порции — это одиннадцать нажатий подряд. Проход серверный, уже спрошенные
    # пропускаются: занятая площадка свободной не станет.
    assert "Прочитать публикации по планируемым" in page, \
        "публикации читаются только по одной площадке из карточки"
    assert "/auctions/krt/press/run" in page, "проход не серверный"


def test_the_decisions_are_not_listed_twice():
    """Площадки без карточки едут строками общего списка — второй таблицы нет.

    «Какого хера карточки с проектами решений остались отдельным свёрнутым
    списком» (владелец, 01.09.2026): те же строки, показанные дважды,
    читаются как два разных множества.
    """
    page = ui.auctions_page(None)
    assert "Решения без карточки в каталоге" not in page, "вторая таблица тех же строк"
    assert "они в таблице выше, с меткой «проект решения»" in page, \
        "счёт есть, а куда смотреть — не сказано"

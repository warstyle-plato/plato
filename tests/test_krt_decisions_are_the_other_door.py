"""Решения о КРТ — вход со стороны документа, а не карточки каталога.

Каталог krt.mos.ru отвечает на «какие площадки город показывает». Решение
публикуется отдельно, и площадка может иметь опубликованное решение, не имея
карточки вовсе. Ручная таблица владельца (27 площадок, 31.08.2026) показала
цену одностороннего хода: шесть площадок с решениями 2023–2025 годов не
появлялись у нас ни при каком фильтре, потому что мы всегда шли от каталога.

Записи здесь — настоящие, из живой выдачи поиска mos.ru (575 документов на
31.08.2026): разбор написан по ответу источника, а не по догадке о полях.

Главное, что проверяется, — строгость сопоставления. Ложная привязка прячет
настоящий пробел: площадка выглядит найденной, хотя карточки у неё нет. Поэтому
улица держится за своим номером владения, а не сравниваются мешок слов с мешком
чисел.

Запуск: python3 -m pytest tests/test_krt_decisions_are_the_other_door.py -q
"""

from __future__ import annotations

import json
import sys
from urllib.parse import parse_qs, urlparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search.krt_decisions import (  # noqa: E402
    collect, match_catalogue, parse_decision, parse_decisions, places,
    qualifier, same_place, search_url, zone_number,
)

# Живые записи выдачи www.mos.ru/aisearch (31.08.2026), обрезанные до полей,
# которые мы читаем.
LIVE = [
    {"id": "347614220", "date": 1787605200, "category": "ДГП",
     "url": "https://www.mos.ru/dgp/documents/view/347614220/",
     "title": "Проект решения о комплексном развитии территории нежилой застройки города "
              "Москвы, расположенной по адресу: г. Москва, Большой Тишинский пер., влд. 8, "
              "стр. 1,2 (ЦАО)"},
    {"id": "337036220", "date": 1769720400, "category": "ДГП",
     "url": "https://www.mos.ru/dgp/documents/view/337036220/",
     "title": "Проект решения о комплексном развитии территории нежилой застройки города "
              "Москвы,  расположенной по адресу: г. Москва, Огородный проезд (проект 2) (СВАО)"},
    {"id": "331617220", "date": 1769756963, "category": "ДГП",
     "url": "https://www.mos.ru/dgp/documents/view/331617220/",
     "title": "Проект решения о комплексном развитии территорий нежилой застройки города "
              "Москвы, расположенной в производственной зоне № 11 «Огородный проезд» "
              "(проект 2) (СВАО)"},
    {"id": "315534220", "date": 1735000000, "category": "ДГП",
     "url": "https://www.mos.ru/dgp/documents/view/315534220/",
     "title": "Проект решения о комплексном развитии территории нежилой застройки  города "
              "Москвы, расположенной по адресу: г. Москва, ул. Малая Филевская, влд. 9, 11 (ЗАО)"},
    {"id": "281782220", "date": 1675141200, "category": "ДГИ",
     "url": "https://www.mos.ru/dgi/documents/view/281782220/",
     "title": "Проект решения о комплексном развитии территории нежилой застройки  города "
              "Москвы, расположенной по адресу: г. Москва, ул. Рогова, вл. 22-24"},
    {"id": "000000000", "date": 1700000000, "category": "ДГИ",
     "url": "https://www.mos.ru/dgi/documents/view/000000000/",
     "title": "О внесении изменений в постановление Правительства Москвы"},
]

CATALOGUE = [
    {"slug": "ogorodnyy-proezd-proekt-2", "name": "Огородный проезд (проект 2)",
     "okrug": "СВАО"},
    {"slug": "ogorodnyy-yug", "name": "№24 Огородный проезд (юг)", "okrug": "СВАО"},
    {"slug": "seslavinskaya", "name": "Ул. Сеславинская, вл. 6А, Минская ул., вл. 2Г",
     "okrug": "ЗАО"},
]


def test_a_decision_is_read_whole() -> None:
    one = parse_decision(LIVE[0])
    assert one is not None
    assert one.id == "347614220"
    assert one.okrug == "ЦАО"
    assert one.kind == "нежилой застройки"
    assert one.address.startswith("Большой Тишинский пер., влд. 8")
    assert "г. Москва" not in one.address, "город в адресе — шум на каждой строке"
    assert one.published_at == 1787605200
    assert one.department == "ДГП"


# Пунктуация «по адресу» у города своя в каждом заголовке. Снято с прода
# 04.09.2026: восемь заголовков из 298 оставались без адреса, и пять из них —
# ровно на этой пунктуации. Адрес — это то, чем площадку ищут в публикациях;
# без него её нельзя ни спросить, ни назвать по имени.
PUNCTUATION = [
    ("Проект решения о комплексном развитии территории нежилой застройки города "
     "Москвы, расположенной по адресу; г. Москва, Боровский пр-д", "Боровский пр-д"),
    ("Проект решения о комплексном развитии территории нежилой застройки города "
     "Москвы, расположенной по адресу г. Москва, ул. Антонова-Овсеенко вл. 13-15",
     "ул. Антонова-Овсеенко вл. 13-15"),
    ("Проект решения о комплексном развитии территории нежилой застройки города "
     "Москвы, расположенной адресу: г. Москва, в производственной зоне № 32 "
     "«Котляково» (территория 1) (ЮАО)", "в производственной зоне № 32 «Котляково»"),
]


def test_the_address_survives_the_city_punctuation() -> None:
    for title, expected in PUNCTUATION:
        one = parse_decision({"id": "1", "title": title, "url": "", "date": 0})
        assert one is not None
        assert one.address.startswith(expected), f"адрес потерян: {title[:60]}"


def test_a_title_without_an_address_stays_without_one() -> None:
    """«Района» и «ограниченной улицами» адресом не становятся.

    Район опознаёт квартал, а не площадку, — то же правило, что у якоря
    публикации. Пустой адрес здесь верный ответ, и по нему прогон не платит
    за поиск: он называет такую строку числом.
    """
    for title in (
        "Проект решения о комплексном развитии территорий нежилой застройки "
        "города Москвы, расположенных в районе Некрасовка (ЮВАО)",
        "Проект решения о комплексном развитии территории нежилой застройки "
        "города Москвы № 125, ограниченной Ленинградским проспектом",
    ):
        one = parse_decision({"id": "1", "title": title, "url": "", "date": 0})
        assert one is not None and not one.address


def test_a_document_that_is_not_about_krt_is_not_ours() -> None:
    assert parse_decision(LIVE[-1]) is None
    assert len(parse_decisions({"results": LIVE})) == len(LIVE) - 1


def test_the_street_keeps_its_own_holding() -> None:
    """Мешок слов против мешка чисел сшивает разные площадки одной улицы."""
    assert places("Игарский пр-д, влд. 2, стр. 2-3") == frozenset({("игарский", "2")})
    assert not same_place("Игарский пр-д, влд. 2",
                          "Кольская ул., вл. 1; Игарский пр-д, вл. 6; Ивовая ул., вл. 5")
    assert same_place("ул. Ярославская, влд. 9, корп. 2, ул. Космонавтов, влд. 2А",
                      "Ярославская, вл. 12, Космонавтов ул., вл. 2А"), \
        "второй адрес совпал целиком — это одна площадка"


def test_the_ordinal_and_the_side_belong_to_the_street_name() -> None:
    assert not same_place("ул. 7-я Парковая, влд. 33",
                          "Верхняя Первомайская ул., влд. 36, ул. 9-я Парковая, влд. 33")
    assert not same_place("ул. Верхняя Первомайская, влд. 36",
                          "ул. Нижняя Первомайская, влд. 36")


def test_a_production_zone_is_told_apart_by_its_qualifier() -> None:
    """«Огородный проезд (юг)» и «(проект 2)» по словам совпадают целиком."""
    assert zone_number("в производственной зоне № 11 «Огородный проезд»") == "11"
    assert qualifier("Огородный проезд (проект 2)") == frozenset({"проект", "2"}), \
        "«проект» и «территория» различают части площадки — выбрасывать их нельзя"
    assert qualifier("Огородный проезд (территория 2)") != qualifier("Огородный проезд (проект 2)")
    assert same_place("в производственной зоне № 11 «Огородный проезд» (проект 2)",
                      "Огородный проезд (проект 2)")
    assert not same_place("в производственной зоне № 11 «Огородный проезд» (проект 2)",
                          "№24 Огородный проезд (юг)")


def test_the_gap_is_visible_and_the_match_is_not_invented() -> None:
    split = match_catalogue(parse_decisions({"results": LIVE}), CATALOGUE)
    matched = {one.matched_slug for one in split["matched"]}
    assert matched == {"ogorodnyy-proezd-proekt-2"}, \
        "по адресу совпала одна площадка — остальные привязки были бы выдуманы"
    gaps = [one.address for one in split["unmatched"]]
    assert any("Малая Филевская" in line for line in gaps), \
        "решение есть, карточки нет — ровно то, ради чего это написано"
    assert split["total"] == 5


def test_the_newest_gap_stands_first() -> None:
    split = match_catalogue(parse_decisions({"results": LIVE}), CATALOGUE)
    stamps = [one.published_at for one in split["unmatched"]]
    assert stamps == sorted(stamps, reverse=True)


def test_an_unfinished_walk_never_pretends_to_be_the_whole_list() -> None:
    """Недособранный список, выданный за полный, читается как «больше нет»."""
    pages = {1: {"results": LIVE}, 2: {"results": []}}

    def page_of(url: str) -> int:
        # Читать номер разбором, а не поиском подстроки: «per_page=25» содержит
        # «page=2», и заглушка молча отдавала бы вторую страницу первой.
        query = parse_qs(urlparse(url).query)
        return int(query["page"][0])

    def fetch(url: str) -> bytes:
        return json.dumps(pages[page_of(url)]).encode("utf-8")

    found, complete = collect(fetch, max_pages=5)
    assert complete is True and len(found) == 5

    def broken(url: str) -> bytes:
        raise OSError("поиск не ответил")

    found, complete = collect(broken, max_pages=5)
    assert found == [] and complete is False


def test_the_same_page_twice_is_the_end_not_a_loop() -> None:
    """Поиск повторяет последнюю страницу вместо отказа — это конец выдачи."""
    def fetch(url: str) -> bytes:
        return json.dumps({"results": LIVE}).encode("utf-8")

    found, complete = collect(fetch, max_pages=6)
    assert complete is True and len(found) == 5


def test_the_query_is_the_one_that_answered() -> None:
    assert "page=1" in search_url(1) and "per_page=25" in search_url(1, 25)
    assert "aisearch" in search_url(1)


# --- Карточка появилась — строка «без карточки» уходит в тот же миг ----------
#
# «Когда карточка появится, она обновится в списке?» (владелец, 31.08.2026).
# Кэш держит сами решения, а разложение считается на каждом чтении: иначе
# площадка, у которой карточка появилась час назад, до суток стоит в списке
# дважды — строкой каталога и строкой «без карточки» из вчерашнего разложения.

def test_the_row_disappears_the_moment_the_card_appears(tmp_path) -> None:
    import json as _json

    from market_search.krt_registry import KrtRegistry

    catalogue: list[dict] = []

    def fetch(url: str) -> bytes:
        page = int(urlparse(url).query.split("page=")[1].split("&")[0])
        return _json.dumps({"results": LIVE if page == 1 else []}).encode("utf-8")

    registry = KrtRegistry(tmp_path, fetch=fetch)
    registry.catalogue = lambda **_: list(catalogue)  # type: ignore[assignment]

    first = registry.decisions()
    gaps = [one["address"] for one in first["decisions"]]
    assert any("Малая Филевская" in line for line in gaps)
    assert first["matched"] == 0

    # Город завёл карточку — источник при этом не спрашивается заново.
    catalogue.append({"slug": "malaya-filevskaya", "okrug": "ЗАО",
                      "name": "ул. Малая Филевская, влд. 9, 11"})
    calls: list[str] = []

    def refuse(url: str) -> bytes:
        calls.append(url)
        raise OSError("источник спрашивать не надо — ответ уже в кэше")

    registry.fetch = refuse  # type: ignore[assignment]
    second = registry.decisions()
    assert not calls, "разложение считается на месте, без нового похода в источник"
    assert second["matched"] == 1
    assert all("Малая Филевская" not in one["address"] for one in second["decisions"]), \
        "строка «без карточки» осталась рядом с появившейся карточкой"

"""Обход, недособравший выдачу, прежний снимок не трогает — и полным себя не зовёт.

Бот весь день писал в чат «в каталоге КРТ новая площадка» об одних и тех же
четырёх площадках (экран владельца, 15.09.2026). Замер того часа развёл
источник и нас.

Источник стабилен: mos.ru объявляет `totalCount` 580 и `pageCount` 58, два
полных обхода подряд дали 580 документов из 580 без единого расхождения, и все
четыре «новые» площадки в выдаче есть.

Шатались мы: снимок решений на проде стоял то 246, то 247, то 248 строк — и
каждый раз с `complete: true`, при неизменных 37 вторых публикациях. Обход
объявлял себя полным, как только страница не приносила новых записей, а выдача
ранжированная: повторившаяся страница в середине обрывала его. Усечённый список
заменял полный снимок, площадка из него выпадала, а вернувшись следующим
заходом, объявлялась НОВОЙ.

Отсюда два утверждения, и оба проверяются здесь: сколько у источника есть —
спрашивают у источника, а недособранный обход прежний снимок не трогает.

Запуск: python3 -m pytest tests/test_a_short_walk_does_not_shrink_the_catalogue.py -q
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from market_search.krt_decisions import collect
from market_search.krt_registry import KrtRegistry

ROOT = Path(__file__).resolve().parents[1]

TITLE = ("Об утверждении проекта решения о комплексном развитии территории "
         "нежилой застройки, расположенной по адресу: г. Москва, {street}, вл. {n} (ЮАО)")


def _doc(number: int, street: str = "Полимерная ул.") -> dict[str, object]:
    return {"id": f"{number}", "url": f"https://www.mos.ru/dgp/documents/view/{number}/",
            "title": TITLE.format(street=street, n=number % 90 + 1),
            "date": 1788728400, "category": "Департамент градостроительной политики"}


def _source(pages: dict[int, list[dict[str, object]]], *, total: int | None = None,
            page_count: int | None = None):
    """Поиск mos.ru: страницы и его собственный счёт в `_meta`."""
    announced = total if total is not None else sum(len(rows) for rows in pages.values())
    counted = page_count if page_count is not None else len(pages)

    def fetch(url: str) -> bytes:
        asked = parse_qs(urlparse(url).query).get("page")
        if not asked:
            # Не поиск: у реестра один `fetch` на все источники, и каталог тут
            # не при чём — пустая страница честнее выдуманной.
            return b""
        page = int(asked[0])
        payload = {"_meta": {"totalCount": announced, "pageCount": counted,
                             "currentPage": page, "perPage": 10},
                   "results": pages.get(page, [])}
        return json.dumps(payload).encode("utf-8")

    return fetch


# --- обход спрашивает объём у источника -------------------------------------


def test_a_barren_page_in_the_middle_does_not_end_the_walk() -> None:
    """Повторившаяся страница — не конец выдачи, а повтор.

    Это и есть та поломка: страница 2 повторяет первую, а на третьей лежат
    документы, которых обход так и не видел.
    """
    first = [_doc(1), _doc(2)]
    pages = {1: first, 2: list(first), 3: [_doc(3), _doc(4)]}
    walk = collect(_source(pages, total=4, page_count=3))
    assert walk.complete is True, walk.shortfall()
    assert sorted(one.id for one in walk.items) == ["1", "2", "3", "4"]
    assert (walk.pages, walk.pages_announced) == (3, 3)
    assert (walk.seen, walk.announced) == (4, 4)


def test_the_walk_is_whole_only_when_the_announced_pages_are_read() -> None:
    """Потолок страниц обрезал обход — значит он недособран, и это сказано."""
    pages = {page: [_doc(page)] for page in range(1, 9)}
    walk = collect(_source(pages, total=8, page_count=8), max_pages=3)
    assert walk.complete is False
    assert "страниц 3 из 8" in walk.shortfall(), walk.shortfall()


def test_reading_fewer_documents_than_announced_is_not_whole() -> None:
    """Страницы дочитаны, а документов меньше объявленного — обход не полон.

    Так выглядит источник, повторивший страницу: страниц столько же, а
    документов меньше. Назвать это полным обходом значило бы потерять разницу
    молча — и объявить её новой при следующем заходе.
    """
    first = [_doc(1), _doc(2)]
    pages = {1: first, 2: list(first)}
    walk = collect(_source(pages, total=4, page_count=2))
    assert walk.complete is False
    assert "документов выдачи 2 из 4" in walk.shortfall(), walk.shortfall()


def test_a_silent_source_keeps_the_old_sign() -> None:
    """Источник своих чисел не назвал — остаётся прежняя примета.

    Предохранитель: без него правка выключила бы обход у всякого источника,
    который `_meta` не отдаёт, и «дочитано» не наступало бы никогда.
    """
    def fetch(url: str) -> bytes:
        page = int(parse_qs(urlparse(url).query)["page"][0])
        return json.dumps({"results": [_doc(1)] if page == 1 else []}).encode("utf-8")

    walk = collect(fetch, max_pages=5)
    assert walk.complete is True and len(walk.items) == 1
    assert walk.pages_announced == 0 and walk.announced == 0


# --- снимок решений ---------------------------------------------------------


def _full(tmp_path: Path) -> KrtRegistry:
    """Реестр с полным снимком решений на диске."""
    store = KrtRegistry(tmp_path, fetch=lambda url: b"{}")
    pages = {1: [_doc(n) for n in (1, 2)], 2: [_doc(n) for n in (3, 4)]}
    store.fetch = _source(pages, total=4, page_count=2)
    got = store.decisions(refresh=True, catalogue=[])
    assert got["complete"] is True and len(got["all"]) == 4
    return store


def test_a_walk_cut_by_pages_does_not_touch_the_snapshot(tmp_path) -> None:
    """Обход оборвался на середине страниц — прежний снимок не тронут.

    Это и есть та поломка: усечённый список заменял полный, площадка выпадала
    из снимка и объявлялась новой, когда возвращалась.
    """
    store = _full(tmp_path)
    before = store.decisions_path.read_text(encoding="utf-8")
    pages = {page: [_doc(page)] for page in range(1, 9)}
    store.fetch = _source(pages, total=8, page_count=8)
    got = store.decisions(refresh=True, catalogue=[], max_pages=3)
    assert got["stale"] is True
    assert len(got["all"]) == 4, "снимок обязан остаться прежним"
    said = got["stale_reason"]
    assert "недособран" in said and "страниц 3 из 8" in said, said
    assert "прежний снимок держит 4" in said, said
    assert store.decisions_path.read_text(encoding="utf-8") == before, \
        "файл снимка правит только дочитанный обход"


def test_a_walk_short_of_documents_adds_to_the_snapshot(tmp_path) -> None:
    """Страницы дочитаны, документов меньше объявленного — обход ДОПОЛНЯЕТ.

    Живой замер 15.09.2026: 58 страниц из 58, 580 строк, различных 579 —
    страница 3 отдала запись, прочитанную на первых двух, и один документ не
    показан ни на одной странице. Какой именно, мы не знаем, поэтому забыть
    никого не вправе; а заморозить снимок до безупречного обхода нельзя —
    источник теряет запись почти в каждом.
    """
    store = _full(tmp_path)
    kept = {one["id"] for one in store.decisions(catalogue=[])["all"]}
    assert kept == {"1", "2", "3", "4"}
    # Обход дочитал обе страницы, а документ 4 из выдачи выпал: строк столько
    # же, различных меньше.
    pages = {1: [_doc(1), _doc(2)], 2: [_doc(3), _doc(1)]}
    store.fetch = _source(pages, total=4, page_count=2)
    got = store.decisions(refresh=True, catalogue=[])
    assert got.get("stale") is False
    assert sorted(one["id"] for one in got["all"]) == ["1", "2", "3", "4"], \
        "документ, потерянный выдачей, остаётся в снимке"
    # Полнота — свойство СНИМКА: у нас столько документов, сколько объявил
    # источник, пусть один и достался прошлому обходу.
    assert got["complete"] is True
    assert got["walk"]["kept"] == 1 and got["walk"]["seen"] == 3


def test_a_full_walk_may_forget(tmp_path) -> None:
    """Документов прочитано не меньше объявленного — это ответ источника целиком.

    Предохранитель к проверке выше: снимок, который только дополняется, вечно
    носил бы документ, снятый городом с публикации.
    """
    store = _full(tmp_path)
    pages = {1: [_doc(1), _doc(2)], 2: [_doc(3)]}
    store.fetch = _source(pages, total=3, page_count=2)
    got = store.decisions(refresh=True, catalogue=[])
    assert got.get("stale") is False and got["complete"] is True
    assert sorted(one["id"] for one in got["all"]) == ["1", "2", "3"], \
        "дочитавший всё обход вправе забыть"


def test_an_empty_answer_does_not_replace_the_snapshot(tmp_path) -> None:
    """Источник не ответил — прежний ответ честнее пустого списка.

    Прежняя защита стояла только на этом случае, и она остаётся.
    """
    store = _full(tmp_path)
    store.fetch = _source({}, total=0, page_count=0)
    got = store.decisions(refresh=True, catalogue=[])
    assert got["stale"] is True and len(got["all"]) == 4


def test_an_empty_page_does_not_wipe_the_snapshot(tmp_path) -> None:
    """Пустая выдача снимок не заменяет, сколько бы страниц ни объявил источник.

    Прежняя защита смотрела на пустой ответ ВМЕСТЕ с «источник своих чисел не
    назвал», и пустая страница при объявленном `pageCount` формально была бы
    ответом источника целиком: 580 записей стёрлись бы одним заходом.
    """
    store = _full(tmp_path)
    store.fetch = _source({1: []}, total=0, page_count=1)
    got = store.decisions(refresh=True, catalogue=[])
    assert got["stale"] is True and len(got["all"]) == 4


def test_the_page_ceiling_is_declared_once() -> None:
    """Потолок страниц живёт у обхода: второй отставал бы от него молча.

    Источник отдаёт по десять записей на страницу, сколько бы мы ни просили, и
    58 объявленных страниц упирались в прежний потолок 60 почти вплотную.
    """
    source = (ROOT / "market_search" / "krt_registry.py").read_text(encoding="utf-8")
    where = source[source.index("def decisions(self"):]
    where = where[:where.index("\n    def ")]
    assert "max_pages: int = 0" in source[source.index("def decisions(self"):][:200]
    assert "60" not in where.split('"""')[0], "число страниц объявлено здесь второй раз"


# --- распоряжения о торгах: тот же обход и то же правило --------------------


ORDER = ("Распоряжение № ДГП-Р-{n}/26 о проведении аукциона на право заключения "
         "договора о комплексном развитии территории нежилой застройки")


def _order(number: int) -> dict[str, object]:
    return {"id": f"9{number}", "url": f"https://www.mos.ru/dgp/documents/view/9{number}/",
            "title": ORDER.format(n=number), "date": 1788728400,
            "category": "Департамент градостроительной политики"}


def _orders(tmp_path: Path) -> KrtRegistry:
    store = KrtRegistry(tmp_path, fetch=lambda url: b"{}")
    store.fetch = _source({1: [_order(1), _order(2)], 2: [_order(3)]},
                          total=3, page_count=2)
    got = store.tender_orders(refresh=True)
    assert len(got["orders"]) == 3, got
    return store


def test_a_short_walk_does_not_shrink_the_orders(tmp_path) -> None:
    """У распоряжений тот же обход — и та же защита снимка.

    Правило, применённое наполовину, выглядит применённым: распоряжение,
    выпавшее из усечённой выдачи, уносит с собой и ось «Торги», и объявленную
    цену входа.
    """
    store = _orders(tmp_path)
    pages = {page: [_order(page)] for page in range(1, 9)}
    store.fetch = _source(pages, total=8, page_count=8)
    got = store.tender_orders(refresh=True, max_pages=2)
    assert got["stale"] is True and len(got["orders"]) == 3
    assert "страниц 2 из 8" in got["stale_reason"], got["stale_reason"]


def test_an_order_lost_by_the_search_stays_in_the_snapshot(tmp_path) -> None:
    """Страницы дочитаны, документов меньше объявленного — обход дополняет."""
    store = _orders(tmp_path)
    store.fetch = _source({1: [_order(1), _order(2)], 2: [_order(1)]},
                          total=3, page_count=2)
    got = store.tender_orders(refresh=True)
    assert got.get("stale") is False
    assert sorted(one["id"] for one in got["orders"]) == ["91", "92", "93"]


def test_a_whole_walk_replaces_the_orders(tmp_path) -> None:
    """Предохранитель: дочитавший всё обход снимок распоряжений обновляет."""
    store = _orders(tmp_path)
    store.fetch = _source({1: [_order(1), _order(4)]}, total=2, page_count=1)
    got = store.tender_orders(refresh=True)
    assert got.get("stale") is False
    assert sorted(one["id"] for one in got["orders"]) == ["91", "94"]


def test_the_walk_is_declared_once(tmp_path) -> None:
    """Обход объявлен один раз: два запроса читает один `_walk`.

    Вторая копия приметы «дочитано» разошлась бы с первой молча — ровно так и
    вышло: у проектов решений её починили, а распоряжения остались шататься.
    """
    source = (ROOT / "market_search" / "krt_decisions.py").read_text(encoding="utf-8")
    assert source.count("def _walk(") == 1
    for name in ("def collect(", "def collect_tender_orders("):
        body = source[source.index(name):]
        body = body[:body.index("\n\ndef ")]
        assert "_walk(" in body, name
        assert "pageCount" not in body, f"{name}: примета дочитанности объявлена второй раз"

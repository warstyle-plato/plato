"""Полнота снимка сравнивает документы с документами, а не записи с документами.

Найдено приёмкой 0.23.87 на проде, то есть в моей же правке. Замер 15.09.2026:
прод отдал 528 строк (282 карточки и 246 решений) при `complete: True`, а до
выкатки решений было 248; живой обход из песочницы в тот же час дал 58 страниц
из 58, **578 различных документов из 580 объявленных** и 576 разобранных
решений — то есть сам себя дочитанным НЕ считал.

Причина: снимок считал `len(записи) >= объявленные документы`. Величины разные,
и плохи обе стороны. Union записей может не дорасти до числа документов
НИКОГДА — тогда снимок «недочитан» навсегда, а сторож новостей на неполном
списке состав не пишет, и новости встают совсем. Либо union через несколько
обходов число документов перевалит — тогда снимок объявит себя полным при
коротком обходе, и замена уронит строки.

Однородная мера: снимок объясняет столько документов, сколько у него записей
ПЛЮС названных неразобранных. Неразобранный документ — это не ошибка (поиск
отдаёт и чужие бумаги), но и не пустяк: пока он выбрасывался молча, объявленное
источником число было недостижимо по построению.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import krt_decisions  # noqa: E402
from market_search.krt_registry import KrtRegistry  # noqa: E402

# Один документ из трёх не про КРТ: он есть у источника и записью не станет
# никогда. Ровно такие и делали объявленное число недостижимым.
OURS = "Об утверждении проекта решения о комплексном развитии территории по адресу: г. Москва, {} "
ALIEN = "Об утверждении схемы размещения нестационарного торгового объекта"


def _page(rows: list[dict], *, total: int, page_count: int) -> bytes:
    return json.dumps({"results": rows, "_meta": {"totalCount": total,
                                                  "pageCount": page_count}}).encode()


def _source(pages: dict[int, list[dict]], *, total: int, page_count: int):
    def fetch(url: str) -> bytes:
        if "page=" not in url:
            return b""
        page = int(url.split("page=")[1].split("&")[0])
        return _page(pages.get(page, []), total=total, page_count=page_count)
    return fetch


def _row(one: str, title: str, stamp: int = 1789000000) -> dict:
    return {"id": one, "title": title, "url": f"https://www.mos.ru/d/{one}",
            "date": stamp, "category": "ДГИ"}


def test_the_walk_names_the_documents_it_could_not_parse():
    """Выброшенный документ называется, а не исчезает."""
    walk = krt_decisions.collect(_source(
        {1: [_row("1", OURS.format("ул. Тестовая, вл. 1")),
             _row("2", ALIEN),
             _row("3", OURS.format("ул. Иная, вл. 2"))]},
        total=3, page_count=1))

    assert len(walk.items) == 2, walk.items
    assert walk.seen == 3
    # Предохранитель: без неразобранного документа первые две проверки зелены
    # на любом коде — мерить нечего.
    assert walk.unparsed == ("2",), walk.unparsed


def test_the_snapshot_explains_every_announced_document(tmp_path):
    """Записи плюс названные неразобранные — это и есть объявленное число."""
    store = KrtRegistry(tmp_path, fetch=_source(
        {1: [_row("1", OURS.format("ул. Тестовая, вл. 1")),
             _row("2", ALIEN),
             _row("3", OURS.format("ул. Иная, вл. 2"))]},
        total=3, page_count=1))
    got = store.decisions(refresh=True, catalogue=[])

    assert got["complete"] is True, got.get("walk")
    walk = got["walk"]
    assert walk["accounted"] == 3 == walk["announced"], walk
    assert walk["unparsed"] == 1, walk
    # Записей ДВЕ — и прежняя мера («записи против документов») объявила бы
    # снимок недочитанным навсегда: третьей записи не будет никогда.
    assert len(got["all"]) == 2, got["all"]


def test_a_short_walk_never_drops_a_row_however_complete_the_snapshot(tmp_path):
    """Полнота снимка замену не разрешает: её решает недостача ОБХОДА.

    Это и есть решение «полнота — свойство СНИМКА, а не обхода»: у нас столько
    документов, сколько объявил источник, даже если один из них достался
    прошлому заходу, — иначе снимок замирал бы навсегда на источнике,
    теряющем запись почти в каждом обходе.

    Я успел сказать обратное — будто выросший union объявит снимок полным и
    тогда замена уронит строки, — и это неверно: слияние привязано к
    `walk.seen < walk.announced`, то есть к недостаче самого обхода, а не к
    признаку полноты. Проверка держит настоящий инвариант: короткий обход
    строк не теряет, каким бы полным снимок ни считался.
    """
    first = {1: [_row("1", OURS.format("ул. Тестовая, вл. 1")),
                 _row("2", OURS.format("ул. Иная, вл. 2"))]}
    store = KrtRegistry(tmp_path, fetch=_source(first, total=3, page_count=1))
    store.decisions(refresh=True, catalogue=[])

    second = {1: [_row("2", OURS.format("ул. Иная, вл. 2")),
                  _row("3", OURS.format("ул. Третья, вл. 3"))]}
    store = KrtRegistry(tmp_path, fetch=_source(second, total=3, page_count=1))
    got = store.decisions(refresh=True, catalogue=[])

    # Документ 1 второй обход не принёс — и он остался: union, а не замена.
    assert {one["id"] for one in got["all"]} == {"1", "2", "3"}, got["all"]
    assert got["walk"]["seen"] == 2 and got["walk"]["announced"] == 3, got["walk"]
    # Снимок объясняет все три объявленных документа — значит он полон, и это
    # ответ о СНИМКЕ. Недостачу обхода он при этом называет своим числом.
    assert got["complete"] is True, got["walk"]
    assert got["walk"]["kept"] == 1, got["walk"]


def test_a_document_that_never_parses_does_not_block_completeness(tmp_path):
    """Снимок не «недочитан навсегда» из-за чужой бумаги в выдаче.

    Прежняя мера сравнивала записи с документами: документ, который записью не
    станет НИКОГДА (заголовок не про КРТ), делал объявленное число
    недостижимым — снимок оставался неполным, а сторож новостей на неполном
    списке состав не пишет, то есть новости встали бы совсем.
    """
    pages = {1: [_row("1", OURS.format("ул. Тестовая, вл. 1")),
                 _row("2", ALIEN), _row("3", ALIEN)]}
    store = KrtRegistry(tmp_path, fetch=_source(pages, total=3, page_count=1))
    got = store.decisions(refresh=True, catalogue=[])

    assert len(got["all"]) == 1, got["all"]
    # Предохранитель: чужих бумаг в примере БОЛЬШЕ, чем наших, — иначе прежняя
    # мера прошла бы и проверка не значила бы ничего.
    assert got["walk"]["unparsed"] == 2, got["walk"]
    assert got["complete"] is True, got["walk"]


def test_the_walk_numbers_reach_the_reader(tmp_path):
    """Чем посчитана полнота — часть ответа, а не запись на диске.

    Снимок хранил эти числа с 0.23.87 и наружу не отдавал: когда после выкатки
    строк стало 246 вместо 248, объяснить это со стороны было нечем.
    """
    store = KrtRegistry(tmp_path, fetch=_source(
        {1: [_row("1", OURS.format("ул. Тестовая, вл. 1"))]},
        total=1, page_count=1))
    store.decisions(refresh=True, catalogue=[])

    state = store.status()
    walk = state["decisions_walk"]
    assert {"pages", "pages_announced", "seen", "announced",
            "unparsed", "accounted"} <= set(walk), walk
    assert walk["pages"] == walk["pages_announced"] == 1, walk

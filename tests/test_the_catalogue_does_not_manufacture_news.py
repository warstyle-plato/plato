"""Каталог не выдумывает новостей: состав пишет тот, кто видит его целиком.

Замер прода 07.09.2026 (0.22.71): одно открытие `/auctions/krt` добавляло в
очередь уведомлений от 4 до 214 записей, а число строк в ответе скакало между
заходами — 767, 779, 514, 521, 517. Половина списка (площадки-решения)
приезжает фоном, воркеров два, память у них раздельная, и `mark_seen`
переписывал снимок ЦЕЛИКОМ по тому, что успел увидеть этот воркер: забытое
одним объявлялось новым у другого. Накопилось 4492 записи — 3290 «площадка»,
1174 «решение», 28 «торги», — и ни одна из них не новость города.

Правило то же, что уже записано про рейтинг: кто пишет файл целиком, тот
теряет чужую запись.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auction_search.krt_ranking import KrtRanking

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def ranking(tmp_path) -> KrtRanking:
    return KrtRanking(tmp_path)


def test_a_partial_list_forgets_nothing_and_announces_nothing(ranking) -> None:
    """Неполный список состав только читает.

    Это и есть та самая поломка: воркер, у которого решения ещё не дочитаны,
    забывал их все, а следующее чтение объявляло двести сорок семь «новых
    площадок».
    """
    whole = ["a", "b", "decision:1", "decision:2"]
    ranking.mark_seen(whole, complete=True)          # первый снимок: тишина
    ranking.take_announcements()

    # Пришёл второй воркер и увидел только каталог.
    half = ranking.mark_seen(["a", "b"])
    assert sorted(half) == sorted(whole), "неполный список забыл чужую половину"
    assert ranking.take_announcements() == [], "неполный список объявил новости"

    # И полный список после него по-прежнему никого новым не считает.
    ranking.mark_seen(whole, complete=True)
    assert ranking.take_announcements() == [], "забытое вернулось «новым»"


def test_a_whole_list_still_names_what_really_appeared(ranking) -> None:
    """Починка не должна сделать сторожа немым: новое остаётся новостью."""
    ranking.mark_seen(["a", "decision:1"], complete=True)
    ranking.take_announcements()
    ranking.mark_seen(["a", "decision:1", "b"], complete=True)
    got = sorted(one["slug"] for one in ranking.take_announcements())
    assert got == ["b"], got


def test_the_event_composition_only_grows(ranking) -> None:
    """У решения и лота ключ не исчезает: заход неполон по построению.

    Сбор лотов ограничен сроком, поиск решений — страницами. Пока состав
    забывал недосчитанное, вернувшийся лот приезжал «новым» второй раз: девять
    запомненных ключей торгов против двадцати восьми записей в очереди.
    """
    events = {"site|1": {"slug": "site"}, "site|2": {"slug": "site"}}
    ranking.mark_watch("tender", events)             # первый снимок: тишина
    ranking.take_announcements()
    ranking.mark_watch("tender", {"site|1": {"slug": "site"}})   # второй не дособрал
    assert ranking.take_announcements() == []
    ranking.mark_watch("tender", events)             # тот же лот вернулся
    assert ranking.take_announcements() == [], "вернувшийся лот — тот же лот"
    ranking.mark_watch("tender", {**events, "site|3": {"slug": "site"}})
    got = [one["slug"] for one in ranking.take_announcements()]
    assert got == ["site"], "настоящий новый лот обязан объявиться"


def test_the_backlog_of_the_old_rule_is_dropped_and_named(ranking) -> None:
    """Очередь прежнего правила выбрасывается один раз и называется числом.

    Доставить её значит показать человеку 3290 «новых площадок», которых город
    не объявлял. А выбросить молча — то же самое, что сказать «новостей нет».
    """
    ranking.announcements_path.parent.mkdir(parents=True, exist_ok=True)
    ranking.announcements_path.write_text(
        "\n".join(json.dumps({"slug": f"s{i}", "seen_at": 1, "kind": "site"})
                  for i in range(7)) + "\n", encoding="utf-8")

    ranking.mark_seen(["a", "b"], complete=True)     # снимка нет — читаем заново
    assert not ranking.announcements_path.exists(), "очередь прежнего правила осталась"

    state = ranking.watch_state()
    assert state["pending"] == 0
    assert state["dropped"]["dropped"] == 7, state["dropped"]
    assert state["dropped"]["reason"], "сброс без причины читается как потеря"


def test_the_watch_counts_the_kind_that_fills_the_queue(ranking) -> None:
    """Счётчик молчания знает вид «площадка» — он и есть самый частый.

    Вид живёт в `first_seen`, а не в `watch_seen`, и пока его здесь не было,
    сторож молчал ровно о том, чего в очереди больше всего.
    """
    ranking.mark_seen(["a", "b"], complete=True)
    kinds = ranking.watch_state()["kinds"]
    assert kinds["site"] == {"known": 2, "bootstrapped": True}, kinds


def test_the_watch_does_not_mark_a_half_read_list() -> None:
    """Сторож отмечает состав, только когда список дочитан целиком."""
    from auction_search import krt_watch

    class _Ranking:
        def __init__(self) -> None:
            self.marked: list[list[str]] = []

        def first_seen(self) -> dict[str, int]:
            return {}

        def mark_seen(self, slugs, now=None, *, complete=False):
            self.marked.append(list(slugs))
            return {}

    ranking = _Ranking()
    rows = [{"slug": "a"}, {"slug": "decision:1"}]

    half = krt_watch.KrtWatch(object(), ranking, screen_list=lambda: (rows, False))
    assert half._catalogue() == []
    assert ranking.marked == [], "недочитанный список отметил состав"

    whole = krt_watch.KrtWatch(object(), ranking, screen_list=lambda: (rows, True))
    whole._catalogue()
    assert ranking.marked == [["a", "decision:1"]], ranking.marked


def test_the_route_reads_the_composition_and_the_watch_writes_it() -> None:
    """Писатель состава один, и он под замком.

    Проверка на текст, а не на поведение, намеренно: поломка была именно в
    том, КТО пишет файл, и увидеть это можно только у писателя.
    """
    api = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")
    route = api[api.index('async def auction_krt_catalogue('):]
    route = route[: route.index("krt_ranking.is_new(")]
    assert "mark_seen" not in route, "маршрут снова пишет состав"
    watch = (ROOT / "auction_search" / "krt_watch.py").read_text(encoding="utf-8")
    assert "complete=True" in watch, "сторож перестал утверждать полноту"
    # Полнота считается там же, где собирается список: второй ответ на
    # «дочитан ли он» разошёлся бы с первым молча.
    assert api.count("def _krt_screen_list(") == 1

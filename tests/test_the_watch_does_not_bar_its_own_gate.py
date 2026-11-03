"""Сторож спрашивает полноту ДО того, как просит обход каталога.

Замер прода 15.09.2026, `/auctions/krt/watch`: `site: known 0, bootstrapped
false` при `decision: known 293` и `tender: known 9` — состав площадок не
отмечен НИ РАЗУ, то есть новая площадка каталога не объявится никогда. При этом
каталог ЦЕЛЫЙ: `/auctions/krt` отдаёт `complete: true`, `refreshing: false`,
529 строк, возраст снимка 0,29 ч.

Причина в самом стороже. `_catalogue` делал два шага подряд:

    self.registry.catalogue(refresh=True)   # 1
    rows, whole = self.screen_list()        # 2

Шаг 1 через `refresh_in_background` ставит `_refreshing = True` СИНХРОННО, до
запуска нити. Шаг 2 считает полноту как «прочитан и не обновляется прямо
сейчас» — то есть она отрицалась ровно тем вызовом, который стоял строкой
выше. И так каждый час: docstring обещал отставание «в один срок», а выходило
навсегда.

Признак, по которому это ловится заранее: у гейта спрашивают, не взводит ли
его сам вызывающий строкой выше.

Запуск: python3 -m pytest tests/test_the_watch_does_not_bar_its_own_gate.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from auction_search import krt_watch  # noqa: E402
from auction_search.krt_ranking import KrtRanking  # noqa: E402

ROWS = [{"slug": "pervaya"}, {"slug": "vtoraya"}]


class Registry:
    """Реестр, ведущий себя как настоящий: обход синхронно поднимает признак.

    Это и есть предмет проверки — не «сколько раз позвали», а то, что признак
    встаёт ДО возврата управления. Заглушка, поднимающая его в нити, повторила
    бы поломку не полностью и зеленела бы на прежнем порядке.
    """

    def __init__(self) -> None:
        self.refreshing = False
        self.walks = 0

    def catalogue(self, *, refresh: bool = False):
        if refresh:
            self.refreshing = True
            self.walks += 1
        return list(ROWS)


def _watch(tmp_path, registry, rows=None):
    ranking = KrtRanking(tmp_path)

    def screen_list():
        # Полноту считает тот же счёт, что у маршрута: прочитан и НЕ
        # обновляется прямо сейчас.
        return list(ROWS if rows is None else rows), not registry.refreshing

    return krt_watch.KrtWatch(registry, ranking, screen_list=screen_list,
                              now=lambda: 0.0), ranking


def test_the_composition_is_marked_on_the_first_pass(tmp_path):
    """Первый же заход отмечает состав — и обход всё равно просится."""
    registry = Registry()
    watch, ranking = _watch(tmp_path, registry)
    assert watch._catalogue() == [], "первый снимок никого новым не делает"
    kinds = ranking.watch_state()["kinds"]
    assert kinds["site"] == {"known": 2, "bootstrapped": True}, kinds
    # Обход не потерян — он просто уехал за отметку: снимок живёт сутки и сам
    # себя не обновляет.
    assert registry.walks == 1, "обход каталога перестал запрашиваться"


def test_a_new_site_is_announced_on_the_next_pass(tmp_path):
    """Появившаяся площадка объявляется — то, ради чего сторож и написан."""
    registry = Registry()
    watch, ranking = _watch(tmp_path, registry)
    watch._catalogue()
    registry.refreshing = False
    watch._screen_list = lambda: (ROWS + [{"slug": "tretya"}], True)
    assert watch._catalogue() == ["tretya"]


def test_an_unread_list_still_marks_nothing(tmp_path):
    """Предохранитель: недочитанный список состав по-прежнему НЕ отмечает.

    Без этой проверки соседние зеленели бы и на стороже, который отмечает
    что угодно, — то есть забытая половина объявлялась бы новой по кругу.
    """
    registry = Registry()
    ranking = KrtRanking(tmp_path)
    watch = krt_watch.KrtWatch(registry, ranking,
                               screen_list=lambda: (list(ROWS), False),
                               now=lambda: 0.0)
    assert watch._catalogue() == []
    assert ranking.watch_state()["kinds"]["site"] == {"known": 0, "bootstrapped": False}
    # Обход при этом просится: список дочитан не весь — тем нужнее обойти.
    assert registry.walks == 1


def test_the_route_says_why_the_composition_is_unmarked(tmp_path, monkeypatch):
    """Почему состав площадок не отмечен — названо на `/auctions/krt/watch`.

    Пока этих полей не было, «состав не отмечен», «каталог обновляется прямо
    сейчас» и «решения дочитаны не все» снаружи выглядели одним и тем же
    `site: known 0`. Считает причину тот же вызов, которым сторож и решает:
    второй ответ разошёлся бы с первым молча.
    """
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auction_search import api as api_module

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(
            catalogue=lambda **_kw: [dict(row) for row in ROWS],
            # Каталог прочитан, но обход идёт — ровно то состояние, в котором
            # сторож сам себя запирал.
            status=lambda: {"complete": True, "refreshing": True},
            find=lambda query: None,
            decisions=lambda **_kw: {"rows": [], "complete": True},
        ),
    )
    api_module.install(app)
    said = TestClient(app).get("/auctions/krt/watch").json()["site_source"]
    assert said["whole"] is False, said
    assert said["catalogue_complete"] is True and said["catalogue_refreshing"] is True, said
    assert said["catalogue_rows"] == len(ROWS), said
    assert said["decisions_whole"] is True, said

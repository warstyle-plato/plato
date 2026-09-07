"""У молчащего сторожа новостей есть счётчик молчания.

«Ну мне ничего не пришло в телеграмме» (владелец, 07.09.2026). Проверить это
было нечем: снаружи «новостей не было», «сторож выключен» и «сторож сломан»
выглядят одинаково. Замер прода в тот час: обе половины на 0.22.64, снимок
каталога обновился за три минуты до запроса — то есть сторож жив, — а сказать
это можно было только чтением чужого кода.

Здесь же держатся два разрыва доставки, найденные тем же разбором: имя
площадки-решения в объявлении (иначе в чат уходит слаг `decision:333331220`) и
срок подачи заявок у события торгов (сырой лот и хранимая выжимка называют его
разными полями).

Запуск: python3 -m pytest tests/test_the_watch_says_whether_it_is_silent.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SLUG = "decision:333331220"
NAME = "Рубцовская наб., влд. 3"
LOT = {"url": "https://www.roseltorg.ru/procedure/21000005000000033452/1",
       "deadline": "09.10.26 15:00", "price_rub": 23_808_328.03}


def _ranking(tmp_path):
    from auction_search.krt_ranking import KrtRanking

    return KrtRanking(tmp_path)


def test_the_first_snapshot_is_named_a_snapshot_not_a_failure(tmp_path):
    """Первый снимок вида никого не объявляет — и это видно снаружи."""
    ranking = _ranking(tmp_path)
    assert ranking.watch_state()["kinds"] == {}, "до первого захода видов нет"

    events = {f"{SLUG}|1": {"slug": SLUG, "deadline": LOT["deadline"]}}
    assert ranking.mark_watch("tender", events) == [], "первый снимок — состав"
    state = ranking.watch_state()
    assert state["kinds"]["tender"]["known"] == 1
    assert state["pending"] == 0, "снимок в очередь не идёт"
    assert state["updated_at"] > 0

    # Второй лот — уже новость, и она видна счётчиком до всякой отправки.
    events[f"{SLUG}|2"] = {"slug": SLUG, "deadline": LOT["deadline"]}
    assert ranking.mark_watch("tender", events) == [f"{SLUG}|2"]
    state = ranking.watch_state()
    assert state["pending"] == 1
    assert state["pending_by_kind"] == {"tender": 1}
    assert state["last_queued_at"] > 0


def test_reading_the_state_does_not_eat_the_queue(tmp_path):
    """Очередь забирает бот: читатель состояния её не уносит."""
    ranking = _ranking(tmp_path)
    ranking.mark_watch("tender", {f"{SLUG}|1": {"slug": SLUG}})
    ranking.mark_watch("tender", {f"{SLUG}|1": {"slug": SLUG},
                                  f"{SLUG}|2": {"slug": SLUG}})
    assert ranking.watch_state()["pending"] == 1
    assert ranking.watch_state()["pending"] == 1, "чтение состояния — не изъятие"
    assert len(ranking.take_announcements()) == 1, "бот забирает то же самое"
    assert ranking.watch_state()["pending"] == 0


def test_the_route_names_the_periods_and_the_switch(tmp_path, monkeypatch):
    """Маршрут отвечает и сроками: «сторож выключен» — тоже ответ."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auction_search import krt_watch
    from auction_search.api import install

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(catalogue=lambda **_: [],
                            status=lambda: {"complete": True, "refreshing": False}))
    install(app)
    answer = TestClient(app).get("/auctions/krt/watch")
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["enabled"] is False, "в прогоне сторож выключен conftest'ом"
    # Сроки берутся у сторожа, а не переписаны числами.
    assert body["periods_seconds"]["tender"] == krt_watch.TENDERS_PERIOD
    assert set(body) >= {"kinds", "pending", "pending_by_kind", "last_queued_at"}


def test_a_tender_event_carries_the_deadline_of_the_stored_lot():
    """Выжимка лота зовёт срок `deadline`, и событие обязано его прочесть."""
    from auction_search.krt_watch import _tender_events

    events = _tender_events({SLUG: {"lots": [LOT]}})
    assert len(events) == 1
    one = next(iter(events.values()))
    assert one["deadline"] == LOT["deadline"], "срок подачи теряется по дороге"
    assert one["price_rub"] == LOT["price_rub"]
    assert one["slug"] == SLUG


def test_the_announcement_names_a_site_without_a_card(tmp_path, monkeypatch):
    """Имя берётся по обеим половинам списка, иначе в чат уедет слаг."""
    from fastapi import FastAPI

    from auction_search.api import install
    from auction_search.krt_ranking import KrtRanking

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    decisions = {"decisions": [{"id": "333331220", "address": NAME,
                                "url": "https://www.mos.ru/x/", "published_at": 1}],
                 "complete": True}
    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(catalogue=lambda **_: [],
                            decisions=lambda **_: decisions,
                            status=lambda: {"complete": True, "refreshing": False}))
    install(app)

    ranking = KrtRanking(Path(tmp_path) / "market")
    ranking.mark_watch("tender", {f"{SLUG}|1": {"slug": SLUG}})
    ranking.mark_watch("tender", {f"{SLUG}|1": {"slug": SLUG},
                                  f"{SLUG}|2": {"slug": SLUG, "deadline": LOT["deadline"]}})

    take = app.state.krt_announcements_take
    records = take()
    assert records and records[0]["slug"] == SLUG
    assert records[0]["name"] == NAME, "площадка-решение приехала бы слагом"

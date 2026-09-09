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

ROOT = Path(__file__).resolve().parents[1]

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
    # Вид «площадка» стоит в счётчике всегда: он живёт в `first_seen`, и пока
    # его здесь не было, сторож молчал ровно о том, чего в очереди больше
    # всего. «Ещё не видели» говорится признаком, а не отсутствием строки.
    kinds = ranking.watch_state()["kinds"]
    assert kinds == {"site": {"known": 0, "bootstrapped": False}}, kinds

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


def test_the_message_links_to_the_lot_itself():
    """«А ссылка на торги?» — адрес приезжал с событием и не печатался.

    Ссылка внизу сообщения ведёт в каталог и отвечает на другой вопрос: «где
    посмотреть список». Открыть сам лот было нечем.
    """
    import main as wrapper

    text = wrapper._krt_announcement_text([
        {"slug": SLUG, "name": NAME, "kind": "tender",
         "deadline": LOT["deadline"], "url": LOT["url"]},
    ])
    assert LOT["url"] in text, "адрес лота до сообщения не доезжает"
    assert f'<a href="{LOT["url"]}">' in text and NAME in text
    # Утверждение здесь — «срок подачи есть в новости», а не «строка площадки
    # напечатана как написана». Прежде сообщение резало сырую запись по длине:
    # «09.10.26 15:00»[:10] даёт «09.10.26 1» — обрубок часа, который читается
    # как часть даты. Теперь печатает тот же разбор, что считает сам срок, и
    # час назван по Москве: зона — часть величины.
    assert "заявки до 09.10.2026, 15:00 МСК" in text, "срок подачи — часть новости"


def test_a_news_without_an_address_stays_a_plain_line():
    """Обещание открыть то, чего у нас нет, хуже молчания."""
    import main as wrapper

    text = wrapper._krt_announcement_text([
        {"slug": SLUG, "name": NAME, "kind": "tender"},
    ])
    assert NAME in text
    assert f"— {NAME}" in text, "имя без адреса печатается как есть"

    # И «ссылка» чужой площадки, которая не адрес, ссылкой не становится.
    dodgy = wrapper._krt_announcement_text([
        {"slug": SLUG, "name": NAME, "kind": "tender", "url": "javascript:alert(1)"},
    ])
    assert "javascript:" not in dodgy


def test_the_delivery_says_what_it_did(monkeypatch) -> None:
    """У доставки тоже есть счётчик молчания — и он на половине бота.

    Замер прода 07.09.2026: очередь на ядре стояла на 4827 записях и не падала
    ни через границу пятнадцати минут, ни через две. Забирает её бот, а он на
    другой машине, и снаружи «новостей не было», «цикл не дошёл» и «ядро не
    ответило» — одно молчание. `/auctions/krt/watch` отвечает за очередь,
    `/krt/delivery` — за того, кто её забирает.
    """
    import main as wrapper

    monkeypatch.setattr(wrapper.core, "_telegram_token", lambda: "токен")
    monkeypatch.setattr(wrapper.core, "_telegram_webhook_enabled", lambda: True)
    monkeypatch.setattr(wrapper.core, "usage_admin_ids", lambda: [7])
    sent: list[tuple[int, str]] = []
    monkeypatch.setattr(wrapper.core, "_telegram_send_message",
                        lambda chat_id, text, **kw: sent.append((chat_id, text)))

    monkeypatch.setattr(wrapper, "_krt_take_announcements", lambda: ([], []))
    wrapper._deliver_krt_announcements()
    assert wrapper.krt_delivery_state()["stopped_by"] == "очередь пуста"

    records = [{"slug": "a", "kind": "site", "seen_at": 1, "name": "Площадка"}]
    monkeypatch.setattr(wrapper, "_krt_take_announcements", lambda: (records, []))
    wrapper._deliver_krt_announcements()
    state = wrapper.krt_delivery_state()
    assert (state["taken"], state["targets"], state["sent"]) == (1, 1, 1), state
    assert not state["stopped_by"], state
    assert sent and sent[0][0] == 7

    # Отказ ядра — это ответ, а не «новостей нет».
    def _boom() -> tuple[list, list]:
        raise RuntimeError("ядро не ответило")

    monkeypatch.setattr(wrapper, "_krt_take_announcements", _boom)
    try:
        wrapper._deliver_krt_announcements()
    except RuntimeError:
        pass
    state = wrapper.krt_delivery_state()
    assert state["stopped_by"] == "очередь у ядра не забрана"
    assert "ядро не ответило" in state["last_error"]


def test_the_delivery_line_stands_where_the_bot_is_asked() -> None:
    """Про доставку спрашивают бота — строка стоит в /status.

    Диск ядра и связка с ГлавАПУ уже там по той же причине: смотрят туда,
    когда что-то проверяют.
    """
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    body = source[source.index("def _status_message("):]
    body = body[: body.index("@app.post(")]
    assert "_krt_delivery_line()" in body, "в /status нет строки о доставке новостей"
    # Счётчик читают и снаружи, но адресатов он не называет — только числом.
    route = source[source.index('@app.get("/krt/delivery")'):]
    route = route[: route.index("\ndef ", route.index("def krt_delivery("))]
    assert "usage_admin_ids" not in route and "subscribers" not in route

"""Число распоряжений называет окно и предмет — иначе его сравнят с лотами.

«Тут нет ошибки по количеству якобы торгов? Во вкладке торги всего 8»
(владелец, 09.09.2026). Ошибки в счёте не было: 55 — это распоряжения города о
проведении аукциона, документы с mos.ru за ВСЁ время (2017 — 3, 2023 — 17,
2026 — 10; за последние двенадцать месяцев 16), а 8 — живые лоты соседней
вкладки. Неверна была подпись: «Город объявил 55 распоряжений» без окна и без
предмета читается как «идёт 55 аукционов».

Считает окно сервер: второй счёт тех же строк на экране однажды разошёлся бы
с первым, и обе цифры выглядели бы верными.

Рядом закрыта устаревшая оговорка. Она говорила «привязать распоряжение к
площадке нечем» — верно на день, когда писалась, и неверно с тех пор, как
адрес достаётся распознаванием скана: на проде адрес прочитан у 27 из 55, к
площадкам привязано 25. Оговорка «мы этого не умеем» устаревает молча.

Запуск: python3 -m pytest tests/test_the_decree_count_has_a_window.py -q
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DAY = 86_400
NOW = time.time()

# Распоряжения: одно свежее, два старше года (400 и 900 дней). Адрес прочитан у одного —
# «распознали» и «есть документ» это разные ответы.
ORDERS = [
    {"id": "1", "number": "ДГП-Р-54/26", "published_at": int(NOW - 10 * DAY),
     "address": "г. Москва, ш. Варшавское, влд. 37"},
    {"id": "2", "number": "ДГП-Р-28/26", "published_at": int(NOW - 400 * DAY)},
    {"id": "3", "number": "70-01", "published_at": int(NOW - 900 * DAY)},
]


def _client(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auction_search.api import install

    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(
            catalogue=lambda **_: [],
            decisions=lambda **_: {"decisions": [], "complete": True},
            status=lambda: {"complete": True, "refreshing": False},
            tender_lots_known=lambda: {},
            remember_tender_lots=lambda *_: None,
            tender_orders=lambda **_: {"orders": ORDERS, "complete": True,
                                       "note": "проба"},
        ),
    )
    install(app)
    return TestClient(app)


def test_the_route_counts_the_window_and_the_addressed(tmp_path):
    """Всего, за последние двенадцать месяцев и с прочитанным адресом."""
    client = _client(tmp_path)
    answer = client.post("/auctions/krt/tenders", json={"lots": []})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["orders_total"] == 3
    assert body["orders_recent_12m"] == 1, "окно не считается — старое видно как свежее"
    assert body["orders_with_address"] == 1, (
        "«есть документ» и «адрес прочитан» — разные ответы")


def test_the_screen_reads_the_window_from_the_server():
    """Поле — это контракт: не читает страница, и окно до экрана не доезжает."""
    page = (ROOT / "auction_search" / "ui.py").read_text(encoding="utf-8")
    assert "orders_recent_12m" in page, "окно посчитано и не показано"
    assert "orders_with_address" in page


def test_the_note_no_longer_claims_we_cannot_bind():
    """Оговорка обязана пережить смену источника — эта её не пережила.

    Утверждение проверяется по СВОДУ, а не поиском слова: строка живёт в
    `tender_orders`, и её текст сверяется с тем, что модуль умеет делать —
    адрес он читает распознаванием (`_read_order_details`).
    """
    from market_search import krt_registry

    source = Path(krt_registry.__file__).read_text(encoding="utf-8")
    note = source[source.index('"note": ('):]
    note = note[: note.index("),")]
    assert "нечем" not in note, (
        "оговорка утверждает, что привязать нельзя, — а распознавание уже есть")
    assert "распозна" in note, "как читается адрес, сказано не будет"

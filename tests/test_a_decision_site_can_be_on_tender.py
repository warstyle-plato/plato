"""Площадка без карточки тоже бывает выставлена на торги — и это видно.

«Я не понимаю, когда я должен был увидеть, что торги начались по Рубцовской?
Это в нашем соседнем блоке видно» (владелец, 07.09.2026).

Ответ на его вопрос: никогда. Замер прода в тот же час — сбор торгов приносит
восемь КРТ-лотов, и один из них «г. Москва, Рубцовская наб., влд. 3», площадью
0,73 га. Площадка при этом лежит в списке слагом `decision:333331220` — у неё
нет карточки krt.mos.ru, она приходит проектом решения с mos.ru. А связку
«площадка ↔ лот» сервер считал по `krt_registry.catalogue()`, то есть по одной
половине списка: кандидатом такая площадка не была вовсе.

Дальше её ждали ещё две двери, и обе закрытые. Хранилище связки проверяет слаг
набором без двоеточия — `decision:…` отбрасывался молча. А в ответе списка
связка приписывалась строкам ДО того, как к каталогу добавлялись
площадки-решения, — то есть у половины строк её не бывало по построению.

Запуск: python3 -m pytest tests/test_a_decision_site_can_be_on_tender.py -q
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DOCUMENT_ID = "333331220"
SLUG = "decision:" + DOCUMENT_ID
ADDRESS = "Рубцовская наб., влд. 3"

# Лот снят с прода 07.09.2026 (`/auctions/discover`), поля оставлены как есть.
LOT = {
    "title": ("21000005000000033452 Лот 1 Имущественные торги (178-ФЗ) Аукцион на право "
              "заключения договора о комплексном развитии территорий нежилой застройки "
              "города Москвы площадью 0,73 га, расположенных по адресу: "
              "г. Москва, Рубцовская наб., влд. 3"),
    "address": "г. Москва, Рубцовская наб., влд. 3",
    "land_area_sqm": 7300.0,
    "source": {"platform": "roseltorg",
               "lot_url": "https://www.roseltorg.ru/procedure/21000005000000033452/1"},
    "application_deadline": time.strftime("%d.%m.%y 15:00",
                                          time.gmtime(time.time() + 3 * 86400)),
    "lot_kind": "krt",
    "start_price_rub": 23_808_328.03,
}
LOT_URL = "https://www.roseltorg.ru/procedure/21000005000000033452/1"

DECISIONS = {
    "decisions": [{
        "id": DOCUMENT_ID,
        "address": ADDRESS,
        "title": "О проекте решения о комплексном развитии территории по адресу: " + ADDRESS,
        "url": "https://www.mos.ru/dgp/documents/" + DOCUMENT_ID + "/",
        "published_at": 1_757_000_000,
        "department": "dgp",
    }],
    "tep": {DOCUMENT_ID: {"read": True, "available": True, "area_ha": 0.73}},
    "complete": True,
}


def _decision_row() -> dict:
    from auction_search.api import krt_decision_rows

    rows = krt_decision_rows(DECISIONS)
    assert len(rows) == 1 and rows[0]["slug"] == SLUG
    return rows[0]


def test_the_lot_binds_to_a_site_without_a_card():
    """Правило совпадения площадку-решение узнаёт — её просто не спрашивали."""
    from auction_search import krt_tenders

    matched = krt_tenders.match([LOT], [_decision_row()])
    assert (matched.get("by_site") or {}).get(SLUG), (
        "лот и площадка про один адрес, а связки нет")


def test_the_store_keeps_a_decision_slug(tmp_path):
    """Слаг здесь ключ в файле, а не имя файла: двоеточие законно."""
    from market_search.krt_registry import KrtRegistry

    registry = KrtRegistry(tmp_path)
    registry.remember_tender_lots({SLUG: [LOT]})
    known = registry.tender_lots_known()
    assert known.get(SLUG, {}).get("lots") == [LOT], "связка не сохранилась"
    assert known[SLUG]["seen_at"] > 0


def _client(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auction_search.api import install
    from market_search.krt_registry import KrtRegistry

    registry = KrtRegistry(tmp_path)
    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(
            catalogue=lambda **_: [],
            decisions=lambda **_: DECISIONS,
            status=lambda: {"complete": True, "refreshing": False},
            tender_lots_known=registry.tender_lots_known,
            remember_tender_lots=registry.remember_tender_lots,
        ),
    )
    install(app)
    return TestClient(app)


def _row(client) -> dict:
    answer = client.get("/auctions/krt")
    assert answer.status_code == 200
    rows = [row for row in answer.json()["projects"] if row.get("slug") == SLUG]
    assert rows, "площадки-решения нет в списке"
    return rows[0]


def test_the_tab_binds_the_lot_to_a_site_without_a_card(tmp_path):
    """Маршрут вкладки «Торги» считает по списку экрана, а не по каталогу."""
    client = _client(tmp_path)
    answer = client.post("/auctions/krt/tenders", json={"lots": [LOT]})
    assert answer.status_code == 200, answer.text
    assert SLUG in (answer.json().get("by_site") or {}), "маршрут площадку не нашёл"

    # Сверяются НАЗВАННЫЕ величины: маршрут хранит выжимку лота, а не тот
    # словарь, что пришёл, и равенство целиком запрещало бы её пополнять.
    row = _row(client)
    lots = row.get("tender_lots") or []
    assert len(lots) == 1, "связка до строки списка не доезжает"
    assert lots[0]["url"] == LOT_URL
    assert lots[0]["deadline"] == LOT["application_deadline"], "срок подачи — часть ответа"
    assert row.get("tender_lots_seen_at", 0) > 0, "когда узнали — часть ответа"


def test_the_row_gets_the_lot_even_without_the_neighbouring_tab(tmp_path):
    """Запомненная связка приписывается ОБЕИМ половинам списка."""
    from market_search.krt_registry import KrtRegistry

    KrtRegistry(tmp_path).remember_tender_lots({SLUG: [{"url": LOT_URL}]})
    # Сверяется НАЗВАННАЯ величина, а не словарь целиком: равенство целиком
    # запрещает добавлять поле, а утверждение здесь другое — связка доехала до
    # строки. Сервер кладёт рядом момент срока (`deadline_iso`), и у лота без
    # срока он пуст — «не поняли», а не «прошёл».
    lots = _row(_client(tmp_path)).get("tender_lots") or []
    assert [lot["url"] for lot in lots] == [LOT_URL]
    assert lots[0]["deadline_iso"] is None

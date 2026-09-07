"""«Работа принята» — не пустой ответ, и карточка КРТ этому научена.

Кнопка «Рекомендация Платона» отвечала «Платон вернул пустой ответ» (владелец,
06.09.2026). Пустоты не было: `plato_ask` — это передача работы опросу
(`plato_answer_handoff`), и на долгом вопросе она отдаёт билет
`{"pending": true, "trace_id": …}` — цепочка ядро → Render → OpenAI одним
соединением не держится. Маршрут читал билет как отсутствие текста и отвечал
502; принятая работа выглядела отказом.

Ждать умеет общий код (`platoAwait` в `plato_question`), а забирать готовое
ходят в ЭТОТ маршрут, а не в `/agent/result` напрямую: ответ надо ещё положить
в отчёт площадки, и отчёт знает он.

Запуск: python3 -m pytest tests/test_accepted_work_is_not_an_empty_answer.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
from auction_search import krt_ranking  # noqa: E402
from auction_search.ui import auctions_page  # noqa: E402

PROJECT = {"slug": "test", "name": "КРТ Тест", "status": "Планируемый",
           "housing_gfa_sqm": 161_680}


def _client(monkeypatch, tmp_path, ask, result):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auction_search.api import install

    monkeypatch.setenv("MARKET_CABINET_KEY", "test-key")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setitem(sys.modules, "developaid_core", core)
    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(catalogue=lambda **_: [PROJECT],
                            status=lambda: {"complete": True, "refreshing": False}),
        plato_ask=ask,
        plato_result=result,
    )
    install(app)
    ranking = krt_ranking.KrtRanking(Path(tmp_path) / "market")
    ranking.save_report("test", {"name": "КРТ Тест", "screening": {"available": False}})
    return TestClient(app)


def test_the_route_hands_the_ticket_over_instead_of_calling_it_empty(monkeypatch, tmp_path):
    """Билет уезжает в окно, а не превращается в 502 «пустой ответ»."""
    handed = {"pending": True, "trace_id": "a1b2c3d4"}
    client = _client(monkeypatch, tmp_path, lambda *a, **k: handed,
                     lambda trace: {"pending": True})
    answer = client.post("/auctions/krt/test/plato", headers={"X-Market-Key": "test-key"})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["pending"] is True, body
    assert body["trace_id"] == "a1b2c3d4", body


def test_the_finished_answer_is_taken_by_the_run_number_and_kept(monkeypatch, tmp_path):
    """Готовое забирается тем же маршрутом и ложится в отчёт площадки."""
    ready = {"reply": "Брать по цене ниже 400 тыс ₽/м².", "pending": False}
    client = _client(monkeypatch, tmp_path,
                     lambda *a, **k: {"pending": True, "trace_id": "a1b2c3d4"},
                     lambda trace: ready if trace == "a1b2c3d4" else {"pending": True})
    answer = client.post("/auctions/krt/test/plato?trace_id=a1b2c3d4",
                         headers={"X-Market-Key": "test-key"})
    assert answer.status_code == 200, answer.text
    assert answer.json()["text"] == ready["reply"]
    # Записан — второй вопрос не заказывает работу заново.
    again = client.post("/auctions/krt/test/plato", headers={"X-Market-Key": "test-key"})
    assert again.json()["cached"] is True, again.text
    assert again.json()["text"] == ready["reply"]


def test_an_error_of_the_model_is_not_a_ticket(monkeypatch, tmp_path):
    """Отказ модели доносится отказом, а не вечным ожиданием."""
    client = _client(monkeypatch, tmp_path,
                     lambda *a, **k: {"pending": True, "trace_id": "a1b2c3d4"},
                     lambda trace: {"status": "error", "detail": "модель не ответила"})
    answer = client.post("/auctions/krt/test/plato?trace_id=a1b2c3d4",
                         headers={"X-Market-Key": "test-key"})
    assert answer.status_code == 502, answer.text
    assert "модель не ответила" in answer.json()["detail"]


def test_the_card_waits_with_the_common_code_and_asks_its_own_route():
    """Своего ожидания карточка не пишет: копий пути к Платону было три."""
    page = auctions_page()
    assert "async function platoAwait(" in page, "общего ожидания на странице нет"
    start = page.index("async function askPlatoAboutKrt(")
    body = page[start:page.index("\n}", start)]
    assert "platoAwait(" in body, body
    assert "trace_id=" in body, "готовое забирается по номеру запуска"
    assert "/auctions/krt/" in body, "забирать ходят в свой маршрут: он и сохраняет"

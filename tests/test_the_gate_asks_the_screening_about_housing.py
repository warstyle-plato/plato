"""Гейт «нет жилья» спрашивает ту же функцию, что и сам скрининг.

Скрининг умеет считать площадку-решение по площади КВАРТИР: жилую СПП он
восстанавливает делением на долю продаваемой и называет это своим пересчётом.
Внешний гейт `auction_search/api.py::_screen_for` держал свою копию вопроса и
читал только жилую СПП — и возвращал `_press_only` РАНЬШЕ, чем скрининг звали
вовсе.

Замер прода 20.09.2026: из 249 площадок-решений у 27 площадь квартир названа
при пустой жилой СПП, и у всех 27 есть адрес — 2-й Лихачевский 220 809 м²,
Братеевская 221 790, Речников 136 550, Криворожская 53 500, Дмитровское ш.
46 520 … и Рубцовская наб. 4 290, та самая, о которой владелец спрашивал
08.09.2026: «как это нет данных и сразу есть?». Все 27 отвечали «жилья в
проекте решения нет» — то есть НАШ пробел выдавался за ответ документа, а
документ это число называет двумя блоками ниже отказа.

Граница методики при этом остаётся: нежилую площадку модель по-прежнему не
считает (решение владельца 05.09.2026), и рынок за неё не оплачивается.

Запуск: python3 -m pytest tests/test_the_gate_asks_the_screening_about_housing.py -q
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from auction_search import krt_screening  # noqa: E402

API = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")


# --- сам ответ ---------------------------------------------------------------

def test_the_named_measure_counts_flats_too() -> None:
    """Названный городом объём жилья — это СПП ИЛИ площадь квартир."""
    named = krt_screening.housing_measure_named
    assert named({"housing_gfa_sqm": 50_400}) is True
    # Рубцовская наб., влд. 3: СПП в решении нет, площадь квартир названа.
    assert named({"flats_sqm": 4_290}) is True
    assert named({"housing_gfa_sqm": 0, "flats_sqm": 0}) is False
    assert named({"nonresidential_gfa_sqm": 40_000}) is False
    # «Площадки нет» — тоже «считать нечем», а не падение.
    assert named(None) is False


def test_the_gate_and_the_screening_share_one_answer() -> None:
    """Копии вопроса нет ни у гейта, ни у скрининга — обе зовут функцию."""
    gate = API[API.index("    def _screen_for("):API.index("\n    @app.post(\"/auctions/krt/press/run\")")]
    assert "housing_measure_named(project)" in gate, gate[-800:]
    # Своей копии условия у гейта больше нет: пересказанное условие отстаёт
    # от скрининга молча — ровно так и отстало.
    assert "housing_gfa_sqm" not in gate, gate

    source = (ROOT / "auction_search" / "krt_screening.py").read_text(encoding="utf-8")
    assert source.count("def housing_measure_named(") == 1
    body = source[source.index("def build_krt_model_screening("):]
    assert "housing_measure_named(project)" in body, "скрининг судит своей копией"


# --- и то, что видно на экране ------------------------------------------------

@pytest.fixture(scope="module")
def core():
    spec = importlib.util.spec_from_file_location("developaid_core", ROOT / "main_legacy.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["developaid_core"] = module
    spec.loader.exec_module(module)
    return module


_REPORT = {
    "analysis": {"site": {"segment": "Бизнес", "price_per_sqm": 450_000,
                          "sold_lot_avg": 58, "units_per_month": 25}},
    "price_hint": {"price_per_sqm": 450_000, "basis": "test fresh comparable median"},
    "subject": {"query": "krt:decision:1"},
}

_ROWS = {
    "decisions": [
        # Площадь квартир названа, жилой СПП в решении нет: Рубцовская наб.
        {"id": "400000001", "title": "Проект решения о КРТ",
         "address": "Рубцовская наб., влд. 3", "okrug": "ЦАО",
         "url": "https://www.mos.ru/dgp/documents/view/400000001/",
         "published_at": 1_788_400_000},
        # Нежилая: объём назван, жилья нет ни в каком виде.
        {"id": "400000002", "title": "Проект решения о КРТ нежилой застройки",
         "address": "Нежилая ул., влд. 1", "okrug": "САО",
         "url": "https://www.mos.ru/dgp/documents/view/400000002/",
         "published_at": 1_788_300_000},
    ],
    "matched_rows": [],
    "tep": {
        "400000001": {"available": True, "read": True, "area_ha": 0.73,
                      "total_gfa_sqm": 9_800, "flats_sqm": 4_290},
        "400000002": {"available": True, "read": True, "area_ha": 2.0,
                      "total_gfa_sqm": 40_000, "nonresidential_gfa_sqm": 40_000},
    },
}


def _app(monkeypatch, core):
    fastapi = pytest.importorskip("fastapi")
    monkeypatch.setenv("MARKET_CABINET_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "developaid_core", core)
    asked: list[str] = []

    def build_report(query, **kw):
        asked.append(query)
        return dict(_REPORT)

    app = fastapi.FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        build_report=build_report,
        search=SimpleNamespace(configured=False),
        krt=SimpleNamespace(
            catalogue=lambda **_: [],
            status=lambda: {"complete": True, "refreshing": False},
            decisions=lambda **_: dict(_ROWS),
            decision_requirements=lambda document_id, **_: {"available": False,
                                                            "warning": "не читали"},
            requirements=lambda slug, **_: None,
            card_facts=lambda slug, **_: {"available": False},
        ),
    )
    from auction_search import api as auction_api

    auction_api.install(app)
    return app, asked


def _finished(client) -> None:
    for _ in range(400):
        if not client.get("/auctions/krt/ranking").json()["progress"]["running"]:
            return
        time.sleep(0.05)
    raise AssertionError("прогон не кончился — итог читался бы наугад")


def test_a_site_with_named_flats_reaches_the_model(monkeypatch, core) -> None:
    """Площадь квартир названа — площадка считается, а не отказывается."""
    from fastapi.testclient import TestClient

    app, asked = _app(monkeypatch, core)
    client = TestClient(app)
    answer = client.post("/auctions/krt/ranking/refresh", headers={"X-Market-Key": "test-key"},
                         json={"slugs": ["decision:400000001", "decision:400000002"]})
    assert answer.status_code == 200, answer.text
    assert answer.json()["started"] is True, answer.json()
    _finished(client)
    rows = {row["slug"]: row for row in client.get("/auctions/krt/ranking").json()["rows"]}

    flats = rows.get("decision:400000001") or {}
    assert flats.get("available") is True, flats
    assert "Москва, Рубцовская наб., влд. 3" in asked, asked
    assert flats.get("project_llcr_x") is not None, flats
    # Есть что продавать: жилая СПП восстановлена из квартир, а строка
    # рейтинга несёт продаваемые метры — иначе «посчитано» было бы про ноль.
    assert (flats.get("saleable_sqm") or 0) > 0, flats

    # Граница методики на месте: нежилая по-прежнему названа отказом, и рынок
    # за неё не оплачен.
    other = rows.get("decision:400000002") or {}
    assert other.get("available") is False, other
    assert "нежилую площадку модель пока не считает" in str(other.get("reason")), other
    assert not any("Нежилая" in value for value in asked), "нежилая всё-таки сходила к рынку"

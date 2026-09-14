"""Сбор у сторожа — своим сроком, а расхождение названо числом.

«Так всего реально на торгах сколько сейчас крт?» и следом «ну так надо
проверить и синхронизировать это все???» (владелец, 14.09.2026). Ответ был
одиннадцать, а на вкладке стояло семь — и меньшее число было НАШИМ: строка
охвата того же ответа говорит «не прочитано карточек 39 из 51», потому что
сбор ограничен сорока секундами. Сорок секунд — это про ШЛЮЗ: он рвёт
соединение на шестидесяти и отдаёт свою HTML-страницу вместо каталога. У
сторожа окна запроса нет вовсе, и держать его тем же сроком значит вечно
дочитывать раздел по четверти.

Числа при этом обязаны стоять рядом: «собрано сейчас» и «связок помним» — не
одно и то же, и пока второго не видно, первое читается как ответ о рынке.
Живым лот тут никто не объявляет: правило живости живёт у каталога
(`krtLiveLot`), и второе такое правило ответило бы про один лот иначе.

Запуск: python3 -m pytest tests/test_the_collection_is_not_cut_by_the_gateway.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import page_blocks  # noqa: E402
from auction_search import api, ui  # noqa: E402
from auction_search.service import AuctionSearchService  # noqa: E402
from market_search.krt_registry import KrtRegistry  # noqa: E402

PAGE = ui.auctions_page(None)


def _app(tmp_path: Path, monkeypatch, *, links: dict) -> FastAPI:
    # Сеть в проверке не трогается: каталог и распоряжения — это mos.ru, и
    # без заглушки один запрос стоил бы полутора минут прогона.
    monkeypatch.setattr(KrtRegistry, "tender_orders",
                        lambda self, **kw: {"orders": [], "note": ""})
    monkeypatch.setattr(KrtRegistry, "projects",
                        lambda self, **kw: {"projects": [], "complete": True})
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    place = tmp_path / "market" / "krt" / "tender_lots.json"
    place.parent.mkdir(parents=True, exist_ok=True)
    place.write_text(json.dumps({"schema_version": 1, "sites": links},
                                ensure_ascii=False), encoding="utf-8")
    app = FastAPI()
    api.install(app)
    return app


def test_the_watchdog_collects_with_its_own_budget(tmp_path, monkeypatch):
    """У сторожа нет окна запроса — и срок у него свой, больше маршрутного."""
    asked: list[float | None] = []
    monkeypatch.setattr(AuctionSearchService, "discover_moscow",
                        lambda self, **kw: asked.append(kw.get("budget_seconds")) or [])
    monkeypatch.setattr(api.krt_pipeline, "read_notices",
                        lambda *a, **k: {"lots": 0})
    app = _app(tmp_path, monkeypatch, links={})
    collect = app.state.krt_tender_links_collect
    collect()
    assert asked, "сбор не звался вовсе"
    # Срок маршрута — про шлюз; сравнение идёт с ним, а не с числом здесь:
    # литерал в проверке разошёлся бы с кодом молча.
    route_budget = 40.0
    assert asked[0] and asked[0] > route_budget, (
        f"сторож собирает маршрутным сроком {asked[0]}")


def test_both_numbers_stand_next_to_each_other(tmp_path, monkeypatch):
    """«Собрано сейчас» и «связок помним» — разные числа, и оба названы."""
    links = {"a": {"lots": [{"url": "u1", "deadline": "09.10.26 15:00"}]},
             "b": {"lots": [{"url": "u2"}, {"url": "u3"}]}}
    app = _app(tmp_path, monkeypatch, links=links)
    client = TestClient(app)
    got = client.post("/auctions/krt/tenders", json={"lots": []})
    assert got.status_code == 200, got.text[:200]
    said = got.json()
    assert said["known_links"] == 3, said.get("known_links")

    # И то же на экране: подпись под таблицей печатает оба числа.
    prelude = (page_blocks.page_const("state", PAGE)
               + "\nstate.krt=[];"
               + "const box={style:{},innerHTML:''};"
               + "function $(id){return id==='krtDecisions'?box:null}"
               + "function esc(s){return String(s==null?'':s)}"
               + "function krtCityDay(t){return 'дата'}")
    tail = ("renderKrtTenderNote({orders:[],orders_by_site:{},krt_lots:7,"
            "known_links:11,orders_recent_12m:0,orders_with_address:0});"
            "console.log(JSON.stringify({html:box.innerHTML}));")
    html = page_blocks.run_json(prelude, tail, page=PAGE)["html"]
    assert "7" in html and "11" in html
    assert "наш" in html, "меньшее число — наш сбор, и это сказано"

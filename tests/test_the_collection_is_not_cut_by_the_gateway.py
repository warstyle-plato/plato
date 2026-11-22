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
import re
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Запись в раздел «Торги» — только команде (аудит 23.10.2026): тест проверяет
# логику маршрута, поэтому ходит с ключом кабинета.
TEAM_KEY = "team-cabinet-key-for-test"


@pytest.fixture(autouse=True)
def _team_cabinet_key(monkeypatch):
    monkeypatch.setenv("MARKET_CABINET_KEY", TEAM_KEY)


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
    monkeypatch.setattr(KrtRegistry, "decisions",
                        lambda self, **kw: {"decisions": [], "complete": True})
    monkeypatch.setattr(KrtRegistry, "catalogue", lambda self, **kw: [])
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
    # литерал в проверке разошёлся бы с кодом молча. Имя берётся целым словом,
    # иначе поиск подстроки находит объявление сторожа.
    source = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")
    found = re.search(r"(?<![A-Z_])DISCOVERY_BUDGET_SECONDS = ([\d.]+)", source)
    assert found, "у маршрута нет срока сбора"
    route_budget = float(found.group(1))
    assert asked[0] and asked[0] > route_budget, (
        f"сторож собирает маршрутным сроком {asked[0]}")


def test_both_numbers_stand_next_to_each_other(tmp_path, monkeypatch):
    """«Собрано сейчас» и «связок помним» — разные числа, и оба названы."""
    links = {"a": {"lots": [{"url": "u1", "deadline": "09.10.26 15:00"}]},
             "b": {"lots": [{"url": "u2"}, {"url": "u3"}]}}
    app = _app(tmp_path, monkeypatch, links=links)
    client = TestClient(app, headers={"X-Market-Key": TEAM_KEY})
    got = client.post("/auctions/krt/tenders", json={"lots": []})
    assert got.status_code == 200, got.text[:200]
    said = got.json()
    assert said["known_links"] == 3, said.get("known_links")

    # И то же на экране: подпись под таблицей печатает оба числа.
    prelude = (page_blocks.page_const("state", PAGE)
               + "\nstate.krt=[];"
               + "const box={style:{},innerHTML:''};"
               + "function $(id){return id==='krtTenderNote'?box:null}"
               + "function esc(s){return String(s==null?'':s)}"
               + "const KRT_FILTERS=[];function krtCityDay(t){return 'дата'}")
    tail = ("renderKrtTenderNote({orders:[],orders_by_site:{},krt_lots:7,"
            "known_links:11,orders_recent_12m:0,orders_with_address:0});"
            "console.log(JSON.stringify({html:box.innerHTML}));")
    html = page_blocks.run_json(prelude, tail, page=PAGE)["html"]
    assert "7" in html and "11" in html
    assert "наш" in html, "меньшее число — наш сбор, и это сказано"


def test_tender_summary_replaces_itself_and_tracks_selection():
    from playwright.sync_api import sync_playwright
    from browser_launch import launch

    prelude = """
const state={krt:Array.from({length:14},(_,i)=>({live:true,eligible:i<10})),
 krtTenders:{a:[]},krtPick:{stage:new Set(),other:new Set(['yes'])}};
const KRT_FILTERS=[{key:'stage',options:[{value:'tender',test:x=>x.live}]},
 {key:'other',options:[{value:'yes',test:x=>x.eligible}]}];
function $(id){return document.getElementById(id)}
function krtLiveLot(x){return x.live}
function krtTenderAnnounced(x){return false}
function esc(s){return String(s||'')}
function krtCityDay(){return ''}
const data={orders:[],known_links:14};
"""
    with sync_playwright() as p:
        browser = launch(p, args=["--no-sandbox"])
        page = browser.new_page()
        page.set_content('<div id="krtDecisions">Проекты решений</div><div id="krtTenderNote"></div>')
        page.add_script_tag(content=prelude
                            + page_blocks.function('krtFilterCount', PAGE)
                            + page_blocks.function('renderKrtTenderNote', PAGE))
        page.evaluate('for(let i=0;i<8;i++)renderKrtTenderNote(data)')
        note = page.locator('#krtTenderNote')
        assert note.is_visible()
        assert note.inner_text().count('Торги по КРТ.') == 1
        assert '14 площадок во всём каталоге; 10 с учётом' in note.inner_text()
        assert page.locator('#krtDecisions').inner_text() == 'Проекты решений'
        page.evaluate("state.krtPick.other.clear();renderKrtTenderNote(data)")
        assert '14 площадок во всём каталоге; 14 с учётом' in note.inner_text()
        browser.close()


def test_reconciliation_is_visible_once_and_failure_replaces_old_result():
    from playwright.sync_api import sync_playwright
    from browser_launch import launch
    from auction_search.krt_reconciliation import reconcile
    audit = reconcile([{'url': 'https://www.roseltorg.ru/procedure/123/1',
                        'name': 'Площадка', 'address': 'Черепановых, 29', 'slugs': ['a']}],
                      [], {'https://www.roseltorg.ru/procedure/123/1':
                           {'state': 'unread', 'reason': 'HTTP 429'}})
    with sync_playwright() as p:
        browser = launch(p, args=['--no-sandbox'])
        page = browser.new_page()
        page.set_content('<div id="krtReconciliation"></div>')
        page.add_script_tag(content='const state={};function $(id){return document.getElementById(id)}'
                            + page_blocks.constant('esc', PAGE)
                            + page_blocks.function('renderKrtReconciliation', PAGE))
        page.evaluate('(data)=>{state.krtReconciliation=data;for(let i=0;i<5;i++)renderKrtReconciliation()}', audit)
        box = page.locator('#krtReconciliation')
        assert box.is_visible()
        assert box.locator('tbody tr').count() == 1
        assert 'HTTP 429' in box.inner_text()
        assert 'Черепановых, 29' in box.inner_text()
        assert '0 из 1' in box.inner_text()
        page.evaluate("state.krtReconciliation={error:'Сбор не выполнен'};renderKrtReconciliation()")
        assert box.inner_text() == 'Сбор не выполнен'
        assert box.locator('tbody tr').count() == 0
        browser.close()


def test_discovery_returns_named_reconciliation_and_seeds_adapter(tmp_path, monkeypatch):
    from auction_search.adapters import RoseltorgAdapter
    url = 'https://www.roseltorg.ru/procedure/100/1'
    app = _app(tmp_path, monkeypatch, links={'site': {'lots': [
        {'url': url, 'address': 'Черепановых, 29', 'deadline': '30.11.2099 15:00'}]}})
    adapter = RoseltorgAdapter()
    def collect(**kw):
        assert adapter.known_krt_lots[0]['url'] == url
        adapter.last_report = {'lot_checks': {url: {'state': 'unread', 'reason': 'HTTP 429'}}}
        return []
    monkeypatch.setattr(adapter, 'discover_moscow', collect)
    monkeypatch.setattr(api, '_discovery_adapters', lambda source: [adapter])
    response = TestClient(app, headers={'X-Market-Key': TEAM_KEY}).get('/auctions/discover')
    assert response.status_code == 200
    result = response.json()['krt_reconciliation']
    assert result['expected'] == 1 and result['included'] == 0
    assert result['rows'][0]['name'] == 'Черепановых, 29'
    assert result['rows'][0]['reason'] == 'HTTP 429', json.dumps(response.json().get('coverage'), ensure_ascii=False)

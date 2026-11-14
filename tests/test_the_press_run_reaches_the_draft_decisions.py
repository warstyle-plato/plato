"""Публикации спрашиваются и по площадкам-решениям — раз в неделю, как по каталогу.

Владелец (04.09.2026): «По решениям надо. Раз в неделю как обычно».

Почему это была потеря. Прогон публикаций ходил по КАТАЛОГУ, а площадка, у
которой опубликован проект решения и нет карточки krt.mos.ru, в каталоге не
стоит: её строку собирает список из решений mos.ru. Спросить о ней было некому,
и все «не знаем» по входу и по реновации сидели ровно в них — 298 из 298 по
входу на снимке прода 04.09.2026. При этом карточка города о них молчит по
построению (её нет вовсе), то есть публикации у них ЕДИНСТВЕННЫЙ источник
ответа на «кто здесь уже собрался строить».

Три вещи, ради которых стоит тест.
1. Строку решения собирает один сборщик — и для экрана, и для прогона.
2. Выбор «чем считать эту строку» объявлен один раз — и прогоном, и кнопкой.
   (С 0.22.6 у решения с названным жильём считается и модель: субъект у него
   появился — адрес из заголовка, — а цифры прочитаны из PDF. Здесь проверяется
   не это, а что выбор один; модель держит соседний тест.)
3. Заголовок решения без адреса — это «искать не по чему», а не «в источниках
   пусто»: платить за поиск по имени документа нельзя, а отказ записывается —
   незаписанный отказ не отличить от отсутствия признака.

Запуск: python3 -m pytest tests/test_the_press_run_reaches_the_draft_decisions.py -q
"""

from __future__ import annotations

import copy
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import api as auction_api  # noqa: E402

API = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")

DECISIONS = {
    "decisions": [
        {"id": "347614220", "title": "Проект решения о комплексном развитии территории",
         "address": "ул. Архитектора Власова, влд. 59", "okrug": "ЮЗАО",
         "url": "https://www.mos.ru/dgp/documents/view/347614220/", "published_at": 1788400000},
        # У этого заголовка адреса нет: город написал «расположенной адресу»
        # без двоеточия, и разбор честно вернул пустую строку.
        {"id": "336775220", "title": "Проект решения о комплексном развитии территории "
                                     "нежилой застройки города Москвы, расположенной адресу",
         "address": "", "okrug": "", "url": "https://www.mos.ru/dgp/documents/view/336775220/",
         "published_at": 1788300000},
    ],
    "matched_rows": [],
    "tep": {"347614220": {"available": True, "read": True, "area_ha": 3.1,
                          "housing_gfa_sqm": 50_400}},
}


class _Doc:
    def __init__(self, title: str, snippet: str, url: str) -> None:
        self.title, self.snippet, self.url = title, snippet, url


class _Search:
    configured = True

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, **kw):
        self.queries.append(query)
        return [_Doc("КРТ на ул. Архитектора Власова, влд. 59",
                     "Оператором КРТ на ул. Архитектора Власова, влд. 59 стала компания "
                     "«Пример». Договор о комплексном развитии заключён.",
                     "https://example.org/vlasova")]


def _app(monkeypatch, *, catalogue=None, decisions=DECISIONS):
    fastapi = pytest.importorskip("fastapi")
    monkeypatch.setenv("MARKET_CABINET_KEY", "test-key")
    search = _Search()
    app = fastapi.FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        search=search,
        krt=SimpleNamespace(
            catalogue=lambda **_: list(catalogue if catalogue is not None else []),
            status=lambda: {"complete": True, "refreshing": False},
            decisions=lambda **_: dict(decisions),
        ),
    )
    auction_api.install(app)
    return app, search


def _run(app):
    from fastapi.testclient import TestClient

    return TestClient(app).post("/auctions/krt/press/run",
                                headers={"X-Market-Key": "test-key"})


def test_the_decision_row_is_built_in_one_place() -> None:
    """Один сборщик строки — у экрана и у прогона."""
    rows = auction_api.krt_decision_rows(DECISIONS)
    assert [row["slug"] for row in rows] == ["decision:347614220", "decision:336775220"]
    assert rows[0]["name"] == "ул. Архитектора Власова, влд. 59"
    assert rows[0]["address_known"] is True
    assert rows[0]["housing_gfa_sqm"] == 50_400, "ТЭП решения до строки не доехал"
    assert rows[1]["address_known"] is False, "адреса нет, а строка это скрывает"
    assert API.count("def krt_decision_rows(") == 1


def test_the_run_plans_the_decisions_too(monkeypatch) -> None:
    app, _ = _app(monkeypatch, catalogue=[
        {"slug": "planned", "name": "Планируемая площадка", "status": "Планируемый"},
        {"slug": "running", "name": "Стройка идёт", "status": "В реализации"},
    ])
    answer = _run(app)
    assert answer.status_code == 200, answer.text
    body = answer.json()
    # Планируемая из каталога и решение с адресом. Площадка в реализации не
    # спрашивается — её застройщика называет карточка города.
    assert body["planned"] == 2, body
    # Решение без адреса названо числом, а не пропущено молча.
    assert body["no_address"] == 1, body


def test_a_decision_without_an_address_is_not_paid_for(monkeypatch) -> None:
    """Поиск по имени документа ответил бы про все проекты решений сразу."""
    app, search = _app(monkeypatch, catalogue=[])
    answer = _run(app)
    assert answer.status_code == 200, answer.text
    assert answer.json()["planned"] == 1
    from fastapi.testclient import TestClient

    # Прогон идёт нитью — ждём его собственный признак, а не «сколько-нибудь».
    client = TestClient(app)
    finished = False
    for _ in range(200):
        if not client.get("/auctions/krt/ranking").json()["progress"]["running"]:
            finished = True
            break
        time.sleep(0.05)
    assert finished, "прогон не кончился — ждать дальше нечего, ответ был бы наугад"
    rows = {row["slug"]: row for row in client.get("/auctions/krt/ranking").json()["rows"]}
    asked = rows.get("decision:347614220") or {}
    assert (asked.get("press_facts") or {}).get("available") is True, \
        "площадку-решение с адресом не спросили вовсе"
    assert any("Власова" in query for query in search.queries), \
        "искали не по адресу площадки"
    assert not any("расположенной адресу" in query for query in search.queries), \
        "заплатили за поиск по заголовку документа"


@pytest.mark.parametrize('case', ['running', 'conflict-planned-first', 'conflict-running-first',
                                 'unknown-after-running'])
def test_the_weekly_run_carries_the_decisions(tmp_path, monkeypatch, case) -> None:
    """The actual weekly loop carries absent-from-catalogue decisions safely.

    Source-call spelling cannot establish this: the complete UI cohort also
    owns early projects, status conflicts and the completeness gate.
    """
    from test_running_krt_models_are_excluded import (
        RUNNING, PLANNED, _app as model_app, _closure, _keep_old_model,
        _one_pass, _synchronous_worker,
    )

    running = dict(RUNNING)
    if case == 'unknown-after-running':
        running.update(status='Новое нераспознанное состояние', last_known_status_kind='running')
    catalogue = [running, dict(PLANNED)]
    if case.startswith('conflict-'):
        conflict = [{'slug': 'conflicting', 'name': 'Synthetic conflict', 'status': status}
                    for status in ['Планируемый', 'В реализации']]
        catalogue.extend(conflict if case == 'conflict-planned-first' else reversed(conflict))
    decisions = {**copy.deepcopy(DECISIONS), 'complete': True}
    decision_rows = auction_api.krt_decision_rows(decisions)
    # The requirements stub may serve these decisions, but the catalogue must
    # not contain them: otherwise a broken decision path would still pass.
    app, ranking, loops, model_calls, _, requirements = model_app(
        tmp_path, monkeypatch, [*catalogue, *decision_rows])
    registry = app.state.market_discovery_service.krt
    registry.catalogue = lambda **_: copy.deepcopy(catalogue)
    registry.projects = lambda **_: copy.deepcopy(catalogue)
    source_calls = []

    def read_decisions(**kwargs):
        source_calls.append(copy.deepcopy(kwargs.get('catalogue')))
        return copy.deepcopy(decisions)

    registry.decisions = read_decisions
    document_reads = []

    def decision_requirements(document_id):
        document_reads.append(document_id)
        return {}

    registry.decision_requirements = decision_requirements
    old_model = _keep_old_model(ranking)
    monkeypatch.setattr(ranking, 'due', lambda *args: True)
    _synchronous_worker(monkeypatch, ranking)
    weekly = loops['krt-weekly']
    dispatch = _closure(weekly)['_screen_for_background']
    cell = dict(zip(dispatch.__code__.co_freevars, dispatch.__closure__))['_screen_for']
    original = cell.cell_contents
    dispatched = []

    def recorded_dispatch(project, **kwargs):
        dispatched.append(project['slug'])
        return original(project, **kwargs)

    cell.cell_contents = recorded_dispatch
    try:
        _one_pass(monkeypatch, weekly)
    finally:
        cell.cell_contents = original

    assert source_calls and source_calls[0] == catalogue
    assert set(model_calls) == {'planned', 'decision:347614220'}
    assert len(model_calls) == 2, 'one source key must never launch two models'
    # Decision requirements come from their own document path, not a missing
    # catalogue card. The catalogue requirements reader sees only the allowed card.
    assert requirements == ['planned']
    assert document_reads == ['347614220']
    assert set(dispatched) == {project['slug'] for project in catalogue+decision_rows}
    assert ranking.report('decision:347614220')['screening']['available']
    refusal = ranking.stored_row('decision:336775220')
    assert 'адрес' in (refusal.get('press_facts') or {}).get('reason', '').lower()
    assert ranking.report_path('running').read_bytes() == old_model
    assert ranking.stored_row('running')['computed_at'] == 100
    if case.startswith('conflict-'):
        assert not ranking.report_path('conflicting').exists()
        assert ranking.stored_row('conflicting')['model_excluded']
    assert ranking.progress()['model_skipped'] == (2 if case.startswith('conflict-') else 1)
    assert ranking.progress()['done'] == len({project['slug'] for project in catalogue+decision_rows})
    # Выбор «чем считать строку» объявлен один раз: разойдись кнопка с
    # прогоном, одна площадка считалась бы двумя способами.
    assert API.count("    def _screen_for(") == 1


def test_the_card_button_answers_a_decision_row(monkeypatch) -> None:
    """Кнопка отвечает там же, где отвечает прогон.

    Прежде она искала площадку только в каталоге и отвечала «не найдена»
    четырёхсоткой — при том что у площадки-решения публикации единственный
    источник ответа. Кнопка, отказывающая там, где отвечает прогон, читается
    как поломка.
    """
    from fastapi.testclient import TestClient

    app, search = _app(monkeypatch, catalogue=[])
    client = TestClient(app)
    answer = client.get("/auctions/krt/decision:347614220/open-sources")
    assert answer.status_code == 200, answer.text
    assert answer.json()["available"] is True
    assert any("Власова" in query for query in search.queries)

    # А у решения без адреса — названная причина, а не поиск и не 404.
    silent = client.get("/auctions/krt/decision:336775220/open-sources")
    assert silent.status_code == 200, silent.text
    body = silent.json()
    assert body["available"] is False
    assert "адрес" in body["reason"]
    assert not any("расположенной адресу" in query for query in search.queries)
    # Причина у отказа объявлена один раз — её отдают и прогон, и кнопка.
    assert API.count("def press_refusal_without_address(") == 1
    assert API.count("искать публикации не по чему") == 1


def test_the_siblings_include_the_decisions() -> None:
    """Улица опознаёт площадку только там, где на ней нет соседа.

    Сосед может стоять и во второй половине списка: пока соседями были одни
    карточки каталога, находка по улице уходила площадке-решению целиком.
    """
    start = API.index("    def _read_open_sources(")
    body = API[start:API.index("\n    def _row_without_stale_facts(", start)]
    assert "_krt_all_sites()" in body, "соседи считаются по одной половине списка"
    assert "krt_registry.catalogue()" not in body

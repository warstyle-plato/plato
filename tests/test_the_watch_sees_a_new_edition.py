"""Сторож нормативов видит новую редакцию, а не только переписанную публикацию.

Ревизия 16.10.2026 (docs/normative_audit_msk_mo_2026-10.md, §8): о поправках к
713/30 — 774-ПП от 02.07.2026 и 1080-ПП от 01.09.2026 — бот не сказал ничего.
Две причины, обе по построению и обе здесь проверяются по отдельности.

Первая — отпечаток снимался с `source_url`, а это публикация САМОЙ поправки на
pravo.gov.ru: страница заморожена днём выхода и не меняется никогда. Меняется
с редакцией консолидированный текст, и когда его адрес назван
(`consolidated_url`), отпечаток обязан сниматься с него — одной функцией
`watch_target`, которой пользуются проба, диагностика и страница.

Вторая — единственный поисковый запрос «713/30 утратил силу или внесены
изменения» приносил Гарант, Главбух и проекты, но не карточку поправки. Карточка
озаглавлена «О внесении изменений в постановление … № 713/30» и ищется своими
словами, по дате; выдачи обоих запросов складываются, и новый номер идёт в
очередь боту.

Третья половина ответа — диагностика: какой адрес сверяется и сколько запросов
ушло. Без неё «отпечаток не изменился» неотличимо от «сверяли замороженную
страницу», а «поправок нет» — от «спросили одним запросом, который их не находит».

Запуск: python3 -m pytest tests/test_the_watch_sees_a_new_edition.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import normatives_registry as registry  # noqa: E402

PUBLICATION = "http://publication.pravo.gov.ru/document/5000202609020006"
CONSOLIDATED = "https://example.test/kodeks/713-30"

CARD = {
    "id": "mo-713-30",
    "scope": "Московская область",
    "title": "Постановление Правительства Московской области от 17.08.2015 № 713/30 "
             "«Об утверждении нормативов градостроительного проектирования Московской области»",
    "short_name": "713/30 — РНГП Московской области",
    "source_url": PUBLICATION,
    "source_label": "Официальное опубликование правовых актов — 1080-ПП",
    "consolidated_url": CONSOLIDATED,
    "consolidated_label": "Действующая редакция 713/30 — база «Кодекс»",
    "watch_terms": ["713/30", "774-ПП"],
    "latest_amendment": "ПП Московской области от 02.07.2026 № 774-ПП",
}


class _Headers:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def get(self, name: str, default: str = "") -> str:
        return self._values.get(name, default)


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.status = 200
        self.headers = _Headers({"Content-Type": "text/html; charset=utf-8"})

    def read(self, _limit: int = 0) -> bytes:
        return self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False


def _page(edition: str) -> bytes:
    return (f"<html><body><h1>Постановление № 713/30 «Об утверждении нормативов "
            f"градостроительного проектирования Московской области»</h1>"
            f"<p>Редакция: {edition}. Поправки: 774-ПП.</p></body></html>").encode("utf-8")


@pytest.fixture()
def world(tmp_path, monkeypatch):
    """Реестр из одной карточки, своё состояние, своя очередь, поиска нет."""
    monkeypatch.setattr(registry, "_STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(registry, "_ANNOUNCE_PATH", tmp_path / "announcements.jsonl")
    monkeypatch.setattr(registry, "_load_registry", lambda: [dict(CARD)])
    monkeypatch.setattr(registry, "_search_client", lambda: None)
    return tmp_path


def _fake_web(monkeypatch, pages: dict[str, bytes], fetched: list[str]) -> None:
    def urlopen(req, timeout: int = 0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        fetched.append(url)
        if url not in pages:
            raise AssertionError(f"сторож пошёл по адресу, которого в подделке нет: {url}")
        return _Response(pages[url])
    monkeypatch.setattr(registry.urllib.request, "urlopen", urlopen)


def _queued(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# --- (а) отпечаток снимается с действующего текста ----------------------------

def test_the_fingerprint_is_taken_from_the_consolidated_text(world, monkeypatch) -> None:
    """Сменилась редакция в консолидированном тексте — это «изменилось» и новость.

    Публикация поправки при этом не трогается вовсе: она заморожена, и
    сверять её — значит молчать по построению.
    """
    fetched: list[str] = []
    pages = {CONSOLIDATED: _page("с 03.07.2026 (774-ПП)")}
    _fake_web(monkeypatch, pages, fetched)
    first = registry._run_check()["checks"]["mo-713-30"]
    assert first["result"] == "ok", first["message"]
    assert first["source_url"] == CONSOLIDATED, "отпечаток снят не с действующего текста"
    assert first["watch_field"] == "consolidated_url"

    pages[CONSOLIDATED] = _page("с 03.09.2026 (1080-ПП)")
    state = registry._run_check()
    second = state["checks"]["mo-713-30"]
    assert second["result"] == "changed", second["message"]
    assert PUBLICATION not in fetched, "публикацию поправки сверять незачем: она не меняется"
    assert fetched == [CONSOLIDATED, CONSOLIDATED]

    queued = _queued(world / "announcements.jsonl")
    assert [item["result"] for item in queued] == ["changed"]
    assert queued[0]["source_url"] == CONSOLIDATED, "объявление ведёт не на сверенный адрес"


def test_without_a_consolidated_text_the_source_is_checked_as_before(world, monkeypatch) -> None:
    """Поля нет — сверяется `source_url`, и это названо полем, а не угадано."""
    card = {k: v for k, v in CARD.items() if not k.startswith("consolidated")}
    monkeypatch.setattr(registry, "_load_registry", lambda: [card])
    fetched: list[str] = []
    _fake_web(monkeypatch, {PUBLICATION: _page("1080-ПП")}, fetched)
    check = registry._run_check()["checks"]["mo-713-30"]
    assert fetched == [PUBLICATION]
    assert check["source_url"] == PUBLICATION and check["watch_field"] == "source_url"


def test_one_function_owns_the_watched_address() -> None:
    """Все читатели спрашивают `watch_target`, а не выбирают поле сами."""
    import inspect

    assert registry.watch_target(CARD)["url"] == CONSOLIDATED
    assert registry.watch_url({"source_url": PUBLICATION}) == PUBLICATION
    assert registry.watch_url({}) == ""
    for reader in (registry._probe, registry._changes_between, registry.watch_state,
                   registry._card):
        body = inspect.getsource(reader)
        assert "watch_target(" in body or "watch_url(" in body, reader.__name__
        assert 'get("consolidated_url")' not in body, reader.__name__


# --- (б) второй вопрос — словами самой поправки ------------------------------

def test_the_second_question_is_asked_the_way_the_amendment_is_titled() -> None:
    queries = registry.watch_queries(CARD)
    assert queries[0]["query"] == registry.watch_query(CARD)
    assert queries[0]["sort_by_date"] is False
    assert queries[1]["query"] == ("О внесении изменений в постановление "
                                   "Правительства Московской области № 713/30")
    assert queries[1]["sort_by_date"] is True, "поправка новее акта: искать по дате"


def test_an_act_without_a_number_gets_no_second_question() -> None:
    """«О внесении изменений в …» без реквизитов нашёл бы чужие поправки."""
    sp = {"title": "СП 42.13330.2016 «Градостроительство»", "short_name": "СП 42.13330.2016"}
    assert registry.amendment_query(sp) == ""
    assert len(registry.watch_queries(sp)) == 1


def test_a_new_number_found_by_the_second_question_reaches_the_queue(world, monkeypatch) -> None:
    """Выдача первого запроса — та, что была на проде: ничего о поправках.

    Карточку 1080-ПП приносит только второй запрос. Номер в реестре не учтён —
    значит, это новость, и она в очереди боту.
    """
    class _Doc:
        def __init__(self, title: str, snippet: str, url: str) -> None:
            self.title, self.snippet, self.url = title, snippet, url

    noise = [_Doc("Нормативы градостроительного проектирования МО — Гарант", "", "https://g.test/1"),
             _Doc("Главбух: как считать парковки", "", "https://glavbukh.test/2")]
    amendment = [_Doc(
        "Постановление Правительства Московской области от 01.09.2026 № 1080-ПП "
        "«О внесении изменений в нормативы градостроительного проектирования Московской области»",
        "Изменения вносятся в нормативы, утвержденные постановлением Правительства "
        "Московской области от 17.08.2015 № 713/30.",
        "http://publication.pravo.gov.ru/document/5000202609020006")]
    asked: list[tuple[str, bool]] = []

    class _Client:
        def search(self, query: str, **kw: object) -> list[_Doc]:
            asked.append((query, bool(kw.get("sort_by_date"))))
            return amendment if query.startswith("О внесении изменений") else noise

    monkeypatch.setattr(registry, "_search_client", lambda: _Client())
    monkeypatch.setattr(registry, "_probe",
                        lambda entry, previous: {"checked_at": "2026-10-18T10:00:00+03:00",
                                                 "result": "ok", "sha256": "x"})
    state = registry._run_check(search=True)
    assert asked == [(registry.watch_query(CARD), False),
                     ("О внесении изменений в постановление Правительства Московской области № 713/30", True)]
    sources = state["checks"]["mo-713-30"]["sources"]
    assert sources["asked"] is True and sources["checked"] == 3
    assert [q["asked"] for q in sources["queries"]] == [True, True]
    queued = _queued(world / "announcements.jsonl")
    assert [item["result"] for item in queued] == ["amended"]
    assert "1080-ПП" in queued[0]["message"]


def test_a_number_already_accounted_for_is_not_news_even_from_the_second_question(
        world, monkeypatch) -> None:
    """774-ПП учтён в реестре — его карточка новостью не становится."""
    class _Doc:
        title = ("Постановление Правительства Московской области от 02.07.2026 № 774-ПП "
                 "«О внесении изменений в нормативы градостроительного проектирования»")
        snippet = "Изменения вносятся в постановление от 17.08.2015 № 713/30."
        url = "https://example.test/774"

    class _Client:
        def search(self, query: str, **kw: object) -> list[_Doc]:
            return [_Doc()]

    monkeypatch.setattr(registry, "_search_client", lambda: _Client())
    monkeypatch.setattr(registry, "_probe",
                        lambda entry, previous: {"result": "ok", "sha256": "x"})
    registry._run_check(search=True)
    assert _queued(world / "announcements.jsonl") == []


def test_the_shared_search_client_can_sort_by_date() -> None:
    """Сортировка — часть вопроса: у клиента движка она есть и попадает в запрос."""
    import inspect

    from market_search.yandex_search import YandexSearchClient

    src = inspect.getsource(YandexSearchClient.search)
    assert "sort_by_date" in src and "SORT_MODE_BY_TIME" in src
    assert "sort_tag" in src, "у выдачи по дате должен быть свой кэш"


# --- (в) диагностика называет адрес и число запросов -------------------------

def test_the_diagnostics_name_the_address_the_fingerprint_checks(world) -> None:
    registry._save_state({
        "last_run_at": "2026-10-18T10:00:00+03:00",
        "last_search_at": "2026-10-18T10:00:00+03:00",
        "checks": {"mo-713-30": {"result": "ok", "sources": {
            "asked": True, "signals": [],
            "queries": [{"query": "a", "asked": True}, {"query": "b", "asked": True},
                        {"query": "c", "asked": False, "reason": "поиск не ответил"}]}}},
    })
    state = registry.watch_state()
    assert state["watched"] == [{"id": "mo-713-30", "url": CONSOLIDATED,
                                 "field": "consolidated_url",
                                 "label": "Действующая редакция 713/30 — база «Кодекс»"}]
    assert state["search_queries"] == 2, "считаются ушедшие запросы, а не задуманные"
    note = registry._watch_note({**state, "enabled": True, "search_available": True})
    assert "запросов поиска за заход: 2" in note


def test_the_card_tells_the_admin_which_address_was_fingerprinted() -> None:
    entry = {**CARD, "check": {"result": "ok", "message": "Источник доступен",
                               "checked_at": "2026-10-18T10:00:00", "http_status": 200}}
    card = registry._card(entry, admin=True)
    assert "Отпечаток снят с" in card
    assert CONSOLIDATED in card and "Действующая редакция 713/30" in card
    # Читателю без ключа — ссылка на действующий текст, а не рабочий контур.
    reader = registry._card(entry, admin=False)
    assert CONSOLIDATED in reader and "Отпечаток снят с" not in reader

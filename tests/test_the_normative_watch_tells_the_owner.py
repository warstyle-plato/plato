"""Проверка актуальности нормативной базы доходит до Платона и до чата.

«Сделать возможность проверки актуальности Платоном и чтобы бот после такой
проверки присылал, что произошли изменения» (владелец, 06.09.2026).

Проверка источников у реестра была и до этого — кнопкой на странице. Кнопка
отвечает тому, кто её нажал; человек, который страницу не открывал, не узнавал
ничего. Дорога до чата та же, что у знакомств и новинок каталога КРТ: до
api.telegram.org достаёт только хост с вебхуком, поэтому ядро копит находки, а
он их объявляет. Второго пути не заводим.

Сообщается ПЕРЕХОД, а не состояние: источник, который лежит третью неделю,
новостью не является, и повторяемое каждые четверть часа сообщение перестало
бы читаться вовсе.

Запуск: python3 -m pytest tests/test_the_normative_watch_tells_the_owner.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as wrapper  # noqa: E402
import normatives_registry as registry  # noqa: E402

core = wrapper.core


@pytest.fixture()
def queue(tmp_path, monkeypatch):
    path = tmp_path / "announcements.jsonl"
    monkeypatch.setattr(registry, "_ANNOUNCE_PATH", path)
    return path


# --- что считается новостью ---------------------------------------------------

def test_a_new_problem_is_announced(queue) -> None:
    entries = {"a": {"scope": "Москва", "short_name": "945-ПП", "source_url": "x"}}
    changes = registry._changes_between(
        {"a": {"result": "ok"}}, {"a": {"result": "changed", "message": "текст другой"}}, entries)
    assert [c["result"] for c in changes] == ["changed"]
    assert changes[0]["was"] == "ok"
    assert changes[0]["short_name"] == "945-ПП"


def test_the_same_problem_is_not_announced_twice(queue) -> None:
    """Источник, который лежит третью неделю, — не новость."""
    entries = {"a": {"short_name": "945-ПП"}}
    assert registry._changes_between(
        {"a": {"result": "unreachable"}}, {"a": {"result": "unreachable"}}, entries) == []


def test_a_missing_source_is_not_a_news_item(queue) -> None:
    """«Ссылки нет» — наш пробел, он и так виден в справочнике.

    Сообщение о нём приходило бы после каждой проверки и приучило бы не читать
    эти сообщения вовсе.
    """
    entries = {"a": {"short_name": "Приказ ДГИ № 303"}}
    assert registry._changes_between({}, {"a": {"result": "no_source"}}, entries) == []


def test_recovery_is_news_too(queue) -> None:
    """Обратный переход в порядок новостью не считается — сообщаем о проблемах."""
    entries = {"a": {"short_name": "945-ПП"}}
    assert registry._changes_between(
        {"a": {"result": "unreachable"}}, {"a": {"result": "ok"}}, entries) == []


# --- очередь ------------------------------------------------------------------

def test_the_queue_is_taken_once(queue) -> None:
    """Забирает только один: воркеров два, и оба пришли бы за одним и тем же."""
    registry._queue_announcements([{"id": "a", "result": "changed"}])
    first = registry.take_announcements()
    assert [x["id"] for x in first] == ["a"]
    assert registry.take_announcements() == [], "очередь отдалась дважды"


def test_an_empty_queue_is_not_a_message(queue) -> None:
    assert registry.take_announcements() == []


# --- дорога до чата -----------------------------------------------------------

def test_the_core_hands_the_queue_over_by_the_shared_signature() -> None:
    """Тот же путь и та же подпись, что у знакомств и новинок КРТ."""
    source = Path(ROOT / "main_legacy.py").read_text(encoding="utf-8")
    assert '@app.post("/internal/normatives/announcements")' in source
    block = source[source.index('@app.post("/internal/normatives/announcements")'):]
    block = block[:block.index('@app.post("/internal/krt/subscribe")')]
    assert '_web_login_sign("normatives-announcements"' in block
    assert "compare_digest" in block, "маршрут отдаёт очередь без проверки подписи"
    # Реестра нет — это говорится вслух: пустой список читался бы как
    # «в нормативной базе ничего не менялось».
    assert "503" in block and "не установлен" in block


def test_the_bot_sends_one_message_for_the_whole_batch() -> None:
    """Тринадцать сообщений подряд читаются как поломка бота."""
    text = wrapper._normatives_announcement_text([
        {"short_name": "945-ПП", "scope": "Москва", "result": "changed",
         "message": "текст источника изменился"},
        {"short_name": "713/30", "scope": "Московская область", "result": "unreachable",
         "message": "Источник ответил HTTP 403"},
    ])
    assert text.count("•") == 2
    assert "945-ПП" in text and "713/30" in text
    assert "источник изменился" in text and "не отвечает" in text
    assert "/normatives" in text, "не сказано, где смотреть, что именно изменилось"


def test_the_delivery_goes_through_the_webhook_host() -> None:
    import inspect

    body = inspect.getsource(wrapper._deliver_normatives_announcements)
    assert "_telegram_webhook_enabled" in body, "шлёт не тот хост"
    assert "/internal/normatives/announcements" in body
    assert "usage_admin_ids" in body


# --- Платон -------------------------------------------------------------------

def test_platon_reads_the_registry_and_not_his_memory() -> None:
    got = core._tool_check_normatives("status")
    assert got["available"] and got["count"] == len(registry._merged_registry())
    names = [item["name"] for item in got["items"]]
    assert any("945-ПП" in str(name) for name in names)
    # Отсутствие ссылки — тоже ответ, и оно не прячется.
    assert any(item["source_missing"] for item in got["items"])
    assert got["page"] == "/normatives"


def test_the_tool_is_declared_and_dispatched() -> None:
    assert "check_normatives" in [tool["name"] for tool in core._AGENT_TOOLS]
    source = Path(ROOT / "main_legacy.py").read_text(encoding="utf-8")
    dispatch = source.split("def _execute_agent_tool", 1)[1][:5000]
    assert "check_normatives" in dispatch, "инструмент не диспетчеризуется"


def test_the_long_probe_is_not_the_default() -> None:
    """«run» опрашивает источники и ходит в сеть — только по прямой просьбе."""
    tool = next(t for t in core._AGENT_TOOLS if t["name"] == "check_normatives")
    assert tool["parameters"]["properties"]["action"]["enum"] == ["status", "run"]
    assert "долгое" in tool["description"]


# --- расписание ---------------------------------------------------------------

def test_the_watch_has_a_switch_and_it_is_off_in_tests() -> None:
    """Расписание, зависящее от календаря, срабатывает в прогоне не вовремя."""
    import os
    import threading

    assert os.getenv("NORMATIVES_WATCH") == "0"
    assert "normatives-watch" not in [t.name for t in threading.enumerate()]
    source = Path(ROOT / "normatives_registry.py").read_text(encoding="utf-8")
    assert 'os.getenv("NORMATIVES_WATCH"' in source


def test_the_watch_waits_for_its_hour(monkeypatch) -> None:
    monkeypatch.setattr(registry, "_load_state", lambda: {})
    assert registry._watch_due(24) is True, "пустое состояние — ни разу не смотрели"
    monkeypatch.setattr(registry, "_load_state", lambda: {"last_run_at": registry._now_iso()})
    assert registry._watch_due(24) is False
    monkeypatch.setattr(registry, "_load_state", lambda: {"last_run_at": "не дата"})
    assert registry._watch_due(24) is True, "нечитаемая отметка — проверяем заново"


# --- что об акте пишут в открытых источниках ----------------------------------
#
# «Искать обновление надо не так» (владелец, 06.09.2026): отпечаток страницы
# отвечает на «страницу переписали?», а спрашивать надо «что с актом стало».
# Страница правовой системы меняется от баннера, а акт отменяют, не трогая наш
# PDF — у файла в библиотеке отпечаток не изменится НИКОГДА, то есть именно
# там, где проверка нужнее всего, она молчит по построению.

def test_the_query_is_built_from_the_act_not_from_its_link() -> None:
    entry = {"short_name": "945-ПП — транспорт и парковки", "source_url": "https://x/y"}
    query = registry.watch_query(entry)
    assert query.startswith("945-ПП")
    assert "утратил силу" in query and "изменения" in query
    assert "http" not in query, "запрос построен из ссылки, а не из реквизитов"


def test_a_signal_needs_the_number_of_this_act() -> None:
    """Сниппет про соседний акт не имеет права забрать находку себе."""
    entry = {"short_name": "945-ПП", "watch_terms": ["945-ПП", "2118-ПП"]}
    docs = [{"title": "Новости", "snippet": "Постановление 123-ПП утратило силу.", "url": "u"}]
    assert registry.find_repeal_signals(entry, docs) == []


def test_the_repeal_is_found_with_its_quote_and_link() -> None:
    entry = {"short_name": "945-ПП", "watch_terms": ["945-ПП"]}
    docs = [{"title": "Гарант", "url": "u1",
             "snippet": "Документ 945-ПП утратил силу с 1 января 2027 года."}]
    got = registry.find_repeal_signals(entry, docs)
    assert [x["kind"] for x in got] == ["repealed"]
    assert "утратил силу" in got[0]["quote"] and got[0]["url"] == "u1"


def test_the_worst_signal_comes_first() -> None:
    entry = {"short_name": "945-ПП", "watch_terms": ["945-ПП"]}
    docs = [{"title": "a", "snippet": "945-ПП в редакции от 05.08.2026.", "url": "u1"},
            {"title": "b", "snippet": "945-ПП признано утратившим силу.", "url": "u2"}]
    assert [x["kind"] for x in registry.find_repeal_signals(entry, docs)] == \
        ["repealed", "amended"]


def test_a_marker_in_another_sentence_is_not_a_signal() -> None:
    """«Отменено» через абзац от нашего номера не значит ничего."""
    entry = {"short_name": "945-ПП", "watch_terms": ["945-ПП"]}
    docs = [{"title": "t", "url": "u",
             "snippet": "945-ПП устанавливает нормативы. Постановление 77-ПП отменено."}]
    assert registry.find_repeal_signals(entry, docs) == []


def test_an_anchor_without_a_number_is_not_an_anchor() -> None:
    """«Кзатр» или «парковка» опознают тему, а не документ."""
    entry = {"short_name": "945-ПП", "watch_terms": ["парковка", "Кзатр"]}
    docs = [{"title": "t", "snippet": "Парковка: документ утратил силу.", "url": "u"}]
    assert registry.find_repeal_signals(entry, docs) == []


def test_an_unconfigured_search_says_so_and_does_not_pretend() -> None:
    """Пустой ответ поиска — «не нашли», а не «действует»."""
    got = registry._search_signals({"short_name": "945-ПП"}, None)
    assert got["asked"] is False and "не настроен" in got["reason"]


def test_a_found_repeal_reaches_the_chat() -> None:
    entries = {"a": {"short_name": "945-ПП", "scope": "Москва"}}
    after = {"a": {"result": "ok", "sources": {"asked": True, "signals": [
        {"kind": "repealed", "quote": "945-ПП утратил силу", "url": "u"}]}}}
    changes = registry._changes_between({"a": {"result": "ok"}}, after, entries)
    assert [c["result"] for c in changes] == ["repealed"]
    assert changes[0]["message"] == "945-ПП утратил силу"
    text = wrapper._normatives_announcement_text(changes)
    assert "утратил силу" in text


def test_the_same_signal_is_not_announced_twice() -> None:
    entries = {"a": {"short_name": "945-ПП"}}
    same = {"asked": True, "signals": [{"kind": "repealed", "quote": "q", "url": "u"}]}
    assert registry._changes_between(
        {"a": {"result": "ok", "sources": same}},
        {"a": {"result": "ok", "sources": same}}, entries) == []


def test_the_paid_search_has_its_own_slower_clock() -> None:
    """Поиск платный: ссылку смотрим сутками, источники — раз в неделю.

    И отметка у него своя: иначе ежедневная проверка ссылки сдвигала бы срок
    поиска, и он не наступал бы никогда.
    """
    import inspect

    body = inspect.getsource(registry._watch_loop)
    assert "NORMATIVES_SEARCH_HOURS" in body
    assert 'key="last_search_at"' in body
    saved = inspect.getsource(registry._run_check)
    assert '"last_search_at"' in saved


def test_the_search_client_is_the_engines_own() -> None:
    """Второй клиент — второй счёт за те же запросы и вторая жизнь у настроек."""
    import inspect

    body = inspect.getsource(registry._search_client)
    assert "market_search.yandex_search" in body
    assert "configured" in body

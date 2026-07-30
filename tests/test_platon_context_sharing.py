"""Контекст Платона Сергеевича переживает переход между воркерами.

Сервис работает в несколько процессов, и память у них раздельная: страница
отправляет расчёт в один воркер, а нажатие «Спросить Платона» приходит вебхуком
в другой. Тот отвечал «Платону пока не передан проект» по только что
посчитанному проекту. Контекст дублируется на диск: словари — быстрый кеш,
диск — общая память воркеров.
Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

CONTEXT = {
    "session": "s-1", "chat_id": 42,
    "inputs": {"purchase_price_mln": 700}, "tep": {},
    "rates": [], "phasing": {}, "selected_view": "all",
}


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(wrapper, "_STATE_DIR", tmp_path)
    for name in ("_PLATON_CONTEXT_BY_SESSION", "_PLATON_LAST_SESSION", "_PLATON_TEP_CONTEXT"):
        monkeypatch.setattr(wrapper, name, {})
    return tmp_path


def forget_memory(monkeypatch):
    """Имитирует другой воркер: та же файловая система, пустая память."""
    for name in ("_PLATON_CONTEXT_BY_SESSION", "_PLATON_LAST_SESSION", "_PLATON_TEP_CONTEXT"):
        monkeypatch.setattr(wrapper, name, {})


def test_full_model_context_survives_a_worker_switch(state, monkeypatch):
    wrapper._state_write("session:s-1", CONTEXT)
    wrapper._state_write("chat:42", {"session": "s-1"})
    forget_memory(monkeypatch)

    session, context = wrapper._resolve_context(42)
    assert session == "s-1"
    assert context["inputs"]["purchase_price_mln"] == 700
    assert wrapper._has_model_context(42)


def test_bot_tep_context_survives_a_worker_switch(state, monkeypatch):
    wrapper._state_write("chat:42", {"tep_context": {**CONTEXT, "origin": "tep"}})
    forget_memory(monkeypatch)

    session, context = wrapper._resolve_context(42)
    assert session == ""
    assert context["origin"] == "tep"


def test_another_chat_gets_nothing(state, monkeypatch):
    wrapper._state_write("session:s-1", CONTEXT)
    wrapper._state_write("chat:42", {"session": "s-1"})
    forget_memory(monkeypatch)
    assert wrapper._resolve_context(99) == ("", {})


def test_memory_is_refilled_so_the_disk_is_read_once(state, monkeypatch):
    wrapper._state_write("session:s-1", CONTEXT)
    wrapper._state_write("chat:42", {"session": "s-1"})
    forget_memory(monkeypatch)
    wrapper._resolve_context(42)
    assert wrapper._PLATON_CONTEXT_BY_SESSION["s-1"]["chat_id"] == 42
    assert wrapper._PLATON_LAST_SESSION[42] == "s-1"


def test_write_is_atomic_and_leaves_no_temporary_files(state):
    wrapper._state_write("session:s-1", CONTEXT)
    assert not list(state.glob("*.tmp")), "временный файл остался — сосед прочитает половину записи"
    stored = json.loads(next(state.glob("*.json")).read_text(encoding="utf-8"))
    assert stored["chat_id"] == 42


def test_unreadable_state_does_not_break_the_bot(state, monkeypatch):
    """Диск — подстраховка: его отказ не должен ронять ответ пользователю."""
    monkeypatch.setattr(wrapper, "_STATE_DIR", state / "нет" / "такого")
    wrapper._state_write("session:s-1", CONTEXT)
    assert wrapper._state_read("session:s-1") in ({}, CONTEXT)
    assert wrapper._resolve_context(42) == ("", {})


def test_stale_state_is_pruned(state):
    import os
    import time
    wrapper._state_write("session:old", CONTEXT)
    old = next(state.glob("*.json"))
    ancient = time.time() - wrapper._STATE_TTL_SECONDS - 60
    os.utime(old, (ancient, ancient))
    wrapper._state_write("session:new", CONTEXT)
    assert not old.exists(), "просроченный контекст должен убираться сам"


def test_full_model_wins_over_the_rough_bot_tep(state, monkeypatch):
    """ТЭП от бота считается на умолчаниях и не должен перекрывать модель.

    Класс жилья, цены и себестоимость в нём не те, что в расчёте: Платон
    отвечал LLCR 1,11x там, где в отчёте 1,62x. Полный расчёт мог лежать в
    памяти соседнего воркера, а грубый ТЭП — в своей, и проверялся раньше.
    """
    wrapper._state_write("session:s-1", CONTEXT)
    wrapper._state_write("chat:42", {"session": "s-1"})
    forget_memory(monkeypatch)
    # Этот воркер сам собирал ТЭП, поэтому он у него в памяти.
    monkeypatch.setattr(wrapper, "_PLATON_TEP_CONTEXT",
                        {42: {**CONTEXT, "origin": "tep", "inputs": {"purchase_price_mln": 0}}})

    session, context = wrapper._resolve_context(42)
    assert session == "s-1", "выбран грубый ТЭП вместо полного расчёта"
    assert context.get("origin") != "tep"
    assert context["inputs"]["purchase_price_mln"] == 700


def test_rough_tep_is_used_only_without_a_full_model(state, monkeypatch):
    forget_memory(monkeypatch)
    monkeypatch.setattr(wrapper, "_PLATON_TEP_CONTEXT", {42: {**CONTEXT, "origin": "tep"}})
    session, context = wrapper._resolve_context(42)
    assert session == ""
    assert context["origin"] == "tep"


def test_arriving_model_retires_the_rough_tep(state, monkeypatch):
    """Иначе устаревший ТЭП всплывёт, когда ссылка на сессию потеряется."""
    wrapper._state_write("chat:42", {"tep_context": {**CONTEXT, "origin": "tep"}})
    monkeypatch.setattr(wrapper, "_PLATON_TEP_CONTEXT", {42: {**CONTEXT, "origin": "tep"}})
    monkeypatch.setattr(wrapper.core, "_telegram_verify_session", lambda s: {"chat_id": 42})
    monkeypatch.setattr(wrapper.core, "_telegram_user_allowed", lambda c: True)

    request = wrapper.TelegramContextRequest(
        session="s-1", inputs={"purchase_price_mln": 700}, tep={},
        rates=[], phasing={}, selected_view="all")
    wrapper.save_telegram_context(request)

    assert 42 not in wrapper._PLATON_TEP_CONTEXT
    assert "tep_context" not in wrapper._state_read("chat:42")


def deliver_context(monkeypatch, session: str = "s-1", price: float = 700) -> None:
    monkeypatch.setattr(wrapper.core, "_telegram_verify_session", lambda s: {"chat_id": 42})
    monkeypatch.setattr(wrapper.core, "_telegram_user_allowed", lambda c: True)
    wrapper.save_telegram_context(wrapper.TelegramContextRequest(
        session=session, inputs={"purchase_price_mln": price}, tep={},
        rates=[], phasing={}, selected_view="all"))


def test_result_card_button_does_not_hide_the_delivered_model(state, monkeypatch):
    """Карточка результата уводила Платона на сессию, у которой контекста нет.

    Мини-приложение сдаёт расчёт под своим токеном, а бот тут же присылает
    карточку с кнопкой «Открыть и изменить расчёт» — её сессия подписывается
    заново и всегда другая. Пока адрес кнопки перезаписывал указатель чата,
    следующий же вопрос получал ответ «Платону пока не передан проект».
    """
    deliver_context(monkeypatch)
    wrapper._remember_markup(42, {"inline_keyboard": [[{
        "text": "Открыть и изменить расчёт",
        "web_app": {"url": "https://example.org/?telegram=1#telegram_session=s-2-fresh&mode=edit"},
    }]]})

    session, context = wrapper._resolve_context(42)
    assert session == "s-1", "указатель чата уехал на сессию кнопки"
    assert context["inputs"]["purchase_price_mln"] == 700
    assert wrapper._PLATON_LAST_URL[42].endswith("mode=edit"), "адрес кнопки запомнить всё же надо"


def test_delivered_model_is_found_by_chat_when_the_session_is_lost(state, monkeypatch):
    """Токен живёт одно сообщение, чат — величина постоянная."""
    deliver_context(monkeypatch)
    forget_memory(monkeypatch)
    pointer = wrapper._state_read("chat:42")
    pointer.pop("session")
    wrapper._state_write("chat:42", pointer)

    _, context = wrapper._resolve_context(42)
    assert context["inputs"]["purchase_price_mln"] == 700


def test_a_new_calculation_replaces_the_previous_one(state, monkeypatch):
    deliver_context(monkeypatch, "s-1", 700)
    deliver_context(monkeypatch, "s-2", 950)
    forget_memory(monkeypatch)

    session, context = wrapper._resolve_context(42)
    assert session == "s-2"
    assert context["inputs"]["purchase_price_mln"] == 950


def test_status_tells_a_broken_disk_from_a_missing_calculation(state, monkeypatch):
    """«Проект не передан» выглядит одинаково при разных причинах — /status их различает."""
    assert "ещё не приходил" in wrapper._state_health(42)

    deliver_context(monkeypatch)
    assert "полный расчёт" in wrapper._state_health(42)

    monkeypatch.setattr(wrapper, "_STATE_DIR", state / "нет" / "\0такого")
    assert "диск недоступен" in wrapper._state_health(42)


def test_an_open_dialog_switches_to_the_recalculated_model(state, monkeypatch):
    """Человек переделал вводные, не закрывая диалог, — отвечать надо по новым."""
    deliver_context(monkeypatch, "s-1", 700)
    monkeypatch.setattr(wrapper, "_PLATON_MODE", {42: "s-1"})
    deliver_context(monkeypatch, "s-2", 950)

    session, context = wrapper._resolve_context(42)
    assert session == "s-2"
    assert context["inputs"]["purchase_price_mln"] == 950


PROPOSAL = {
    "title": "СМР, тыс ₽/м² ГНС: 135.0 → 150.0",
    "patch": {"construction_cost_th_per_sqm": 150.0},
    "changes": [{"variable": "construction_cost_th_per_sqm",
                 "label": "СМР, тыс ₽/м² ГНС", "old": 135.0, "new": 150.0}],
}


def arm_proposal(monkeypatch, session: str = "s-1") -> None:
    monkeypatch.setattr(wrapper, "_PLATON_PENDING",
                        {42: {"session": session, "proposal": PROPOSAL}})


def test_applied_message_names_what_changed(state, monkeypatch):
    """«Применены к новой ссылке» не говорит ни что применено, ни на что."""
    deliver_context(monkeypatch)
    arm_proposal(monkeypatch)
    monkeypatch.setattr(wrapper.core, "_telegram_web_app_url",
                        lambda *a, **k: "https://example.org/#telegram_session=s-new&mode=edit")

    text = wrapper._applied_message(wrapper._apply_proposal(42))
    assert "СМР" in text and "135,00" in text and "150,00" in text
    assert "Открыть текущую модель" in text, "человеку не сказано, где новая ссылка"


def test_a_broken_link_is_not_reported_as_success(state, monkeypatch):
    """Ссылка не пересобралась — раньше бот всё равно рапортовал успех."""
    deliver_context(monkeypatch)
    arm_proposal(monkeypatch)

    def refuse(*a, **k):
        raise RuntimeError("Ручной ТЭП слишком велик для Telegram-сессии")
    monkeypatch.setattr(wrapper.core, "_telegram_web_app_url", refuse)

    applied = wrapper._apply_proposal(42)
    assert applied["error"], "отказ пересобрать ссылку потерялся"
    text = wrapper._applied_message(applied)
    assert "прежний расчёт" in text
    assert "Изменения применены." not in text


def test_the_model_link_survives_a_worker_switch(state, monkeypatch):
    """Адрес модели жил в памяти одного воркера — у соседа кнопка пропадала."""
    url = "https://example.org/#telegram_session=s-new&mode=edit"
    wrapper._remember_markup(42, {"inline_keyboard": [[
        {"text": "Открыть и изменить расчёт", "web_app": {"url": url}}]]})
    forget_memory(monkeypatch)
    monkeypatch.setattr(wrapper, "_PLATON_LAST_URL", {})

    markup = wrapper._platon_markup(42)
    buttons = [b for row in markup["inline_keyboard"] for b in row if b.get("web_app")]
    assert buttons and buttons[0]["web_app"]["url"] == url


def test_a_stale_proposal_says_so(state, monkeypatch):
    assert "устарело" in wrapper._applied_message(wrapper._apply_proposal(42))

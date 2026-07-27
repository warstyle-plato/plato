"""Тесты комментария Платона к ТЭП в Telegram-боте (обёртка main.py).

Сеть не используется: Telegram API и вызов OpenAI подменяются.
Расчёт при этом выполняется настоящим движком модели.
Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")

import main as wrapper  # noqa: E402

core = wrapper.core

CHAT_ID = 4242


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    for store in (
        wrapper._PLATON_TEP_CONTEXT,
        wrapper._PLATON_CONTEXT_BY_SESSION,
        wrapper._PLATON_MODE,
        wrapper._PLATON_HISTORY,
        wrapper._PLATON_PENDING,
        wrapper._PLATON_LAST_SESSION,
        wrapper._PLATON_LAST_URL,
    ):
        store.clear()
    wrapper._TEP_REVIEW_CHATS.clear()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(core, "_telegram_api", lambda method, payload=None: {"ok": True})
    yield


@pytest.fixture
def sent(monkeypatch):
    """Перехват исходящих сообщений Telegram."""
    messages: list[dict] = []

    def fake_send(chat_id, text, *, reply_markup=None, **kwargs):
        messages.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return {"ok": True}

    monkeypatch.setattr(wrapper, "_ORIGINAL_SEND_MESSAGE", fake_send)
    return messages


def parsed_tep() -> dict:
    return core.build_freeform_tep("", raw_values={
        "project_name": "Тестовый квартал",
        "site_area_ha": 4.5,
        "apartments_saleable_sqm": 60000,
        "commercial_saleable_sqm": 4000,
    })


def callbacks(reply_markup) -> list[str]:
    rows = (reply_markup or {}).get("inline_keyboard") or []
    return [
        button.get("callback_data")
        for row in rows if isinstance(row, list)
        for button in row if isinstance(button, dict) and button.get("callback_data")
    ]


def fake_agent(answer: str = "Разбор ТЭП: площади сбалансированы.", proposals=None):
    """Подмена только вызова OpenAI — модель при этом считается по-настоящему."""
    captured: dict = {}

    def _call(req, bundle):
        captured["message"] = req.message
        captured["inputs"] = req.inputs
        captured["tep"] = req.tep
        captured["bundle"] = bundle
        return {"answer": answer, "proposals": proposals or []}

    return _call, captured


# --- контекст ТЭП -----------------------------------------------------------

def test_tep_review_stores_full_model_context(sent):
    core._telegram_send_tep_review(CHAT_ID, parsed_tep(), dialog_mode=False)
    context = wrapper._PLATON_TEP_CONTEXT[CHAT_ID]
    assert context["origin"] == "tep"
    # частичный ТЭП бота развёрнут до полного набора вводных и продуктов модели
    assert set(core.DEFAULT_INPUTS).issubset(set(context["inputs"]))
    assert set(core.TEP_DEFAULT).issubset(set(context["tep"]))
    assert context["tep"]["apartments"]["saleable"] == pytest.approx(60000, rel=1e-6)
    assert context["project_name"] == "Тестовый квартал"


def test_tep_review_card_offers_platon_buttons(sent):
    core._telegram_send_tep_review(CHAT_ID, parsed_tep(), dialog_mode=False)
    assert sent, "карточка ТЭП не отправлена"
    data = callbacks(sent[-1]["reply_markup"])
    assert "platon_tep" in data
    assert "ask_platon" in data


def test_context_survives_after_review(sent):
    core._telegram_send_tep_review(CHAT_ID, parsed_tep(), dialog_mode=False)
    assert wrapper._TEP_REVIEW_CHATS == set()
    assert wrapper._has_model_context(CHAT_ID) is True


def test_mini_app_context_wins_over_bot_tep(sent, monkeypatch):
    core._telegram_send_tep_review(CHAT_ID, parsed_tep(), dialog_mode=False)
    wrapper._PLATON_LAST_SESSION[CHAT_ID] = "sess-1"
    wrapper._PLATON_CONTEXT_BY_SESSION["sess-1"] = {
        "inputs": dict(core.DEFAULT_INPUTS),
        "tep": dict(core.TEP_DEFAULT),
        "origin": "mini_app",
    }
    session, context = wrapper._resolve_context(CHAT_ID)
    assert session == "sess-1"
    assert wrapper._context_label(context) == "полный расчёт из мини-приложения"


# --- сам комментарий --------------------------------------------------------

def test_comment_runs_real_model_and_answers(sent, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    call, captured = fake_agent()
    monkeypatch.setattr(core, "_call_openai_tool_agent", call)
    core._telegram_send_tep_review(CHAT_ID, parsed_tep(), dialog_mode=False)
    sent.clear()

    wrapper._comment_tep(CHAT_ID)

    texts = [item["text"] for item in sent]
    assert any("разбирает ТЭП" in text for text in texts)
    assert any("Разбор ТЭП" in text for text in texts)
    # запрос ушёл структурированный, а не пустой
    assert "Состав ТЭП" in captured["message"]
    # модель посчиталась настоящим движком: в bundle есть сводные показатели
    summary = captured["bundle"]["consolidated"]["summary"]
    assert summary["revenue"] > 0
    assert summary["net_profit"] != 0
    assert "llcr" in summary


def test_comment_without_context_explains_what_to_do(sent):
    wrapper._comment_tep(CHAT_ID)
    assert "Комментировать пока нечего" in sent[-1]["text"]


def test_comment_without_api_key_reports_clearly(sent, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    core._telegram_send_tep_review(CHAT_ID, parsed_tep(), dialog_mode=False)
    sent.clear()
    wrapper._comment_tep(CHAT_ID)
    assert any("OPENAI_API_KEY" in item["text"] for item in sent)


def test_long_answer_is_chunked(sent, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    call, _ = fake_agent(answer="я" * 9000)
    monkeypatch.setattr(core, "_call_openai_tool_agent", call)
    core._telegram_send_tep_review(CHAT_ID, parsed_tep(), dialog_mode=False)
    sent.clear()
    wrapper._comment_tep(CHAT_ID)
    body = [item for item in sent if "разбирает ТЭП" not in item["text"]]
    assert len(body) >= 3
    assert all(len(item["text"]) <= 3900 for item in body)


def test_comment_does_not_capture_plain_text_flow(sent, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    call, _ = fake_agent()
    monkeypatch.setattr(core, "_call_openai_tool_agent", call)
    core._telegram_send_tep_review(CHAT_ID, parsed_tep(), dialog_mode=False)
    wrapper._comment_tep(CHAT_ID)
    # обычный текст после разбора по-прежнему идёт в основной сценарий бота
    assert CHAT_ID not in wrapper._PLATON_MODE

    routed: list[str] = []
    monkeypatch.setattr(wrapper, "_ORIGINAL_HANDLE_MESSAGE", lambda message: routed.append("core"))
    wrapper._handle_message({"chat": {"id": CHAT_ID}, "from": {"id": CHAT_ID}, "text": "77:01:0001001:1"})
    assert routed == ["core"]


# --- диалог и применение правок --------------------------------------------

def test_ask_platon_works_on_bot_tep(sent):
    core._telegram_send_tep_review(CHAT_ID, parsed_tep(), dialog_mode=False)
    sent.clear()
    wrapper._start_platon(CHAT_ID)
    assert "Платон Сергеевич на связи" in sent[0]["text"]
    assert "ТЭП, собранный ботом" in sent[0]["text"]
    assert CHAT_ID in wrapper._PLATON_MODE


def test_ask_platon_without_project_explains(sent):
    wrapper._start_platon(CHAT_ID)
    assert "не передан проект" in sent[-1]["text"]


def test_proposal_applies_to_bot_tep_context(sent, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    call, _ = fake_agent(proposals=[{"patch": {"purchase_price_mln": 1234.0}}])
    monkeypatch.setattr(core, "_call_openai_tool_agent", call)
    core._telegram_send_tep_review(CHAT_ID, parsed_tep(), dialog_mode=False)
    wrapper._comment_tep(CHAT_ID)

    assert wrapper._PLATON_PENDING[CHAT_ID]["proposal"]["patch"]["purchase_price_mln"] == 1234.0
    assert wrapper._apply_proposal(CHAT_ID) is True
    assert wrapper._PLATON_TEP_CONTEXT[CHAT_ID]["inputs"]["purchase_price_mln"] == 1234.0
    assert CHAT_ID not in wrapper._PLATON_PENDING
    # ссылка на модель пересобрана с учётом правки
    assert wrapper._PLATON_LAST_URL[CHAT_ID].startswith("http")


def test_apply_without_pending_proposal_is_false():
    assert wrapper._apply_proposal(CHAT_ID) is False


# --- маршрутизация колбэков и команд ----------------------------------------

def test_callback_platon_tep_routes_to_comment(sent, monkeypatch):
    called: list[int] = []
    monkeypatch.setattr(wrapper, "_comment_tep", lambda chat_id: called.append(chat_id))
    wrapper._handle_update({
        "callback_query": {
            "id": "1",
            "data": "platon_tep",
            "from": {"id": CHAT_ID},
            "message": {"chat": {"id": CHAT_ID}},
        }
    })
    assert called == [CHAT_ID]


def test_comment_command_routes_to_comment(sent, monkeypatch):
    called: list[int] = []
    monkeypatch.setattr(wrapper, "_comment_tep", lambda chat_id: called.append(chat_id))
    wrapper._handle_message({"chat": {"id": CHAT_ID}, "from": {"id": CHAT_ID}, "text": "/comment"})
    assert called == [CHAT_ID]


def test_status_reports_context_source(sent):
    core._telegram_send_tep_review(CHAT_ID, parsed_tep(), dialog_mode=False)
    sent.clear()
    wrapper._status_message(CHAT_ID, CHAT_ID)
    assert "ТЭП, собранный ботом" in sent[-1]["text"]
    assert wrapper._RUNTIME_VERSION in sent[-1]["text"]


def test_land_lookup_endpoint_is_available_through_wrapper():
    # федеральный поиск участка из main_legacy.py доступен в собранном приложении
    routes = {getattr(route, "path", "") for route in wrapper.app.routes}
    assert "/land/lookup" in routes
    assert "/land/providers" in routes
    assert "/telegram/context" in routes


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


# --- инструкция бота --------------------------------------------------------

def test_help_explains_all_three_territory_cases(monkeypatch):
    sent = []
    monkeypatch.setattr(wrapper, "_send_message", lambda chat_id, text, **kw: sent.append(text))
    wrapper._send_help(1)
    text = sent[0]
    # Три случая названы и разведены по методикам.
    assert "<b>Москва</b> — считает калькулятор нормативных ТЭП ГлавАПУ" in text
    assert "<b>Московская область</b> — считает формула из нормативных документов" in text
    assert "<b>Другой регион</b> — экспертная оценка" in text
    # Новая Москва объяснена отдельно: кадастр 50:* не означает область.
    assert "Троицкий и Новомосковский" in text
    assert "114-Р" in text
    # Шаги пронумерованы.
    for step in ("Шаг 1", "Шаг 2", "Шаг 3", "Шаг 4", "Шаг 5"):
        assert step in text


def test_help_tells_what_arrives_in_the_archive(monkeypatch):
    sent = []
    monkeypatch.setattr(wrapper, "_send_message", lambda chat_id, text, **kw: sent.append(text))
    wrapper._send_help(1)
    text = sent[0]
    assert "00_Модель" in text and "90_Детализация" in text
    assert "правка вводной пересчитывает весь расчёт" in text


def test_short_help_names_the_three_cases():
    """Кнопка «Что умеет DevelopAid» тоже разводит три случая."""
    source = (Path(__file__).resolve().parent.parent / "main_legacy.py").read_text(encoding="utf-8")
    assert "нормативные ТЭП" in source and "калькулятору ГлавАПУ" in source
    assert "Московская область" in source and "114-Р" in source
    assert "другой регион" in source and "экспертно" in source
    assert "команда /help" in source

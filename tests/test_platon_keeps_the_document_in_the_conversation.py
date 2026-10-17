"""Документ, присланный Платону на разбор, остаётся в разговоре.

Владелец: «если Платону сгружаешь тизер для разбора, он не ведёт дальше диалог
в контексте». Разбор шёл отдельным путём: на сайте документ и ответ разбора в
`aiHistory` не попадали, и следующий вопрос («а какая там IRR?») уходил в
`/agent/chat` без них. В Telegram разбор в историю не писался вовсе, а сама
история жила в памяти воркера — при двух воркерах следующее сообщение
попадало в соседний процесс, где разговора не было.

Теперь документ — `document_intake.chat_context` — один для сайта и бота:
окно шлёт его рядом с историей в каждом вопросе, бот хранит его вместе с
историей на диске по chat_id. Новая загрузка заменяет прежний документ.

Запуск: python3 -m pytest tests/test_platon_keeps_the_document_in_the_conversation.py -q
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

from browser import chromium_or_skip

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import document_intake  # noqa: E402
import main as wrapper  # noqa: E402

core = wrapper.core
CHAT_ID = 5151
PORT = 18241
TEXT = ("Тизер участка «Южное Медведково». IRR проекта 23,4%. "
        "ВРИ участка: многоэтажная жилая застройка (2.6). Цена входа 1 650 000 000 ₽.")
EXTRACTION = {"fields": [{"key": "purchase_price_mln", "value": "1 650 000 000",
                          "unit": "₽", "quote": "Цена входа 1 650 000 000 ₽"}],
              "questions": [], "notes": ["IRR в тизере — оценка продавца"]}


# --- общий источник ----------------------------------------------------------

def test_the_context_carries_fields_quotes_and_text_within_a_limit() -> None:
    long_text = TEXT + " хвост" * 20_000
    got = document_intake.chat_context({"text": long_text, "filename": "t.pdf", "pages": 3},
                                        EXTRACTION)
    assert got["filename"] == "t.pdf"
    assert "Цена входа 1 650 000 000 ₽" in got["text"], "цитата поля не в разговоре"
    assert "IRR проекта 23,4%" in got["text"], "текст документа не в разговоре"
    assert len(got["text"]) <= document_intake.DOCUMENT_CONTEXT_BUDGET + 50
    assert got["trimmed"] is True and got["total_chars"] == len(long_text)
    prompt = document_intake.context_prompt(got)
    assert "ДОКУМЕНТ В КОНТЕКСТЕ" in prompt and "t.pdf" in prompt
    assert "первые" in prompt, "обрезка документа не названа"
    # Пустой документ в разговор не кладётся, и подложенный страницей не
    # раздувает вопрос мимо предела.
    assert document_intake.chat_context({"text": "  "}, EXTRACTION) == {}
    assert len(document_intake.context_prompt({"text": "x" * 100_000})) < (
        document_intake.DOCUMENT_CONTEXT_BUDGET + 1_000)


def test_the_model_sees_the_document_next_to_the_history(monkeypatch) -> None:
    """Документ доходит до входа модели, а не только до тела запроса."""
    seen: dict[str, Any] = {}

    def fake_request(payload, **_kw):
        seen["input"] = payload.get("input")
        return {"id": "r1", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": "IRR 23,4% — по тизеру."}]}]}

    monkeypatch.setattr(core, "_openai_responses_request", fake_request)
    context = document_intake.chat_context({"text": TEXT, "filename": "teaser.pdf"}, EXTRACTION)
    req = core.AgentChatRequest(message="а какая там IRR?", inputs=dict(core.DEFAULT_INPUTS),
                                tep={k: dict(v) for k, v in core.TEP_DEFAULT.items()},
                                document=context)
    bundle = core._run_authoritative_model(req.inputs, req.tep, req.rates, req.phasing)
    core._call_openai_tool_agent(req, bundle)
    said = json.dumps(seen.get("input"), ensure_ascii=False)
    assert "IRR проекта 23,4%" in said, "модель не видит документ"
    assert "ДОКУМЕНТ В КОНТЕКСТЕ" in said


# --- Telegram: два воркера ---------------------------------------------------

def _forget_process_memory() -> None:
    """Другой воркер: памяти первого процесса у него нет, диск общий."""
    for store in (wrapper._PLATON_MODE, wrapper._PLATON_LAST_SESSION,
                  wrapper._PLATON_CONTEXT_BY_SESSION, wrapper._PLATON_TEP_CONTEXT,
                  wrapper._PLATON_PENDING, wrapper._PLATON_LAST_URL):
        store.clear()
    core._TELEGRAM_DIALOGS.clear()


def _message(text: str) -> dict[str, Any]:
    return {"chat": {"id": CHAT_ID, "type": "private"}, "from": {"id": CHAT_ID}, "text": text}


def test_the_bot_answers_the_next_question_by_the_document_in_another_worker(monkeypatch) -> None:
    sent: list[str] = []
    asked: list[Any] = []
    monkeypatch.setattr(core, "_telegram_api", lambda *_a, **_k: {"ok": True})
    monkeypatch.setattr(wrapper, "_send_message", lambda _chat, text, **_k: sent.append(text))
    monkeypatch.setattr(core, "_telegram_send_message", lambda _chat, text, **_k: sent.append(text))
    monkeypatch.setattr(core, "usage_track", lambda *_a, **_k: None)
    monkeypatch.setattr(wrapper, "_user_to_core", lambda *_a, **_k: None)
    monkeypatch.setattr(wrapper, "_agent_ready", lambda: True)
    monkeypatch.setattr(document_intake, "extract_text",
                        lambda _data, name: {"text": TEXT, "pages": 2, "filename": name})

    def fake_answer(req, _request):
        if req.scenario == "document_intake":
            return {"answer": json.dumps(EXTRACTION, ensure_ascii=False)}
        asked.append(req)
        return {"answer": f"ответ {len(asked)}"}

    monkeypatch.setattr(core, "plato_answer", fake_answer)

    core._telegram_handle_intake_document(CHAT_ID, b"%PDF stub", "teaser.pdf")
    assert any("Документ в разговоре" in text for text in sent), sent

    _forget_process_memory()
    wrapper._handle_message(_message("а какая там IRR?"))
    assert asked, f"вопрос по документу не дошёл до Платона: {sent[-2:]}"
    first = asked[-1]
    assert first.document.get("filename") == "teaser.pdf", "документ потерян между воркерами"
    assert "IRR проекта 23,4%" in first.document.get("text", "")
    assert any("Разобрал документ «teaser.pdf»" in item["content"] for item in first.history), (
        first.history)

    _forget_process_memory()
    wrapper._handle_message(_message("что с ВРИ?"))
    second = asked[-1]
    contents = [item["content"] for item in second.history]
    assert "а какая там IRR?" in contents and "ответ 1" in contents, (
        f"история не пережила переход между воркерами: {contents}")
    assert second.document.get("filename") == "teaser.pdf"

    # Новая загрузка заменяет прежний документ.
    core._telegram_handle_intake_document(CHAT_ID, b"%PDF stub", "второй.pdf")
    assert wrapper._platon_memory(CHAT_ID)["document"]["filename"] == "второй.pdf"


def test_a_lost_history_is_said_aloud(monkeypatch) -> None:
    """Не сохранилось — человек читает причину, а не забывчивость Платона."""
    sent: list[str] = []
    monkeypatch.setattr(core, "_telegram_send_message", lambda _chat, text, **_k: sent.append(text))
    monkeypatch.setattr(core, "usage_track", lambda *_a, **_k: None)
    monkeypatch.setattr(document_intake, "extract_text",
                        lambda _data, name: {"text": TEXT, "pages": 1, "filename": name})
    monkeypatch.setattr(core, "plato_answer",
                        lambda *_a: {"answer": json.dumps(EXTRACTION, ensure_ascii=False)})
    monkeypatch.setattr(wrapper, "_state_write", lambda *_a: "OSError: диск только для чтения")
    core._telegram_handle_intake_document(CHAT_ID, b"%PDF stub", "teaser.pdf")
    assert any("не попал" in text and "только для чтения" in text for text in sent), sent


# --- сайт: живая страница ----------------------------------------------------

def test_on_the_page_the_next_question_carries_the_document() -> None:
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(wrapper.app, host="127.0.0.1", port=PORT,
                                           log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started

    # Ответ разбора — тем же источником, что у маршрута: копия формата здесь
    # разошлась бы с ним.
    context = document_intake.chat_context({"text": TEXT, "filename": "teaser.pdf", "pages": 2},
                                           EXTRACTION)
    intake = {"document": {"filename": "teaser.pdf", "pages": 2}, **EXTRACTION,
              "context": context}
    bodies: list[dict[str, Any]] = []

    def on_chat(route):
        bodies.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"answer": f"ответ {len(bodies)}"}))

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chrome))
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.route("**/agent/document", lambda route: route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(intake, ensure_ascii=False)))
            page.route("**/agent/chat", on_chat)
            page.goto(f"http://127.0.0.1:{PORT}/", wait_until="networkidle")
            page.set_input_files("#aiFile", files=[{"name": "teaser.pdf",
                                                    "mimeType": "application/pdf",
                                                    "buffer": b"%PDF-1.4 stub"}])
            page.wait_for_function("() => !aiBusy && aiIntake !== null", timeout=10_000)
            said = page.evaluate("() => document.getElementById('aiMessages').innerText")
            # Пересчёт страницы между вопросами не должен терять разговор.
            page.evaluate("() => calculate()")
            page.wait_for_timeout(800)
            page.evaluate("() => askAgentQuick('а какая там IRR?')")
            page.wait_for_function("() => !aiBusy", timeout=10_000)
            page.evaluate("() => askAgentQuick('что с ВРИ?')")
            page.wait_for_function("() => !aiBusy", timeout=10_000)
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert not errors, errors
    assert "Документ «teaser.pdf» в разговоре" in said, said
    assert len(bodies) == 2, bodies
    first, second = bodies
    assert first["document"].get("filename") == "teaser.pdf", "вопрос ушёл без документа"
    assert "IRR проекта 23,4%" in first["document"].get("text", "")
    history = [item["content"] for item in first["history"]]
    assert any("Разобрал документ «teaser.pdf»" in item for item in history), history
    assert second["document"].get("filename") == "teaser.pdf", "документ выпал после первого ответа"
    assert "ответ 1" in [item["content"] for item in second["history"]]

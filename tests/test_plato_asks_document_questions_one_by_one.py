"""Платон разбирает документ и спрашивает по одному, а ответ ложится в модель.

Владелец 18.10.2026 (developaid.ru, телефон): после «Приложить документ»
Платон вывалил все уточняющие вопросы одним списком, каждый со своими
вариантами, и «реальной передачи данных в движок не происходит. Даже кадастр в
итоге не лёг во вкладку «Проект»». Варианты были подписями, а не кнопками, и
ответить было некуда; «Применить отмеченное» на кадастре отвечало «участок
применяется отдельным запросом ЕГРН», а запроса никто не делал.

Теперь: очередь вопросов на диске (воркеров два), на экране один вопрос с
вариантами-кнопками, ответ применяется к полю модели с происхождением «из
документа», затем следующий вопрос. Кадастровый номер — в поле участка.

Запуск: python3 -m pytest tests/test_plato_asks_document_questions_one_by_one.py -q
"""

from __future__ import annotations

import base64
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from browser import chromium_or_skip  # noqa: E402

import document_intake  # noqa: E402
import main as wrapper  # noqa: E402

core = wrapper.core
PORT = 18287
NUMBER = "77:08:0010008:1049"

# Ответ модели — как на скриншоте владельца: вопросы с вариантами строками,
# число стоит в хвосте подписи после тире.
EXTRACTION = {
    "fields": [{"key": "cadastral_numbers", "value": [NUMBER], "unit": "список",
                "quote": f"здание 2863,7 кв.м (кад. {NUMBER})"}],
    "questions": [
        {"key": "demolition_area_sqm",
         "question": f"Существующее нежилое здание 2863,7 кв.м (кад. {NUMBER}) подлежит сносу?",
         "options": ["Снос всего здания — 2863,7 м²", "Снос не предполагается / иная площадь"]},
        {"key": "resettlement_cost_mln",
         "question": "Требуется ли расселение/освобождение объекта от прав третьих лиц?",
         "options": ["Расселение не требуется — 0", "Требуется, сумма по оценке"]},
        {"key": "",
         "question": "Обязательства перед городом (КБО: школа 47 мест, ДОО 23 места) — куда отнести их цену?",
         "options": ["В цену сделки — платится на входе", "В соцнагрузку — идёт своей датой"]},
    ],
    "notes": [],
}


def _stub_model(monkeypatch) -> None:
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    monkeypatch.setattr(core, "usage_track", lambda *_a, **_k: None)
    monkeypatch.setattr(document_intake, "extract_text",
                        lambda _data, name: {"text": "Тизер. Народного 29.", "pages": 1,
                                             "filename": name})
    monkeypatch.setattr(core, "plato_answer",
                        lambda *_a: {"answer": json.dumps(EXTRACTION, ensure_ascii=False)})


def _parse(monkeypatch) -> dict:
    _stub_model(monkeypatch)
    return core.agent_document(core.AgentDocumentRequest(
        filename="teaser.pdf", content_b64=base64.b64encode(b"%PDF stub").decode()), None)


def _answer(queue: dict, index: int, **kw) -> dict:
    return core.agent_document_answer(core.AgentDocumentAnswerRequest(
        intake_id=queue["id"], index=index, inputs={"demolition_area_sqm": 0}, tep={}, **kw))


# --- сервер: очередь на диске, ответ ложится в поле --------------------------

def test_the_parse_opens_a_queue_with_one_question(monkeypatch) -> None:
    got = _parse(monkeypatch)
    queue = got["queue"]
    assert queue["total"] == 3 and queue["index"] == 0
    assert queue["card"]["question"].startswith("Существующее нежилое здание")
    # Очередь — на диске, а не в памяти воркера.
    assert list(core._PLATO_STAGE_DIR.glob(f"intake_{queue['id']}.json"))


def test_an_answer_lands_in_the_field_and_the_next_question_follows(monkeypatch) -> None:
    queue = _parse(monkeypatch)["queue"]
    got = _answer(queue, 0, choice=0)
    assert [(a["key"], a["now"]) for a in got["applied"]] == [("demolition_area_sqm", 2863.7)]
    assert got["inputs"]["demolition_area_sqm"] == 2863.7
    assert got["queue"]["index"] == 1
    assert got["queue"]["card"]["question"].startswith("Требуется ли расселение")

    zero = _answer(queue, 1, choice=0)
    assert zero["inputs"]["resettlement_cost_mln"] == 0.0, "«не требуется — 0» не легло нулём"

    # Обязательство: вариант называет поле, но не сумму — не применено, и
    # причина названа; ответ всё равно записан.
    kbo = _answer(queue, 2, choice=1)
    assert not kbo["applied"]
    assert "нет числа" in kbo["refused"][0]["reason"]
    assert kbo["queue"]["card"] is None
    assert [a["answer"] for a in kbo["queue"]["answers"]][0] == "Снос всего здания — 2863,7 м²"


def test_a_typed_sum_for_the_obligation_lands_in_its_field(monkeypatch) -> None:
    queue = _parse(monkeypatch)["queue"]
    _answer(queue, 0, action="skip")
    _answer(queue, 1, action="skip")
    got = _answer(queue, 2, choice=1, value="120 млн")
    assert [(a["key"], a["now"]) for a in got["applied"]] == [("social_compensation_mln", 120.0)]


def test_a_repeated_click_does_not_answer_the_next_question(monkeypatch) -> None:
    queue = _parse(monkeypatch)["queue"]
    _answer(queue, 0, choice=0)
    again = _answer(queue, 0, choice=0)
    assert again["stale"] is True and again["queue"]["index"] == 1
    assert not again["applied"]


def test_the_cadastral_number_is_applied_to_the_site_not_just_noted() -> None:
    got = document_intake.apply_intake(EXTRACTION, {}, {}, accept=["cadastral_numbers"])
    row = got["applied"][0]
    assert row["target"] == "land" and row["value"] == [NUMBER]


# --- страница: что видит человек ---------------------------------------------

def test_on_the_page_one_question_at_a_time_and_the_number_reaches_the_site(monkeypatch) -> None:
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright
    import uvicorn

    _stub_model(monkeypatch)
    server = uvicorn.Server(uvicorn.Config(wrapper.app, host="127.0.0.1", port=PORT,
                                           log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chrome))
            page = browser.new_page(viewport={"width": 390, "height": 844})
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(f"http://127.0.0.1:{PORT}/", wait_until="networkidle")
            page.evaluate("() => toggleAgent(true)")
            page.wait_for_timeout(400)
            page.set_input_files("#aiFile", files=[{"name": "teaser.pdf",
                                                    "mimeType": "application/pdf",
                                                    "buffer": b"%PDF-1.4 stub"}])
            page.wait_for_function("() => !aiBusy && aiIntake !== null", timeout=10_000)
            first = page.evaluate("() => document.getElementById('aiMessages').innerText")
            cards_before = page.locator(".ai-question").count()
            # Старое окно печатало все вопросы подряд и кнопок не давало:
            # падаем здесь, своим утверждением, а не на ожидании кнопки.
            assert cards_before == 1, "на экране не один вопрос"
            assert "Требуется ли расселение" not in first, \
                "второй вопрос показан до ответа на первый"

            page.locator(".ai-question").last.get_by_role(
                "button", name="Снос всего здания — 2863,7 м²").click()
            page.wait_for_function(
                "() => !aiBusy && document.querySelectorAll('.ai-question').length===2",
                timeout=10_000)
            demolition = page.evaluate("() => inputs.demolition_area_sqm")
            origin = page.evaluate("() => (inputs._field_origin||{})['inputs.demolition_area_sqm']")
            second = page.evaluate(
                "() => [...document.querySelectorAll('.ai-question')].pop().innerText")

            page.locator(".ai-question").last.get_by_text("Пропустить").click()
            page.wait_for_function(
                "() => !aiBusy && document.querySelectorAll('.ai-question').length===3",
                timeout=10_000)
            third = page.evaluate(
                "() => [...document.querySelectorAll('.ai-question')].pop().innerText")

            page.evaluate("() => applyAiIntake()")
            page.wait_for_function("() => (inputs._cadastral_query||'').length>0",
                                   timeout=10_000)
            field = page.evaluate("() => document.getElementById('cadastralNumbers').value")
            cad_origin = page.evaluate("() => inputs._cadastral_origin")
            cad_note = page.evaluate(
                "() => (document.getElementById('cadastralOrigin')||{}).textContent||''")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert not errors, errors
    assert "Существующее нежилое здание" in first
    assert "Вопрос 1 из 3" in first
    assert demolition == 2863.7, "ответ не лёг в поле расчёта"
    assert origin and origin["source"] == "document", origin
    assert "Требуется ли расселение" in second and "Вопрос 2 из 3" in second
    assert "Вопрос 3 из 3" in third, "«Пропустить» не перевёл к следующему вопросу"
    assert field == NUMBER, "кадастровый номер из документа не лёг в поле участка"
    assert cad_origin["source"] == "document", cad_origin
    assert "teaser.pdf" in cad_note

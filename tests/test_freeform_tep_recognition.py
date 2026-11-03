"""Свободный ТЭП: образец бота разбирается всегда, сбой модели назван причиной.

Бот на любой текст ТЭП, включая собственный образец из подсказки, отвечал
«Не хватает исходных данных. Не удалось разобрать распознанные показатели».
Reasoning-модель тратила потолок в 1800 токенов на размышление и не дописывала
JSON, а обрыв читался как «не разобрали»; ответ Anthropic шёл без схемы вовсе.
Теперь простая запись разбирается без модели, обрыв повторяется один раз с
большим бюджетом, а отказ называет причину и место.

Запуск: python3 -m pytest tests/test_freeform_tep_recognition.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
import plato_provider  # noqa: E402

OWNER_TEXT = "Участок 2.4 га квартиры 42000 коммерция 2500"


def _no_network(payload, budget_seconds=None):
    raise AssertionError("простая запись не должна ходить в модель")


def _answer(status="completed", text="", reason=""):
    response = {"status": status, "output": [
        {"type": "message", "content": [{"type": "output_text", "text": text}]}]}
    if reason:
        response["incomplete_details"] = {"reason": reason}
    return response


def _model_values(**values):
    raw = {key: None for key in core._freeform_tep_schema()["properties"]}
    raw.update({"project_name": "", "district": ""})
    raw.update(values)
    return raw


@pytest.mark.parametrize("text", [core.FREEFORM_TEP_EXAMPLE, OWNER_TEXT])
def test_the_bot_example_is_recognized_without_the_model(monkeypatch, text):
    monkeypatch.setattr(core, "_openai_responses_request", _no_network)
    raw = core._recognize_freeform_tep_text(text)
    assert raw["site_area_ha"] == pytest.approx(2.4)
    assert raw["apartments_saleable_sqm"] == pytest.approx(42000)
    assert raw["commercial_saleable_sqm"] == pytest.approx(2500)
    tep = core.build_freeform_tep(text)
    assert tep["site_area_ha"] == pytest.approx(2.4)
    assert tep["summary"]["apartment_saleable_sqm"] == pytest.approx(42000)


def test_thousands_are_scaled():
    raw = core._simple_freeform_tep("Участок 3 га. Квартиры 42 тыс. м²")
    assert raw["apartments_saleable_sqm"] == pytest.approx(42000)


@pytest.mark.parametrize("text", [
    "Проект Северный. Участок 2,4 га. Квартиры 42 000 м².",
    "Участок 2,4 га. Квартиры 42 000 м². Подземный паркинг 620 мест.",
    "Участок 2,4 га. ГНС квартир 42 000 м².",
    "Участок 2,4 га. Квартиры 42,000 м².",
    "Квартиры 42 000 м²",
])
def test_anything_beyond_the_simple_record_goes_to_the_model(text):
    """Сказанное сверх трёх строк не теряется молча: такую запись читает модель."""
    assert core._simple_freeform_tep(text) is None


def test_the_bot_hint_prints_the_same_example(monkeypatch):
    sent = []
    monkeypatch.setattr(core, "_telegram_send_message",
                        lambda chat_id, text, **k: sent.append(text) or {"ok": True})

    def fail(text):
        raise ValueError("Укажите площадь территории в гектарах")

    monkeypatch.setattr(core, "build_freeform_tep", fail)
    core._telegram_handle_freeform_tep(1, "что-то")
    assert "Не хватает исходных данных." in sent[0]
    assert f"<code>{core.html.escape(core.FREEFORM_TEP_EXAMPLE)}</code>" in sent[0]


def test_a_recognition_failure_is_not_called_missing_data(monkeypatch):
    sent = []
    monkeypatch.setattr(core, "_telegram_send_message",
                        lambda chat_id, text, **k: sent.append(text) or {"ok": True})

    def fail(text):
        raise core.FreeformTepRecognitionError("Модель оборвала ответ")

    monkeypatch.setattr(core, "build_freeform_tep", fail)
    core._telegram_handle_freeform_tep(1, "что-то")
    assert "Не удалось распознать текст." in sent[0]
    assert "Не хватает исходных данных" not in sent[0]


COMPLEX = "Участок 2,4 га. Квартиры 42 000 м². Подземный паркинг 620 мест."


def test_a_cut_answer_is_retried_once_with_a_bigger_budget(monkeypatch):
    calls = []

    def model(payload, budget_seconds=None):
        calls.append(payload["max_output_tokens"])
        if len(calls) == 1:
            return _answer("incomplete", '{"site_area_ha": 2.4, "apart', "max_output_tokens")
        return _answer(text=json.dumps(_model_values(site_area_ha=2.4, parking_spaces=620)))

    monkeypatch.setattr(core, "_openai_responses_request", model)
    raw = core._recognize_freeform_tep_text(COMPLEX)
    assert raw["parking_spaces"] == 620
    assert len(calls) == 2 and calls[1] > calls[0] > 1800


def test_a_cut_answer_names_the_reason(monkeypatch):
    monkeypatch.setattr(core, "_openai_responses_request", lambda payload, budget_seconds=None:
                        _answer("incomplete", '{"site_area_ha": 2.4, "apart', "max_output_tokens"))
    with pytest.raises(core.FreeformTepRecognitionError) as caught:
        core._recognize_freeform_tep_text(COMPLEX)
    message = str(caught.value)
    assert "incomplete: max_output_tokens" in message
    assert "распознавание свободного ТЭП" in message


def test_a_truncated_json_is_called_not_json(monkeypatch):
    monkeypatch.setattr(core, "_openai_responses_request", lambda payload, budget_seconds=None:
                        _answer(text='{"site_area_ha": 2.4, "apart'))
    with pytest.raises(core.FreeformTepRecognitionError, match="не в формате JSON"):
        core._recognize_freeform_tep_text(COMPLEX)


def test_a_fenced_json_answer_is_read(monkeypatch):
    body = json.dumps(_model_values(site_area_ha=2.4, parking_spaces=620))
    monkeypatch.setattr(core, "_openai_responses_request", lambda payload, budget_seconds=None:
                        _answer(text=f"```json\n{body}\n```"))
    assert core._recognize_freeform_tep_text(COMPLEX)["parking_spaces"] == 620


def test_an_unreachable_model_is_named(monkeypatch):
    def down(payload, budget_seconds=None):
        raise core.HTTPException(status_code=502, detail="OpenAI API: timeout")

    monkeypatch.setattr(core, "_openai_responses_request", down)
    with pytest.raises(core.FreeformTepRecognitionError, match="Модель недоступна: OpenAI API: timeout"):
        core._recognize_freeform_tep_text(COMPLEX)


def test_anthropic_gets_the_schema_and_reports_the_cut_the_same_way():
    fmt = plato_provider.format_for_anthropic({"format": {
        "type": "json_schema", "name": "x", "strict": True,
        "schema": core._freeform_tep_schema()}})
    assert fmt["type"] == "json_schema"
    assert "minimum" not in json.dumps(fmt["schema"])
    assert plato_provider.format_for_anthropic(None) is None

    message = SimpleNamespace(id="m", stop_reason="max_tokens",
                              content=[{"type": "text", "text": '{"site_area'}])
    internal = plato_provider.response_to_internal(message, turn_id="t")
    assert core._freeform_tep_incomplete_reason(internal) == "max_output_tokens"

"""Бот разбирает тизер тремя шагами, как сайт: карточка, вопросы, кнопка.

«Бот выплюнул 10 вопросов в одном сообщении, а не один за одним» (владелец,
27.08.2026). Затем (25.10.2026): бот одновременно разбирал и спрашивал, а
ответы оставались текстом — «Это ваши ответы, а не расчёт» — и в движок из
тизера не доходило ничего, кроме номера участка.

Теперь первый шаг — карточка без вопросов; вопросы — кнопкой, по одному,
только о недостающем, и ответ меняет карточку; расчёт — кнопкой «Всё верно,
считать», и мини-приложение получает ровно строки карточки.

Проверки гоняют настоящий обработчик: `_telegram_handle_intake_document`,
`_telegram_handle_update` (кнопки) и `_telegram_handle_dialog_text`.

Запуск: python3 -m pytest tests/test_the_bot_asks_one_question_at_a_time.py -q
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import document_intake  # noqa: E402
import main_legacy as engine  # noqa: E402

CHAT = 777
NUMBER = "77:08:0010008:1049"
TEXT = ("[стр. 1]\nТизер\n\n[стр. 2]\nофисы – 26 300 м2\n\n"
        f"[стр. 4]\nКН {NUMBER}")
EXTRACTION = {
    "fields": [
        {"key": "cadastral_numbers", "value": [NUMBER], "unit": "список", "quote": f"КН {NUMBER}"},
        {"key": "offices_gba_sqm", "value": "26 300", "unit": "м2", "quote": "офисы – 26 300 м2"},
    ],
    "questions": [
        {"key": "", "question": "Платёж 2,55 млрд руб. за SPV — куда отнести?",
         "options": ["В цену сделки — платится на входе", "В соцнагрузку — идёт своей датой"]},
        {"key": "resettlement_cost_mln", "question": "Требуется ли расселение?",
         "options": ["Расселение не требуется — 0", "Требуется"]},
    ],
    "notes": [],
}


class Chat(list):
    """Отправленные сообщения и участки, ушедшие в расчёт."""
    parcels: list[list[str]]


@pytest.fixture()
def bot(monkeypatch, tmp_path):
    sent = Chat()

    def fake_send(chat_id, text, reply_markup=None, **_):
        sent.append({"chat_id": chat_id, "text": text, "markup": reply_markup})
        return {"ok": True}

    monkeypatch.setattr(engine, "_telegram_send_message", fake_send)
    monkeypatch.setattr(engine, "_telegram_api", lambda *_a, **_k: {})
    monkeypatch.setattr(engine, "_PLATO_STAGE_DIR", tmp_path)
    monkeypatch.setattr(engine, "_telegram_token", lambda: "123:test")
    monkeypatch.setattr(engine, "_telegram_agent_request", lambda _chat: None)
    monkeypatch.setattr(engine, "_telegram_allowed_user_ids", lambda: set())
    monkeypatch.setattr(document_intake, "extract_text",
                        lambda _data, name: {"text": TEXT, "pages": 4, "filename": name})
    monkeypatch.setattr(engine, "plato_answer",
                        lambda *_a: {"answer": json.dumps(EXTRACTION, ensure_ascii=False)})
    parcels: list[list[str]] = []
    monkeypatch.setattr(engine, "_telegram_handle_cadastral_numbers",
                        lambda _chat, numbers, *_a: parcels.append(list(numbers)))
    # Москва: регион участка бот решает запросом территории (как для номера,
    # присланного сообщением). В песочнице сети нет — территория московская.
    monkeypatch.setattr(engine, "analyze_cadastral_territory",
                        lambda _req: {"territory": {"inside_moscow": True}})
    engine._telegram_dialog_clear(CHAT)
    sent.parcels = parcels
    return sent


def _press(data: str) -> None:
    engine._telegram_handle_update({"callback_query": {
        "id": "", "data": data, "from": {"id": CHAT},
        "message": {"chat": {"id": CHAT}}}})


def _buttons(message: dict) -> list[dict]:
    return [button for row in ((message.get("markup") or {}).get("inline_keyboard") or [])
            for button in row]


def _session(url: str) -> dict:
    fragment = url.split("#", 1)[1]
    from urllib.parse import parse_qs
    token = parse_qs(fragment)["telegram_session"][0]
    encoded = token.split(".", 1)[0]
    return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))


def test_the_first_message_is_a_card_and_asks_nothing(bot):
    engine._telegram_handle_intake_document(CHAT, b"%PDF", "svetly.pdf")
    card = bot[-1]
    assert "Что найдено в тизере" in card["text"]
    assert "стр. 2" in card["text"] and "стр. 4" in card["text"]
    assert "Что уйдёт в расчёт" in card["text"] and "26 300" in card["text"]
    assert "Чего нет в тизере" in card["text"]
    assert "Вопрос 1" not in card["text"], "первый шаг уже спрашивает"
    assert "offices_gba_sqm" not in card["text"], "в карточке ключ вместо подписи"
    assert [b["callback_data"] for b in _buttons(card)] == ["intake_questions"]
    assert not bot.parcels, "расчёт участка начался без кнопки"


def test_questions_go_one_by_one_and_change_only_the_card(bot):
    engine._telegram_handle_intake_document(CHAT, b"%PDF", "svetly.pdf")
    _press("intake_questions")
    assert "Вопрос 1 из 3" in bot[-1]["text"]
    assert "Вопрос 2" not in bot[-1]["text"]
    _press(_buttons(bot[-1])[0]["callback_data"])  # в цену сделки
    said = "\n".join(m["text"] for m in bot[-2:])
    assert "в карточку" in said and "Вопрос 2 из 3" in bot[-1]["text"]
    # Номер варианта сообщением — тоже ответ.
    engine._telegram_handle_dialog_text(CHAT, "1")
    assert "Вопрос 3 из 3" in bot[-1]["text"] and "класс" in bot[-1]["text"].lower()
    assert not bot.parcels


def test_the_button_carries_exactly_the_card(bot):
    engine._telegram_handle_intake_document(CHAT, b"%PDF", "svetly.pdf")
    _press("intake_questions")
    _press(_buttons(bot[-1])[0]["callback_data"])
    _press(_buttons(bot[-1])[0]["callback_data"])
    _press(_buttons(bot[-1])[1]["callback_data"])  # класс «Бизнес»
    final = bot[-1]
    assert "Итог разбора перед расчётом" in final["text"]
    button = _buttons(final)[0]
    assert button["text"] == "Всё верно, считать"
    session = _session(button["web_app"]["url"])
    overrides = session["calc_overrides"]
    assert session["cad"] == [NUMBER]
    assert overrides["purchase_price_mln"] == 2550.0
    assert overrides["resettlement_cost_mln"] == 0.0
    assert overrides["offices_gba_sqm"] == 26_300 and overrides["offices_enabled"] is True
    assert overrides["project_class"] == "business"
    assert overrides["apartment_price_th"] == engine.PROJECT_CLASS_PRESETS["business"]["apartment_price_th"]
    assert "стр. 2" in overrides["_field_origin"]["inputs.offices_gba_sqm"]["text"]
    # Чего нет в карточке «уйдёт в расчёт», того нет и в расчёте.
    assert "social_compensation_mln" not in overrides
    assert not bot.parcels, "расчёт начался до кнопки"


def test_a_skip_and_a_stop_are_answers_and_say_so(bot):
    engine._telegram_handle_intake_document(CHAT, b"%PDF", "svetly.pdf")
    _press("intake_questions")
    engine._telegram_handle_dialog_text(CHAT, "-")
    assert any("Пропущено" in m["text"] for m in bot[-2:])
    engine._telegram_handle_dialog_text(CHAT, "стоп")
    assert "Итог разбора перед расчётом" in bot[-1]["text"]
    assert _buttons(bot[-1])[0]["text"] == "Всё верно, считать"


def test_the_dialogue_survives_the_other_worker(bot):
    """Воркеров два, память у них раздельная: следующее сообщение попадает в
    другой процесс, где разговора не было."""
    engine._telegram_handle_intake_document(CHAT, b"%PDF", "svetly.pdf")
    _press("intake_questions")
    engine._TELEGRAM_DIALOGS.pop(CHAT, None)
    engine._telegram_handle_dialog_text(CHAT, "1")
    assert "Вопрос 2 из 3" in bot[-1]["text"]


OTHER = "66:41:0000000:1"


def _teaser_with(monkeypatch, numbers: list[str]) -> None:
    extraction = json.loads(json.dumps(EXTRACTION))
    extraction["fields"][0] = {"key": "cadastral_numbers", "value": numbers, "unit": "список",
                               "quote": f"КН {NUMBER}"}
    monkeypatch.setattr(engine, "plato_answer",
                        lambda *_a: {"answer": json.dumps(extraction, ensure_ascii=False)})


def test_another_region_is_counted_with_our_defaults_and_the_card(bot, monkeypatch):
    """Другой регион считается (госреестр и наши умолчания), и строки карточки
    едут в этот расчёт так же, как в московский; карточка говорит, что норм
    региона у нас нет."""
    _teaser_with(monkeypatch, [OTHER])
    engine._telegram_handle_intake_document(CHAT, b"%PDF", "ekb.pdf")
    first = bot[-1]["text"]
    assert "Норм этого региона у нас нет" in first
    assert "ставим нулём" in first and "калькулятором ГлавАПУ" not in first
    _press("intake_questions")
    engine._telegram_handle_dialog_text(CHAT, "стоп")
    button = _buttons(bot[-1])[0]
    assert button["text"] == "Всё верно, считать"
    url = button["web_app"]["url"]
    assert "mode=intake" in url
    session = _session(url)
    assert session["cad"] == [OTHER]
    assert session["calc_overrides"]["offices_gba_sqm"] == 26_300


def test_parcels_of_two_regions_get_no_button_and_a_reason(bot, monkeypatch):
    _teaser_with(monkeypatch, [OTHER, NUMBER])
    engine._telegram_handle_intake_document(CHAT, b"%PDF", "two.pdf")
    _press("intake_questions")
    engine._telegram_handle_dialog_text(CHAT, "стоп")
    assert "разных регионов" in bot[-1]["text"]
    assert not _buttons(bot[-1])

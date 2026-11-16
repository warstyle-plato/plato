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
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import document_intake  # noqa: E402
import main_legacy as engine  # noqa: E402

CHAT = 777
NUMBER = "77:08:0010008:1049"
TEXT = ("[стр. 1]\nТизер\n\n[стр. 2]\nофисы – 26 300 м2\n\n"
        f"[стр. 4]\nКН {NUMBER}\nПлатёж 2,55 млрд руб. за SPV")
EXTRACTION = {
    "fields": [
        {"key": "cadastral_numbers", "value": [NUMBER], "unit": "список", "quote": f"КН {NUMBER}"},
        {"key": "offices_gba_sqm", "value": "26 300", "unit": "м2", "quote": "офисы – 26 300 м2"},
    ],
    "questions": [
        {"key": "", "question": "Платёж 2,55 млрд руб. за SPV — куда отнести?",
         "quote": "Платёж 2,55 млрд руб. за SPV",
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


class TelegramHTML(HTMLParser):
    """Reject the incomplete markup that Telegram rejected in the incident."""

    def __init__(self, text, *, bounded=True):
        super().__init__(convert_charrefs=True)
        self.stack, self.plain = [], []
        self.feed(text)
        self.close()
        assert not self.stack, f"Telegram cannot find end tag: {self.stack}"
        if bounded:
            assert len(''.join(self.plain).encode('utf-16-le')) // 2 <= 4096

    def handle_starttag(self, tag, attrs):
        self.stack.append(tag)

    def handle_endtag(self, tag):
        assert self.stack and self.stack.pop() == tag

    def handle_data(self, data):
        self.plain.append(data)


def test_long_final_card_after_elite_answer_is_complete_and_keeps_the_calculate_button(bot, monkeypatch):
    engine._telegram_handle_intake_document(CHAT, b"%PDF", "synthetic.pdf")
    _press("intake_questions")
    _press(_buttons(bot[-1])[0]["callback_data"])
    _press(_buttons(bot[-1])[0]["callback_data"])
    dialog = engine._telegram_dialog_get(CHAT)
    queue = engine._intake_queue_load(dialog['intake']['id'], request=engine._telegram_agent_request(CHAT))
    queue['notes'] = [('Синтетическое пояснение ' + str(i) + ': ' + 'проверить & сверить <значение> 😀 ' * 12)
                      for i in range(24)]
    engine._intake_queue_save(queue)
    original_send = engine._telegram_send_message

    def validate_send(chat_id, text, **kwargs):
        TelegramHTML(text)
        return original_send(chat_id, text, **kwargs)

    monkeypatch.setattr(engine, '_telegram_send_message', validate_send)
    before = len(bot)
    _press(_buttons(bot[-1])[2]["callback_data"])  # Элитный, последний вопрос.
    parts = bot[before + 1:]  # The first message acknowledges the saved answer.
    assert len(parts) > 1
    assert 'Итог разбора перед расчётом' in parts[0]['text']
    assert all(not _buttons(message) for message in parts[:-1])
    assert [b['text'] for b in _buttons(parts[-1])] == ['Всё верно, считать']
    session = _session(_buttons(parts[-1])[0]['web_app']['url'])
    assert session['calc_overrides']['project_class'] == 'elite'
    updated = engine._intake_queue_load(dialog['intake']['id'], request=engine._telegram_agent_request(CHAT))
    card = engine.teaser_card_view(updated, dict(engine.DEFAULT_INPUTS),
                                  {k: dict(v) for k, v in engine.TEP_DEFAULT.items()},
                                  by_parcel=True, parcel_region=dialog['intake']['region'])
    expected = engine._telegram_intake_card_text(card, first=False)
    rendered = ''.join(''.join(TelegramHTML(p['text']).plain) for p in parts)
    assert rendered.startswith(''.join(TelegramHTML(expected, bounded=False).plain))
    assert 'Синтетическое пояснение 23' in rendered
    assert len(updated['answers']) == 3 and updated['index'] == 3
    assert not bot.parcels


def test_calc_menu_can_return_to_the_saved_intake_without_reloading_the_document(bot):
    engine._telegram_handle_intake_document(CHAT, b"%PDF", "synthetic.pdf")
    _press('intake_questions')
    engine._telegram_handle_dialog_text(CHAT, 'стоп')
    saved = engine._telegram_dialog_get(CHAT)['intake']['id']
    engine._TELEGRAM_DIALOGS.pop(CHAT, None)
    engine._telegram_calc_menu(CHAT)
    assert any(b.get('callback_data') == 'intake_questions' for b in _buttons(bot[-1]))
    _press('intake_questions')
    assert 'Итог разбора перед расчётом' in bot[-1]['text']
    assert _buttons(bot[-1])[0]['text'] == 'Всё верно, считать'
    assert engine._telegram_dialog_get(CHAT)['intake']['id'] == saved


@pytest.mark.parametrize('text', [
    '<b>Заголовок</b>\n<i>' + 'Сверить &amp; проверить &lt;число&gt; 😀 ' * 700 + '</i>',
    '<b><i>' + '😀' * 5000 + '</i></b>',
    '<b>Начало\n' + 'А' * 12000 + '\nконец</b>',
])
def test_intake_parts_preserve_all_text_and_never_split_entities_unicode_or_emphasis(text):
    from telegram_intake_text import split_intake_html
    parts = split_intake_html(text)
    assert len(parts) > 1
    assert all(len(part.encode('utf-16-le')) // 2 <= 3900 for part in parts)
    actual = ''.join(''.join(TelegramHTML(part).plain) for part in parts)
    # No Telegram limit is applied to the original, unfragmented test source.
    parser = HTMLParser(convert_charrefs=True)
    original = []
    parser.handle_data = original.append
    parser.feed(text)
    parser.close()
    assert actual == ''.join(original)


def test_long_first_card_keeps_its_complete_text_before_the_questions_button(bot, monkeypatch):
    extraction = json.loads(json.dumps(EXTRACTION))
    extraction['notes'] = ['Первое чтение ' + str(i) + ': ' + 'проверить ' * 35 for i in range(24)]
    monkeypatch.setattr(engine, 'plato_answer', lambda *_a: {'answer': json.dumps(extraction, ensure_ascii=False)})
    original_send = engine._telegram_send_message
    def validate_send(chat_id, text, **kwargs):
        TelegramHTML(text)
        return original_send(chat_id, text, **kwargs)
    monkeypatch.setattr(engine, '_telegram_send_message', validate_send)
    engine._telegram_handle_intake_document(CHAT, b'%PDF', 'synthetic.pdf')
    parts = bot[1:]
    assert len(parts) > 1
    assert 'Что я прочитал в тизере' in parts[0]['text']
    assert 'Первое чтение 23' in ''.join(p['text'] for p in parts)
    assert all(not _buttons(p) for p in parts[:-1])
    assert _buttons(parts[-1])[0]['callback_data'] == 'intake_questions'
    assert not bot.parcels


@pytest.mark.parametrize('chat_id,error,notified', [
    (CHAT, 'Synthetic callback failure', True),
    (-CHAT, 'Synthetic callback failure', False),
    (CHAT, '429 Too Many Requests', False),
])
def test_callback_failure_is_visible_in_private_chat_but_not_in_groups_or_rate_limits(bot, monkeypatch, chat_id, error, notified):
    def fail(_update):
        raise RuntimeError(error)
    monkeypatch.setattr(engine, '_telegram_handle_update', fail)
    engine._telegram_process_update({'callback_query': {'from': {'id': CHAT},
        'message': {'chat': {'id': chat_id, 'type': 'private' if chat_id > 0 else 'group'}}}})
    assert bool(bot) is notified
    if notified:
        assert 'Не удалось завершить запрос' in bot[-1]['text']


OTHER = "66:41:0000000:1"


def _teaser_with(monkeypatch, numbers: list[str]) -> None:
    extraction = json.loads(json.dumps(EXTRACTION))
    extraction["fields"][0] = {"key": "cadastral_numbers", "value": numbers, "unit": "список",
                               "quote": "КН " + ", ".join(numbers)}
    monkeypatch.setattr(document_intake, "extract_text",
                        lambda _data, name: {"text": TEXT.replace(NUMBER, ", ".join(numbers)), "pages": 4, "filename": name})
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


def test_new_moscow_with_a_50_number_goes_to_glavapu(bot, monkeypatch):
    """У Новой Москвы (ТиНАО) номера тоже 50:…, и префикс область не выбирает:
    регион решает территория ГлавАПУ. Москва — экспресс-расчёт ГлавАПУ по
    участку, а не нормы области."""
    new_moscow = "50:21:0120316:1234"
    _teaser_with(monkeypatch, [new_moscow])
    asked: list[list[str]] = []
    monkeypatch.setattr(engine, "analyze_cadastral_territory", lambda req: (
        asked.append(list(req.cadastral_numbers)), {"territory": {"inside_moscow": True}})[1])
    engine._telegram_handle_intake_document(CHAT, b"%PDF", "tinao.pdf")
    assert asked, "регион 50:… решён без территории ГлавАПУ"
    assert "калькулятором ГлавАПУ" in bot[-1]["text"]
    assert "Московской области" not in bot[-1]["text"]
    _press("intake_questions")
    engine._telegram_handle_dialog_text(CHAT, "стоп")
    url = _buttons(bot[-1])[0]["web_app"]["url"]
    assert "mode=intake" not in url, "Новая Москва ушла в расчёт по нормам области"
    assert _session(url)["cad"] == [new_moscow]



def test_a_50_number_without_glavapu_is_not_guessed(bot, monkeypatch):
    """50:… без ответа ГлавАПУ — Новая Москва или область, неизвестно. Решение
    владельца 25.10.2026: не угадывать — карточка говорит причину, кнопки
    расчёта нет, «Проверить участок ещё раз» спрашивает ГлавАПУ снова."""
    number = "50:21:0120316:1234"
    _teaser_with(monkeypatch, [number])
    answers = [RuntimeError("ГлавАПУ не ответил"), {"territory": {"inside_moscow": True}}]

    def analyze(_req):
        got = answers.pop(0)
        if isinstance(got, Exception):
            raise got
        return got
    monkeypatch.setattr(engine, "analyze_cadastral_territory", analyze)
    engine._telegram_handle_intake_document(CHAT, b"%PDF", "tinao.pdf")
    assert "Новая Москва это или Московская область" in bot[-1]["text"]
    assert "нормам Московской области" not in bot[-1]["text"]
    _press("intake_questions")
    engine._telegram_handle_dialog_text(CHAT, "стоп")
    button = _buttons(bot[-1])[0]
    assert button.get("callback_data") == "intake_region" and "web_app" not in button
    _press("intake_region")
    url = _buttons(bot[-1])[0]["web_app"]["url"]
    assert "mode=intake" not in url and _session(url)["cad"] == [number]


def test_real_upload_questions_and_answer_keep_exact_public_telegram_owner(bot, monkeypatch):
    """Exercise the adapter contract; no intake/ACL/card helper is mocked."""
    import agent_access

    key = "synthetic-admin-key-intake-test"
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", key)
    monkeypatch.setattr(engine, "_telegram_download_document", lambda _doc: (b"%PDF", "own.pdf"))
    actors = []
    def extract(req, request):
        actor = engine._agent_actor_current(req)
        actors.append(actor)
        assert actor == request.scope["plato_actor"]
        assert actor.surface == "telegram" and not actor.private and not actor.key
        assert not engine._execute_agent_tool("search_project_knowledge",
            {"query": "FOREIGN_PRIVATE_SENTINEL", "source": "rules"}, req, {})["available"]
        return {"answer": json.dumps(EXTRACTION, ensure_ascii=False)}
    monkeypatch.setattr(engine, "plato_answer", extract)
    engine._telegram_handle_update({"message": {
        "chat": {"id": CHAT, "type": "private"}, "from": {"id": CHAT},
        "document": {"file_id": "synthetic-pdf", "file_name": "own.pdf"}}})
    dialog = engine._telegram_dialog_get(CHAT)
    intake_id = dialog["intake"]["id"]
    metadata = agent_access.load(engine._PLATO_STAGE_DIR / "intake_access", intake_id)
    assert metadata == actors[0].metadata()
    assert metadata["owner"] == agent_access.digest(engine._PLATO_STAGE_DIR, "bot:" + str(CHAT))
    assert metadata["private"] is False and metadata["acl"] == "public"
    assert key not in json.dumps(metadata)
    _press("intake_questions")
    assert "Вопрос 1 из 3" in bot[-1]["text"]
    # Another worker reconstructs the same actor from the trusted Telegram chat.
    engine._TELEGRAM_DIALOGS.pop(CHAT, None)
    _press(_buttons(bot[-1])[0]["callback_data"])
    assert "Вопрос 2 из 3" in bot[-1]["text"]
    queue = engine._intake_queue_load(intake_id, request=engine._telegram_agent_request(CHAT))
    card = engine.teaser_card_view(queue, dict(engine.DEFAULT_INPUTS), dict(engine.TEP_DEFAULT))
    assert card["questions"]["index"] == 1
    assert engine.teaser_card.calc_overrides(card)["purchase_price_mln"] == 2550.0
    assert "FOREIGN_PRIVATE_SENTINEL" not in json.dumps(list(bot), ensure_ascii=False)


def test_foreign_chat_web_identity_and_forged_bot_claim_cannot_read_or_answer_intake(bot, monkeypatch):
    import copy
    from fastapi.testclient import TestClient
    from starlette.requests import Request

    monkeypatch.setenv("DEVELOPAID_PAYWALL", "0")
    key = "synthetic-admin-key-intake-test"
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", key)
    engine._telegram_handle_intake_document(CHAT, b"%PDF", "own.pdf")
    dialog = engine._telegram_dialog_get(CHAT)
    intake_id = dialog["intake"]["id"]
    before = engine._intake_queue_path(intake_id).read_bytes()
    with pytest.raises(engine.HTTPException) as denied:
        engine._intake_queue_load(intake_id, request=engine._telegram_agent_request(CHAT + 1))
    assert denied.value.status_code == 403
    forged = Request({"type": "http", "method": "POST", "path": "/telegram/intake",
        "headers": [(b"x-developaid-admin-key", key.encode())], "query_string": b"",
        "plato_bot_actor": ("client-claimed", CHAT),
        "plato_actor": {"owner": CHAT, "private": True, "surface": "telegram"}})
    with pytest.raises(engine.HTTPException) as denied:
        engine._intake_queue_load(intake_id, request=forged)
    assert denied.value.status_code == 403
    # A different Telegram chat cannot answer even after obtaining an intake ID.
    foreign_dialog = copy.deepcopy(dialog)
    engine._telegram_dialog_save(CHAT + 1, foreign_dialog)
    engine._telegram_handle_update({"callback_query": {
        "id": "", "data": "intake_opt:0:0", "from": {"id": CHAT + 1},
        "message": {"chat": {"id": CHAT + 1, "type": "private"}}}})
    assert engine._intake_queue_path(intake_id).read_bytes() == before
    assert "недоступен" in bot[-1]["text"]
    # Same numeric ID through signed web login is a separate surface/owner.
    session = engine._telegram_session(CHAT, [])
    with TestClient(engine.app) as client:
        body = {"session": session, "access_key": key, "intake_id": intake_id,
                "owner": CHAT, "caller": "telegram", "is_admin": True,
                "plato_bot_actor": ["client-claimed", CHAT]}
        response = client.post("/agent/document/card", json=body)
        assert response.status_code == 403
        assert "own.pdf" not in response.text
        response = client.post("/agent/document/answer", json={**body,
            "index": 0, "action": "answer", "choice": 0})
        assert response.status_code == 403
    assert engine._intake_queue_path(intake_id).read_bytes() == before
    # Failed foreign attempts do not break the owning chat's next question.
    _press("intake_questions")
    assert "Вопрос 1 из 3" in bot[-1]["text"]

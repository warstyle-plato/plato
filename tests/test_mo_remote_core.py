"""Бот считает Подмосковье через ядро, а не сам.

На Render нет доступа к nspd.gov.ru, поэтому локальный расчёт там дал бы ТЭП
без данных ЕГРН — молча неверные. Бот отправляет исходный текст пользователя
в ядро на MO_CALC_API_URL и только раскладывает ответ по сообщениям; методики
расчёта в коде бота нет.
Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import json
import socket
import sys
import re
import urllib.error
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

main = _wrapper.core

ADDRESS = "Московская область, Мытищи, Олимпийский проспект, 29"
ONE_NUMBER = "50:12:0100131:259"
TWENTY_TWO = ", ".join(f"50:12:0100131:{n}" for n in range(200, 222))


class Recorder:
    """Подменяет и запрос к ядру, и отправку в Telegram."""

    def __init__(self, response=None, error=None):
        self.response = response or {}
        self.error = error
        self.requests: list[dict] = []
        self.messages: list[str] = []

    def core(self, query, limit=30):
        self.requests.append({"query": query, "limit": limit})
        if self.error:
            raise self.error
        return self.response

    def send(self, chat_id, text, **kwargs):
        self.messages.append(text)
        return {"ok": True}


def sample_response(parcel_count: int) -> dict:
    return {
        "territory": {
            "site_area_ha": 22.423, "parcel_count": parcel_count,
            "district": "Городской округ Мытищи", "quarter": "50:12:0100131",
        },
        "density_sqm_per_ha": 30000.0,
        "social": {
            "apartments_sqm": 672690.0, "population": 24025,
            "kindergarten": {"places": 1562, "gba_sqm": 42174.0},
            "school": {"places": 3250, "gba_sqm": 87750.0},
            "clinic": {"capacity": 427, "gba_sqm": 6405.0},
            "parking": {"permanent_spaces": 7698},
        },
        "upks": {"source": {"land": {"report": "Отчёт № 01/2022"},
                            "oks": {"report": "Отчёт № 01/2023"}}},
        "vri": {
            "payment_used_rub": 16_013_519_988.0,
            "payment_basis": "прямая формула Кср × площадь квартир × Кд",
            "market_price_document": "Распоряжение Комитета по ценам и тарифам МО",
            "market_price_period": "III, IV кварталы 2026 года",
            "kd_document": "Постановление Правительства МО от 19.12.2025 № 1745",
            "warnings": ["Участки ЕГРН не заданы"],
        },
        "warnings": ["Кср взят из распоряжения о средней рыночной стоимости"],
        "inputs": {"land_rights_cost_mln": 16013.52},
    }


@pytest.fixture
def bot(monkeypatch):
    def make(response=None, error=None):
        rec = Recorder(response, error)
        monkeypatch.setattr(main, "mo_calculate_via_core", rec.core)
        monkeypatch.setattr(main, "_telegram_send_message", rec.send)
        monkeypatch.setattr(main, "_telegram_send_tep_review", lambda *a, **k: None)
        return rec
    return make


# --- маршрут запроса ---------------------------------------------------------

def test_one_cadastral_number_goes_to_the_core(bot):
    rec = bot(sample_response(1))
    main._telegram_handle_mo_numbers(1, [ONE_NUMBER], ONE_NUMBER)
    assert rec.requests == [{"query": ONE_NUMBER, "limit": main._LAND_LOOKUP_MAX_RESULTS}]


def test_twenty_two_parcels_go_as_one_request(bot):
    rec = bot(sample_response(22))
    numbers = main._parse_cadastral_numbers(TWENTY_TWO)
    assert len(numbers) == 22
    main._telegram_handle_mo_numbers(1, numbers, TWENTY_TWO)
    assert len(rec.requests) == 1
    assert rec.requests[0]["query"] == TWENTY_TWO
    assert rec.requests[0]["limit"] >= 22


def test_address_is_forwarded_untouched(bot):
    """Адрес разбирает ядро: бот не пытается извлечь из него номера."""
    rec = bot(sample_response(3))
    main._telegram_handle_mo_numbers(1, [], ADDRESS)
    assert rec.requests[0]["query"] == ADDRESS


def test_coordinates_are_forwarded_untouched(bot):
    rec = bot(sample_response(1))
    main._telegram_handle_mo_numbers(1, [], "55.9105, 37.7365")
    assert rec.requests[0]["query"] == "55.9105, 37.7365"


# --- сообщения пользователю --------------------------------------------------

def test_progress_message_comes_before_the_long_request(bot):
    rec = bot(sample_response(22))
    numbers = main._parse_cadastral_numbers(TWENTY_TWO)
    main._telegram_handle_mo_numbers(1, numbers, TWENTY_TWO)
    assert rec.messages[0] == "Получил 22 участка. Запрашиваю сведения ЕГРН и выполняю расчёт…"


@pytest.mark.parametrize("count,expected", [(1, "1 участок"), (2, "2 участка"), (5, "5 участков"),
                                            (11, "11 участков"), (22, "22 участка")])
def test_progress_message_declines_the_noun(bot, count, expected):
    rec = bot(sample_response(count))
    main._telegram_handle_mo_numbers(1, [ONE_NUMBER] * count, ONE_NUMBER)
    assert expected in rec.messages[0]


def test_report_carries_every_required_block(bot):
    rec = bot(sample_response(22))
    main._telegram_handle_mo_numbers(1, main._parse_cadastral_numbers(TWENTY_TWO), TWENTY_TWO)
    report = "\n".join(rec.messages)
    for fragment in ("22", "22,4230 га", "Городской округ Мытищи", "672 690",
                     "24 025", "1 562", "3 250", "427", "7 698",
                     "Исходные нормативы", "Отчёт № 01/2022", "№ 1745", "Предупреждения"):
        assert fragment in report, fragment


def test_found_fewer_parcels_than_asked_is_visible(bot):
    """Если ЕГРН отдал не все участки, это должно быть видно, а не потеряться."""
    rec = bot(sample_response(10))
    main._telegram_handle_mo_numbers(1, main._parse_cadastral_numbers(TWENTY_TWO), TWENTY_TWO)
    assert "10</b> из 22" in "\n".join(rec.messages)


# --- ошибки ------------------------------------------------------------------

def test_core_failure_is_reported_and_never_falls_back(bot, monkeypatch):
    calls = []
    monkeypatch.setattr(main, "mo_calculate", lambda *a, **k: calls.append(1))
    rec = bot(error=HTTPException(status_code=502, detail="Ядро расчёта недоступно"))
    main._telegram_handle_mo_numbers(1, [ONE_NUMBER], ONE_NUMBER)
    assert "Ядро расчёта недоступно" in "\n".join(rec.messages)
    assert calls == [], "локальный расчёт не должен подменять недоступное ядро"


def test_timeout_says_how_long_it_waited(monkeypatch):
    monkeypatch.setattr(main, "_MO_CALC_API_URL", "https://example.invalid/mo/calculate")
    monkeypatch.setattr(main, "_MO_CALC_TIMEOUT_SECONDS", 180.0)

    def boom(*args, **kwargs):
        raise socket.timeout()

    monkeypatch.setattr(main.urllib.request, "urlopen", boom)
    with pytest.raises(HTTPException) as exc:
        main._mo_calculate_remote(ONE_NUMBER, 30)
    assert exc.value.status_code == 504
    assert "180" in str(exc.value.detail)


def test_http_error_detail_reaches_the_user(monkeypatch):
    monkeypatch.setattr(main, "_MO_CALC_API_URL", "https://example.invalid/mo/calculate")

    def boom(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://example.invalid", 400, "Bad Request", {},
            io.BytesIO(json.dumps({"detail": "Кадастровый номер не найден"}).encode()),
        )

    monkeypatch.setattr(main.urllib.request, "urlopen", boom)
    with pytest.raises(HTTPException) as exc:
        main._mo_calculate_remote(ONE_NUMBER, 30)
    assert "Кадастровый номер не найден" in str(exc.value.detail)


# --- разделение обязанностей -------------------------------------------------

def test_bot_and_browser_share_one_entry_point(monkeypatch):
    """Бот и страница зовут один и тот же метод: развилка «локально или наружу»
    живёт в самом эндпоинте, иначе они разъедутся."""
    seen = {}
    monkeypatch.setattr(main, "mo_calculate", lambda req: seen.setdefault("query", req.query))
    main.mo_calculate_via_core(ONE_NUMBER)
    assert seen == {"query": ONE_NUMBER}


def test_bot_does_not_reimplement_the_methodology():
    """В обработчике бота не должно быть ни нормативов, ни формул расчёта."""
    source = Path(main.__file__).read_text(encoding="utf-8")
    start = source.index("def _telegram_handle_mo_numbers")
    body = source[start:source.index("\ndef ", start + 10)]
    for forbidden in ("_mo_upks", "_mo_vri_kd", "МoNorm", "* 0.0", "/ 1000 *"):
        assert forbidden not in body, forbidden


# --- поиск по адресу ---------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Мишина 46 Москва",
    "Московская область, Мытищи, Олимпийский проспект, 29",
    "город Химки улица Победы",
])
def test_address_text_is_recognized_as_an_address(text):
    assert main._looks_like_address(text)


@pytest.mark.parametrize("text", [
    "Проект Северный. Участок 2,4 га. Квартиры 42 000 м², коммерция 2 500 м².",
    "Участок 2,4 га",
    "Подземный паркинг 620 мест",
])
def test_tep_description_is_not_mistaken_for_an_address(text):
    """Описание объёма не должно уходить в ЕГРН и ждать там три минуты."""
    assert not main._looks_like_address(text)


def test_address_lookup_feeds_the_cadastral_flow(monkeypatch):
    sent, routed = [], []
    monkeypatch.setattr(main, "_telegram_send_message",
                        lambda chat_id, text, **k: sent.append(text) or {"ok": True})
    monkeypatch.setattr(main, "land_lookup_via_core", lambda q, limit=30: {
        "results": [
            {"cadastral_number": "50:12:0100131:259", "area_sqm": 6509.0, "address": "Мытищи"},
            {"cadastral_number": "50:12:0100131:46", "area_sqm": 4210.0, "address": "Мытищи"},
        ],
    })
    monkeypatch.setattr(main, "_telegram_handle_cadastral_numbers",
                        lambda chat_id, numbers, query="": routed.append(numbers))
    assert main._telegram_handle_address(1, "Мытищи, Олимпийский 29") is True
    assert routed == [["50:12:0100131:259", "50:12:0100131:46"]]
    assert "Нашёл по адресу: 2 участка" in "\n".join(sent)


def test_address_with_only_premises_says_so(monkeypatch):
    sent = []
    monkeypatch.setattr(main, "_telegram_send_message",
                        lambda chat_id, text, **k: sent.append(text) or {"ok": True})
    monkeypatch.setattr(main, "land_lookup_via_core",
                        lambda q, limit=30: {"results": [], "hidden_count": 14})
    main._telegram_handle_address(1, "Мишина 46 Москва")
    report = "\n".join(sent)
    assert "не найден" in report and "14" in report


def test_lookup_goes_to_the_core_when_configured(monkeypatch):
    seen = {}
    monkeypatch.setattr(main, "_MO_CALC_API_URL", "https://developaid.ru/mo/calculate")
    monkeypatch.setattr(main, "_core_post", lambda url, payload, timeout: seen.setdefault("url", url))
    main.land_lookup_via_core("Мытищи", 30)
    assert seen["url"] == "https://developaid.ru/land/lookup"


def test_web_app_link_can_leave_the_webhook_host(monkeypatch):
    """Вебхук остаётся на боте, мини-приложение уезжает на ядро."""
    monkeypatch.setattr(main, "_TELEGRAM_WEB_APP_BASE_URL", "https://developaid.ru")
    monkeypatch.setattr(main, "_telegram_session", lambda *a, **k: "session")
    url = main._telegram_web_app_url(1, [])
    assert url.startswith("https://developaid.ru/?telegram=1#")
    assert main._TELEGRAM_PUBLIC_BASE_URL not in url


# --- два хоста, один бот ------------------------------------------------------

def test_missing_token_names_the_real_cause(monkeypatch):
    """«Сессия истекла» уводит в ложном направлении: истекать там нечему."""
    monkeypatch.setattr(main, "_telegram_token", lambda: "")
    with pytest.raises(HTTPException) as exc:
        main._telegram_verify_session("что-угодно.подпись")
    assert exc.value.status_code == 503
    assert "TELEGRAM_BOT_TOKEN" in str(exc.value.detail)
    assert "TELEGRAM_WEBHOOK_ENABLED=0" in str(exc.value.detail)


def test_session_signed_by_the_bot_verifies_on_the_model_host(monkeypatch):
    """Хост с моделью проверяет подпись тем же токеном — сессия должна пройти."""
    monkeypatch.setattr(main, "_telegram_token", lambda: "111:AAA")
    session = main._telegram_session(42, ["50:12:0100131:259"])
    payload = main._telegram_verify_session(session)
    assert payload["chat_id"] == 42
    assert payload["cad"] == ["50:12:0100131:259"]


def test_another_token_does_not_verify(monkeypatch):
    monkeypatch.setattr(main, "_telegram_token", lambda: "111:AAA")
    session = main._telegram_session(42, [])
    monkeypatch.setattr(main, "_telegram_token", lambda: "222:BBB")
    with pytest.raises(HTTPException) as exc:
        main._telegram_verify_session(session)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("value,expected", [
    ("0", False), ("false", False), ("no", False), ("off", False), ("OFF", False),
    ("1", True), ("true", True), ("", True),
])
def test_webhook_registration_can_be_switched_off(monkeypatch, value, expected):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_ENABLED", value)
    assert main._telegram_webhook_enabled() is expected


def test_webhook_is_not_registered_when_disabled(monkeypatch):
    """Второй хост с тем же токеном не должен уводить вебхук себе."""
    calls = []
    monkeypatch.setattr(main, "_telegram_token", lambda: "111:AAA")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_ENABLED", "0")
    monkeypatch.setattr(main, "_telegram_api",
                        lambda method, payload=None: calls.append(method) or {})
    main._telegram_configure()
    assert "setWebhook" not in calls
    assert "getMe" in calls


# --- интерфейс на одном сервере, данные ЕГРН на другом ------------------------

def test_endpoints_forward_when_the_core_is_configured(monkeypatch):
    """Браузер зовёт эти методы относительной ссылкой — они и должны пересылать."""
    calls = []
    monkeypatch.setattr(main, "_MO_CALC_API_URL", "https://developaid.ru/mo/calculate")
    monkeypatch.setattr(main, "_core_post",
                        lambda url, payload, timeout: calls.append((url, payload)) or {"ok": True})

    main.mo_calculate(main.MoCalculateRequest(query=ONE_NUMBER, site_area_ha=2.4, district="Мытищи"))
    main.land_lookup(main.LandLookupRequest(query=ADDRESS))
    main.analyze_cadastral_territory(main.CadastralAnalysisRequest(cadastral_numbers=[ONE_NUMBER]))

    urls = [url for url, _ in calls]
    assert urls == [
        "https://developaid.ru/mo/calculate",
        "https://developaid.ru/land/lookup",
        "https://developaid.ru/cadastral/analyze",
    ]
    # Ручные вводные пользователя обязаны доехать: иначе посчитается не то.
    assert calls[0][1]["site_area_ha"] == 2.4
    assert calls[0][1]["district"] == "Мытищи"


def test_endpoints_compute_locally_without_a_core(monkeypatch):
    """На сервере, где данные доступны, пересылки быть не должно — иначе он позовёт сам себя."""
    monkeypatch.setattr(main, "_MO_CALC_API_URL", "")
    monkeypatch.delenv("CORE_API_URL", raising=False)
    monkeypatch.setattr(main, "_core_post", lambda *a, **k: pytest.fail("ушёл наружу"))
    with pytest.raises(HTTPException):
        # Локальный расчёт без данных ЕГРН честно ругается, а не пересылает запрос.
        main.mo_calculate(main.MoCalculateRequest(query=ONE_NUMBER))


def test_mini_app_url_prefers_the_new_variable():
    """TELEGRAM_WEBAPP_URL — основное имя; прежнее оставлено, чтобы не ломать стенды."""
    source = Path(main.__file__).read_text(encoding="utf-8")
    block = source[source.index("_TELEGRAM_WEB_APP_BASE_URL = ("):]
    block = block[:block.index(").rstrip")]
    # Имя самой константы тоже содержит старое имя переменной — сверяем чтения окружения.
    assert (block.index('os.environ.get("TELEGRAM_WEBAPP_URL")')
            < block.index('os.environ.get("TELEGRAM_WEB_APP_BASE_URL")'))
    assert "TELEGRAM_PUBLIC_BASE_URL" in block


def test_every_web_app_button_uses_one_builder():
    """Кнопок много, адрес один: иначе часть из них останется на старом хосте."""
    source = Path(main.__file__).read_text(encoding="utf-8")
    for match in re.finditer(r'"web_app":\s*\{"url":\s*([^}]+)\}', source):
        assert "_telegram_web_app_url" in match.group(1) or match.group(1).strip() == "url", match.group(1)


# --- вопрос не адрес ---------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Как цена покупки объекта оптимальна",
    "Какая цена объекта оптимальна?",
    "Почему LLCR такой высокий",
    "Сколько стоит смена ВРИ?",
    "Объясни структуру расходов",
    "Стоит ли покупать по этой цене",
    "Сравни очереди",
])
def test_questions_do_not_go_to_the_land_registry(text):
    """«Какая цена объекта оптимальна?» уходило искать участок и не находило его."""
    assert main._looks_like_question(text)
    assert not main._looks_like_address(text)


@pytest.mark.parametrize("text", [
    "Мишина 46 Москва",
    "Московская область, Мытищи, Олимпийский проспект, 29",
    "город Химки улица Победы",
])
def test_addresses_are_still_recognized(text):
    assert not main._looks_like_question(text)
    assert main._looks_like_address(text)


def test_menu_offers_asking_platon():
    """Спросить было неоткуда: кнопка появлялась только на карточках результата."""
    source = Path(main.__file__).read_text(encoding="utf-8")
    start = source.index("def _telegram_start_message")
    menu = source[start:source.index("\ndef ", start + 10)]
    assert '"callback_data": "ask_platon"' in menu
    assert '{"command": "platon"' in source

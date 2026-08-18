"""Оценка рынка конкурентов на трёх поверхностях.

Панель, Платон Сергеевич и бот обязаны отвечать одним расчётом и одними
словами. Разъезд поверхностей на одних данных в этом проекте уже случался
дважды — с PDF бота и с отчётом сайта, — и оба раза выглядел безупречно с
обеих сторон. Поэтому проверяется не «модуль работает», а именно совпадение:
одно вычисление, одно основание цены, одно название единиц.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from market_search import assessment as md
from market_search import bot as market_bot
from market_search import plato_tool


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": {
            "address": "Москва, ул. Мишина, 46",
            "radius_km": 3.0,
            "limit": 10,
            "district": "Савёловский",
            "subject_district": "Савёловский",
            "segment": "бизнес",
            "segment_source": "nearest_neighbours",
        },
        "projects": [
            {
                "name": "Петровский парк II",
                "developer": "Донстрой",
                "distance_km": 0.62,
                "segment": "бизнес",
                "district": "Савёловский",
                "address": "Москва, Верхняя Масловка, 20",
                "geo_status": "resolved",
                "price_verified": True,
                "eligible_analogue": True,
                "confirmed": True,
                "market_price": {
                    "available": True,
                    "verified": True,
                    "price_per_sqm": 620000,
                    "sample_count": 3,
                    "quality": "high",
                    "sources": ["ЦИАН", "Домклик"],
                    "observed_at": "2026-08-10",
                    "basis": "asking",
                },
                "inventory": {"units": 42, "quality": "reported", "source": "ЦИАН"},
                "sales": {"units_per_month": 18},
                "market_source": {"url": "https://cian.ru/zhiloy-kompleks-1", "domain": "cian.ru"},
            },
            {
                "name": "Сидней Сити",
                "distance_km": 2.4,
                "segment": "бизнес",
                "geo_status": "resolved",
                "price_verified": False,
                "eligible_analogue": False,
                "confirmed": False,
                "market_price": {
                    "available": False,
                    "verified": False,
                    "reason": "Ни одно ценовое наблюдение не привязано доказанно",
                },
                "inventory": {"units": None, "quality": "unknown"},
                "sales": {"units_per_month": None, "quality": "unknown"},
                "market_source": {"url": "https://cian.ru/zhiloy-kompleks-2", "domain": "cian.ru"},
            },
        ],
        "count": 2,
        "priced_count": 1,
        "confirmed_count": 1,
        "quarantine": [
            {"name": "Дом Дау", "status": "district_mismatch"},
            {"name": "Мод", "status": "geo_unresolved"},
            {"name": "Тургенев", "status": "geo_unresolved"},
        ],
        "quarantine_count": 3,
        "price_summary": {
            "price_per_sqm": 620000,
            "market_median_price_per_sqm": 620000,
            "corridor_low_price_per_sqm": 590000,
            "corridor_high_price_per_sqm": 650000,
            "analogue_count": 1,
            "confidence": 0.62,
            "method": "median_mad",
            "basis": "asking",
            "note": "",
        },
        "official_price_summary": None,
        "warning": None,
        "source": {"mode": "forensic_entity_pipeline_v6"},
    }
    payload.update(overrides)
    return payload


class _Search:
    configured = True


class _Service:
    """Двойник конвейера: считает один раз и запоминает, сколько раз спросили."""

    def __init__(self, payload: dict[str, Any] | None = None, *, configured: bool = True) -> None:
        self.payload = payload if payload is not None else _payload()
        self.search = _Search()
        self.search.configured = configured
        self.calls: list[dict[str, Any]] = []

    def discover(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return copy.deepcopy(self.payload)


# --- общий расчёт -----------------------------------------------------------


def test_assessment_names_units_of_the_price_it_reports() -> None:
    """Цена приходит парой: ₽/м² для чтения и тыс. ₽/м² для поля модели.

    Удельный показатель без второй базы читается как другой показатель — 620
    тысяч и 620 в одном ответе без подписи неразличимы.
    """
    result = md.assess(_Service(), address="Москва, ул. Мишина, 46")
    assert result["available"] is True
    assert result["price_per_sqm"] == 620000
    assert result["price_th_per_sqm"] == 620.0
    assert result["price_basis"] == md.ASKING


def test_assessment_runs_the_pipeline_once() -> None:
    service = _Service()
    md.assess(service, address="Москва, ул. Мишина, 46")
    assert len(service.calls) == 1


def test_official_average_is_never_called_an_asking_price() -> None:
    """Средняя ЕИСЖС — среднее по сделкам, и подпись обязана это называть."""
    payload = _payload(
        price_summary=None,
        official_price_summary={
            "price_per_sqm": 410000,
            "analogue_count": 2,
            "confidence": 0.3,
            "basis": "official_domrf_average",
        },
    )
    result = md.assess(_Service(payload), address="Москва, ул. Мишина, 46")
    assert result["price_basis"] == md.OFFICIAL
    assert result["price_per_sqm"] == 410000
    meaning = md.for_agent(result)["price_basis_meaning"]
    assert "зарегистрированным сделкам" in meaning
    assert "отстаёт от рынка" in meaning
    assert "Цены предложения" not in meaning


def test_unconfigured_search_answers_instead_of_raising() -> None:
    """Ошибка, ушедшая только в лог, — это ошибка, которой нет."""
    result = md.assess(_Service(configured=False), address="Москва, ул. Мишина, 46")
    assert result["available"] is False
    assert "YANDEX_SEARCH_API_KEY" in result["reason"]


def test_quarantine_is_summarised_not_hidden() -> None:
    result = md.assess(_Service(), address="Москва, ул. Мишина, 46")
    assert result["quarantine_count"] == 3
    labels = {item["status"]: item["count"] for item in result["quarantine_summary"]}
    assert labels == {"geo_unresolved": 2, "district_mismatch": 1}
    assert md.quarantine_label("geo_unresolved") == "адрес проекта не подтверждён"


def test_address_is_taken_from_the_cadastral_analysis_of_the_model() -> None:
    inputs = {"_cadastral_analysis": {"territory": {"address": "Москва,  ул. Мишина,   46"}}}
    assert md.address_from_inputs(inputs) == "Москва, ул. Мишина, 46"
    assert md.address_from_inputs({}) == ""


# --- Платон Сергеевич -------------------------------------------------------


class _Core:
    def __init__(self) -> None:
        self._AGENT_TOOLS: list[dict[str, Any]] = [{"type": "function", "name": "explain_metric"}]
        self.calls: list[str] = []

        def execute(name: str, args: dict[str, Any], req: Any, bundle: dict[str, Any]) -> dict[str, Any]:
            self.calls.append(name)
            return {"tool": name}

        self._execute_agent_tool = execute


class _Request:
    def __init__(self, inputs: dict[str, Any] | None = None) -> None:
        self.inputs = inputs or {}


def test_plato_gets_the_tool_and_keeps_the_others() -> None:
    core, service = _Core(), _Service()
    plato_tool.install(core, service)
    assert [tool["name"] for tool in core._AGENT_TOOLS] == ["explain_metric", plato_tool.TOOL_NAME]

    assert core._execute_agent_tool("explain_metric", {}, _Request(), {}) == {"tool": "explain_metric"}
    assert core.calls == ["explain_metric"]

    answer = core._execute_agent_tool(
        plato_tool.TOOL_NAME,
        {"address": "Москва, ул. Мишина, 46", "radius_km": 0, "limit": 0},
        _Request(),
        {},
    )
    assert answer["recommended_price_per_sqm"] == 620000
    assert answer["model_field"] == {
        "input": "apartment_price_th",
        "label": "Цена квартир",
        "units": "тыс. ₽/м²",
        "value": 620.0,
    }
    assert service.calls[0]["radius_km"] == 3.0 and service.calls[0]["limit"] == 10


def test_plato_install_is_idempotent() -> None:
    core, service = _Core(), _Service()
    plato_tool.install(core, service)
    plato_tool.install(core, service)
    assert [tool["name"] for tool in core._AGENT_TOOLS].count(plato_tool.TOOL_NAME) == 1


def test_plato_takes_the_address_from_the_model_before_asking() -> None:
    service = _Service()
    answer = plato_tool.run(
        service,
        {"address": "", "radius_km": 0, "limit": 0},
        {"_cadastral_analysis": {"territory": {"address": "Москва, ул. Мишина, 46"}}},
    )
    assert answer["address"] == "Москва, ул. Мишина, 46"
    assert answer["address_source"] == "model_inputs"


def test_plato_asks_for_an_address_instead_of_guessing_one() -> None:
    service = _Service()
    answer = plato_tool.run(service, {"address": "", "radius_km": 0, "limit": 0}, {})
    assert answer["available"] is False
    assert "Спроси адрес" in answer["reason"]
    assert service.calls == []


def test_agent_view_carries_no_raw_payload() -> None:
    """Платону нужны числа, а не диагностика поиска."""
    view = md.for_agent(md.assess(_Service(), address="Москва, ул. Мишина, 46"))
    assert "raw" not in view
    assert "diagnostics" not in view
    assert view["analogue_count"] == 1 and view["found_count"] == 2


# --- бот --------------------------------------------------------------------


class _Inline:
    """Поток, который выполняется на месте: фон в тесте нечего ждать."""

    def __init__(self, target: Any = None, args: tuple = (), **_: Any) -> None:
        self._target, self._args = target, args

    def start(self) -> None:
        self._target(*self._args)


class _BotCore:
    TELEGRAM_MENU_EXTENSION_ANCHOR = "platon"

    def __init__(self) -> None:
        self.TELEGRAM_BOT_COMMANDS = [
            {"command": "calc", "description": "Расчёт модели"},
            {"command": "platon", "description": "Платон Сергеевич"},
            {"command": "help", "description": "Помощь"},
        ]
        self.sent: list[dict[str, Any]] = []
        self.dialogs: dict[int, dict[str, Any]] = {}
        self.delegated: list[dict[str, Any]] = []

        def send(chat_id: int, text: str, *, reply_markup: dict[str, Any] | None = None) -> None:
            self.sent.append({"chat_id": chat_id, "text": text, "markup": reply_markup})

        self._telegram_send_message = send
        self._telegram_handle_update = self.delegated.append

    def _telegram_dialog_get(self, chat_id: int) -> dict[str, Any] | None:
        return self.dialogs.get(int(chat_id))

    def _telegram_dialog_save(self, chat_id: int, dialog: dict[str, Any]) -> None:
        self.dialogs[int(chat_id)] = dialog

    def _telegram_dialog_clear(self, chat_id: int) -> None:
        self.dialogs.pop(int(chat_id), None)

    def _telegram_web_app_url(self, chat_id: int, numbers: list[str], **kwargs: Any) -> str:
        self.last_overrides = kwargs.get("calc_overrides")
        return "https://developaid.ru/?telegram=1"

    def _telegram_api(self, method: str, payload: dict[str, Any]) -> None:
        return None


class _Base:
    def __init__(self, core: _BotCore) -> None:
        self.core = core

    @staticmethod
    def _help_markup(chat_id: int) -> dict[str, Any]:
        return {"inline_keyboard": [
            [{"text": "Расчёт по кадастровым номерам", "callback_data": "flow_cad_yes"}],
            [{"text": "Собрать ТЭП без кадастра", "callback_data": "flow_cad_no"}],
            [{"text": "Посчитать ВРИ и ТЭП", "callback_data": "vritep_start"}],
            [{"text": "Спросить Платона", "callback_data": "ask_platon"}],
        ]}


def _message(text: str, chat_id: int = 77) -> dict[str, Any]:
    return {"message": {"chat": {"id": chat_id, "type": "private"},
                        "from": {"id": chat_id}, "text": text}}


@pytest.fixture()
def bot(monkeypatch: pytest.MonkeyPatch) -> tuple[_Base, _BotCore, _Service]:
    monkeypatch.setattr(market_bot.threading, "Thread", _Inline)
    core = _BotCore()
    base = _Base(core)
    service = _Service()
    market_bot.install(base, service)
    return base, core, service


def test_bot_command_stands_among_the_calculations(bot) -> None:
    _, core, _ = bot
    assert [item["command"] for item in core.TELEGRAM_BOT_COMMANDS] == [
        "calc", "market", "platon", "help"
    ]


def test_bot_menu_offers_the_market(bot) -> None:
    base, _, _ = bot
    texts = [button["text"] for row in base._help_markup(77)["inline_keyboard"] for button in row]
    assert market_bot.MENU_TEXT in texts


def test_temporary_keyboards_are_left_alone(bot) -> None:
    markup = {"inline_keyboard": [[{"text": "Да", "callback_data": "yes"}]]}
    assert market_bot._help_with_market(markup) == markup


def test_command_with_an_address_answers_with_the_card(bot) -> None:
    base, core, service = bot
    core._telegram_handle_update(_message("/market Москва, ул. Мишина, 46"))
    assert core.delegated == []
    assert len(service.calls) == 1
    assert "Ищу конкурентов" in core.sent[0]["text"]
    card = core.sent[1]["text"]
    assert "620 000 ₽/м²" in card
    assert "Петровский парк II" in card
    assert "в карантине: 3" in card
    assert core.sent[1]["markup"]["inline_keyboard"][0][0]["web_app"]["url"]
    assert core.last_overrides == {"apartment_price_th": 620.0}


def test_bare_command_asks_for_the_address_then_uses_it(bot) -> None:
    base, core, service = bot
    core._telegram_handle_update(_message("/market"))
    assert service.calls == []
    assert core.dialogs[77]["step"] == "market_await_address"

    core._telegram_handle_update(_message("Москва, ул. Мишина, 46"))
    assert len(service.calls) == 1
    assert 77 not in core.dialogs
    assert "Петровский парк II" in core.sent[-1]["text"]


def test_another_command_ends_the_wait_instead_of_being_swallowed(bot) -> None:
    base, core, service = bot
    core._telegram_handle_update(_message("/market"))
    core._telegram_handle_update(_message("/cancel"))
    assert 77 not in core.dialogs
    assert core.delegated and core.delegated[-1]["message"]["text"] == "/cancel"
    assert service.calls == []


def test_everything_else_goes_on(bot) -> None:
    base, core, _ = bot
    core._telegram_handle_update(_message("77:02:0016009:1934"))
    assert core.delegated and core.delegated[-1]["message"]["text"] == "77:02:0016009:1934"


def test_official_average_gets_no_apply_button(bot, monkeypatch: pytest.MonkeyPatch) -> None:
    """Кнопкой применяется только цена предложения.

    Подпись под кнопкой предупреждения не удержит: применённое число потом
    неотличимо от посчитанного по рынку.
    """
    base, core, service = bot
    service.payload = _payload(
        price_summary=None,
        official_price_summary={"price_per_sqm": 410000, "analogue_count": 2, "confidence": 0.3},
    )
    core._telegram_handle_update(_message("/market Москва, ул. Мишина, 46"))
    card = core.sent[-1]["text"]
    assert "Цен предложения не найдено" in card
    assert "отстаёт от рынка" in card
    assert core.sent[-1]["markup"] is None


def test_broken_search_is_reported_to_the_chat(bot) -> None:
    base, core, service = bot
    service.search.configured = False
    core._telegram_handle_update(_message("/market Москва, ул. Мишина, 46"))
    assert "Оценка рынка не выполнена" in core.sent[-1]["text"]
    assert "YANDEX_SEARCH_API_KEY" in core.sent[-1]["text"]


def test_bot_install_is_idempotent(bot) -> None:
    base, core, service = bot
    market_bot.install(base, service)
    assert [item["command"] for item in core.TELEGRAM_BOT_COMMANDS].count("market") == 1
    texts = [button["text"] for row in base._help_markup(77)["inline_keyboard"] for button in row]
    assert texts.count(market_bot.MENU_TEXT) == 1

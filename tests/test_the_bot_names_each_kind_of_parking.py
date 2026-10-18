"""Карточка расчёта в чате называет машино-места по видам — числами движка.

Строка «подземный паркинг — N м/м» складывала подземный, наземный и
приобъектные места, а в жилом проекте брала их из ТЭП страницы или выгрузки,
а не из расчёта. Решение владельца (16.10.2026): раздельно по видам —
подземный (из них к продаже), наземный, приобъектные; числа из расчёта
движка, как в итогах и PDF.

Запуск: python3 -m pytest tests/test_the_bot_names_each_kind_of_parking.py -q
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main_legacy as core  # noqa: E402
from tests import page_blocks  # noqa: E402

INPUTS = {
    "above_parking_enabled": True, "above_parking_spaces": 300,
    "offices_enabled": True, "offices_gba_sqm": 40000, "offices_saleable_sqm": 25000,
    "offices_parking_under_spaces": 120, "offices_parking_over_spaces": 0,
    "_parking_by_hand": ["offices"],
}


@pytest.fixture(scope="module")
def result() -> dict:
    inputs = {**core.DEFAULT_INPUTS, **INPUTS}
    return core._run_authoritative_model(inputs, copy.deepcopy(core.TEP_DEFAULT),
                                         [], None)["consolidated"]


@pytest.fixture(scope="module")
def kinds(result) -> dict:
    # Настоящая функция страницы на настоящем ответе движка.
    return page_blocks.run_json(
        f"const lastResult={json.dumps(result, ensure_ascii=False, default=str)};\n",
        "console.log(JSON.stringify(telegramParkingByKind(lastResult)));")


def _row(result: dict, key: str) -> dict:
    return next(r for r in result["tep"]["rows"] if r["key"] == key)


def test_the_page_takes_each_kind_from_the_engine(result, kinds) -> None:
    under = _row(result, "underground_parking")
    assert under["units"] > under["saleable_units"] > 0, "в проекте нет гостевых — тест пуст"
    assert kinds == {
        "underground": under["units"],
        "underground_saleable": under["saleable_units"],
        "above": _row(result, "above_parking")["units"],
        "attached": result["tep"]["total"]["parking_units"],
    }
    assert kinds["above"] == 300 and kinds["attached"] == 120


NBSP = "\u00a0"


def _num(value: float) -> str:
    return core._telegram_number(value, 0).replace(NBSP, " ")


def _card(monkeypatch, summary: dict) -> str:
    sent: list[str] = []
    monkeypatch.setattr(core, "_telegram_verify_session", lambda session: {"chat_id": 42, "cad": []})
    monkeypatch.setattr(core, "_telegram_user_allowed", lambda chat_id: True)
    monkeypatch.setattr(core, "_telegram_send_message",
                        lambda chat_id, text, **kwargs: sent.append(text))
    monkeypatch.setattr(core, "_telegram_web_app_url", lambda *args, **kwargs: "https://example.org/")
    core.telegram_result(core.TelegramResultRequest(session="s", summary={
        "purchase_price_mln": 6500, "net_profit_mln": 900, "llcr": 1.3, **summary}))
    return sent[0].replace(NBSP, " ")


def test_the_card_names_each_kind(monkeypatch, kinds) -> None:
    text = _card(monkeypatch, {"parking": kinds})
    under, sold = kinds["underground"], kinds["underground_saleable"]
    assert f"• подземный паркинг — {_num(under)} м/м, из них к продаже {_num(sold)}\n" in text
    assert "• наземный паркинг — 300 м/м" in text
    assert "• приобъектные места — 120 м/м" in text
    assert f"подземный паркинг — {_num(under + 300 + 120)}" not in text


def test_a_project_without_other_kinds_prints_only_the_garage(monkeypatch) -> None:
    text = _card(monkeypatch, {"parking": {"underground": 44, "underground_saleable": 40,
                                           "above": 0, "attached": 0}})
    assert "• подземный паркинг — 44 м/м, из них к продаже 40" in text
    assert "наземный паркинг" not in text and "приобъектные" not in text


def test_an_old_page_sum_is_not_called_underground(monkeypatch) -> None:
    text = _card(monkeypatch, {"parking_spaces": 1619})
    assert "подземный паркинг" not in text
    assert "• машино-места всех видов — 1 619 м/м" in text

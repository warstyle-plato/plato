"""Вписанные руками места подземного паркинга доходят до итога расчёта.

«Ручной ввод 49 ничего не меняет» (владелец, прод, «Донской», 07.10.2026).
Места до строки доезжали, а гостевые — нет: в строке ТЭП стояло прежнее число
гостевых (у умолчаний шаблона 109), и продаваемых при любом вводе меньше него
оставался ноль. Теперь гостевые выводятся из вписанных мест (S/11).

Проверяется на отрисованной странице: ввод в поле его же обработчиком →
запрос `/calculate` → ответ сервера.

Запуск: python3 -m pytest tests/test_typed_underground_spaces_reach_the_result.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main_legacy as core  # noqa: E402

TYPE = """(value)=>{
  const el=document.getElementById('f_underground_manual_spaces');
  el.value=value;
  el.dispatchEvent(new Event('change'));
}"""


def _garage_row(body):
    """Строка подземного паркинга в ответе, где бы её ни положили."""
    if isinstance(body, dict):
        if body.get("key") == "underground_parking" and "saleable_units" in body:
            return body
        items = body.values()
    elif isinstance(body, list):
        items = body
    else:
        return None
    for item in items:
        found = _garage_row(item)
        if found:
            return found
    return None


@pytest.fixture(scope="module")
def typed():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    with browser.serve(core.app, 18157) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_context(viewport={"width": 1440, "height": 900}).new_page()
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            page.wait_for_load_state("networkidle")
            # Ждём именно тот расчёт, который вызвал ввод, — по телу запроса.
            with page.expect_response(
                lambda r: r.url.endswith("/calculate") and r.request.method == "POST"
                and '"underground_manual_spaces": 49' in (r.request.post_data or "")
                .replace('":49', '": 49'),
                timeout=60000,
            ) as answer:
                page.evaluate(TYPE, "49")
            response = answer.value
            sent = json.loads(response.request.post_data or "{}")
            return {"sent": sent, "row": _garage_row(response.json())}


def test_the_typed_spaces_go_out_as_the_hand_decision(typed) -> None:
    inputs = typed["sent"].get("inputs") or typed["sent"]
    assert float(inputs["underground_manual_spaces"]) == 49
    assert "underground" in (inputs.get("_parking_by_hand") or [])
    assert "underground" not in (inputs.get("_parking_by_norm") or [])


def test_the_result_builds_49_and_sells_45(typed) -> None:
    row = typed["row"]
    assert row is not None, "в ответе /calculate нет строки подземного паркинга"
    assert row["units"] == 49
    assert row["guest_units"] == 4
    assert row["saleable_units"] == 45

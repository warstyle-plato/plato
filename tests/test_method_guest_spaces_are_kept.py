"""Гостевые места, которые дал метод, доходят до расчёта и при ручной паре.

Метод — норматив по ТЭП (`recalcFromTepByNorms`) или сценарий ГлавАПУ
(`recalcFromTep`) — пишет в пару «постоянные + гостевые». Если пара была
ручной, движок выводил гостевые как места/11, а не брал число метода: на 341
месте 34 вместо 35, и одно гостевое уходило в продажу. Решение владельца
(16.10.2026): гостевые — из метода, пока места те же самые.

Запуск: python3 -m pytest tests/test_method_guest_spaces_are_kept.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main_legacy as core  # noqa: E402

PORT = 18978


def _row(extra: dict) -> dict:
    x = {**core.DEFAULT_INPUTS, "_parking_by_hand": ["underground"],
         "underground_manual_spaces": 341, **extra}
    result = core.calculate(core.CalcRequest(inputs=x, tep=copy.deepcopy(core.TEP_DEFAULT),
                                             rates=[]))
    return next(r for r in result["tep"]["rows"] if r["key"] == "underground_parking")


def test_the_method_guests_reach_the_engine() -> None:
    row = _row({"_underground_method_guest": {"spaces": 341, "guest": 35}})
    assert (row["units"], row["guest_units"], row["saleable_units"]) == (341, 35, 306)


def test_without_the_method_the_eleventh_stays() -> None:
    assert _row({})["guest_units"] == 31


def test_spaces_changed_by_hand_drop_the_method_number() -> None:
    row = _row({"underground_manual_spaces": 340,
                "_underground_method_guest": {"spaces": 341, "guest": 35}})
    assert row["guest_units"] == 31


def test_moscow_region_still_has_no_guests() -> None:
    row = _row({"vri_region": "mo", "_underground_method_guest": {"spaces": 341, "guest": 35}})
    assert row["guest_units"] == 0


PROBE = r"""async () => {
  tep.apartments = Object.assign(tep.apartments || {}, {saleable: 18666.7, units: 280, gns: 28000});
  inputs.underground_manual_spaces = 50; inputs.underground_manual_gns_sqm = 1750;
  markParkingByHand(PROJECT_PARKING_KEY);
  let asked = null;
  const real = window.fetch;
  window.fetch = async (url, opts) => {
    const r = await real(url, opts);
    if (String(url).includes('/tep/derived-by-site')) asked = await r.clone().json();
    return r;
  };
  await recalcFromTepByNorms({silent: true});
  await calculate();
  window.fetch = real;
  const row = lastResult.tep.rows.find(r => r.key === 'underground_parking');
  return {method: asked && asked.parking, hand: parkingByHand(PROJECT_PARKING_KEY),
          units: row.units, guest: row.guest_units, pinned: inputs._underground_method_guest || null};
}"""


@pytest.fixture(scope="module")
def page_state() -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            page.goto(base, wait_until="domcontentloaded")
            # Ждём стартовый расчёт страницы, а не фиксированное время: при
            # медленном раннере 1,5 с не хватало, и `lastResult` оставался null.
            page.wait_for_function("() => typeof lastResult !== 'undefined' && lastResult",
                                   timeout=60_000)
            got = page.evaluate(PROBE)
            page.close()
    return got


def test_the_page_method_guests_reach_the_result(page_state) -> None:
    method = page_state["method"]
    assert method and method["guest"] > 0, page_state
    assert page_state["units"] == method["underground"], page_state
    assert page_state["guest"] == method["guest"], page_state
    # Числа подобраны так, что места/11 даёт другое: проверка падает на подделке.
    assert round(method["underground"] / 11) != method["guest"], page_state

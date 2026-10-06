"""Вписанная руками площадь двора в сумме очередей равна вписанной.

Мытищи (владелец, 05.10.2026): вписал «Благоустройство — площадь двора»
78 595 м², а под полем встало «Двор 78 617 м²». Площадь приводилась к мере на
человека и умножалась на население каждой очереди, а население очереди
округляется вверх: 2 286 + 1 858 + 1 572 + 1 429 = 7 145 жителей против 7 143
у проекта, и к двору прибавлялись 22 м². Теперь очередь получает долю
вписанной площади по своему населению, и сумма сходится ровно.

Проверяется на отрисованной странице: число читается из подписи под полем, а
не из ответа сервера. Предохранитель — методика (поле пустое) по-прежнему
считает двор населением очередей, иначе проверка ниже могла бы пройти и на
счёте, который вписанное число просто копирует.

Запуск: python3 -m pytest tests/test_a_typed_yard_sums_over_the_queues.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main_legacy as core  # noqa: E402

# Своё число, а не число методики (на этих вводных она сама даёт 78 595):
# иначе вписанное и посчитанное на экране не различить.
TYPED = 80000

# Состояние Мытищ: МО, 200 000 м² квартир, четыре очереди 32/26/22/20.
SETUP = """async (yard)=>{
  // Всё — тем писателем, которым это делает человек: поле и ячейка ТЭП.
  const set=(id,value)=>{const el=document.getElementById('f_'+id);
    el.value=value;el.dispatchEvent(new Event('change'));};
  set('vri_region','mo');
  tepCellChanged('apartments','saleable','200000');syncTep(false);
  set('landscaping_area_sqm',String(yard));
  phasing=makeDefaultPhasing(4);phasing.enabled=true;
  phasing.products.apartments=[32,26,22,20];
  await calculate();
  openTab('inputs');renderInputs();
  const box=document.getElementById('landscapingRateNote');
  return {note:box?box.textContent:'', area:lastResult.summary.landscaping_area_sqm,
          typed:Number(inputs.landscaping_area_sqm||0), phased:!!phaseBundle};
}"""


def _shown(note: str) -> int:
    m = re.search(r"Двор\s+([\d\s  ]+)\s*м²", note)
    assert m, f"в подписи нет площади двора: {note!r}"
    return int(re.sub(r"\D", "", m.group(1)))


@pytest.fixture(scope="module")
def seen():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    out: dict = {}
    with browser.serve(core.app, 18165) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            for name, yard in (("typed", TYPED), ("norm", 0)):
                page = engine.new_page(viewport={"width": 1440, "height": 900})
                page.goto(base, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                out[name] = page.evaluate(SETUP, yard)
                page.close()
    return out


def test_the_norm_still_counts_the_queues(seen):
    """Предохранитель: методика двора — население очередей × норма, и сумма
    очередей здесь законно не равна вписанному числу."""
    got = seen["norm"]
    assert got["phased"]
    assert _shown(got["note"]) > 0
    assert _shown(got["note"]) != TYPED, (
        "методика дала ровно вписанное число — сценарий не отличает одно от другого")


def test_the_typed_yard_is_shown_as_typed(seen):
    got = seen["typed"]
    assert got["phased"], "очереди не включились"
    assert _shown(got["note"]) == TYPED, got["note"]
    assert got["area"] == pytest.approx(TYPED, abs=1e-6)

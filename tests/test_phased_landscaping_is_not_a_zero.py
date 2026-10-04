"""Благоустройство проекта с очередями не называется нулём.

Мытищи (владелец, 04.10.2026: «почему там 0 благоустройства в Подмосковье?»).
На экране под полем «Благоустройство, тыс. ₽/м² ГНС»: «Методика класса дала
ноль: сумма площадей очередей — у каждой своё население. Пока ставка здесь не
задана, благоустройства в расчёте нет», а рядом — «Двор 78 595 м²». Деньги
при этом были в CAPEX: свод очередей (`consolidated.summary`) не нёс
`landscaping_per_gns_th`, и подпись читала отсутствие показателя как ноль
методики — то есть отсутствие ключа как ответ.

Проверяется на отрисованной странице с тремя очередями: поле показывает
показатель свода, подпись не говорит «ноль», а показатель сходится с деньгами
CAPEX свода на его ГНС. Предохранитель — подпись при удалённом показателе
обязана сказать «ноль», иначе проверка зелена на любом коде.

Запуск: python3 -m pytest tests/test_phased_landscaping_is_not_a_zero.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main_legacy as core  # noqa: E402

READ = """()=>{
  openTab('inputs');renderInputs();
  const note=document.getElementById('landscapingHouseRateNote');
  const field=document.getElementById('f_landscaping_gns_th_per_sqm');
  const s=lastResult.summary;
  return {phased:!!phaseBundle,note:note?note.textContent:'',field:field?field.value:'',
          money:Number((lastResult.capex||{}).landscaping||0),gns:Number(s.project_gns_sqm||0),
          rate:s.landscaping_per_gns_th};
}"""

# Как было до правки: у свода показателя нет.
STRIP = """()=>{delete lastResult.summary.landscaping_per_gns_th;
  openTab('inputs');renderInputs();
  const note=document.getElementById('landscapingHouseRateNote');
  return note?note.textContent:'';}"""


@pytest.fixture(scope="module")
def seen():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    out: dict = {}
    with browser.serve(core.app, 18161) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            page.evaluate("""async ()=>{
              inputs.vri_region='mo';
              phasing=makeDefaultPhasing(3);phasing.enabled=true;
              await calculate();
            }""")
            page.wait_for_function("()=>phaseBundle&&lastResult&&lastResult.summary",
                                   timeout=60000)
            out["after"] = page.evaluate(READ)
            out["stripped"] = page.evaluate(STRIP)
    return out


def test_the_counterfeit_reads_as_zero(seen):
    """Предохранитель: без показателя подпись говорит «ноль» — значит, ниже
    проверяется именно показатель, а не что-то, что зелено всегда."""
    assert "дала ноль" in seen["stripped"], seen["stripped"]


def test_the_phased_project_shows_its_landscaping(seen):
    got = seen["after"]
    assert got["phased"], "очереди не включились — сценарий не воспроизведён"
    assert got["money"] > 0, "в CAPEX свода благоустройства нет"
    assert "дала ноль" not in got["note"], got["note"]
    assert "в расчёте нет" not in got["note"], got["note"]
    assert float(got["field"] or 0) > 0, f"поле пустое: {got['field']!r}"
    assert got["rate"] == pytest.approx(got["money"] / got["gns"] / 1000)

"""«Очерёдность → Отдельные коммерческие объекты»: очередь — только объектам проекта.

Владелец (04.10.2026, проект Мытищи): включён один объект — «Офисы»; ТЦ/ОСЗ,
ФОК и наземный паркинг выключены, «Офисы 2» заведены с нулями и выключены. А
в блоке очередей стояли селекторы всех заведённых объектов: «Почему в
Очерёдности есть все эти объекты, если по факту включён только один
офисник?» Та же болезнь, что у ТЭП тизера (#596).

Есть ли объект в проекте — отвечает движок (`row_listed`, признак `listed`
строки ТЭП); страница читает признак, а не выводит состав заново. Очередь
спрятанного объекта не сбрасывается: включённый обратно, он возвращается в
свою очередь. Движок очередей выключенный объект и так не считает.

Проверяется отрисованная страница: настоящий PAGE в Chromium, настоящий
`calculate()`.

Запуск: python3 -m pytest tests/test_the_phasing_lists_only_project_objects.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main as wrapper  # noqa: E402

core = wrapper.core
PORT = 18983

INSTANCES = ["offices2", "standalone_retail2", "above_parking2"]


def _owner_project() -> tuple[dict, dict]:
    """Мытищи владельца: включены только офисы, остальное заведено и выключено."""
    x = {"offices_enabled": True, "offices_gba_sqm": 10000, "offices_saleable_sqm": 6000,
         "retail_enabled": False, "sports_enabled": False, "above_parking_enabled": False,
         "offices2_enabled": False, "retail2_enabled": False, "above_parking2_enabled": False,
         "object_instances": INSTANCES}
    t = {"offices": {"gns": 10000, "total_area": 9400, "saleable": 6000}}
    return x, t


def _phased(x: dict, t: dict) -> dict:
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(x)
    tep = copy.deepcopy(core.TEP_DEFAULT)
    for key, row in t.items():
        tep[key].update(row)
    phasing = {"enabled": True, "phase_count": 3, "phase_gap_months": 12,
               "phases": [{"name": f"О{i + 1}", "start_offset_months": 12 * i,
                           "construction_months": 24} for i in range(3)],
               "discrete": {"offices": 3, "standalone_retail": 2}}
    return core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, rates=[], phasing=phasing))


# Отрисованная страница: проект, три очереди, настоящий расчёт и блок очередей.
RENDER = """async (arg)=>{
  if(arg.fake)window.phaseObjectListed=()=>true;
  Object.keys(arg.t).forEach(k=>{tep[k]=Object.assign(tep[k]||{},arg.t[k])});
  Object.assign(inputs, arg.x);
  renderInputs();
  phasing.enabled=true;phasing.user_enabled=true;
  setPhaseCount(3);
  // Сохранённая очередь ТЦ — третья: спрятанный, он не должен её терять.
  phasing.discrete.standalone_retail=3;
  await calculate();
  renderPhasing();
  const read=()=>Array.from(document.querySelectorAll('#assignObjects .field')).map(f=>({
    label:(f.querySelector('label').textContent||'').trim(),
    value:f.querySelector('select').value}));
  const shown=read();
  const keptQueue=phasing.discrete.standalone_retail;
  // Включаем ТЦ обратно — с метрами.
  inputs.retail_enabled=true;inputs.retail_gba_sqm=5000;inputs.retail_saleable_sqm=3000;
  tep.standalone_retail=Object.assign(tep.standalone_retail||{},{gns:5000,total_area:4700,saleable:3000});
  renderInputs();
  await calculate();
  return {shown:shown, keptQueue:keptQueue, back:read()};
}"""


@pytest.fixture(scope="module")
def drawn():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    import browser

    path = browser.chromium_or_skip()
    x, t = _owner_project()
    out: dict = {}
    errors: list[str] = []
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            for fake in (False, True):
                page = engine.new_page(viewport={"width": 1300, "height": 900})
                page.on("pageerror", lambda exc: errors.append(str(exc)))
                page.on("dialog", lambda dialog: dialog.accept())
                page.goto(base, wait_until="domcontentloaded")
                page.evaluate("localStorage.removeItem('plato_v04')")
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(1500)
                out["fake" if fake else "real"] = page.evaluate(
                    RENDER, {"x": x, "t": t, "fake": fake})
                page.close()
    out["errors"] = errors
    return out


def _check_one_office(shown: list[dict]) -> None:
    assert [item["label"] for item in shown] == ["Офисы"], shown


def test_one_enabled_office_gets_one_selector(drawn) -> None:
    assert drawn["errors"] == [], drawn["errors"]
    _check_one_office(drawn["real"]["shown"])
    assert drawn["real"]["shown"][0]["value"] == "3", drawn["real"]["shown"]


def test_the_counterfeit_that_lists_everything_is_caught(drawn) -> None:
    """Подделка «селектор каждому заведённому» обязана ронять проверку."""
    shown = drawn["fake"]["shown"]
    assert len(shown) > 1, shown
    with pytest.raises(AssertionError):
        _check_one_office(shown)


def test_a_hidden_object_keeps_its_queue(drawn) -> None:
    """Спрятанный — не сброшенный: ТЦ, включённый обратно, стоит в своей очереди."""
    assert drawn["real"]["keptQueue"] == 3
    back = {item["label"]: item["value"] for item in drawn["real"]["back"]}
    assert back.get("Коммерция ОСЗ") == "3", back
    assert set(back) == {"Офисы", "Коммерция ОСЗ"}, back


def test_the_queue_engine_does_not_count_disabled_objects() -> None:
    """Движок очередей: выключенный объект не стоит ни в одной очереди."""
    got = _phased(*_owner_project())
    disabled = ("standalone_retail", "sports", "above_parking", *INSTANCES)
    for phase in got["phases"]:
        rows = {row["key"]: row for row in phase["result"]["tep"]["rows"]}
        for key in disabled:
            row = rows.get(key) or {}
            assert not float(row.get("gns") or 0), (phase.get("name"), key)
            assert not float(row.get("saleable") or 0), (phase.get("name"), key)
    rows = {row["key"]: row for row in got["consolidated"]["tep"]["rows"]}
    assert rows["offices"]["listed"] is True
    for key in disabled:
        assert rows[key]["listed"] is False, key

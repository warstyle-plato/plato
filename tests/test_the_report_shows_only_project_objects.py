"""Таблица ТЭП отчёта показывает только объекты проекта.

Владелец (29.09.2026, прод): в «Результат → Отчёт» стояли нулями «Коммерция
ОСЗ», «Коммерция ОСЗ 2…5», «Офисы 2…4» — «объектов ОСЗ и ТЦ нет уже, они
удалены, а в отчёте есть?». Окно классов и вводные экземпляры вне проекта уже
прятали, а ТЭП движка отдавал их строки всем поверхностям.

Состав решает движок одним предикатом (`tep_row_outside_project`) и ставит
признак `excluded` на строку — отчёт страницы, PDF и Платон читают его, а не
выводят состав заново. Законный ноль продукта дома (кладовые, СОШ) в составе
и остаётся строкой. Итог таблицы не меняется: скрытые строки пусты.

Запуск: python3 -m pytest tests/test_the_report_shows_only_project_objects.py -q
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
PORT = 18979

# Что видно в проекте владельца: первый офис и добавленный второй.
SHOWN_OBJECTS = {"Офисы", "Офисы 2"}
OBJECT_LABELS = {row.get("label") for key, row in core.TEP_DEFAULT.items()
                 if key in core._BY_KEY}


def _project() -> tuple[dict, dict]:
    """Первый офис, добавленный второй; ТЦ выключен, прочие экземпляры удалены.

    У удалённого «ОСЗ 2» в ТЭП остались прежние метры, а «ОСЗ 3» включён
    вводной без записи в составе — так выглядит проект после удаления.
    """
    x = dict(core.DEFAULT_INPUTS)
    x.update(offices_enabled=True, offices_gba_sqm=10000, offices_saleable_sqm=6000,
             offices2_enabled=True, offices2_gba_sqm=8000, offices2_saleable_sqm=5000,
             retail_enabled=False, retail3_enabled=True,
             object_instances=["offices2"])
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["offices"].update(gns=10000, total_area=9400, saleable=6000)
    t["offices2"].update(gns=8000, total_area=7520, saleable=5000)
    t["standalone_retail2"].update(gns=5000, total_area=4700, saleable=3000)
    return x, t


def _run(x: dict, t: dict, phasing: dict | None = None) -> dict:
    if phasing:
        got = core.calculate_phased(core.PhasedCalcRequest(
            inputs=copy.deepcopy(x), tep=copy.deepcopy(t), rates=[], phasing=phasing))
        return got["consolidated"]
    return core.calculate(core.CalcRequest(
        inputs=copy.deepcopy(x), tep=copy.deepcopy(t), rates=[]))


PHASED = {"enabled": True, "phase_count": 2, "phase_gap_months": 12,
          "phases": [{"name": f"О{i + 1}", "start_offset_months": 12 * i,
                      "construction_months": 24} for i in range(2)],
          # Второй офис — во второй очереди: в первой он выключен, и ответ
          # первой очереди не прячет его из свода.
          "discrete": {"offices": 1, "offices2": 2}}


def _shown(result: dict) -> list[dict]:
    return [row for row in result["tep"]["rows"] if not row["excluded"]]


@pytest.mark.parametrize("phasing", [None, PHASED], ids=["single", "phased"])
def test_the_engine_hides_objects_outside_the_project(phasing) -> None:
    result = _run(*_project(), phasing)
    labels = {row["label"] for row in _shown(result)}
    assert labels & OBJECT_LABELS == SHOWN_OBJECTS, sorted(labels & OBJECT_LABELS)
    # Законный ноль продукта дома — в составе, строка остаётся.
    rows = {row["key"]: row for row in result["tep"]["rows"]}
    for key in ("storage", "school"):
        assert rows[key]["excluded"] is False, key
    # Ключи не пропадают у тех, кто ищет строку по имени.
    assert {"standalone_retail", "offices3"} <= set(rows)


@pytest.mark.parametrize("phasing", [None, PHASED], ids=["single", "phased"])
def test_the_totals_do_not_move(phasing) -> None:
    """Скрытые строки пусты: итог — сумма показанных, как и всех строк."""
    result = _run(*_project(), phasing)
    total = result["tep"]["total"]
    for field in (*core.TEP_SUMMABLE_FIELDS, "units"):
        hidden = sum(float(row.get(field) or 0) for row in result["tep"]["rows"]
                     if row["excluded"] and row["key"] in core._BY_KEY)
        assert hidden == 0.0, field
    for field in core.TEP_SUMMABLE_FIELDS:
        assert sum(row[field] for row in _shown(result)) == pytest.approx(total[field]), field


def test_a_disabled_object_with_area_stays_in_the_table() -> None:
    """Выключенный объект с метрами складывается в итог — строку не прячут."""
    x, t = _project()
    x["offices_enabled"] = False
    rows = {row["key"]: row for row in _run(x, t)["tep"]["rows"]}
    assert rows["offices"]["gns"] > 0
    assert rows["offices"]["excluded"] is False


def test_the_predicate_is_the_composition() -> None:
    x, _t = _project()
    empty = {"gns": 0.0}
    assert core.tep_row_outside_project(x, "offices2", empty) is False
    assert core.tep_row_outside_project(x, "offices3", empty) is True
    assert core.tep_row_outside_project(x, "standalone_retail", empty) is True
    assert core.tep_row_outside_project(x, "storage", empty) is False


def test_the_pdf_prints_the_same_composition() -> None:
    pypdf = pytest.importorskip("pypdf")
    x, t = _project()
    result = _run(x, t)
    content = core._build_developaid_pdf({
        "project_name": "Состав", "result": result, "inputs": x, "tep": t, "rates": []})
    path = Path("/tmp") / "composition.pdf"
    path.write_bytes(content)
    text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(str(path)).pages)
    tep_part = text.split("ТЭП", 1)[1][:3000]
    assert "Офисы 2" in tep_part
    for label in ("Коммерция ОСЗ", "Офисы 3", "Офисы 4"):
        assert label not in tep_part, label


def test_platon_reads_the_same_composition() -> None:
    x, t = _project()
    req = core.AgentChatRequest(message="ТЭП", inputs=x, tep=t)
    got = core._tool_explain_metric(req, {"consolidated": _run(x, t)}, "tep", "consolidated")
    labels = {row["label"] for row in got["tep"]}
    assert labels & OBJECT_LABELS == SHOWN_OBJECTS


# Отрисованная страница: настоящий `calculate()` и таблица отчёта.
RENDER = """async (arg)=>{
  Object.keys(arg.t).forEach(k=>{tep[k]=Object.assign(tep[k]||{},arg.t[k])});
  Object.assign(inputs, arg.x);
  renderInputs();
  await calculate();
  const rows=Array.from(document.querySelectorAll('#reportTep tbody tr:not(.sub)'))
    .map(tr=>(tr.cells[0].textContent||'').trim());
  const foot=Array.from(document.querySelectorAll('#reportTep tfoot th, #reportTep tfoot td'))
    .map(th=>(th.textContent||'').trim());
  return {rows:rows, foot:foot};
}"""


@pytest.fixture(scope="module")
def drawn():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    import browser

    path = browser.chromium_or_skip()
    x, t = _project()
    errors: list[str] = []
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1300, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(base, wait_until="domcontentloaded")
            page.evaluate("localStorage.removeItem('plato_v04')")
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            got = page.evaluate(RENDER, {"x": x, "t": t})
            page.close()
    got["errors"] = errors
    got["result"] = _run(x, t)
    return got


def test_the_drawn_report_shows_only_project_objects(drawn) -> None:
    assert drawn["errors"] == [], drawn["errors"]
    assert drawn["rows"], "таблица отчёта пуста — мерить нечего"
    objects = {row for row in drawn["rows"] if row in OBJECT_LABELS}
    assert objects == SHOWN_OBJECTS, drawn["rows"]
    # Продукты дома с законным нулём — на месте.
    assert "Кладовые" in drawn["rows"], drawn["rows"]

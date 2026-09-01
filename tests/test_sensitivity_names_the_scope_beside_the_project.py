"""Чувствительность называет охват рядом с величиной всего проекта.

«Чувствительность в очередности считает кажется только первую или самую слабую
очередь? В целом LLCR 1,18, а чувствительность показала данные по очереди, где
0,9» (владелец, 31.08.2026).

Считает она то, что выбрано: у многоочередного проекта охват по умолчанию —
слабейшая очередь, и это осознанный выбор, банк смотрит на неё. Ошибки счёта
здесь нет. Есть другое: на экране рядом стоит LLCR всего проекта, и два разных
числа под одним словом читаются как расхождение расчёта. Поэтому величина
проекта едет вместе с базой — не вместо неё и не подменяя выбор.

`None` в этом поле значит «не считали» (одноочередной проект или охват «весь
проект»), а не «столько же»: пустое поле нельзя показывать как ноль.

Запуск: python3 -m pytest tests/test_sensitivity_names_the_scope_beside_the_project.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))


def test_the_default_scope_for_a_phased_project_is_the_weakest_phase() -> None:
    """Умолчание остаётся прежним — меняется не выбор, а то, как он назван."""
    source = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    assert 'scope = "weakest_phase" if base_bundle.get("mode") == "phased"' in source


def test_the_project_value_travels_with_the_base() -> None:
    source = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    body = source[source.index("def run_sensitivity("):source.index("def _phase_llcr(")]
    assert '"project_value"' in body and '"project_label"' in body
    assert 'scope != "consolidated"' in body, \
        "у охвата «весь проект» второй величины нет — сравнивать не с чем"
    assert '_metric_value(\n            base_bundle, metric, "consolidated", selected_view)' in body, \
        "величина проекта считается тем же способом, что и база — второго счёта нет"


def test_the_screen_says_it_is_not_the_whole_project() -> None:
    page = core.PAGE
    block = page[page.index("function renderReportSensitivity"):]
    block = block[:block.index("\nfunction ", 1)]
    assert "project_value" in block
    assert "не весь проект" in block
    assert "===null||base.project_value===undefined?''" in block.replace(" ", ""), \
        "пустое поле не должно печататься как число"


def test_the_paper_says_the_same() -> None:
    source = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    start = source.index('f"охват: {base.get(\'scope_label\')')
    fragment = source[start:start + 400]
    assert "не весь проект" in fragment
    assert 'base.get("project_value") is None' in fragment, \
        "у одноочередного проекта приписки быть не должно"


def test_a_single_phase_project_gets_no_second_number() -> None:
    """Одноочередной проект в эту ветку не заходит — приписке неоткуда взяться."""
    source = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    body = source[source.index("def run_sensitivity("):source.index("def _phase_llcr(")]
    guard = re.search(r'if scope != "consolidated" and base_bundle\.get\("mode"\) == "phased":', body)
    assert guard, "условие должно требовать и охват, и многоочередной режим"


def test_a_phased_project_really_carries_both_numbers() -> None:
    """Проверка счётом, а не строкой: движок обязан вернуть обе величины."""
    import copy
    import importlib

    fixture = importlib.import_module("test_sensitivity")
    inputs, tep = fixture.project()
    report = core.run_sensitivity(inputs, tep, [], copy.deepcopy(fixture.PHASING),
                                  metric="llcr")
    base = report["base"]
    assert base["scope"] == "weakest_phase", "умолчание охвата не менялось"
    assert base["project_value"] is not None, "величины проекта рядом с базой нет"
    assert base["project_label"], "у величины проекта нет имени охвата"
    # Ради этого всё и написано: на слабейшей очереди база ниже проектной.
    assert base["value"] <= base["project_value"] + 1e-9

    whole = core.run_sensitivity(inputs, tep, [], copy.deepcopy(fixture.PHASING),
                                 metric="llcr", scope="consolidated")
    assert whole["base"]["project_value"] is None, \
        "при охвате «весь проект» второй величины быть не должно"

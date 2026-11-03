"""Проверка терминов БРИДЖа знает, что у проекта без ПФ плитки нет.

Владелец 06.10.2026, v0.25.10, проект без ПФ: на главной плашка «Слой
перестройки не нашёл 1 узла страницы — термины БРИДЖа переименованы частично
(2 из 3)». Плитку «Пиковый БРИДЖ» из шапки убирает сама страница, когда движок
отвечает `report.layout.project_finance = false` (нежилой проект вне ДДУ), —
слой же ждал её всегда.

Гоняется настоящий код: `relabelBridge` слоя и `reportLayout` страницы.

Запуск: python3 -m pytest tests/test_ia_bridge_terms_follow_the_report_layout.py -q
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core
_ROOT = Path(__file__).resolve().parent.parent
_OVERLAY = (_ROOT / "ia_preview" / "assets" / "overlay.js").read_text(encoding="utf-8")
NODE = shutil.which("node")


def _page_function(name: str) -> str:
    page = core.PAGE
    start = page.index(f"function {name}(")
    return page[start:page.index("\n}", start) + 2]


def _harness() -> str:
    start = _OVERLAY.index("var bridgeChecked = false;")
    end = _OVERLAY.index("function explainBridge()")
    return (
        "var missing = []; function report(){} function explainBridge(){}\n"
        "var lastResult = null;\n"
        "function pageResult() { return lastResult; }\n"
        + _page_function("reportLayout") + "\n"
        + _OVERLAY[start:end]
    )


def _run(result: dict, kpi: list[str], table: list[str]) -> list[str]:
    script = _harness() + f"""
function node(text) {{ return {{ textContent: text }}; }}
var KPI = {json.dumps(kpi, ensure_ascii=False)}.map(node);
var TABLE = {json.dumps(table, ensure_ascii=False)}.map(node);
var document = {{ querySelectorAll: function (sel) {{
  return sel.indexOf('#reportKpi') === 0 ? KPI : TABLE; }} }};
lastResult = {json.dumps(result, ensure_ascii=False)};
relabelBridge();
console.log(JSON.stringify(missing));
"""
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


TABLE = ["Расчётный лимит", "1 000", "Пиковый остаток", "900"]


def test_a_project_without_pf_raises_no_false_alarm():
    if not NODE:
        pytest.skip("node недоступен")
    nonres = {"report": {"layout": {"housing": False, "project_finance": False,
                                    "nonres_strategy": True, "nonres_tiles": []}}}
    assert _run(nonres, ["Собственные средства до ПФ"], TABLE) == []


def test_a_housing_project_still_reports_a_missing_tile():
    if not NODE:
        pytest.skip("node недоступен")
    housing = {"report": {}}
    got = _run(housing, ["Собственные средства до ПФ"], TABLE)
    assert len(got) == 1 and "2 из 3" in got[0]
    assert _run(housing, ["Пиковый БРИДЖ"], TABLE) == []

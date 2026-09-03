"""Балл площадки КРТ в списке и в карточке считается из одного источника.

«А это не бред случаем? При 1,23 LLCR» (владелец, 03.09.2026): у одной
площадки на экране стояли 41 · Низкое в списке и 59 · Среднее в карточке.
Функция балла одна, но числа она брала из двух копий одного счёта — строки
рейтинга и сохранённого отчёта площадки, — и карточка после загрузки отчёта
считала по нему, а список по строке. Теперь берётся тот источник, что
посчитан позже, и после загрузки отчёта пересчитываются оба места.

Гоняется настоящий код страницы через node, а не его пересказ.

Запуск: python3 -m pytest tests/test_the_krt_score_has_one_source.py -q
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.ui import auctions_page  # noqa: E402


def _function(script: str, name: str) -> str:
    start = script.index(f"function {name}(")
    depth, index = 0, script.index("{", start)
    for index in range(index, len(script)):
        if script[index] == "{":
            depth += 1
        elif script[index] == "}":
            depth -= 1
            if depth == 0:
                return script[start:index + 1]
    raise AssertionError(name)


def _run(rank: dict, model: dict | None) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    page = auctions_page()
    script = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", page, re.S))
    js = _function(script, "krtScoreSource") + "\n" + f"""
const state={{krtModels:{{}},krtRank:{{s:{json.dumps(rank)}}}}};
if({json.dumps(model)})state.krtModels.s={json.dumps(model)};
console.log(JSON.stringify(krtScoreSource({{slug:'s'}})));
"""
    out = subprocess.run([node, "-e", js], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


RANK = {"computed_at": 100, "project_llcr_x": 1.14, "margin_pct": 11.7, "weakest_phase_llcr_x": 1.12}
REPORT = {"available": True, "computed_at": 200,
          "metrics": {"project_llcr_x": 1.23, "margin_pct": 15.0, "weakest_phase_llcr_x": 1.2}}


def test_the_newer_report_wins_over_the_older_row() -> None:
    got = _run(RANK, REPORT)
    assert got["from"] == "report" and got["metrics"]["project_llcr_x"] == 1.23


def test_an_older_or_undated_report_does_not_override_the_row() -> None:
    assert _run(RANK, {**REPORT, "computed_at": 50})["from"] == "rank"
    undated = dict(REPORT)
    del undated["computed_at"]
    assert _run(RANK, undated)["from"] == "rank"
    assert _run(RANK, None)["from"] == "rank"


def test_an_empty_row_never_beats_a_report() -> None:
    """Строка без чисел модели спорить с отчётом не может.

    Отчёт без даты проигрывал ПУСТОЙ строке рейтинга, и площадка с посчитанной
    моделью стояла в списке «не посчитанной» — балл терял снижения и
    объяснения. Спор по дате — только когда числа есть у обоих.
    """
    undated = dict(REPORT)
    del undated["computed_at"]
    assert _run({}, undated)["from"] == "report"
    assert _run({"computed_at": 500}, undated)["from"] == "report"
    assert _run({}, REPORT)["metrics"]["project_llcr_x"] == 1.23


def test_the_card_header_is_refreshed_after_the_report_loads() -> None:
    page = auctions_page()
    body = _function("\n".join(re.findall(r"<script[^>]*>(.*?)</script>", page, re.S)), "loadKrtReport")
    assert "computed_at:Number(d.computed_at||0)" in body
    assert "refreshKrtScoreBox(x)" in body and "renderKrt()" in body
    assert 'id="krtScoreBox"' in page

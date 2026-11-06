"""Сверщик «Книга ↔ движок» (`scripts/book_engine_parity.py`) сам проверен.

Полный прогон по всем эталонам идёт отдельным workflow («Книга ↔ движок»), на
PR, трогающем методику или книгу, и ночью на main. Здесь — то, без чего его
зелёный ничего не значит:

* эталоны покрывают каждый вид проекта, который обязан сходиться;
* жилая книга и книга нежилого проекта сходятся с движком, а испорченная
  формула в каждой из них даёт расхождение с подписью «проект, строка, книга,
  движок, разница»;
* известное расхождение методики (`KNOWN_GAPS`) существует на самом деле:
  исчезло — запись надо снять, иначе она прячет будущую поломку.

Запуск: python3 -m pytest tests/test_book_engine_parity.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("openpyxl")

import book_engine_parity as bep  # noqa: E402
import main_legacy as core  # noqa: E402

_BUILT: dict[str, tuple] = {}


def _built(name: str) -> tuple:
    if name not in _BUILT:
        _BUILT[name] = bep.build(core, name)
    return _BUILT[name]


def test_the_reference_set_covers_every_kind_of_project() -> None:
    titles = " | ".join(title for _, title, _ in bep.PROJECTS.values())
    for word in ("Жильё", "Офис по ДДУ", "Офис без ДДУ", "ТЦ", "ФОК", "паркинг", "Смешанный"):
        assert word in titles, word
    assert {kind for kind, _, _ in bep.PROJECTS.values()} == {"v4", "office"}


def test_the_housing_book_agrees_and_its_known_gaps_are_real() -> None:
    result = bep.check(core, "default", built=_built("default"))
    assert result.checked > 100
    assert result.mismatches == [], [line.text("default") for line in result.mismatches]
    # Каждая запись KNOWN_GAPS ещё расходится: исчезло расхождение — запись снять.
    seen = {key for key in bep.KNOWN_GAPS for line, _ in result.known if line.row.startswith(key)}
    assert seen == set(bep.KNOWN_GAPS), set(bep.KNOWN_GAPS) - seen


def test_a_tampered_housing_book_is_caught() -> None:
    result = bep.check(core, "default", bep.tamper_v4_reserve, built=_built("default"))
    rows = [line.row for line in result.mismatches]
    assert "CAPEX: Резерв" in rows and any(row.startswith("ОТЧЕТ: CAPEX") for row in rows), rows
    text = result.mismatches[0].text("default")
    assert text.startswith("проект default, строка «") and "книга" in text and "движок" in text and "разница" in text


def test_the_office_book_agrees_and_a_tampered_one_is_caught() -> None:
    clean = bep.check(core, "office_ddu", built=_built("office_ddu"))
    assert clean.checked > 30
    assert clean.mismatches == [], [line.text("office_ddu") for line in clean.mismatches]
    tampered = bep.check(core, "office_ddu", bep.tamper_office_revenue, built=_built("office_ddu"))
    assert any(line.row.endswith("Выручка проекта") for line in tampered.mismatches), tampered.mismatches


def test_a_word_against_a_number_is_a_mismatch() -> None:
    assert not bep.Line("IRR", "N/A — долг не погашен", 0.12, ratio=True).agrees()
    assert bep.Line("IRR", "N/A — долг не погашен", "N/A — долг не погашен").agrees()
    assert not bep.Line("Выручка", None, 5.0).agrees()
    assert bep.Line("Выручка", 1000.0005, 1000.0).agrees()
    assert not bep.Line("Выручка", 1000.2, 1000.0).agrees()

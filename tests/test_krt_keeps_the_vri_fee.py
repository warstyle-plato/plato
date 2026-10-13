"""Режим «Требование КРТ» плату за смену ВРИ не отменяет — её срезают льготы проекта.

«У нас ошибка в режиме КРТ. Если льгота не генерируется за счёт строительства
не жилья, то плата за смену ВРИ есть… Если льготы нет, то режим КРТ плату не
отменяет» (владелец, 13.10.2026). Прежде переключение в КРТ обнуляло плату
(`krtClearsVriFee`), а движок предупреждал, что «в КРТ платы нет».

Закреплено:
- КРТ без нежилья и без передачи квартир — плата начисляется целиком;
- КРТ с офисами/ТЦ — плата уменьшена ровно на льготы, которые уже считает
  `vri_benefits_for` (карточка «Льготы» вкладки «ВРИ»), и не ниже нуля;
- вписанная руками льгота главнее расчётной;
- очередь не получает льготу второй раз;
- все читатели `vri_relief` передают ТЭП — без него льгота КРТ молча нулевая.

Запуск: python3 -m pytest tests/test_krt_keeps_the_vri_fee.py -q
"""

from __future__ import annotations

import copy
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
for _key in ("AUCTION_KRT_WEEKLY", "AUCTION_KRT_WATCH", "DEVELOPAID_WORKBOOK_CACHE",
             "NORMATIVES_WATCH", "NAGATINO_EGRN_READ"):
    os.environ.setdefault(_key, "0")

OUTSIDE = {"recognized": ["77:05:0004001:1"],
           "territory": {"district": "Нагатино-Садовники", "inside_ttc": False,
                         "cadastral_quarter": "77:05:0004001"}}


@pytest.fixture(scope="module")
def core():
    import main as wrapper
    return wrapper.core


def _calc(core, inputs, tep):
    return core._calculate_economics(core.CalcRequest(inputs=inputs, tep=tep))


def _nagatino(core, **changes):
    import golden_snapshot
    case = golden_snapshot.s_nagatino(core, ROOT)
    inputs = dict(case["inputs"], vri_required=True,
                  _cadastral_analysis=copy.deepcopy(OUTSIDE), **changes)
    return inputs, case["tep"], case["phasing"]


def test_krt_without_non_residential_keeps_the_whole_fee(core) -> None:
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(social_area_source="manual", land_rights_cost_mln=2864.3)
    result = _calc(core, inputs, copy.deepcopy(core.TEP_DEFAULT))
    totals = result["vri"]["totals"]
    assert result["vri"]["benefits"]["total_mln"] == 0
    assert totals["relief_basis"] == "krt_benefits"
    assert totals["relief"] == 0
    assert result["capex"]["land_rights"] == pytest.approx(2864.3 * 1e6, rel=1e-9)
    # Прежнее «в КРТ отдельного платежа городу нет» — неверное правило.
    assert not [w for w in result["vri"].get("warnings") or [] if "платежа городу нет" in w]


def test_krt_with_offices_cuts_the_fee_by_the_project_benefits(core) -> None:
    inputs, tep, _ = _nagatino(core, social_area_source="manual", land_rights_cost_mln=30000.0)
    result = _calc(core, inputs, tep)
    benefits = result["vri"]["benefits"]
    assert benefits["mpt_mln"] > 0, "у офисов и ТЦ Нагатино льгота за МПТ есть"
    totals = result["vri"]["totals"]
    assert totals["relief_basis"] == "krt_benefits"
    assert totals["relief"] == pytest.approx(benefits["total_mln"] * 1e6, rel=1e-9)
    assert result["capex"]["land_rights"] == pytest.approx(
        (30000.0 - benefits["total_mln"]) * 1e6, rel=1e-9)


def test_benefits_bigger_than_the_fee_zero_it_and_no_lower(core) -> None:
    inputs, tep, _ = _nagatino(core, social_area_source="manual", land_rights_cost_mln=1000.0)
    result = _calc(core, inputs, tep)
    assert result["vri"]["benefits"]["total_mln"] > 1000.0
    assert result["vri"]["totals"]["relief"] == pytest.approx(1000.0 * 1e6)
    assert result["capex"]["land_rights"] == pytest.approx(0.0, abs=1e-6)


def test_outside_krt_the_benefits_stay_a_suggestion(core) -> None:
    inputs, tep, _ = _nagatino(core, social_area_source="norm", land_rights_cost_mln=30000.0)
    result = _calc(core, inputs, tep)
    assert result["vri"]["benefits"]["total_mln"] > 0
    assert result["vri"]["totals"]["relief"] == 0
    assert result["vri"]["totals"]["relief_basis"] == "none"


def test_a_relief_entered_by_hand_wins_in_krt(core) -> None:
    inputs, tep, _ = _nagatino(core, social_area_source="manual", land_rights_cost_mln=30000.0,
                               vri_relief_mode="amount", vri_relief_mln=1200.0)
    result = _calc(core, inputs, tep)
    assert result["vri"]["totals"]["relief_basis"] == "amount"
    assert result["vri"]["totals"]["relief"] == pytest.approx(1200.0 * 1e6)


def test_phases_do_not_take_the_krt_relief_twice(core) -> None:
    inputs, tep, phasing = _nagatino(core, social_area_source="manual",
                                     land_rights_cost_mln=30000.0)
    assert phasing.get("enabled"), "эталон Нагатино — с очередями"
    bundle = core._run_authoritative_model(inputs, tep, [], phasing)
    totals = bundle["vri"]["totals"]
    relief = bundle["vri"]["benefits"]["total_mln"] * 1e6
    assert totals["relief"] == pytest.approx(relief, rel=1e-9)
    assert totals["amount"] == pytest.approx(30000.0 * 1e6 - relief, rel=1e-6)
    assert totals["relief_basis"] == "krt_benefits"


def test_every_reader_of_vri_relief_passes_the_tep() -> None:
    """Без ТЭП `vri_relief` не знает объектов, и льгота КРТ молча выходит нулём."""
    calls = []
    for path in list((ROOT / "engine").glob("*.py")) + list(ROOT.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"(?<![\w.])vri_relief\(", text):
            line_start = text.rfind("\n", 0, match.start()) + 1
            if text[line_start:match.start()].lstrip().startswith("def "):
                continue
            depth, i = 0, match.end() - 1
            while True:
                ch = text[i]
                depth += ch == "("
                depth -= ch == ")"
                if depth == 0:
                    break
                i += 1
            args = text[match.end():i]
            top = 0
            commas = 0
            for ch in args:
                top += ch in "([{"
                top -= ch in ")]}"
                commas += ch == "," and top == 0
            calls.append((path.name, commas + 1))
    assert len(calls) >= 5, calls
    assert all(count == 3 for _, count in calls), calls

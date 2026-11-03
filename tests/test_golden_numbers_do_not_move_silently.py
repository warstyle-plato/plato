"""Экономика эталонных проектов не меняется молча.

28–29.09.2026 за сутки уехало три десятка выпусков, и у владельца «само»
поменялось то, что работало: паркинг первых этажей офиса, LLCR проекта,
подписи ТЭП на телефоне. Каждый PR был зелёным — ни одна проверка не держала
ЧИСЛА целого проекта, только свои частные утверждения.

Здесь держатся ключевые числа восьми эталонных проектов (`scripts/golden_snapshot.py`):
ТЭП по строкам, выручка по продуктам, CAPEX по статьям, финансирование, LLCR,
NPV/IRR, итоги отчёта. Любое их изменение роняет тест. Изменение намеренное —
снимок обновляется явным коммитом с причиной:

    python3 scripts/golden_snapshot.py --update --reason "что и почему"

и та же причина строкой в описании PR (tests/golden/README.md).
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import golden_snapshot as golden  # noqa: E402

HOW = ('Намеренное изменение — `python3 scripts/golden_snapshot.py --update --reason "…"` '
       "отдельным коммитом и та же строка в описании PR; иначе это регресс.")


@pytest.fixture(scope="module")
def current() -> dict:
    return golden.golden_view(golden.snapshot(ROOT))


def _stored(name: str) -> dict:
    path = golden.GOLDEN_DIR / f"{name}.json"
    assert path.exists(), f"нет снимка {path.name}: {HOW}"
    return json.loads(path.read_text("utf-8"))


@pytest.mark.parametrize("name", [*golden.SCENARIOS, "krt_catalog"])
def test_the_reference_project_keeps_its_numbers(current, name) -> None:
    got = current[name]
    assert "error" not in got, f"эталон «{name}» больше не считается: {got.get('error')}"
    rows = golden.diff({name: _stored(name)}, {name: got})
    shown = "\n".join(f"  {key}: {a} → {b}" for key, a, b in rows[:30])
    more = f"\n  … ещё {len(rows) - 30}" if len(rows) > 30 else ""
    assert not rows, f"эталон «{name}»: сдвинулось {len(rows)} чисел\n{shown}{more}\n{HOW}"


def test_every_snapshot_is_explained() -> None:
    """Последняя строка журнала называет именно те снимки, что лежат в наборе."""
    lines = [line for line in golden.CHANGES.read_text("utf-8").splitlines()
             if line.startswith("- ")]
    assert lines, "журнал снимков пуст"
    digest = golden.golden_digest()
    assert lines[-1].startswith(f"- {digest} "), (
        f"снимки tests/golden/ (отпечаток {digest}) не записаны в CHANGES.md последней "
        f"строкой — их правили руками или без --reason. {HOW}")
    reason = lines[-1].split(":", 1)[-1].strip()
    assert len(reason) >= 15, "причина обновления не названа"


def test_the_guard_notices_a_moved_number(current) -> None:
    """Контрпример: подделанный LLCR, пропавшая строка ТЭП и сдвиг CAPEX видны сравнению."""
    stored = _stored("mixed_osz_parking")
    forged = copy.deepcopy(stored)
    part = forged["consolidated"]
    part["summary.llcr"] = round(part["summary.llcr"] + 0.04, 4)
    part["capex.total"] = part["capex.total"] * 1.001
    del part["tep.offices.saleable"]
    keys = {key for key, _, _ in golden.diff({"x": stored}, {"x": forged})}
    assert {"x.consolidated.summary.llcr", "x.consolidated.capex.total",
            "x.consolidated.tep.offices.saleable"} <= keys


def test_the_office_garage_on_the_first_floors_takes_saleable_area(current) -> None:
    """Предохранитель смысла эталона: 40 мест на первых этажах вычтены из ПРОДАННОГО офиса.

    Строка ТЭП держит площадь здания, вычет живёт в структуре продукта
    (владелец, 29.09.2026). Без этой проверки снимок мог бы честно хранить уже
    сломанное число.
    """
    tep = current["mixed_osz_parking"]["consolidated"]
    gba, saleable, over = 40000.0, 24000.0, 40
    per_space = 25.0
    expected = saleable * (gba - over * per_space) / gba
    assert tep["tep.offices.parking_over_units"] == over
    assert tep["tep.offices.saleable"] == pytest.approx(saleable, rel=1e-6)
    assert tep["report.products[offices].saleable"] == pytest.approx(expected, rel=1e-6)

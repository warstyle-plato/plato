"""Строка «По очередям» называет очереди, а не печатает None.

Экран владельца 08.09.2026: «**По очередям:** None — 1,260x, None — 1,519x,
None — 1,081x, None — 1,185x». Числа верные, имена — нет: `_phase_llcr` кладёт
ключ `name`, а печать спрашивала `phase` — ключа с таким именем в строке нет
вовсе. Ответ на «какая очередь слабее» — это и есть имя, и None не отвечает ни
на что; хуже того, снаружи это выглядит поломкой РАСЧЁТА, а не подписи.

Правило шире опечатки: **ключ читают у того, кто его кладёт.** Проверка держит
не имя ключа, а то, что видит человек, — иначе она сойдётся на переименовании и
разойдётся с экраном.

Запуск: python3 -m pytest tests/test_the_queue_line_names_the_queues.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


@pytest.fixture(scope="module")
def phased_bundle() -> dict:
    return core.calculate_phased(core.PhasedCalcRequest(
        inputs=copy.deepcopy(core.DEFAULT_INPUTS),
        tep=copy.deepcopy(core.TEP_DEFAULT),
        rates=[],
        phasing={"enabled": True, "phase_count": 3},
    ))


def test_every_queue_row_carries_a_name(phased_bundle: dict) -> None:
    rows = core._phase_llcr(phased_bundle)
    assert len(rows) == 3, rows
    for row in rows:
        assert row.get("name"), f"у строки очереди нет имени: {row}"
        assert isinstance(row.get("llcr_x"), float)


def test_the_printed_line_names_the_queues_and_never_says_none(phased_bundle: dict) -> None:
    """Проверяется ТА САМАЯ печать, которую видел человек, а не её пересказ.

    Первая версия этой проверки собирала строку сама и на исходной поломке
    оставалась зелёной — то есть проверяла себя. Зовём `_local_llcr_breakdown`.
    """
    req = core.AgentChatRequest(message="почему такой LLCR?",
                                inputs=copy.deepcopy(core.DEFAULT_INPUTS),
                                tep=copy.deepcopy(core.TEP_DEFAULT))
    text = core._local_llcr_breakdown(req, phased_bundle)
    line = [row for row in text.splitlines() if "По очередям" in row]
    assert line, f"строки об очередях нет вовсе:\n{text}"
    assert "None" not in line[0], line[0]
    for row in core._phase_llcr(phased_bundle):
        assert row["name"] in line[0], f"имя {row['name']!r} до строки не доехало: {line[0]}"


def test_the_engine_reads_the_key_its_own_builder_writes() -> None:
    """Читатель и писатель строки очереди сходятся по ключу.

    Держится утверждение, а не литерал: печать берёт из строки ровно то поле,
    которое `_phase_llcr` в неё кладёт. Разойдись они снова — на экране опять
    появится None, и выглядеть это будет ошибкой расчёта.
    """
    source = Path(core.__file__).read_text(encoding="utf-8")
    builder = source.split("def _phase_llcr(", 1)[1].split("\ndef ", 1)[0]
    written = {key for key in ("name", "phase", "title", "label") if f'"{key}":' in builder}
    assert written == {"name"}, f"строка очереди кладёт другие ключи: {written}"

    printer = source.split('"**По очередям:** "', 1)[1][:400]
    for wrong in ("phase", "title", "label"):
        assert f"p.get('{wrong}')" not in printer, (
            f"печать спрашивает {wrong!r}, а строка кладёт name")
    assert "p.get('name')" in printer

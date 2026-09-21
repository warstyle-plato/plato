"""Комиссии выдачи платятся капиталом — и книга говорит это сама.

Внешний аудит (19.09.2026) заметил: комиссия БРИДЖа и резервирование ПФ
вычитаются из `equity_cf` и в потребность ПФ не входят — и нигде это не
объявлено. Решение владельца: оставить капиталом и написать. Подпись строки
57 листов CF называет источник оплаты; сама методика при этом не двигается —
вклад капитала (49) по-прежнему включает строку 57.

Запуск: python3 -m pytest tests/test_the_fees_say_they_are_paid_by_equity.py -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def _book():
    content, _, meta = core.build_project_workbook(
        dict(core.DEFAULT_INPUTS),
        {key: dict(value) for key, value in core.TEP_DEFAULT.items()},
        [], {}, project_name="Комиссии")
    assert not [m for m in meta.get("missing") or []
                if "подпись строки" in str(m)], meta.get("missing")
    openpyxl = pytest.importorskip("openpyxl")
    return openpyxl.load_workbook(io.BytesIO(content), data_only=False)


def test_every_cf_sheet_names_the_source_of_the_fees():
    book = _book()
    for phase in range(1, 5):
        label = str(book[f"CF_{phase}"][f"A{core._V4_FEES_ROW}"].value)
        assert label.startswith("Комиссии выдачи"), label
        assert "капиталом" in label and "лимит ПФ не входят" in label, label


def test_the_label_describes_what_the_book_does():
    """Подпись обещает вклад капитала — строка 49 обязана читать строку 57."""
    book = _book()
    formula = str(book["CF_1"]["D49"].value)
    assert "D57" in formula, formula
    pf_need = str(book["CF_1"]["D44"].value)
    assert "D57" not in pf_need, "комиссии попали в потребность ПФ — подпись врёт"

"""Фильтр КРТ по округам не теряет площадки с общей меткой «ТиНАО».

Город в части решений и списков КРТ пишет «ТиНАО», не уточняя, Новомосковский
это округ или Троицкий (лот 28 «п. Знамя Октября, мкр. Родники»). Фильтр
сравнивал метку строго, и такая площадка пропадала при выборе и НАО, и ТАО.
Теперь «ТиНАО» проходит при выборе любого из двух; округ не угадывается.

Проверяется настоящая функция страницы торгов через node.

Запуск: python3 -m pytest tests/test_krt_okrug_filter_keeps_tinao.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import page_blocks  # noqa: E402


def _pass(okrug: str, selected: list[str]) -> bool:
    code = page_blocks.auctions_const("KRT_OKRUG_JOINT") + "\n" + \
        page_blocks.auctions_function("krtOkrugPass")
    return page_blocks.run_json(
        code, f"console.log(JSON.stringify(krtOkrugPass({json.dumps(okrug)},"
              f"new Set({json.dumps(selected, ensure_ascii=False)}))))")


@pytest.mark.parametrize("selected", [["НАО"], ["ТАО"], ["НАО", "ТАО"], ["ЦАО", "ТАО"]])
def test_tinao_passes_either_new_moscow_okrug(selected) -> None:
    assert _pass("ТиНАО", selected) is True


@pytest.mark.parametrize("okrug, selected, expected", [
    ("ТиНАО", ["ЦАО"], False),      # не Новая Москва — не проходит
    ("НАО", ["ТАО"], False),        # конкретный округ не подменяет другой
    ("ТАО", ["ТАО"], True),
    ("ЦАО", [], True),              # фильтр пуст — проходят все
])
def test_other_okrugs_are_compared_as_before(okrug, selected, expected) -> None:
    assert _pass(okrug, selected) is expected


def test_the_filter_uses_the_rule() -> None:
    from auction_search import ui
    page = ui.auctions_page()
    body = page_blocks.function("filterKrt", page)
    assert "krtOkrugPass(x.okrug,state.krtOkrugs)" in body
    assert "state.krtOkrugs.has(x.okrug)" not in body

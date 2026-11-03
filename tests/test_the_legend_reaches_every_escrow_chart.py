"""Легенда графика эскроу доезжает до карточек очередей.

Правило «легенда объявляется там же, где график один» закрыто 01.09.2026 —
у сводного графика и у отчёта она стоит разметкой, подставленной из движка.
Карточки очередей собирает скрипт, и подставленная разметка туда не попадала:
шесть линий без единой подписи (владелец, 04.09.2026: «а в графиках в очередях
таких же отсутствует легенда»).

Запуск: python3 -m pytest tests/test_the_legend_reaches_every_escrow_chart.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

PAGE = core.PAGE


def _function(name: str) -> str:
    start = PAGE.index(f"function {name}(")
    depth, index, seen = 0, PAGE.index("{", start), False
    while index < len(PAGE):
        if PAGE[index] == "{":
            depth, seen = depth + 1, True
        elif PAGE[index] == "}":
            depth -= 1
            if seen and depth == 0:
                return PAGE[start:index + 1]
        index += 1
    raise AssertionError(f"не нашёл конец функции {name}")


def test_the_legend_is_declared_once_in_the_engine() -> None:
    """Подписи линий живут в движке — у страницы и PDF один список."""
    texts = [text for text, _colour, _style in core._ESCROW_CHART_LEGEND]
    assert len(texts) == len(set(texts)), "две линии под одной подписью"
    html = core._escrow_chart_legend_html()
    for text in texts:
        assert text in html


def test_every_escrow_chart_on_the_page_carries_it() -> None:
    """Сводный, отчётный и по очередям — три графика, одна легенда."""
    # Плейсхолдер подставлен на импорте: в собранной странице его уже нет.
    assert core.ESCROW_CHART_LEGEND_PLACEHOLDER not in PAGE
    first = core._ESCROW_CHART_LEGEND[0][0]
    # Два места разметкой (свод и отчёт) плюс строка сборки карточек очередей.
    assert PAGE.count(first) >= 3, "легенда доехала не до всех графиков"
    body = _function("renderPhaseEscrowCharts")
    assert "ESCROW_LEGEND_HTML" in body, (
        "карточка очереди рисует график без легенды — шесть линий без подписей")
    assert "escrowCoverSvg(" in body, "рисовальщик у очередей должен быть общий"


def test_the_queue_legend_is_not_a_second_copy() -> None:
    """Своих подписей у карточек очередей нет — они берут ту же строку."""
    body = _function("renderPhaseEscrowCharts")
    for text, _colour, _style in core._ESCROW_CHART_LEGEND:
        assert text not in body, (
            f"подпись «{text}» переписана в карточке очереди — копию негде обновлять")

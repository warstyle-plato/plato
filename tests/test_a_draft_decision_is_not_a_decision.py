"""Проект решения о КРТ — не решение, и называться должен своим именем.

Строка приезжает из поиска mos.ru по запросу «проект решения о комплексном
развитии территории». На экране она стояла со статусом «Решение опубликовано»,
меткой «без карточки» и колонкой «Решение» — то есть показывала стадию, которой
не наступало (владелец, 31.08.2026: «то, что ты назвал КРТ без карточки,
вообще-то ПРОЕКТ решения»). Разница не в слове: проект город публикует для
сбора мнений правообладателей, решения ещё нет — и это самый ранний сигнал из
всех, до торгов остаётся время.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auction_search import ui  # noqa: E402
from auction_search import api as auction_api  # noqa: E402


def test_the_row_says_draft_and_not_decision():
    source = Path(auction_api.__file__).read_text(encoding="utf-8")
    assert '"status": "Проект решения",' in source
    assert '"draft_decision_at"' in source
    assert '"status": "Решение опубликовано"' not in source, \
        "проект решения назван принятым решением"
    assert "decided_at" not in source, \
        "поле называется датой решения — его прочитают как дату решения"


def test_the_page_names_the_document_not_its_absence():
    page = ui.auctions_page(None)
    assert ">проект решения</span>" in page, \
        "метка называет отсутствие карточки, а не сам документ"
    assert "Проект решения о КРТ" in page
    assert "решения ещё нет" in page, \
        "стадия не оговорена: «есть решение» и «есть его проект» — разные ответы"
    assert "Есть решение о КРТ" not in page
    assert "decided_at" not in page


def test_the_platon_prompt_does_not_promise_a_decision():
    source = Path(auction_api.__file__).read_text(encoding="utf-8")
    assert "не найдено в опубликованном проекте решения" in source
    assert "не найдено в опубликованном решении" not in source

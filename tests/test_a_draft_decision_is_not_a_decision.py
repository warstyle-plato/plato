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
    # Слова каталога у такой строки нет вовсе — карточки ещё не существует, —
    # а вид её объявлен на сервере один раз. Пока вид выводил экран, отбор по
    # статусу перестал её находить (см. test_the_krt_filters_actually_filter).
    assert '"status_kind": "draft",' in source
    assert '"draft_decision_at"' in source
    assert '"status": "Решение опубликовано"' not in source, \
        "проект решения назван принятым решением"
    assert "decided_at" not in source, \
        "поле называется датой решения — его прочитают как дату решения"


def test_the_page_names_the_document_not_its_absence():
    page = ui.auctions_page(None)
    assert ">только проект решения</span>" in page, \
        "метка называет отсутствие карточки, а не стадию"
    assert "Проект решения о КРТ" in page
    assert "решения ещё нет" in page, \
        "стадия не оговорена: «есть решение» и «есть его проект» — разные ответы"
    assert "Есть решение о КРТ" not in page
    assert "decided_at" not in page


def test_the_platon_prompt_does_not_promise_a_decision():
    source = Path(auction_api.__file__).read_text(encoding="utf-8")
    assert "не найдено в опубликованном проекте решения" in source
    assert "не найдено в опубликованном решении" not in source


def test_the_source_filter_speaks_stages_not_our_jargon():
    """«Карточка» — наше слово, читателю оно ничего не говорит.

    «Так с карточкой и без — это по сути решение принято или это ещё проект.
    А так не ясно, что за карточка» (владелец, 01.09.2026). Отдельной оси
    «Источник» с тех пор не стало вовсе — «источник туфта какая-то и он не
    нужен» (04.09.2026), — а вопрос, который она задавала, отвечается стадией:
    «Проект решения» и есть площадка, которой в каталоге города ещё нет.
    """
    page = ui.auctions_page(None)
    assert "Источник: любой" not in page, "ось источника вернулась"
    assert "Карточка: любая" not in page, "жаргон остался в отборе"
    assert "Любая стадия" in page, "стадия — общая ось воронки — пропала"
    assert "{value:'draft',    name:'Проект решения'," in page
    assert "Карточки в каталоге krt.mos.ru нет" in page, \
        "отсутствие карточки больше нигде не названо"


def test_a_catalogue_site_also_shows_its_draft_decision():
    """Дата документа стояла только у площадок без карточки.

    Сопоставленные решения давали лишь счёт, и у площадки каталога колонка
    была пустой, будто документа не существует.
    """
    source = Path(auction_api.__file__).read_text(encoding="utf-8")
    assert "matched_rows" in source, "сопоставленные решения до строк не доезжают"
    assert "draft_decision_url" in source
    page = ui.auctions_page(None)
    assert "draft_decision_url" in page, "ссылка на документ на экран не выводится"

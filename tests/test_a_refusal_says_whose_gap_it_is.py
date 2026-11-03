"""Отказ вложения называет, ЧЕЙ это пробел — площадки или наш.

«И почему тут не разобралсь ничего» (владелец, 21.09.2026, страница территории
МКАД, 41 км). На экране стояло «площадка не отдала вложения лота: не отдано
вложений: 3 (Территория.Фото объекта.zip; Территория.Постановление.pdf;
Территория.Схема границ.pdf). Спросим снова» — а живой разбор лота
21000005000000031293/1 с прода говорит `asked 27, fetched 27, read 24,
from_store 27`: Росэлторг отдал ВСЁ. Три «неотданных» несут
`kind: extraction_error` — два скана PDF и архив с четырьмя PNG-скриншотами,
где текста нет и быть не должно.

Виды отказа разведены `_refusal_kind` давно (нас не пустили / площадка
отказала временно / документ не прочитан нами), а ЗАГОЛОВОК над ними утверждал
одно на все три. Наш пробел, приписанный источнику, выглядит на экране ровно
так же уверенно, как его настоящий отказ.

Утверждения здесь такие.

**Ответ один на всех читателей.** Чей это пробел, считает `docsRefusalSides`;
счёт у числа вложений, плашка причин и строка вложения выписки читают её, а не
перечисляют виды каждый по-своему.

**Наш отказ не обещает второго захода.** «Спросим снова» уместно у перебоя
площадки: прочитанное лежит на складе, и заново поедет только неотданное. У
скана заново качать нечего — нужен читатель, и так и написано.

**Настоящий отказ площадки по-прежнему называется её отказом**: правило
разводит два ответа, а не подменяет один другим.

Проверяется прогоном настоящих функций страницы через node: в исходнике
сломанный заголовок выглядит так же, как верный.

Запуск: python3 -m pytest tests/test_a_refusal_says_whose_gap_it_is.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import page_blocks  # noqa: E402
from auction_search import ui  # noqa: E402

# Три вложения лота МКАД, 41 км, которые площадка ОТДАЛА, а мы не прочитали, и
# одно рядом, которое она правда не отдала.
OURS = [
    {"document": "Территория.Постановление.16995746.pdf",
     "kind": "extraction_error",
     "reason": "PDF contains no extractable text; likely a scan"},
    {"document": "Территория.Схема границ.16995746.pdf",
     "kind": "extraction_error",
     "reason": "PDF contains no extractable text; likely a scan"},
    {"document": "Территория.Фото объекта.16995746.zip",
     "kind": "extraction_error",
     "reason": "в архиве нет читаемого текста"},
]
THEIRS = [{"document": "Территория.Лотовая документация.pdf",
           "kind": "temporary", "reason": "HTTP 503 после трёх попыток"}]


def _run(tail: str, rows: list[dict]) -> str:
    prelude = "const ROWS=%s;\n" % json.dumps(rows, ensure_ascii=False)
    out, _ = page_blocks.run(prelude, tail, page=ui.auctions_page())
    return out


def test_the_sides_are_counted_once_and_by_kind() -> None:
    """Чей пробел — один ответ, и считается он видом отказа."""
    got = json.loads(_run(
        "const s=docsRefusalSides(ROWS);"
        "console.log(JSON.stringify({ours:s.ours.length,theirs:s.theirs.length}));",
        OURS + THEIRS))
    assert got == {"ours": 3, "theirs": 1}, got


def test_the_count_at_the_number_of_attachments_splits_the_two() -> None:
    """«Прочитано 24 из 27» рядом с «мы не прочитали 3», а не «не отдала 3»."""
    line = _run(
        "console.log(docsRead({read:24,total:27,refused:ROWS,skipped:[],"
        "from_store:27},27));", OURS)
    assert "мы не прочитали 3" in line, line
    assert "площадка не отдала" not in line, line

    both = _run(
        "console.log(docsRead({read:23,total:27,refused:ROWS,skipped:[],"
        "from_store:27},27));", OURS + THEIRS)
    assert "мы не прочитали 3" in both and "площадка не отдала 1" in both, both


def test_our_gap_does_not_promise_a_second_pass() -> None:
    """У скана «спросим снова» — обещание, которого второй заход не исполнит."""
    note = _run(
        "console.log(docsRefusalNote({refused:ROWS,skipped:[],ask_again:[]}));",
        OURS)
    assert "Мы не прочитали 3" in note, note
    assert "нужен читатель" in note, note
    assert "Площадка не отдала" not in note, note
    assert "Спросим снова" not in note, note


def test_a_real_platform_refusal_is_still_hers() -> None:
    """Правило разводит два ответа, а не подменяет один другим."""
    note = _run(
        "console.log(docsRefusalNote({refused:ROWS,skipped:[],"
        "ask_again:[{document:'x'}]}));", THEIRS)
    assert "Площадка не отдала 1" in note, note
    assert "Спросим снова при следующем разборе: 1" in note, note
    assert "Мы не прочитали" not in note, note


def test_the_extract_attachment_line_names_whose_gap_it_is() -> None:
    """Строка вложения выписки: «отдано, а мы не прочитали» вместо «не отдала»."""
    block = _run(
        "console.log(egrnBlock({records:0,owners:[],refused:ROWS},'Выписки',''));",
        OURS[:1])
    assert "мы его не прочитали" in block, block
    assert "Площадка не отдала вложение" not in block, block

    hers = _run(
        "console.log(egrnBlock({records:0,owners:[],refused:ROWS},'Выписки',''));",
        THEIRS)
    assert "Площадка не отдала вложение" in hers, hers

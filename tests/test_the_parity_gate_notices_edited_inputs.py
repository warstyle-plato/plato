"""Цель паритета замерла на дате сборки — правка вводной её не двигает.

Строки «ПАРИТЕТ С ДВИЖКОМ» сравнивают то, что посчитала книга, с тем, что
посчитал движок в момент выгрузки. Это самый ценный сторож книги: он нашёл
забытую статью сноса, базу НДС и паркинг офисника. И он же кричал зря на
верной работе — а кричащая зря проверка хуже отсутствующей, её перестают
читать.

Замер, ради которого гейт и написан: поднять цену квартир на 10% прямо в
скачанной книге (владелец делает это постоянно — «эксель должен работать
почти как движок») — книга пересчитывается ВЕРНО, а ВОСЕМЬ строк паритета из
одиннадцати краснеют, потому что цель осталась прежней.

Ответов теперь три: сошлось, расходится, и «сверять не с чем — вводные
правлены». Третий ставится по отпечатку листа ввода: книга складывает его
сама, а цель сложена нами при сборке.

Запуск: python3 -m pytest tests/test_the_parity_gate_notices_edited_inputs.py -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402

PARITY_ROWS = range(76, 87)
EDITED = "вводные правлены — сверять не с чем"


def _book():
    content, _, meta = core.build_project_workbook(
        dict(core.DEFAULT_INPUTS),
        {key: dict(value) for key, value in core.TEP_DEFAULT.items()},
        [], {}, project_name="Гейт паритета")
    assert not [m for m in meta.get("missing") or [] if "гейт" in str(m)], meta
    return content


def _opened(content):
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    sys.setrecursionlimit(400000)
    book = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    return book, Evaluator


def _input_cell(book, key):
    sheet = book["Вводные"]
    for row in range(1, sheet.max_row + 1):
        if sheet.cell(row, 4).value == key:
            return sheet.cell(row, 2)
    raise AssertionError(f"вводной {key} нет на листе ввода")


def _verdicts(evaluator):
    return [evaluator.cell("ПРОВЕРКИ", f"F{row}") for row in PARITY_ROWS]


def test_a_fresh_book_agrees_with_its_own_fingerprint():
    """Собранная книга гейт не поднимает: иначе паритет молчит всегда.

    Отпечаток считают двое — мы при сборке и книга формулой, — и это ровно
    то место, где они могут разойтись молча. Разошлись уже: запрет по одному
    наличию `t=` выкидывал четырнадцать живых чисел, а даты считал только
    отпечаток, и гейт кричал на свежесобранной книге.
    """
    book, Evaluator = _opened(_book())
    evaluator = Evaluator(book)
    target = float(book["ПРОВЕРКИ"][f"C{core._V4_PARITY_GATE_ROW}"].value or 0)
    assert target > 0, "отпечаток листа ввода не записан — гейт мёртв"
    assert evaluator.cell("ПРОВЕРКИ", f"B{core._V4_PARITY_GATE_ROW}") == pytest.approx(
        target, abs=0.001), "книга и сборщик считают отпечаток по-разному"
    assert evaluator.cell("ПРОВЕРКИ", f"F{core._V4_PARITY_GATE_ROW}") == "OK"
    verdicts = _verdicts(evaluator)
    assert len(verdicts) >= 9, "строк паритета не осталось — проверять нечего"
    assert set(verdicts) == {"OK"}, verdicts


def test_an_edited_input_says_there_is_nothing_to_compare_with():
    """Правка вводной в книге — не поломка книги, и краснеть тут нечему."""
    book, Evaluator = _opened(_book())
    before = Evaluator(book)
    was_revenue = float(before.cell("ОТЧЕТ", "B5") or 0)

    # Строку читают по ключу, а не по номеру: лист ввода растёт вместе с
    # вводными, и B57 однажды уже стал подписью колонки.
    price = _input_cell(book, "apartment_price_th")
    assert float(price.value or 0) > 0, "цена квартир не на месте — правка мимо"
    price.value = float(price.value) * 1.1
    after = Evaluator(book)

    # Предохранитель: если книга не пересчиталась, проверять нечего вовсе.
    assert after.cell("ОТЧЕТ", "B5") > was_revenue * 1.01, \
        "книга не пересчитала выручку — гейт проверяется на неподвижной книге"

    assert after.cell("ПРОВЕРКИ", f"F{core._V4_PARITY_GATE_ROW}") == "WARN"
    verdicts = _verdicts(after)
    assert "FAIL" not in verdicts, verdicts
    assert set(verdicts) == {EDITED}, verdicts
    # Молчание не выдаётся за «всё сошлось»: лист говорит о предупреждении.
    assert after.cell("ПРОВЕРКИ", "B3") == "ПРОЙДЕНО С ПРЕДУПРЕЖДЕНИЯМИ"


def test_a_missing_fingerprint_gives_the_parity_back_and_does_not_silence_it():
    """Отказ гейта обязан вернуть проверку, а не выключить её.

    Не собрался лист ввода, не записался отпечаток — строки паритета ведут
    себя ровно так, как до появления гейта. Молчащий паритет хуже кричащего:
    он неотличим от сошедшегося.
    """
    book, Evaluator = _opened(_book())
    book["ПРОВЕРКИ"][f"C{core._V4_PARITY_GATE_ROW}"].value = None
    evaluator = Evaluator(book)
    assert evaluator.cell("ПРОВЕРКИ", f"F{core._V4_PARITY_GATE_ROW}") == ""
    verdicts = _verdicts(evaluator)
    assert set(verdicts) == {"OK"}, verdicts


def test_the_parity_verdict_is_declared_once():
    """Вердикт собирает один код — у строк блока и у дописанных ниже.

    Копий было две: шаблон нёс свою формулу для строк 76–84, а
    `_v4_add_parity_row` писал свою для дописанных. Разойдись они — и гейт
    действовал бы на половине блока, а вторая половина краснела бы по-старому.

    Запрещается МЕСТО, а не слово: `_v4_parity_verdict` — единственное, где
    «OK»/«FAIL» строки паритета собираются, и его собственный текст под запрет
    не попадает.
    """
    source = (ROOT / "main_legacy.py").read_text()
    declaration = source.index("def _v4_parity_verdict(")
    body_end = source.index("\ndef ", declaration)
    outside = source[:declaration] + source[body_end:]
    assert '"OK","FAIL"' not in outside.replace(" ", ""), \
        "вердикт паритета собран второй раз — гейт подействует не на все строки"


def test_a_range_sum_skips_labels_the_way_excel_does():
    """`SUM` по диапазону с подписями — число, а не ошибка.

    Отпечаток складывает ВЕСЬ лист ввода, где рядом с числами стоят подписи
    строк. Excel текст в диапазоне пропускает; вычислитель его бракует — и
    проверка расходилась бы с тем, что она проверяет.
    """
    from xlsx_eval import FUNCTIONS

    assert FUNCTIONS["SUM"]([[1.0, "Цена квартир", 2.0, None, ""]]) == 3.0

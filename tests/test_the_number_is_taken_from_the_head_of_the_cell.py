"""Кадастровый номер берётся из НАЧАЛА клетки, а не из всей клетки.

Прежний гейт требовал `_CAD.fullmatch` по всему значению под подписью — и
печатная форма, у которой под подписью стоит номер и приклеенный к нему
остаток листа, отказывала целиком. Замер прода 16.09.2026 по девяти складам
лотов: отказов печатной формы на последнем заходе читателя 55 — 51 на 1-й
Горловской, по два на обоих Прожекторах, — и у всех 55 форма клетки одна:
19 × «99:99:9999999:9999 бббббббббб», 11 × та же с цифрой на конце,
10 × «99:99:9999999:99 бббббббббб бббб (бббббб, ббббб) …» и продолжения.
Второго кадастрового номера нет ни в одном.

Что за слово приклеено, замер сказал сам: десять букв — это «РОСКАДАСТР»,
остаток блока электронной подписи, а цифра за ним — номер листа. Форма ЭТО И
ЕСТЬ, и придумывать склейку не понадобилось: в живом снимке она уже стоит —
подпись «Кадастровый номер:» повторяется на каждом листе, и на втором за
значением идёт не следующая подпись, а блок подписи, из которого сбор забирает
«РОСКАДАСТР» и «1». Здесь тот же хвост ставится к первому листу — чтобы клетка,
которую читает разбор, была ровно замеренной формой прода.
"""

from __future__ import annotations

import pytest

from auction_search import egrn_print_form
from tests.egrn_fixtures import LIVE

# Хвост замерен, а не выдуман: «бббббббббб 9» прода — это остаток блока
# электронной подписи, который сбор значения забирает следом за номером.
TAIL = ["РОСКАДАСТР", "1"]


def _glued(*, ahead: bool = False) -> str:
    """Живая форма, у которой клетка номера склеена с остатком листа.

    `ahead=True` ставит тот же хвост ПЕРЕД номером: тогда ведущего номера в
    клетке нет вовсе, и отказ обязан остаться — иначе правка превращает в
    запись всякую клетку, а не только склеенную.
    """
    lines = LIVE.splitlines()
    where = next(index for index, line in enumerate(lines)
                 if line.strip() == "Кадастровый номер:")
    cut = where + 1 if ahead else where + 2
    return "\n".join(lines[:cut] + TAIL + lines[cut:])


def test_the_glued_cell_is_read() -> None:
    """Склеенная клетка читается, и номер берётся целиком, а не обрывком."""
    record = egrn_print_form.read_text(_glued())
    assert record["cadastral_number"] == "77:05:0012007:2054"


def test_the_measured_shape_is_the_one_being_read() -> None:
    """Пример — ровно замеренная форма прода, а не похожая на неё.

    Без этого проверка выше зеленела бы на любой склейке, а чинилась одна
    названная: «номер, за ним буквы и цифра листа».
    """
    lines = _glued().splitlines()
    where = next(index for index, line in enumerate(lines)
                 if line.strip() == "Кадастровый номер:")
    cell = " ".join(one.strip() for one in lines[where + 1:where + 4])
    assert egrn_print_form._shape(cell) == "99:99:9999999:9999 бббббббббб 9"


def test_the_clean_cell_is_read_the_same() -> None:
    """Чистая форма от правки не двигается: путь, который работал, тот же."""
    was = egrn_print_form.read_text(LIVE)
    assert was["cadastral_number"] == "77:05:0012007:2054"
    assert was["quarter"] == "77:05:0012007"
    assert was["area_sqm"] == 95.0


def test_a_cell_without_a_leading_number_is_still_refused() -> None:
    """Нет номера в начале — отказ остаётся и называет форму клетки.

    Предохранитель: без него проверка выше зеленела бы на читателе, который
    отвечает записью на любую клетку.
    """
    with pytest.raises(ValueError) as refusal:
        egrn_print_form.read_text(_glued(ahead=True))
    said = str(refusal.value)
    assert "под подписью форма" in said
    # Наружу идёт форма, а не содержимое: ни цифр номера, ни слова хвоста.
    assert "77:05:0012007:2054" not in said and "РОСКАДАСТР" not in said, said


def test_two_numbers_in_a_cell_stay_a_refusal() -> None:
    """Два номера в клетке — непонятое, и молча взятый первый хуже отказа.

    Какой из двух номер объекта, документ не говорит. Такого случая на проде
    нет ни в одном из 55 отказов, и потому он тем более не повод ослаблять
    гейт: на месте отказа встало бы НЕВЕРНОЕ значение.
    """
    lines = LIVE.splitlines()
    where = next(index for index, line in enumerate(lines)
                 if line.strip() == "Кадастровый номер:")
    text = "\n".join(lines[:where + 2] + ["77:05:0012007:2055"]
                     + lines[where + 2:])
    with pytest.raises(ValueError) as refusal:
        egrn_print_form.read_text(text)
    assert "под подписью форма" in str(refusal.value)


def test_the_quarter_is_trimmed_by_the_same_rule() -> None:
    """Квартал читается тем же правилом: его клетка склеивается так же.

    Правка выше превращает отказ в ЗАПИСЬ, и без этого склейка квартала
    уехала бы в поле молча — то есть на месте отказа встало бы неверное
    значение, что хуже отказа.
    """
    lines = LIVE.splitlines()
    where = next(index for index, line in enumerate(lines)
                 if line.strip() == "Номер кадастрового квартала:")
    record = egrn_print_form.read_text(
        "\n".join(lines[:where + 2] + TAIL + lines[where + 2:]))
    assert record["quarter"] == "77:05:0012007"


def test_the_glued_tail_is_named_by_its_shape() -> None:
    """Приклеенное не выбрасывается молча — оно названо ФОРМОЙ, не значением.

    Это наш артефакт разбора, а не ответ документа, поэтому он живёт своим
    полем; формой — по той же причине, по какой формой говорит отказ: в
    выписке стоят имена правообладателей, а запись уезжает в свод площадки.
    """
    record = egrn_print_form.read_text(_glued())
    glued = record.get("glued_cells") or {}
    assert "cadastral_number" in glued, "склейка названа"
    shape = glued["cadastral_number"]
    assert shape == "бббббббббб 9", shape
    assert "РОСКАДАСТР" not in shape, "наружу идёт форма, а не содержимое"


def test_the_last_group_of_the_number_is_not_cut() -> None:
    """Граница номеру задаётся формой, а не длиной: «:2054» — не «:2».

    Без взгляда вперёд `(?![\\d:])` ведущее совпадение кончилось бы внутри
    последней группы, и номер вышел бы другого объекта — того же вида, что
    «3 306 021 ₽/м² → 306 021».
    """
    number, tail = egrn_print_form._leading(
        egrn_print_form._CAD_HEAD, "77:05:0012007:2054 РОСКАДАСТР 1")
    assert (number, tail) == ("77:05:0012007:2054", "РОСКАДАСТР 1")

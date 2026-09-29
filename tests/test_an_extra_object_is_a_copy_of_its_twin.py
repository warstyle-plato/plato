"""Дописанный объект встаёт в книгу копией блока своего двойника.

Шаблон несёт три блока объектов — офисы, ТЦ, наземный паркинг. ФОК был
четвёртым и единственным дописанным, и его строки стояли числами в десятке
мест поимённо: «поставить второй офисник» значило переписать их все ещё раз.
Теперь ответ «на какой строке объект» один — раскладка `_v4_object_layouts`,
— и второй офисник это строка реестра с `book_twin="offices"`.

Проверки здесь — на саму раскладку: ФОК остался на своих строках (книги,
собранные до обобщения, читаются так же), а объекты, которых в реестре пока
нет, раскладываются без наложений и получают ячейки двойника со сдвигом.

Запуск: python3 -m pytest tests/test_an_extra_object_is_a_copy_of_its_twin.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def _object(key, prefix, twin, *, garage=True, sellable=False, measure="sqm"):
    base = next(o for o in core.STANDALONE_OBJECTS if o.key == twin)
    return base._replace(key=key, prefix=prefix, label=f"{base.label} 2",
                         garage=garage, garage_sellable=sellable, measure=measure,
                         rate_cost=f"{prefix}_x", rate_price=f"{prefix}_y",
                         sale_gate="", purposes=(), tep_label=f"{base.tep_label} 2",
                         group_label=f"{base.group_label} 2", book_twin=twin)


# Вторые объекты стоят в реестре с шага 2 — раскладка проверяется на нём.
SECOND = core.STANDALONE_OBJECTS
assert {"offices2", "standalone_retail2", "above_parking2"} <= {o.key for o in SECOND}


def test_the_sports_object_stays_where_the_book_had_it() -> None:
    """Обобщение не двигает ФОК: вводные с 121-й, ОБЪЕКТЫ с 124-й, места 165/166."""
    lay = core._v4_layout("sports")
    assert lay.twin == "standalone_retail"
    assert (lay.input_head, lay.object_head, lay.disposition_row, lay.residual_row) \
        == (121, 124, 139, 140)
    assert (lay.parking_under, lay.parking_over, lay.tep_row, lay.report_row) \
        == ("K165", "K166", 34, 53)
    # Ячейки, по которым книга и движок сверяются, — те же, что стояли литералом.
    assert core._V4_INPUT_CELLS["sports_gba_sqm"] == "K126"
    assert core._V4_INPUT_CELLS["sports_price_th_per_sqm"] == "K134"
    assert core._V4_INPUT_CELLS["sports_growth_post_pct"] == "K138"
    assert core._V4_BOOL_CELLS["sports_enabled"] == "K123"
    assert core._V4_OBJECT_PRODUCT_CELLS["sports"] == (126, 142)


def test_the_template_objects_are_not_copies() -> None:
    for key in ("offices", "standalone_retail", "above_parking"):
        lay = core._v4_layout(key)
        assert not lay.extra and lay.twin == key


def test_second_objects_do_not_overlap_anything() -> None:
    """Каждый дописанный объект — свои строки на каждом листе, и ни одна чужая.

    Наложение не падает при сборке: копия блока ляжет поверх соседа, и книга
    посчитает два объекта одними ячейками с уверенным видом.
    """
    layouts = core._v4_object_layouts(SECOND)
    extras = [lay for lay in layouts if lay.extra]
    # ФОК — первым дописанным (его строки книга несёт давно), экземпляры
    # типов — следом, порядком реестра.
    assert [lay.obj.key for lay in extras] == ["sports", *(
        o.key for o in SECOND if o.family)]

    inputs: dict[int, str] = {}
    objects: dict[int, str] = {}
    for lay in layouts:
        rows = set(range(lay.input_head, lay.input_head + core._V4_INPUT_BLOCK_ROWS))
        rows |= {lay.residual_row} | ({lay.disposition_row} - {0})
        rows |= {int(c[1:]) for c in (lay.parking_under, lay.parking_over,
                                      lay.parking_guest, lay.parking_under_price,
                                      lay.parking_over_price) if c}
        for row in rows:
            assert row not in inputs, (lay.obj.key, row, inputs.get(row))
            inputs[row] = lay.obj.key
        for row in range(lay.object_head, lay.object_head + 28):
            assert row not in objects, (lay.obj.key, row, objects.get(row))
            objects[row] = lay.obj.key
    # Свободный низ, а не занятые места: общий блок мест 157–170 отдан объектам
    # шаблона и ФОКу (165/166), аллокация ОБЪЕКТОВ 90–122 — ни одному блоку.
    later = {row for row, key in inputs.items()
             if key not in ("offices", "standalone_retail", "above_parking", "sports")}
    assert min(later) > 170
    assert not set(range(90, 123)) & set(objects)
    tep_rows = [lay.tep_row for lay in layouts]
    assert len(set(tep_rows)) == len(tep_rows)
    assert not {35, 36, *range(38, 45)} & set(tep_rows), "итоги и соцобъекты ТЭП"


def test_second_objects_take_the_cells_of_their_twin() -> None:
    layouts = core._v4_object_layouts(SECOND)
    cells = core._v4_extra_object_cells(core._V4_INPUT_CELLS, layouts)
    offices2 = next(lay for lay in layouts if lay.obj.key == "offices2")
    shift = offices2.input_offset
    for key in ("gba_sqm", "start", "price_th_per_sqm", "growth_post_pct"):
        twin_row = int(core._V4_INPUT_CELLS[f"offices_{key}"][1:])
        assert cells[f"offices2_{key}"] == f"K{twin_row + shift}"
    # Места и их цены — свои ячейки, а не офисные 161–170.
    assert cells["offices2_parking_under_spaces"] == offices2.parking_under
    assert cells["offices2_parking_under_price_mln_per_space"] == offices2.parking_under_price
    assert int(offices2.parking_under[1:]) > 170
    # Наземному паркингу мест не положено: своего гаража у него нет.
    assert not any(key.startswith("above_parking2_parking") for key in cells)
    # Приставка не «съедает» соседей: `offices` не отдаёт `offices2` свои ячейки.
    assert not any(key.startswith("offices_") for key in cells)


def test_an_object_without_a_twin_block_is_refused() -> None:
    """Объект без блока-двойника — ошибка сборки, а не молча пропущенный объект."""
    orphan = _object("warehouse", "warehouse", "offices")._replace(book_twin="warehouse")
    with pytest.raises(ValueError, match="warehouse"):
        core._v4_object_layouts(core.STANDALONE_OBJECTS + (orphan,))


def test_the_tep_price_is_in_thousands_per_metre_for_every_object() -> None:
    """Колонка «Стартовая цена» ТЭП — тыс. ₽ за метр (или за место).

    Строка ФОКа была написана руками и умножала цену метра на 1000 — как у
    наземного паркинга, где цена стоит в миллионах за место. Стартовая цена
    ФОКа читалась 300 000 рядом с 450 у офисов и ТЦ.
    """
    sports = core._v4_object_tep_cells(core._v4_layout("sports"))["F"]
    assert sports.startswith("'Вводные'!$K$134*'Вводные'!$H$5")
    assert "*1000" not in sports
    parking2 = next(lay for lay in core._v4_object_layouts(SECOND)
                    if lay.obj.key == "above_parking2")
    assert re.match(r"'Вводные'!\$K\$\d+\*1000\*", core._v4_object_tep_cells(parking2)["F"])

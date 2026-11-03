"""Строки проверок объекта берутся из карты, а не выписываются literal'ом.

Гараж заведён 06.09.2026, а проверки листа ПРОВЕРКИ остались прежними — и с
тех пор шесть из них кричали «FAIL» на верном расчёте. Кричащая зря проверка
хуже отсутствующей: её перестают читать.

**Само это утверждение — «ни одна проверка книги не кричит зря» — держит
`tests/test_the_book_checks_know_the_object_garage.py`**, и держит строже:
он читает ВСЕ строки вердикта, а не семь названных. Второй сторож на то же
утверждение разошёлся бы с первым молча, поэтому здесь остаётся только то,
чего у соседа нет, — устройство карты:

* строки проверок выводятся из `_V4_OBJECT_PRODUCT_CELLS` и `_V4_OBJECT_PARKING`,
  значит пятый объект попадает в них тем, что он появился;
* у ФОКа своих строк проверок в шаблоне нет, и это сказано картой, а не
  умолчанием: молчание читалось бы как «его проверяют».

Запуск: python3 -m pytest tests/test_the_checks_know_about_the_object_garage.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402


def test_the_garage_rows_come_from_the_map_not_from_literals():
    """Пятый объект попадает в проверки тем, что он появился."""
    rows = [row for _, _, _, row, *_rest in core._V4_OBJECT_PARKING]
    assert rows, "в карте паркинга объектов нет ни одной строки"

    missing: list[str] = []
    template = core._V4_TEMPLATE_OBJECT_REVENUE_ROWS
    objects = ",".join(f"'ОБЪЕКТЫ'!B{r}" for r in template)
    sales = "'Продажи'!B26,'Продажи'!B49,'Продажи'!B72,'Продажи'!B95"
    shift = core._V4_OBJECT_CHECKS_CAPEX_SHIFT
    capex = ",".join("'ОБЪЕКТЫ'!B%d" % (r + shift) for r in template)
    # Строки 49 («ТЭП: выручка = CF») в наборе нет намеренно: выручку гаража
    # кладёт в САМУ строку ТЭП `_v4_object_parking_in_tep`, и прибавка здесь
    # была бы вторым счётом той же величины.
    formulas = (f"SUM({sales},{objects})", f"SUM({objects})", f"SUM({capex})")
    xml = "".join('<c r="B%d"><f>%s</f></c>' % (i, core.xml_escape(f))
                  for i, f in enumerate(formulas, start=40))
    out = core._v4_object_checks(xml, missing)

    assert missing == []
    for row in rows:
        assert core.xml_escape(f"'ОБЪЕКТЫ'!B{row}") in out, row


def test_an_object_without_its_own_checks_is_named_not_silent():
    """У ФОКа своих строк проверок в шаблоне нет, и это сказано картой.

    Молчание карты читалось бы как «его проверяют», а его не проверяют.
    """
    enabled = {row for _, row, *_rest in core._V4_OBJECT_PARKING}
    assert set(core._V4_OBJECT_CHECK_ROWS) < enabled
    covered = {row for row in enabled if row in core._V4_OBJECT_CHECK_ROWS}
    assert covered, "ни у одного объекта нет своих проверок"

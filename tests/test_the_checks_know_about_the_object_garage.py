"""Проверки книги знают о гараже отдельно стоящего объекта.

Гараж заведён 06.09.2026, а проверки листа ПРОВЕРКИ остались прежними — и с
тех пор шесть из них кричали «FAIL» на верном расчёте:

* «Офисы / ТЦ: реализованный объём» сравнивал проданное с СЫРОЙ вводной
  продаваемой площади, хотя метры первых этажей из неё вычтены: тот же этаж
  нельзя продать дважды — офисом и машино-местами;
* «Офисы / ТЦ: CAPEX» сравнивал фактический расход с «GBA × ставка» без
  подземного гаража, который в этот расход входит;
* «Выручка продуктов = CF», «ТЭП: выручка = CF» и «Аллокация выручки
  объектов» не складывали выручку мест вовсе — в аллокации и в CF она есть.

Кричащая зря проверка хуже отсутствующей: её перестают читать. Ровно это
однажды было с проверкой лимита при переносе долга.

**Действующий сторож паритета этого не видел и не мог**: он читает только
строки, чьё имя начинается на «паритет», — то есть сверял поверхность, которой
проблема не касается.

Запуск: python3 -m pytest tests/test_the_checks_know_about_the_object_garage.py -q
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402

# Строки листа ПРОВЕРКИ, которые гараж когда-то ронял.
_OBJECT_ROWS = (39, 40, 42, 43, 48, 49, 50)


def _project() -> tuple[dict, dict]:
    """Согласованные вводные: и вводные, и ТЭП говорят об объекте одно и то же.

    К1 и К2 заданы намеренно — без них московский норматив отказывается, гаража
    у объекта нет вовсе, и проверять было бы нечего.
    """
    x = dict(core.DEFAULT_INPUTS)
    x.update(offices_enabled=True, retail_enabled=True,
             parking_k1=1.0, parking_k2=0.5,
             offices_gba_sqm=40000, offices_saleable_sqm=34000,
             offices_parking_under_spaces=300, offices_parking_over_spaces=80,
             retail_gba_sqm=22000, retail_saleable_sqm=18000,
             retail_parking_under_spaces=210)
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["offices"].update(gns=40000, total_area=37600, saleable=34000)
    t["standalone_retail"].update(gns=22000, total_area=20680, saleable=18000)
    return x, t


def test_a_project_with_an_object_garage_passes_its_own_checks():
    import openpyxl
    from xlsx_eval import Evaluator

    x, t = _project()
    content, _, meta = core.build_project_workbook(
        x, t, [], None, project_name="Гараж")
    assert meta["missing"] == []
    sys.setrecursionlimit(400000)
    book = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    ev = Evaluator(book)

    # Предохранитель: без мест и без их выручки проверка не значит ничего —
    # все строки сойдутся нулями на любом коде.
    spaces = sum(ev.cell("ОБЪЕКТЫ", f"B{row}")
                 for _, _, row, _, *_rest in core._V4_OBJECT_PARKING)
    revenue = sum(ev.cell("ОБЪЕКТЫ", f"B{row}")
                  for _, _, _, row, *_rest in core._V4_OBJECT_PARKING)
    assert spaces > 0, "у объектов нет ни одного места — проверять нечего"
    assert revenue > 0, "гараж ничего не продал — проверять нечего"

    checks = book["ПРОВЕРКИ"]
    bad = []
    for row in _OBJECT_ROWS:
        if ev.cell("ПРОВЕРКИ", f"F{row}") != "OK":
            bad.append(f"{row} «{checks[f'A{row}'].value}»: "
                       f"{ev.cell('ПРОВЕРКИ', f'B{row}'):.2f} против "
                       f"{ev.cell('ПРОВЕРКИ', f'C{row}'):.2f}")
    assert not bad, bad


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
    formulas = (f"SUM({sales},{objects})", f"SUM({objects})",
                f"SUM({capex})", core._V4_TEP_REVENUE_CHECK)
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

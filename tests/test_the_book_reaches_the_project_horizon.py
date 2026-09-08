"""Сетка месяцев книги продлевается до горизонта проекта, а не молчит.

Шаблон v4 несёт 120 месяцев — колонки D..DS (у «СРОКИ» E..DT: левее стоят
даты вех). Проект длиннее сетки обрезался МОЛЧА: итоги считаются `SUM(D..DS)`,
хвост просто не складывался, `missing` при этом оставался пуст. Измерено на
умолчаниях: четыре очереди с шагом 24 — 127 месяцев (хвост пуст, книга
сходится), с шагом 36 — 163 месяца и 638,2 млн ₽ потока за сеткой, с шагом
48 — 199 месяцев и 2 363,9 млн. Пресеты владельца в сетку помещаются (91 и
103 месяца) — поэтому поломка и дожила: ни один прогон в неё не заходил.

Проверяется то, ради чего правка написана: длинный проект получает свои
колонки, короткий не платит ни одной лишней, а неопознанный шаблон уходит в
`missing`, а не считает молча.

Запуск: python3 -m pytest tests/test_the_book_reaches_the_project_horizon.py -q
"""
from __future__ import annotations

import html
import io
import re
import sys
import zipfile
from pathlib import Path

import pytest
from openpyxl.utils import column_index_from_string as col_number

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as wrapper  # noqa: E402

core = wrapper.core
TEMPLATE = zipfile.ZipFile(core._V4_TEMPLATE_PATH)


def _inputs():
    return dict(core.DEFAULT_INPUTS), {k: dict(v) for k, v in core.TEP_DEFAULT.items()}


def _phasing(step: int, count: int = 4):
    return {"enabled": True, "mode": "phased", "user_enabled": True,
            "phase_count": count,
            "phases": [{"name": f"О{i + 1}", "start_offset_months": i * step}
                       for i in range(count)]}


def _sheets(blob: bytes) -> dict[str, str]:
    """Имя листа -> его XML в собранной книге."""
    archive = zipfile.ZipFile(io.BytesIO(blob))
    names = core._v4_sheet_names_by_path(archive)
    return {name: archive.read(path).decode("utf-8")
            for path, name in names.items()}


def _last_column(xml: str) -> str:
    columns = set(re.findall(r'<x:c r="([A-Z]{1,3})\d+"', xml))
    return max(columns, key=col_number)


@pytest.fixture(scope="module")
def long_book():
    """Четыре очереди с шагом 36 — 163 месяца, на 43 длиннее сетки."""
    inputs, tep = _inputs()
    phasing = _phasing(36)
    engine = core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, phasing=phasing))
    months = len(engine["consolidated"]["cashflow"]["months"])
    blob, _name, meta = core.build_project_workbook(
        inputs, tep, None, phasing, project_name="Горизонт")
    return months, blob, meta


def test_the_project_really_is_longer_than_the_grid(long_book) -> None:
    """Предохранитель самого теста.

    Стань этот проект короче 120 месяцев — набор продолжил бы зеленеть, ничего
    больше не проверяя: ровно так поломка и прожила до сегодня.
    """
    months, _blob, _meta = long_book
    assert months > core._V4_GRID_MONTHS, (
        f"проект на {months} мес. помещается в сетку — проверять нечего")


def test_the_grid_reaches_the_horizon(long_book) -> None:
    """Каждый лист сетки дотягивается до последнего месяца проекта."""
    months, blob, _meta = long_book
    sheets = _sheets(blob)
    quarters = -(-months // 3) * 3            # сетка растёт кварталами
    for name, (first, _last) in core._V4_GRID_SHEETS.items():
        if name in core._V4_GRID_SHEETS_BUILT:
            continue          # у КОНСОЛИДАТОРА правее сетки свои колонки
        expected = col_number(first) + quarters - 1
        got = col_number(_last_column(sheets[name]))
        assert got == expected, (
            f"{name}: сетка кончается на {got}-й колонке вместо {expected}")


def test_the_month_number_follows_the_column(long_book) -> None:
    """Номер месяца — само число, а не формула, и копия его не двигает.

    Скопированный как есть, он объявляет каждый новый месяц сто двадцатым, а
    по нему считается кривая ключевой ставки.
    """
    months, blob, _meta = long_book
    sheets = _sheets(blob)
    quarters = -(-months // 3) * 3
    for name in core._V4_GRID_SHEETS:
        if name in core._V4_GRID_SHEETS_WITHOUT_PERIOD:
            continue
        last = _last_column(sheets[name])
        cell = re.search(r'<x:c r="%s%d"[^>]*?>(.*?)</x:c>'
                         % (last, core._V4_GRID_PERIOD_ROW), sheets[name], re.S)
        assert cell, f"{name}: нет ячейки номера месяца в {last}"
        assert re.search(r"<x:(?:f|v)>%d</x:(?:f|v)>" % quarters, cell.group(1)), (
            f"{name}: последний месяц назван не {quarters}-м: {cell.group(1)[:60]}")


def test_the_totals_span_the_whole_grid(long_book) -> None:
    """Итог строки складывает все месяцы, а не первые сто двадцать.

    Это и есть та самая потеря: `SUM(D10:DS10)` при 163 месяцах — двенадцать
    лет из тринадцати с половиной, и выглядит она посчитанной.
    """
    _months, blob, _meta = long_book
    sheets = _sheets(blob)
    last = _last_column(sheets["CF_1"])
    total = re.search(r'<x:c r="B10"[^>]*?><x:f>(.*?)</x:f>', sheets["CF_1"], re.S)
    assert total, "у CF_1 нет строки итога B10"
    assert f":{last}10)" in total.group(1), (
        f"итог CF_1!B10 кончается не на {last}: {total.group(1)}")
    # ОТЧЁТ читает сетку через лист, и его диапазоны обязаны ехать следом.
    report = re.search(r'<x:c r="B17"[^>]*?><x:f>(.*?)</x:f>', sheets["ОТЧЕТ"], re.S)
    assert report and f":{last}19)" in report.group(1), (
        f"пиковый долг в ОТЧЁТе считается не по всей сетке: "
        f"{report.group(1) if report else 'ячейки нет'}")


def test_a_full_row_range_keeps_its_start(long_book) -> None:
    """Продлевается конец диапазона, а начало остаётся на D.

    `SUMPRODUCT($D10:$DS10,$D9:$DS9)` — весь ряд сетки; уехавшее вместе с
    концом начало отрезало бы первый месяц у каждой из ста шестидесяти пяти
    колонок, и на экране это выглядело бы обычным числом.
    """
    _months, blob, _meta = long_book
    sales = _sheets(blob)["Продажи"]
    last = _last_column(sales)
    cell = re.search(r'<x:c r="D11"[^>]*?><x:f>(.*?)</x:f>', sales, re.S)
    assert cell, "нет ячейки Продажи!D11"
    assert f"$D10:${last}10" in cell.group(1), cell.group(1)


def test_a_month_to_date_range_does_not_reach_the_end(long_book) -> None:
    """`$D$26:DS$26` — «по этот месяц», и продлевать его нельзя.

    Продлённый, он собрал бы в каждый месяц продажи всего проекта. Отличается
    он от диапазона на весь ряд знаком доллара у конца — и это единственное,
    чем их различает шаблон.
    """
    _months, blob, _meta = long_book
    cf = _sheets(blob)["CF_1"]
    last = _last_column(cf)
    cell = re.search(r'<x:c r="E14"[^>]*?><x:f>(.*?)</x:f>', cf, re.S)
    assert cell, "нет ячейки CF_1!E14"
    assert "'Продажи'!$D$26:'Продажи'!D$26" in cell.group(1), cell.group(1)
    assert last not in cell.group(1), (
        f"накопление «по этот месяц» дотянули до конца сетки: {cell.group(1)}")


def test_the_dashboard_quarters_cover_the_project(long_book) -> None:
    """Диаграммы читают квартальную сводку, а не сетку.

    Не продлив её, книга показала бы графиками первые десять лет и промолчала
    об этом: сорок кварталов выглядят полным проектом.
    """
    months, blob, _meta = long_book
    sheets = _sheets(blob)
    quarters = -(-months // 3)
    last_row = core._V4_DASHBOARD_FIRST_QUARTER_ROW + quarters - 1
    dash = sheets["Дашборд"]
    cell = re.search(r'<x:c r="S%d"[^>]*?><x:f>(.*?)</x:f>' % last_row, dash, re.S)
    assert cell, f"нет квартала в строке {last_row} «Дашборда»"
    grid_last = _last_column(sheets["CF"])
    assert f"'CF'!{grid_last}6)" in cell.group(1), (
        f"последний квартал кончается не на {grid_last}: {cell.group(1)}")
    # А сорок первый квартал больше не повторяет сороковой.
    fortieth = re.search(r'<x:c r="S43"[^>]*?><x:f>(.*?)</x:f>', dash, re.S)
    assert fortieth and "DQ6" in fortieth.group(1), fortieth.group(1) if fortieth else "нет"


def test_the_charts_follow_the_quarters(long_book) -> None:
    """Диапазон диаграммы едет вместе со сводкой: иначе он читает пустое."""
    months, blob, _meta = long_book
    quarters = -(-months // 3)
    last_row = core._V4_DASHBOARD_FIRST_QUARTER_ROW + quarters - 1
    archive = zipfile.ZipFile(io.BytesIO(blob))
    charts = [n for n in archive.namelist() if "drawings/charts/chart" in n]
    assert charts, "в книге нет диаграмм"
    # Диаграмм четыре, и квартальную сводку читают две: у остальных свои
    # короткие ряды (статьи расходов, очереди). Признак — прежний конец ряда
    # на сороковом квартале: он и обязан уехать.
    seen = 0
    for name in charts:
        text = archive.read(name).decode("utf-8")
        rows = re.findall(r"<c:f>'?Дашборд'?!\$[A-Z]{1,3}\$4:\$[A-Z]{1,3}\$(\d+)</c:f>", text)
        assert str(core._V4_DASHBOARD_CHART_ROWS[1]) not in rows, (
            f"{name}: диаграмма осталась на сороковом квартале")
        seen += sum(1 for row in rows if int(row) == last_row)
    assert seen, "ни одна диаграмма не читает квартальную сводку целиком"


def test_a_short_project_pays_for_nothing() -> None:
    """Обычный проект остаётся на сетке шаблона — байт в байт.

    Продление «на всякий случай» стоило бы каждой книге сорока лишних колонок
    на одиннадцати листах, а расширенный навсегда шаблон — ещё и правки
    методики владельца.
    """
    inputs, tep = _inputs()
    blob, _name, meta = core.build_project_workbook(
        inputs, tep, None, {}, project_name="Короткий")
    sheets = _sheets(blob)
    for name, (_first, last) in core._V4_GRID_SHEETS.items():
        if name in core._V4_GRID_SHEETS_BUILT:
            continue
        assert _last_column(sheets[name]) == last, (
            f"{name}: короткому проекту дописали колонки до "
            f"{_last_column(sheets[name])}")
    assert not [m for m in meta["missing"] if "сетк" in m], meta["missing"]


def test_the_declared_grid_matches_the_template() -> None:
    """Границы сетки объявлены в движке — и обязаны совпасть с шаблоном.

    Разойдись объявление с книгой, продление начнётся не с той колонки и
    молча испортит методику владельца.
    """
    names = core._v4_sheet_names_by_path(TEMPLATE)
    by_name = {name: path for path, name in names.items()}
    for sheet, (first, last) in core._V4_GRID_SHEETS.items():
        if sheet in core._V4_GRID_SHEETS_BUILT:
            continue          # эти колонки дописывает движок, в шаблоне их нет
        xml = TEMPLATE.read(by_name[sheet]).decode("utf-8")
        assert _last_column(xml) == last, f"{sheet}: шаблон кончается не на {last}"
        assert col_number(last) - col_number(first) + 1 == core._V4_GRID_MONTHS, (
            f"{sheet}: между {first} и {last} не {core._V4_GRID_MONTHS} месяцев")


def test_an_unreadable_grid_is_named_not_swallowed() -> None:
    """Не нашли последнюю колонку — это `missing`, а не тихая книга на 120 месяцев."""
    missing: list[str] = []
    core._v4_extend_month_grid("<x:sheetData></x:sheetData>", "CF_1", 12, missing)
    assert missing and "сетка месяцев" in missing[0], missing


def test_an_unmeasured_horizon_is_named() -> None:
    """Горизонт не пришёл — книга осталась прежней и сказала об этом.

    Без этой строки «не измерили» неотличимо от «проект короткий».
    """
    inputs, tep = _inputs()
    _blob, _name, meta = core.build_project_workbook(
        inputs, tep, None, {}, project_name="Без горизонта", finance_hints={})
    assert any("горизонт проекта не измерен" in m for m in meta["missing"]), \
        meta["missing"]

def test_every_whole_grid_range_reaches_the_new_end(long_book) -> None:
    """Диапазон, кончавшийся на краю сетки, кончается на новом краю — везде.

    Проверка независимая: она не спрашивает у правки, что та считает концом
    сетки, а берёт КОРОТКУЮ книгу (сетка шаблона нетронута), находит в ней
    диапазоны с абсолютным концом на последней колонке и смотрит те же ячейки
    в длинной. Ровно она и нашла настоящую ошибку: доля расходов очереди
    считается двумерным `SUM($D$118:$DS$128)`, у концов которого РАЗНЫЕ
    строки, и первая версия правки его не продлила — четвёртая очередь
    показала CAPEX минус 230 млрд ₽ при 11 млрд у соседних.

    Сверка «ничего лишнего не изменилось» такого не видит: непродлённый
    диапазон выглядит как нетронутая ячейка.
    """
    _months, blob, _meta = long_book
    long_sheets = _sheets(blob)
    inputs, tep = _inputs()
    short, _name, _meta2 = core.build_project_workbook(
        inputs, tep, None, {}, project_name="Короткий")
    short_sheets = _sheets(short)
    grown = {name: _last_column(long_sheets[name]) for name in core._V4_GRID_SHEETS}
    bad: list[str] = []
    for host, xml in short_sheets.items():
        after = {coord: formula for coord, formula in re.findall(
            r'<x:c r="([A-Z]{1,3}\d+)"[^>]*?><x:f>(.*?)</x:f>', long_sheets[host], re.S)}
        for coord, formula in re.findall(
                r'<x:c r="([A-Z]{1,3}\d+)"[^>]*?><x:f>(.*?)</x:f>', xml, re.S):
            before = html.unescape(formula)
            for sheet, (_first, last) in core._V4_GRID_SHEETS.items():
                # Конец диапазона: `:$DS$128`, `:'CF'!$DS$37`, `:$DT10`.
                ends = re.findall(r":(?:'[^']+'!)?\$%s\$?\d+" % last, before)
                if not ends:
                    continue
                now = html.unescape(after.get(coord, ""))
                for end in ends:
                    if end.replace(f"${last}", f"${grown[sheet]}") not in now:
                        bad.append(f"{host}!{coord}: {end} осталось на месте")
    assert not bad, "концы сетки не продлены: " + "; ".join(sorted(set(bad))[:5])


def test_no_formula_points_past_the_grid(long_book) -> None:
    """Ссылок за край сетки нет: пустая колонка молча считается нулём."""
    _months, blob, _meta = long_book
    sheets = _sheets(blob)
    limits = {name: col_number(_last_column(sheets[name]))
              for name in core._V4_GRID_SHEETS}
    bad: list[str] = []
    for host, xml in sheets.items():
        if host not in core._V4_GRID_SHEETS:
            continue
        for coord, formula in re.findall(
                r'<x:c r="([A-Z]{1,3}\d+)"[^>]*?><x:f>(.*?)</x:f>', xml, re.S):
            for ref in core._v4_formula_refs(html.unescape(formula), host):
                if ref["sheet"] not in limits:
                    continue
                if col_number(ref["column"]) > limits[ref["sheet"]]:
                    bad.append(f"{host}!{coord} → {ref['sheet']}!{ref['column']}")
    assert not bad, "ссылки за краем сетки: " + "; ".join(bad[:5])

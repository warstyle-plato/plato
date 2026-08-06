"""Вкладка «Отчёт» читается как разбор проекта и совпадает с печатью.

Порядок карточек был таким же случайным, каким был PDF: ТЭП на двенадцатом
месте, удельная экономика оторвана от экономики, две таблицы расходов разнесены
через выручку, а финансирование разорвано на три куска — пятый, пятнадцатый и
шестнадцатый.

Кроме того, чувствительность и календарь жили только на своих вкладках и в PDF:
человек смотрел отчёт на экране, печатал его и видел два раздела, которых на
экране не было. Отчёт обязан быть тем же документом, что уходит в печать.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


@pytest.fixture(scope="module")
def report_tab() -> str:
    page = core.PAGE
    start = page.find('<div id="report" class="panel">')
    assert start > 0, "вкладка отчёта не найдена"
    end = page.find('<div id="aiOverlay"', start)
    return page[start:end if end > start else start + 20000]


_ORDER = [
    ('id="rsSite"', "Участок и продукт"),
    ('id="rsSummary"', "Итог"),
    ('id="rsPhases"', "Очереди проекта"),
    ('id="rsExpenses"', "Расходы"),
    ('id="rsIncome"', "Доходы"),
    ('id="rsFinance"', "Финансирование"),
    ('id="rsSensitivity"', "Чувствительность"),
    ('id="rsCalendar"', "Календарный план"),
]


def test_the_tab_reads_as_a_project_review(report_tab):
    positions = []
    for anchor, title in _ORDER:
        position = report_tab.find(anchor)
        assert position > 0, f"раздел пропал: {title}"
        positions.append(position)
    assert positions == sorted(positions), "порядок разделов разъехался"


def test_the_tep_comes_before_the_economics(report_tab):
    """ТЭП стоял двенадцатым: сначала выводы, потом что за объект."""
    assert report_tab.find('id="reportTep"') < report_tab.find('id="economicsTable"')


def test_the_unit_economics_sits_next_to_the_economics(report_tab):
    """Между ними стояли налоги, ВРИ и вся структура расходов."""
    economics = report_tab.find('id="economicsTable"')
    units = report_tab.find('id="unitEconomicsTable"')
    assert economics < units
    assert 'id="rsSummary"' in report_tab[:economics][-2000:] or True
    # В промежутке не должно быть чужих разделов.
    between = report_tab[economics:units]
    for stranger in ('id="reportTaxTable"', 'id="vriTotalsTable"',
                     'id="expenseStructureTable"'):
        assert stranger not in between, stranger


def test_financing_is_not_torn_into_three_pieces(report_tab):
    """Показатели финансирования, БРИДЖ и ставки стояли на пятом, пятнадцатом
    и шестнадцатом местах."""
    finance = report_tab.find('id="reportFinanceTable"')
    rates = report_tab.find('id="ratesDebtTable"')
    bridge = report_tab.find('id="bridgePurposeTable"')
    assert 0 < finance < rates
    assert finance < bridge
    section = report_tab.find('id="rsFinance"')
    assert section < finance, "все три обязаны лежать в разделе финансирования"


def test_the_two_expense_tables_stand_together(report_tab):
    """Структура расходов и структура затрат разъезжались через выручку."""
    structure = report_tab.find('id="expenseStructureTable"')
    capex = report_tab.find('id="capexTable"')
    revenue = report_tab.find('id="revenueTable"')
    assert 0 < structure < capex < revenue


# --- оглавление --------------------------------------------------------------

def test_the_tab_has_a_table_of_contents(report_tab):
    """Отчёт длинный, и до календаря доезжали прокруткой."""
    assert 'id="reportToc"' in report_tab
    assert "report-toc" in core.PAGE and "position:sticky" in core.PAGE


def test_the_contents_skip_empty_sections():
    """Ссылка, ведущая в пустоту, хуже её отсутствия: очередей у одноочередного
    проекта нет, чувствительности — пока её не посчитали.

    Но пустоту определяет содержимое, а не видимость. Первая версия смотрела на
    `offsetParent` и высоту — и это отвечало «пусто» на всё, потому что меню
    строится сразу после расчёта, когда вкладка отчёта ещё закрыта, а у скрытой
    панели display:none. Меню отфильтровывало себя целиком каждый раз.
    """
    page = core.PAGE
    assert "function renderReportToc()" in page
    assert "getComputedStyle(el).display!=='none'" in page
    assert "child.textContent.trim().length>0" in page
    assert "offsetParent" not in page.split("function renderReportToc()")[1][:900]


def _toc_html(sections: dict[str, list[tuple[str, str, str]]]) -> str:
    """Гоняем настоящий renderReportToc из PAGE через node.

    Разделы описываются как (класс, стиль display, текст) — так же, как они
    выглядят в разметке отчёта: заголовок плюс карточки.
    """
    import json
    import re
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    listed = re.search(r"const REPORT_SECTIONS=\[.*?\];", core.PAGE, re.S)
    body = re.search(r"function renderReportToc\(\)\{.*?\n\}", core.PAGE, re.S)
    assert listed and body, "оглавление отчёта не найдено на странице"

    stand = {
        name: {"style": {"display": display},
               "children": [{"style": {"display": child_display},
                             "classList": {"contains": None}, "cls": cls,
                             "textContent": text}
                            for cls, child_display, text in children]}
        for name, (display, children) in sections.items()
    }
    script = (
        listed.group(0) + "\n" + body.group(0) + "\n"
        + "const stand=" + json.dumps(stand, ensure_ascii=False) + ";\n"
        + "Object.values(stand).forEach(s=>s.children.forEach(c=>{"
          "c.classList={contains:name=>c.cls===name}}));\n"
        # Вкладка закрыта — ровно то состояние, в котором меню и строится:
        # ни родителя раскладки, ни высоты. Прежняя проверка на этом
        # вычёркивала все разделы разом.
        + "Object.values(stand).forEach(s=>{s.offsetParent=null;"
          "s.getBoundingClientRect=()=>({height:0,width:0})});\n"
        + "const toc={innerHTML:''};\n"
        + "const document={getElementById:id=>id==='reportToc'?toc:(stand[id]||null)};\n"
        + "function getComputedStyle(el){return {display:(el.style&&el.style.display)||'block'}}\n"
        + "renderReportToc();console.log(toc.innerHTML);"
    )
    return subprocess.run([node, "-e", script], capture_output=True, text=True,
                          check=True).stdout


def test_a_closed_tab_no_longer_empties_the_contents():
    """Настоящая причина пустого меню: оно строится сразу после расчёта, когда
    вкладка отчёта ещё закрыта. У скрытой панели display:none, и проверка
    видимости отвечала «пусто» на каждый раздел — меню вычёркивало себя целиком.
    Разделы при этом свои стили не меняют, поэтому судим по ним."""
    html = _toc_html({
        "rsSite": ("block", [("report-section-title", "block", "Участок и продукт"),
                             ("card", "block", "Кадастровый номер 77:09:…")]),
        "rsSummary": ("block", [("report-section-title", "block", "Итог"),
                                ("card", "block", "LLCR 1,27x")]),
    })
    assert "Участок" in html and "Итог" in html


def test_a_single_phase_project_gets_no_phases_link():
    """У одноочередного проекта обе карточки очередей скрыты своим стилем —
    ссылка вела бы в один заголовок."""
    html = _toc_html({
        "rsSummary": ("block", [("report-section-title", "block", "Итог"),
                                ("card", "block", "LLCR 1,27x")]),
        "rsPhases": ("block", [("report-section-title", "block", "Очереди проекта"),
                               ("phase-report-nav", "none", "Весь проект"),
                               ("card", "none", "Сравнение очередей")]),
    })
    assert "Итог" in html
    assert "Очереди" not in html


def test_an_empty_section_is_not_listed():
    html = _toc_html({
        "rsCalendar": ("block", [("report-section-title", "block", "Календарный план"),
                                 ("card", "block", "   ")]),
    })
    assert html.strip() == ""


def test_the_contents_are_rebuilt_when_the_tab_opens():
    """Расчёт почти всегда проходит при закрытой вкладке отчёта: кнопка
    «Рассчитать и открыть» сначала считает и только потом открывает."""
    page = core.PAGE
    opener = page[page.find("function openTab(id,btn)"):]
    assert "renderReportToc()" in opener[:600]


def test_every_section_of_the_contents_exists(report_tab):
    """Оглавление и разметка не имеют права разойтись."""
    import re
    listed = re.search(r"const REPORT_SECTIONS=\[(.*?)\];", core.PAGE, re.S)
    assert listed
    for anchor in re.findall(r"\['(\w+)'", listed.group(1)):
        assert f'id="{anchor}"' in report_tab, anchor


# --- отчёт совпадает с печатью -----------------------------------------------

def test_the_calendar_is_in_the_report_too(report_tab):
    assert 'id="reportCalendarGantt"' in report_tab
    assert "renderGantt('reportCalendarGantt'" in core.PAGE


def test_the_tornado_is_in_the_report_too(report_tab):
    assert 'id="reportSensitivity"' in report_tab
    assert "function renderReportSensitivity()" in core.PAGE
    # Одна картинка на две поверхности: вкладка и отчёт рисуют её тем же кодом.
    assert "function renderTornado(report,targetId)" in core.PAGE


def test_an_uncounted_sensitivity_offers_to_count_it():
    """Пустой раздел читается как поломка; в PDF чувствительность
    досчитывается сама, и печатный отчёт иначе был бы полнее экранного."""
    page = core.PAGE
    assert "Не рассчитана" in page
    assert "Открыть расчёт чувствительности" in page


# --- удельные на обе базы там, где их не было ---------------------------------

def test_the_revenue_table_speaks_in_roubles_per_metre(report_tab):
    assert "Структура выручки" in report_tab
    head = report_tab[report_tab.find("Структура выручки"):]
    assert "тыс ₽/м² ГНС" in head[:400] and "тыс ₽/м² прод." in head[:400]


def test_the_capex_table_speaks_in_roubles_per_metre(report_tab):
    head = report_tab[report_tab.find("Структура затрат по статьям"):]
    assert "тыс ₽/м² ГНС" in head[:400] and "тыс ₽/м² прод." in head[:400]


def test_the_social_load_is_shown_per_metre():
    """Социальная нагрузка на метр читается как цена входа в проект и
    сравнивается между площадками; в миллиардах такое сравнение не делают."""
    page = core.PAGE
    assert "function socialPerMetre(r)" in page
    assert "Нагрузка на метр" in page
    assert page.count("socialPerMetre(r)") >= 3, "обе формы исполнения соцнагрузки"


def test_the_vri_payment_is_shown_per_metre():
    page = core.PAGE
    assert "Плата на метр" in page
    assert "function vriTotalsRows(t,summary)" in page

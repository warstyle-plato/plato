"""Сумма наземной и подземной площади зовётся «общей», а не «суммарной в ГНС».

Владелец (17.10.2026), к тизеру 0.25.91 — «Суммарная площадь в ГНС 60 944 м²»
под наземной 44 894 и подземной 16 050: «Это же ошибка. Это не общая в ГНС, а с
подземной. У нас был термин загружен общий». «Суммарная площадь в ГНС»
читается как СПП ГлавАПУ — суммарная поэтажная площадь, а она только
наземная. Величина с подземной частью — «Общая площадь» (`TOTAL_AREA`), у МКД
и у объектов — со своим уточнением.

Слово — у одного владельца, `terms_glossary`; проверки ниже смотрят то, что
видит человек (тизер, PDF, книгу, отрисованную страницу) и то, откуда
поверхности берут подпись: литерал удельной подписи в коде поверхности —
второй источник, и он запрещён.

Запуск: python3 -m pytest tests/test_the_total_area_is_not_called_in_gns.py -q
"""
from __future__ import annotations

import copy
import io
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as _wrapper  # noqa: E402
import terms_glossary as tg  # noqa: E402
from browser import chromium_or_skip, serve, wait_for_result  # noqa: E402
from terms_glossary import CORE_TOTAL_AREA, OBJECTS_TOTAL_AREA, TERMS, TOTAL_AREA  # noqa: E402

core = _wrapper.core
PORT = 19633

OLD = ("Суммарная площадь в ГНС", "суммарной площади в ГНС", "суммарную площадь в ГНС",
       "Суммарная ГНС", "Суммарная площадь МКД", "суммарной площади МКД",
       "Суммарная площадь объектов", "суммарной площади объектов")

# Поверхности, печатающие величину: подпись удельного («м² <база>») здесь
# обязана прийти из словаря, а не стоять литералом.
SURFACES = sorted([*(ROOT / "engine").glob("*.py"), ROOT / "teaser_pdf.py",
                   ROOT / "pdf_first_page_extension.py", ROOT / "v4_dashboard.py",
                   ROOT / "main_legacy.py", ROOT / "scripts" / "prod_smoke.py"])


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " "))


def _old_in(text: str) -> list[str]:
    return [label for label in OLD if label in text]


def _code_lines(path: Path) -> list[str]:
    """Строки кода без комментариев: `#` и `//` человек не видит."""
    return [line for line in path.read_text(encoding="utf-8").splitlines()
            if not re.match(r"^\s*(#|//)", line)]


@pytest.fixture(scope="module")
def bundle():
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    tep = copy.deepcopy(core.TEP_DEFAULT)
    return inputs, tep, core._run_authoritative_model(inputs, tep, [], None)


def test_the_glossary_says_total_not_in_gns() -> None:
    for term in (TOTAL_AREA, CORE_TOTAL_AREA, OBJECTS_TOTAL_AREA):
        assert term.name.startswith("Общая площадь"), term
        assert "ГНС" not in term.name and "уммарн" not in term.name, term
        assert term.genitive.startswith("общей площади"), term
    assert TOTAL_AREA.full == "Общая площадь (наземная ГНС + подземная), м²"
    assert CORE_TOTAL_AREA.name == "Общая площадь МКД"
    assert OBJECTS_TOTAL_AREA.name == "Общая площадь объектов"
    # Прежнее имя — в запретном списке: проверки отрисованных поверхностей
    # (`test_the_total_area_is_not_called_construction_volume.py`) ищут его сами.
    forbidden = tg.forbidden_labels()
    for label in OLD:
        assert label in forbidden, label
    assert not _old_in(" ".join(f"{t.name} {t.full} {t.genitive} {t.prepositional}"
                                for t in TERMS.values()))


def test_no_surface_keeps_the_label_as_its_own_literal() -> None:
    """Один источник: ни старого слова, ни копии нового в коде поверхностей."""
    # Подпись удельного кончается базой: «м² общей площади жилья» (норма МО) и
    # «м² общей площади на место» (соцобъект) — другие величины, их не трогаем.
    unit_labels = [re.compile(rf"м²\s+{re.escape(t.genitive)}(?!\s*[\wё])")
                   for t in (TOTAL_AREA, CORE_TOTAL_AREA, OBJECTS_TOTAL_AREA)]
    found: list[str] = []
    for path in SURFACES:
        for number, line in enumerate(_code_lines(path), start=1):
            # Пропуск f-строки, читающей словарь, — не литерал.
            if "genitive}" in line or "genitive)" in line or ".genitive" in line:
                continue
            for label in OLD:
                if label in line:
                    found.append(f"{path.name}: «{label}»")
            for pattern in unit_labels:
                if pattern.search(line):
                    found.append(f"{path.name}:{number}: {line.strip()[:80]}")
    assert not found, found[:10]
    # Разметка страницы берёт слово плейсхолдером, и он подставлен.
    assert "__DEVELOPAID_TERM_" not in core.PAGE
    assert f'id="expenseBaseHead">тыс ₽/м² {TOTAL_AREA.genitive}<' in core.PAGE


def test_the_teaser_calls_the_sum_total_area(bundle) -> None:
    pypdf = pytest.importorskip("pypdf")
    import teaser_pdf

    inputs, tep, report = bundle
    model = core.project_presentation(report, inputs, tep, None)
    content = teaser_pdf.build_teaser_pdf(model, core._pdf_font_names(), core._pdf_num)
    reader = pypdf.PdfReader(io.BytesIO(content))
    text = _flat("\n".join(page.extract_text() or "" for page in reader.pages))
    assert not _old_in(text), _old_in(text)
    summary = report["consolidated"]["summary"]
    assert summary["underground_gns_sqm"] > 0, "без подземной части проверять нечего"
    volume = core._pdf_num(summary["construction_volume_sqm"], 0).replace("\xa0", " ")
    # Первая страница: наземная ГНС, подземная часть и под ними — общая площадь.
    assert "Наземная площадь ГНС" in text and "Подземная часть" in text
    assert f"{TOTAL_AREA.name} {volume}" in text, text[text.find("Наземная площадь ГНС"):][:300]
    # Колонка удельных расходов подписана словарём.
    assert f"тыс ₽/м² {TOTAL_AREA.genitive}" in text
    # Сетка ТЭП: итог колонки ГНС — общая площадь, и так и назван.
    assert f"Итого — {TOTAL_AREA.lower()} {volume}" in text


def test_the_pdf_report_calls_the_sum_total_area(bundle) -> None:
    pypdf = pytest.importorskip("pypdf")
    inputs, tep, _ = bundle
    result = core.calculate(core.CalcRequest(inputs=copy.deepcopy(inputs),
                                             tep=copy.deepcopy(tep), rates=[]))
    content = core._build_developaid_pdf({
        "project_name": "Общая площадь", "result": result,
        "inputs": inputs, "tep": tep, "rates": [],
    })
    reader = pypdf.PdfReader(io.BytesIO(content))
    text = _flat("\n".join(page.extract_text() or "" for page in reader.pages))
    assert not _old_in(text), _old_in(text)
    assert f"Расходы — на {TOTAL_AREA.genitive}" in text
    assert f"от {CORE_TOTAL_AREA.genitive}" in text
    # Городская методика по-прежнему названа своим словом — СПП наземная.
    assert "суммарной поэтажной площади" in text


def test_the_workbook_calls_the_sum_total_area() -> None:
    openpyxl = pytest.importorskip("openpyxl")
    data, _name, _report = core.build_project_workbook(
        copy.deepcopy(core.DEFAULT_INPUTS), copy.deepcopy(core.TEP_DEFAULT),
        None, None, project_name="Общая площадь")
    book = openpyxl.load_workbook(io.BytesIO(data))
    found = [f"{sheet.title}!{cell.coordinate}: {label}"
             for sheet in book.worksheets for row in sheet.iter_rows() for cell in row
             if isinstance(cell.value, str) and not cell.value.startswith("=")
             for label in _old_in(cell.value)]
    assert not found, found[:5]
    report = book["ОТЧЕТ"]
    assert report["F6"].value == TOTAL_AREA.name
    assert report["A62"].value == f"CAPEX на м² {TOTAL_AREA.genitive}"
    assert report["A58"].value.startswith(f"{TOTAL_AREA.name}: наземная + подземная")
    assert book["ТЭП"]["A36"].value == f"ИТОГО ПРОЕКТ — {TOTAL_AREA.lower()}"


def test_the_rendered_page_calls_the_sum_total_area() -> None:
    """Страница до и после расчёта: заголовок колонки расходов и подпись под
    ТЭП отчёта — словарным словом; старого — нигде в тексте."""
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    from main_registry import app as registry_app

    with serve(registry_app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.goto(f"{base}/classic", wait_until="domcontentloaded")
            wait_for_result(tab)
            got = tab.evaluate("""async ()=>{
              const head=()=>document.getElementById('expenseBaseHead').textContent;
              const before=head();
              await settledCalculate();
              const body=document.body.cloneNode(true);
              body.querySelectorAll('script,style,noscript').forEach(x=>x.remove());
              const attrs=[...document.querySelectorAll('[title],[placeholder],[data-hint]')]
                .map(x=>[x.getAttribute('title'),x.getAttribute('placeholder'),
                         x.getAttribute('data-hint')].filter(Boolean).join(' '));
              return {before, after: head(),
                      note: document.getElementById('reportTepNote').textContent,
                      tepNote: document.getElementById('tepUndergroundNote').textContent,
                      text: body.textContent + ' ' + attrs.join(' ')};
            }""")
        finally:
            browser.close()

    other = [line for line in errors if "Failed to fetch" not in line]
    assert not other, f"страница упала: {other[:2]}"
    assert got["before"] == got["after"] == f"тыс ₽/м² {TOTAL_AREA.genitive}"
    # Подпись под таблицей ТЭП (владелец, 17.10.2026, скриншот 0.25.91: «Та же
    # ошибка»): наземная ГНС, подземная часть и их сумма словом глоссария.
    tep_note = _flat(got["tepNote"])
    assert tep_note.startswith("Итог ГНС — наземная площадь"), tep_note[:80]
    assert re.search(rf"{re.escape(TOTAL_AREA.name)} [\d ]+(,\d)? м²\.$", tep_note), tep_note
    assert not _old_in(tep_note), tep_note
    assert _flat(got["note"]).startswith(f"{TOTAL_AREA.name} — ")
    text = _flat(got["text"])
    assert not _old_in(text), _old_in(text)

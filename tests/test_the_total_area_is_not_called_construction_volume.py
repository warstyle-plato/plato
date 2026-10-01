"""Сумма площадей в м² не зовётся «строительным объёмом».

Строительный объём в отрасли — объём здания в м³ по наружному обмеру,
надземная и подземная части (владелец, 29.09.2026). Наша величина — наземная
ГНС плюс подземная часть в м² (Нагатино: 443 701 + 122 920 = 566 621 м²), и
подписана она была этим чужим термином на странице, в PDF, тизере и книге.

Подпись теперь у одного владельца — `terms_glossary.TOTAL_AREA`; проверки ниже
смотрят то, что видит человек: отрисованную страницу после расчёта, текст
PDF-отчёта и тизера, строки книги. Запрещённое слово ищется по всему выводу, а
новое — там, где величина обязана стоять, и именно словарным словом.

Запуск: python3 -m pytest tests/test_the_total_area_is_not_called_construction_volume.py -q
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
import terms_glossary  # noqa: E402
from browser import chromium_or_skip, serve  # noqa: E402
from terms_glossary import CORE_TOTAL_AREA, TOTAL_AREA  # noqa: E402

core = _wrapper.core
PORT = 19631


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " "))


def _forbidden_in(text: str) -> list[str]:
    return [label for label in terms_glossary.forbidden_labels() if label in text]


@pytest.fixture(scope="module")
def bundle():
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    tep = copy.deepcopy(core.TEP_DEFAULT)
    return inputs, tep, core._run_authoritative_model(inputs, tep, [], None)


def test_the_glossary_owns_the_word() -> None:
    """Слово — у словаря, в движке старого нет ни в одной строке, что видна."""
    assert TOTAL_AREA.unit == "м²"
    # Название — решение владельца (29.09.2026): СПП по ГлавАПУ только
    # наземная, «общая площадь» у нас и у ГлавАПУ — НП.
    assert TOTAL_AREA.full == "Суммарная площадь в ГНС (СПП + подземная), м²"
    assert "Общая" not in TOTAL_AREA.name and not TOTAL_AREA.name.startswith("СПП")
    # Страница получает словарь целиком, а не копию слов.
    assert "const TERMS=__DEVELOPAID_TERMS__" not in core.PAGE
    assert f'"name": "{TOTAL_AREA.name}"' in core.PAGE
    assert not _forbidden_in(re.sub(r"(?m)^\s*//.*$", "", core.PAGE)), \
        _forbidden_in(core.PAGE)
    hints = {name: hint for _group, fields in core.FIELD_GROUPS
             for name, _title, hint, *_rest in fields}
    assert not [key for key, hint in hints.items() if _forbidden_in(str(hint))]


def test_the_pdf_report_names_the_sum_by_the_glossary(bundle) -> None:
    pypdf = pytest.importorskip("pypdf")
    inputs, tep, _ = bundle
    result = core.calculate(core.CalcRequest(inputs=copy.deepcopy(inputs),
                                             tep=copy.deepcopy(tep), rates=[]))
    content = core._build_developaid_pdf({
        "project_name": "Словарь терминов", "result": result,
        "inputs": inputs, "tep": tep, "rates": [],
    })
    reader = pypdf.PdfReader(io.BytesIO(content))
    text = _flat("\n".join(page.extract_text() or "" for page in reader.pages))
    assert not _forbidden_in(text), _forbidden_in(text)
    assert TOTAL_AREA.name in text


def test_the_teaser_names_the_sum_by_the_glossary(bundle) -> None:
    pypdf = pytest.importorskip("pypdf")
    import teaser_pdf

    inputs, tep, report = bundle
    model = core.project_presentation(report, inputs, tep, None)
    content = teaser_pdf.build_teaser_pdf(model, core._pdf_font_names(), core._pdf_num)
    reader = pypdf.PdfReader(io.BytesIO(content))
    text = _flat("\n".join(page.extract_text() or "" for page in reader.pages))
    assert not _forbidden_in(text), _forbidden_in(text)
    assert TOTAL_AREA.name in text


def test_the_workbook_names_the_sum_by_the_glossary() -> None:
    openpyxl = pytest.importorskip("openpyxl")
    data, _name, _report = core.build_project_workbook(
        copy.deepcopy(core.DEFAULT_INPUTS), copy.deepcopy(core.TEP_DEFAULT),
        None, None, project_name="Словарь терминов")
    book = openpyxl.load_workbook(io.BytesIO(data))
    found: list[str] = []
    named = 0
    for sheet in book.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if not isinstance(cell.value, str) or cell.value.startswith("="):
                    continue
                found += [f"{sheet.title}!{cell.coordinate}: {label}"
                          for label in _forbidden_in(cell.value)]
                named += TOTAL_AREA.name.lower() in cell.value.lower()
    assert not found, found[:5]
    assert book["ОТЧЕТ"]["F6"].value == TOTAL_AREA.name
    assert named >= 2, "подпись суммарной площади пропала из книги"


def test_the_rendered_page_names_the_sum_by_the_glossary() -> None:
    """После расчёта: весь текст страницы и подсказки — без чужого термина,
    а подпись под ТЭП отчёта называет сумму словарным словом."""
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
            tab.wait_for_timeout(700)
            got = tab.evaluate("""async ()=>{
              await calculate();
              const attrs=[...document.querySelectorAll('[title],[placeholder],[data-hint]')]
                .map(x=>[x.getAttribute('title'),x.getAttribute('placeholder'),
                         x.getAttribute('data-hint')].filter(Boolean).join(' '));
              const note=document.getElementById('reportTepNote');
              // Текст всех вкладок, и скрытых тоже, — но не исходник скриптов:
              // комментарий кода человек не видит.
              const body=document.body.cloneNode(true);
              body.querySelectorAll('script,style,noscript').forEach(x=>x.remove());
              return {text: body.textContent + ' ' + attrs.join(' '),
                      note: note ? note.textContent : null,
                      volume: lastResult.summary.construction_volume_sqm};
            }""")
        finally:
            browser.close()

    other = [line for line in errors if "Failed to fetch" not in line]
    assert not other, f"страница упала: {other[:2]}"
    text = _flat(got["text"])
    assert not _forbidden_in(text), _forbidden_in(text)
    assert got["note"], "подписи под ТЭП отчёта нет"
    note = _flat(got["note"])
    assert note.startswith(f"{TOTAL_AREA.name} — "), note[:120]


def test_the_shared_articles_name_their_own_base(bundle) -> None:
    """Общие статьи считаются от суммарной площади МКД, а не проекта.

    Под одним именем стояли две величины: база общих статей `core_total_gns`
    (только жилые дома) и сумма всего проекта. Пояснение «на ней считаются
    общие статьи» висело у второй — с объектами это неправда.
    """
    pypdf = pytest.importorskip("pypdf")
    inputs, tep, report = bundle
    summary = report["consolidated"]["summary"]
    tep_report = report["consolidated"]["tep"]
    core_total = tep_report["core_above_gns"] + tep_report["core_under_gns"]
    # С соцобъектом база общих статей меньше суммы проекта — иначе проверять нечего.
    assert core_total < summary["construction_volume_sqm"]
    assert CORE_TOTAL_AREA.name != TOTAL_AREA.name
    result = core.calculate(core.CalcRequest(inputs=copy.deepcopy(inputs),
                                             tep=copy.deepcopy(tep), rates=[]))
    content = core._build_developaid_pdf({
        "project_name": "Словарь терминов", "result": result,
        "inputs": inputs, "tep": tep, "rates": [],
    })
    reader = pypdf.PdfReader(io.BytesIO(content))
    text = _flat("\n".join(page.extract_text() or "" for page in reader.pages))
    line = text[text.index("Общие статьи"):][:300]
    assert CORE_TOTAL_AREA.genitive in line, line
    assert core._pdf_num(core_total, 0).replace("\xa0", " ") in line, line

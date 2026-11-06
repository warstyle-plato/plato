"""Кнопка «Excel» калькулятора под всплывающим уведомлением.

26.10.2026 сверка с ГлавАПУ на проде падала, и посетитель видел лог Playwright:
«Locator.click: Timeout 7000ms exceeded … <div class="MuiAlert-message"> from
<div class="notistack-SnackbarContainer"> subtree intercepts pointer events».
Калькулятор после ввода сценария показывает уведомление, оно перекрывает
кнопку, а notistack не прячет его, пока над ним курсор, — а Playwright ведёт
курсор именно туда.

Проверяется настоящий `glavapu_scenario.export_xlsx` в настоящем Chromium на
подделке страницы с той же разметкой notistack / MUI Alert:
* информационное уведомление поверх кнопки — убирается, книга скачивается;
* уведомление об ошибке — сверка останавливается и называет его текст;
* без уведомления — книга скачивается сразу.

Запуск: python3 -m pytest tests/test_glavapu_excel_behind_a_notice.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import glavapu_scenario as gs  # noqa: E402

BOOK = b"PK-fake-calculator-book"

# Кнопка «Excel» в углу, уведомление notistack лежит прямо на ней. Как у
# настоящего notistack, уведомление не уходит, пока над ним курсор: таймер
# скрытия идёт только после ухода курсора; щелчок по нему закрывает его.
PAGE = """<!doctype html><html><body style="margin:0">
<button id="excel" style="position:absolute;left:20px;top:20px;width:120px;height:40px">Excel</button>
%(notice)s
<script>
document.getElementById('excel').onclick = () => {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob(['PK-fake-calculator-book']));
  a.download = 'ТЭП.xlsx'; document.body.appendChild(a); a.click();
};
const box = document.querySelector('.notistack-SnackbarContainer');
if (box) {
  let timer = null;
  const hide = () => box.remove();
  box.addEventListener('mouseenter', () => { clearTimeout(timer); timer = null; });
  box.addEventListener('mouseleave', () => { timer = setTimeout(hide, 600); });
  box.querySelector('.MuiAlert-root').addEventListener('click', hide);
}
</script></body></html>"""

NOTICE = """<div class="notistack-SnackbarContainer" style="position:fixed;left:0;top:0;width:400px;height:120px;z-index:1400">
 <div class="notistack-CollapseWrapper"><div class="notistack-Snackbar">
  <div class="MuiPaper-root MuiAlert-root %(cls)s" role="alert" style="height:110px;cursor:pointer;background:#2e7d32;color:#fff">
   <div class="MuiAlert-message">%(text)s</div>
  </div></div></div></div>"""


def _page(notice: str = ""):
    pytest.importorskip("playwright.sync_api")
    import browser_launch
    from playwright.sync_api import sync_playwright
    manager = sync_playwright().start()
    try:
        browser = browser_launch.launch(manager)
    except Exception as exc:  # noqa: BLE001
        manager.stop()
        pytest.skip(f"Chromium не поднялся: {exc}")
    page = browser.new_page(accept_downloads=True)
    page.set_content(PAGE % {"notice": notice})
    return manager, browser, page


def _run(notice: str = ""):
    manager, browser, page = _page(notice)
    try:
        return gs.export_xlsx(page, 15000)
    finally:
        browser.close()
        manager.stop()


def test_an_info_notice_over_the_button_is_cleared_and_the_book_arrives():
    notice = NOTICE % {"cls": "MuiAlert-filledSuccess MuiAlert-colorSuccess",
                       "text": "Расчёт населения, социальных объектов и объектов "
                               "обслуживания изменился!"}
    assert _run(notice) == BOOK


def test_an_error_notice_stops_the_check_and_names_its_text():
    notice = NOTICE % {"cls": "MuiAlert-filledError MuiAlert-colorError",
                       "text": "Ошибка при создании Excel: поле не принято"}
    with pytest.raises(gs.CalculatorNotice) as caught:
        _run(notice)
    message = caught.value.public_message
    assert "Ошибка при создании Excel: поле не принято" in message
    assert "Playwright" not in message and "Timeout" not in message
    assert "запустите сверку ещё раз" in message
    assert caught.value.where == "калькулятор ГлавАПУ: выгрузка книги сценария"


def test_without_a_notice_the_book_arrives_at_once():
    assert _run() == BOOK


def test_the_engine_passes_the_calculators_words_to_the_window(monkeypatch, tmp_path):
    """Ошибка калькулятора доходит до окна его словами и с местом, без стека."""
    import main as wrapper

    core = wrapper.core
    monkeypatch.setenv("DEVELOPAID_DATA_DIR", str(tmp_path))

    def refused(numbers, area_ha, params=None):
        raise gs.CalculatorNotice(["Ошибка при создании Excel: поле не принято"],
                                  "калькулятор ГлавАПУ: выгрузка книги сценария")
    monkeypatch.setattr(core, "_glavapu_headless_run", refused)
    saved: dict = {}
    monkeypatch.setattr(core, "_glavapu_scenario_load", lambda key: saved.get(key))
    monkeypatch.setattr(core, "_glavapu_scenario_save", lambda key, rec: saved.update({key: dict(rec)}))
    core._glavapu_scenario_run("k", {"numbers": ["77:06:0003002:18"], "params": {"area_ha": 1.0}})
    record = saved["k"]
    assert record["state"] == "error"
    assert "Ошибка при создании Excel: поле не принято" in record["error"]
    assert record["where"] == "калькулятор ГлавАПУ: выгрузка книги сценария"

"""Тип проекта спрашивается раньше участка — на отрисованной странице.

Слой `/ia` переносил ВСЕ `.scenario` шапки в «Экономику», и вместе с классом
туда уезжал выбор «Жильё / Нежилое / Гостиница». Человек вводил кадастр,
получал расчёт жилья и только потом, где-то в «Экономике», узнавал, что тип
можно сменить (замечание владельца). Теперь «что строим» стоит первым на шаге
«Проект → Участок», до поля кадастра; класс и сценарий остались в «Экономике».

Проверка идёт в браузере с настоящим overlay: порядок и видимость меряются на
отрисованной странице, а не по позиции литералов в исходнике. На старом слое
она падает — select типа там лежит в `.ia-setup`.

Отдельно: узел перенесён, а не скопирован (один select, варианты — из
PROJECT_KINDS движка), и смена типа после загруженного проекта по-прежнему
открывает окно `#projectKindDialog` и обнуляет жилые вводные.

Запуск: python3 -m pytest tests/test_ia_project_kind_comes_before_the_site.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

LAYOUT = """() => {
  const box = el => { if (!el) return null; const r = el.getBoundingClientRect();
    return {top: r.top, height: r.height, visible: r.width > 0 && r.height > 0}; };
  const kind = document.getElementById('projectKindSelect');
  const site = document.getElementById('iaSite');
  return {
    kinds: document.querySelectorAll('#projectKindSelect').length,
    options: kind ? [...kind.options].map(o => o.value) : [],
    engineKinds: PROJECT_KINDS.map(p => p[0]),
    inSite: !!(kind && site && site.contains(kind)),
    inSetup: !!(kind && kind.closest('.ia-setup')),
    inHeader: !!(kind && kind.closest('.actions')),
    classInSetup: !!document.querySelector('.ia-setup #projectClassSelect'),
    scenarioInSetup: !!document.querySelector('.ia-setup #scenarioSelect'),
    noteInSite: !!document.querySelector('#iaSite #projectKindNoteTop'),
    kindBox: box(kind),
    cadBox: box(document.getElementById('cadastralNumbers')),
    siteActive: !!(site && site.classList.contains('active')),
    missing: document.querySelector('.ia-missing') ? document.querySelector('.ia-missing').innerText : '',
  };
}"""

# Проект «как после загрузки кадастра»: жилые метры в ТЭП и жилые вводные,
# которые нежилой режим обязан убрать.
LOAD = """() => {
  const keys = Object.keys(NONRESIDENTIAL_CLEARED);
  keys.forEach(k => { inputs[k] = 123; });
  calculate();
  return keys;
}"""

AFTER = """keys => ({
  kind: inputs.project_kind,
  select: document.getElementById('projectKindSelect').value,
  dialog: getComputedStyle(document.getElementById('projectKindDialog')).display,
  left: keys.filter(k => Number(inputs[k] || 0) !== 0),
  cleared: (inputs._nonres_cleared || []).length,
})"""


@pytest.fixture(scope="module")
def drawn() -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    import browser
    import main_registry

    path = browser.chromium_or_skip()
    out: dict = {}
    with browser.serve(main_registry.app, 18171) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_function("() => typeof lastResult !== 'undefined' && lastResult")
            page.wait_for_function("() => document.getElementById('iaSite')")
            out["layout"] = page.evaluate(LAYOUT)

            keys = page.evaluate(LOAD)
            page.wait_for_function("() => lastResult")
            # Выбор — тем самым select, что стоит на «Участке». force: пересчёт
            # проверяется отдельно от расположения, и на слое, где select
            # спрятан в «Экономике», должны падать проверки места, а не эта.
            page.select_option("#projectKindSelect", "nonresidential", force=True)
            page.wait_for_function(
                "() => getComputedStyle(document.getElementById('projectKindDialog')).display !== 'none'")
            out["switched"] = page.evaluate(AFTER, keys)
            page.evaluate("() => cancelNonResidential()")
            out["restored"] = page.evaluate(AFTER, keys)
            out["errors"] = errors
            page.close()
    return out


def test_the_kind_stands_first_on_the_site_step(drawn) -> None:
    layout = drawn["layout"]
    assert layout["siteActive"], "страница должна открываться на шаге «Участок»"
    assert layout["inSite"], "выбор типа проекта должен стоять на шаге «Участок»"
    assert layout["noteInSite"], "пояснение типа должно ехать вместе с ним"
    assert layout["kindBox"]["visible"], "выбор типа на «Участке» не виден"
    assert layout["cadBox"]["visible"], "поле кадастра на «Участке» не видно"
    assert layout["kindBox"]["top"] < layout["cadBox"]["top"], (
        "«что строим» должно спрашиваться раньше «где»: select типа выше поля кадастра", layout)


def test_the_kind_left_the_economics_and_the_class_stayed(drawn) -> None:
    layout = drawn["layout"]
    assert not layout["inSetup"], "тип проекта не должен оставаться в «Экономике»"
    assert not layout["inHeader"]
    assert layout["classInSetup"], "класс остаётся в «Экономике»"
    assert layout["scenarioInSetup"], "сценарий остаётся в «Экономике»"


def test_the_node_is_moved_not_copied(drawn) -> None:
    layout = drawn["layout"]
    assert layout["kinds"] == 1, "select типа должен быть один"
    assert layout["options"] == layout["engineKinds"], "варианты рисует движок из PROJECT_KINDS"
    assert not layout["missing"], layout["missing"]
    assert not drawn["errors"], drawn["errors"]


def test_switching_the_kind_after_a_loaded_project_still_recalculates(drawn) -> None:
    switched = drawn["switched"]
    assert switched["kind"] == "nonresidential" and switched["select"] == "nonresidential"
    assert switched["dialog"] != "none", "окно последствий переключения должно открыться"
    assert not switched["left"], f"жилые вводные не обнулены: {switched['left']}"
    assert switched["cleared"] > 0
    restored = drawn["restored"]
    assert restored["kind"] == "mixed" and restored["select"] == "mixed"
    assert restored["dialog"] == "none"
    assert not restored["cleared"], "отмена должна вернуть убранное"

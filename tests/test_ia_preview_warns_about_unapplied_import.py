"""Найденный расчёт участка, который не применили, объявляет о себе сам.

Владелец ввёл адрес, не заметил кнопку «Применить к Вводным и ТЭП», ушёл
вводить экономику — и досчитал проект на прежних, не обнулённых ТЭП
(16.08.2026). Снаружи это не видно никак: карточка с кнопкой осталась на
«Участке», а остальные вкладки выглядят обычно.

Здесь закреплено:

- «не применён» определяется данными, а не видимостью карточки: применение
  перерисовывает ту же карточку, поэтому видимость ни о чём не говорит.
  Применённый импорт держит mappings той же ссылкой, применённый расчёт МО —
  territory; сравнение ссылок гоняется через node на настоящем коде слоя;
- страница обязана сохранять этот контракт ссылок (applyGlavapu,
  renderStoredGlavapu, applyMo) — иначе плашка станет вечной;
- шаги «Участок» и «ТЭП» помечаются warn, плашка со «Применить к Вводным и
  ТЭП» и «Сбросить карточку» ходит за человеком по вкладкам, на «Участке»
  её нет — там карточка и так перед глазами;
- «Далее» с «Участка» применяет и расчёт МО, а не только файл ГлавАПУ.

Запуск: python3 -m pytest tests/test_ia_preview_warns_about_unapplied_import.py -q
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core
_ROOT = Path(__file__).resolve().parent.parent
_OVERLAY = (_ROOT / "ia_preview" / "assets" / "overlay.js").read_text(encoding="utf-8")
_CSS = (_ROOT / "ia_preview" / "assets" / "overlay.css").read_text(encoding="utf-8")
NODE = shutil.which("node")


def _pending_harness() -> str:
    start = _OVERLAY.index("function pageResult()")
    end = _OVERLAY.index("function pageTep()")
    return "var window = { applyGlavapu: function(){}, applyMo: function(){} };\n" + _OVERLAY[start:end]


def test_pending_is_a_matter_of_data_not_of_a_visible_card():
    """Настоящие pendingGlavapu/pendingMo слоя, сценарий за сценарием."""
    if not NODE:
        pytest.skip("node недоступен")
    script = _pending_harness() + """
let glavapuImport = null, inputs = {}, moResult = null, lastResult = null;
var out = {};
out.nothing = pendingImport();
var mappings = { inputs: { purchase_price_mln: 100 }, tep: {} };
glavapuImport = { mappings: mappings, source: { filename: 'a.xlsx' } };
out.fresh = pendingImport();
// Применение кладёт те же mappings по ссылке — карточка видима, но применена.
inputs._glavapu_import = { mappings: mappings };
out.applied = pendingImport();
// Новый разбор файла — новый объект: снова «не применён».
glavapuImport = { mappings: { inputs: { x: 1 }, tep: {} } };
out.reparsed = pendingImport();
// Проект прежних версий без mappings: применять нечего — и предупреждать не о чем.
glavapuImport = { mappings: { inputs: {}, tep: {} } };
out.empty = pendingImport();
glavapuImport = null;
var territory = { site_area_ha: 2 };
moResult = { query: 'x', territory: territory };
out.moFresh = pendingImport();
inputs._mo_calc = { territory: territory, query: 'x' };
out.moApplied = pendingImport();
moResult = { query: 'y', territory: { site_area_ha: 3 } };
out.moRerun = pendingImport();
console.log(JSON.stringify(out));
"""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    out = json.loads(result.stdout)
    assert out == {
        "nothing": None,
        "fresh": "glavapu",
        "applied": None,
        "reparsed": "glavapu",
        "empty": None,
        "moFresh": "mo",
        "moApplied": None,
        "moRerun": "mo",
    }, out


def test_the_page_keeps_the_reference_contract():
    """Слой сравнивает ссылки — страница обязана их сохранять.

    Стоит applyGlavapu начать копировать mappings (или applyMo — territory),
    и плашка «не применён» станет вечной: применение перестанет её снимать.
    """
    assert "mappings:glavapuImport.mappings" in core.PAGE, "applyGlavapu больше не хранит mappings ссылкой"
    assert "mappings:stored.mappings" in core.PAGE, "renderStoredGlavapu больше не возвращает ссылку из проекта"
    assert "territory:moResult.territory" in core.PAGE, "applyMo больше не хранит territory ссылкой"
    for name in ("applyGlavapu", "applyMo", "dropGlavapuPreview", "dropMoPreview"):
        assert re.search(rf"(async )?function {name}\(", core.PAGE), f"на странице нет функции {name}"


def test_the_steps_and_the_banner_carry_the_warning():
    for step in ("iaSite", "tep"):
        body = _OVERLAY[_OVERLAY.index(step + ": function ()"):]
        body = body[:body.index("return { mark: 'need'")]
        assert "pendingImport()" in body, f"шаг {step} не смотрит на неприменённый расчёт"
        assert "'warn'" in body, f"шаг {step} не помечается warn"
    banner = _OVERLAY[_OVERLAY.index("function renderPendingWarn"):]
    banner = banner[:banner.index("\n  }\n", banner.index("box.appendChild(drop)"))]
    # Подпись кнопки — дословно кнопка страницы: плашка не выдумывает интерфейс.
    assert banner.count("Применить к Вводным и ТЭП") == 1
    assert "Применить к Вводным и ТЭП" in core.PAGE
    assert "Сбросить карточку" in banner
    assert "activeTab === 'iaSite'" in banner, "на «Участке» плашка должна сниматься"
    assert "renderPendingWarn(activeTab)" in _OVERLAY.split("function renderPendingWarn")[0], (
        "syncNav не перерисовывает плашку"
    )
    assert ".ia-pending{" in _CSS
    assert re.search(r"@media print\{[^}]*\.ia-pending\{display:none\}", _CSS), "плашка попадёт в печать"


def test_forward_from_the_site_applies_the_mo_result_too():
    forward = _OVERLAY[_OVERLAY.index("// Уход с «Участка» вперёд"):]
    forward = forward[:forward.index("sub.appendChild(forward)")]
    assert "pendingGlavapu()" in forward and "window.applyGlavapu()" in forward
    assert "pendingMo()" in forward and "window.applyMo()" in forward

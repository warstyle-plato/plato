"""Предупреждение «формулы разошлись с калькулятором» — про свой участок.

Ночная проверка «Посадка ↔ нормативы» 25.10.2026: под ТЭП участка стояло
предупреждение с суммами ДРУГОГО участка. Итог сверки лежал одним общим
флагом в памяти процесса и пристёгивался к любому ответу, а прод работает
двумя воркерами — второй флага не видел вовсе.

Проверяется на настоящих путях: серверный ТЭП (`cadastral_tep_server`),
импорт штатного калькулятора (`import_cadastral_tep`) и карточка кнопки бота
(`vri_tep_quick`).

Запуск: python3 -m pytest tests/test_glavapu_drift_names_its_site.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core

SITE_A = "77:09:0004014:13"
SITE_B = "77:07:0008006:3"
DRIFT = ["компенсация школа: калькулятор 110.321, формулы 102.122"]


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVELOPAID_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(core, "analyze_cadastral_territory", lambda req: {
        "territory": {"area_ha": 0.651, "district": "Савеловский"},
        "coefficients": {"rail": 0.75, "business_outside_ttc": 0.5,
                         "rent": 0.1281, "base_cost_zh_high": 229036.29},
    })
    # Сверка в фоне здесь не нужна: итог сверки записывается руками.
    monkeypatch.setattr(core, "_glavapu_drift_in_background", lambda *a, **k: None)
    monkeypatch.setattr(core, "_glavapu_tep_cached", lambda *a, **k: None)
    saved = dict(core._GLAVAPU_FORMULA_DRIFT)
    yield tmp_path
    core._GLAVAPU_FORMULA_DRIFT.clear()
    core._GLAVAPU_FORMULA_DRIFT.update(saved)


def _found_on_site_a_by_the_other_worker() -> None:
    """Сверка прошла на соседнем воркере: у этого в памяти ничего нет."""
    core._glavapu_drift_record([SITE_A], DRIFT)
    core._GLAVAPU_FORMULA_DRIFT.update(items=[], numbers=[])


def _full_calculator_table() -> list[dict]:
    """Полная таблица «штатного калькулятора» — из серверного файла."""
    quick = core.vri_tep_quick("msk", SITE_A)
    rows = [list(r) + [""] * (4 - len(r)) for r in core._xlsx_read_tables(quick["file"])["ТЭП"]]
    return [{"code": str(r[0] or ""), "name": str(r[1] or ""),
             "unit": str(r[2] or ""), "value": str(r[3] or "")}
            for r in rows[1:] if str(r[1] or "").strip()]


def _drift_lines(warnings: list[str]) -> list[str]:
    return [w for w in warnings if "разошлись" in w]


def test_another_sites_drift_stays_off_this_sites_tep(isolated):
    _found_on_site_a_by_the_other_worker()
    server = core.cadastral_tep_server(core.CadastralAnalysisRequest(cadastral_numbers=SITE_B))
    assert not _drift_lines(server["warnings"]), \
        "под ТЭП участка Б висит расхождение, найденное на участке А"
    card = core.vri_tep_quick("msk", SITE_B)["card"]
    assert "разошлись" not in card


def test_this_sites_drift_reaches_every_surface_and_names_the_site(isolated):
    _found_on_site_a_by_the_other_worker()
    server = core.cadastral_tep_server(core.CadastralAnalysisRequest(cadastral_numbers=SITE_A))
    lines = _drift_lines(server["warnings"])
    assert lines and SITE_A in lines[0] and "110.321" in lines[0], \
        "расхождение участка обязано дойти до его ТЭП и назвать участок"
    card = core.vri_tep_quick("msk", SITE_A)["card"]
    assert "по этому участку серверные формулы разошлись" in card

    rows = _full_calculator_table()
    imported = core.import_cadastral_tep(core.CadastralTepRequest(
        rows=rows, cadastral_analysis={"recognized": [SITE_A]}))
    lines = _drift_lines(imported["warnings"])
    assert lines and SITE_A in lines[0]
    other = core.import_cadastral_tep(core.CadastralTepRequest(
        rows=rows, cadastral_analysis={"recognized": [SITE_B]}))
    assert not _drift_lines(other["warnings"])


def test_matching_formulas_clear_only_their_own_site(isolated):
    core._glavapu_drift_record([SITE_A], DRIFT)
    core._glavapu_drift_record([SITE_B], DRIFT)
    core._glavapu_drift_record([SITE_B], [])
    core._GLAVAPU_FORMULA_DRIFT.update(items=[], numbers=[])
    assert core._glavapu_drift_for([SITE_A]) == DRIFT
    assert core._glavapu_drift_for([SITE_B]) == []


def test_a_record_from_another_release_does_not_speak(isolated):
    """Новая выкатка могла починить формулы — старая запись молчит до новой
    сверки."""
    core._glavapu_drift_record([SITE_A], DRIFT)
    core._GLAVAPU_FORMULA_DRIFT.update(items=[], numbers=[])
    path = isolated / "glavapu-drift.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["version"] = "0.0.1"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    assert core._glavapu_drift_for([SITE_A]) == []

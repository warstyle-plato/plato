"""Норма площади поликлиники называет акт, а не «нормы города нет».

Поле `social_clinic_norm_sqm` стояло 15 м² на посещение в смену и подписывалось
«норматива города для поликлиники нет — наша экспертная величина». Акт есть:
2150-ПП (нормативы градостроительного проектирования Москвы в области
здравоохранения), разд. 1.4 в ред. 2579-ПП от 28.10.2025 — «не более 27 кв.м»
нежилой наземной площади на одно посещение в смену, уточняется
медико-технологическим заданием. Это верхний предел, а не ступень по ёмкости,
поэтому он живёт умолчанием поля, а не таблицей РНГП (решение владельца,
16.10.2026, docs/normative_audit_msk_mo_2026-10.md §6 п.1).

Две вещи держатся отдельно: область (`mo_calc`) пишет в то же поле своё число,
а сохранённый проект со своим значением его не теряет — умолчание только
накладывается под сохранённое состояние.

Запуск: python3 -m pytest tests/test_the_clinic_norm_names_the_act.py -q
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

KEY = "social_clinic_norm_sqm"


def _hint(field: str) -> str:
    for _group, fields in core.FIELD_GROUPS:
        for item in fields:
            if item[0] == field:
                return str(item[2] or "")
    raise AssertionError(f"поля {field} нет в FIELD_GROUPS")


def _rule(rule_id: str) -> str:
    for item in core._DevelopAid_METHODOLOGY:
        if item.get("id") == rule_id:
            return str(item["rule"])
    raise AssertionError(f"правила {rule_id} нет у Платона")


def test_the_default_is_the_upper_limit_of_the_act() -> None:
    """27 м² на посещение в смену — предел 2150-ПП, а не прежние 15."""
    assert core.DEFAULT_INPUTS[KEY] == 27


def test_the_hint_names_the_act_and_the_limit() -> None:
    """Подпись поля называет акт и число и не утверждает, что нормы нет."""
    hint = _hint(KEY)
    assert "2150-ПП" in hint and "27" in hint, hint
    assert "верхний предел" in hint and "МТЗ" in hint, hint
    assert "норматива города для поликлиники нет" not in hint
    assert "экспертная величина" not in hint


def test_platon_names_the_act_too() -> None:
    """Правило Платона о площади соцобъекта говорит то же, что подпись поля."""
    rule = _rule("SOCIAL_AREA_VS_BUDGET")
    assert "2150-ПП" in rule and "27" in rule, rule
    assert "норматива города нет" not in rule, rule


def test_the_clinic_stays_a_field_not_a_step() -> None:
    """Предел — не ступень по ёмкости: таблица РНГП о поликлинике молчит, отвечает поле."""
    assert core.moscow_social_area_per_place("clinic", 300) is None
    inputs = {**core.DEFAULT_INPUTS, "clinic_capacity": 300}
    assert core.social_area_per_place(inputs, "clinic") == 27.0
    # Сохранённое своё число сильнее умолчания — его не переписывают пределом.
    assert core.social_area_per_place({**inputs, KEY: 15}, "clinic") == 15.0


def test_the_region_keeps_its_own_number() -> None:
    """Область пишет в то же поле свою норму, а не московский предел."""
    assert core.MO_NORMS_DEFAULT["clinic_gba_sqm_per_visit"] == 15.0
    # Тот же путь, что у `/mo/calculate`: программа соцобъектов области → вводные.
    social = core.mo_social_program(50000.0, core.MO_NORMS_DEFAULT)
    assert social["clinic"]["capacity"] > 0
    _tep, inputs = core._mo_tep_and_inputs(
        social, {}, site_area_ha=5.0, norms=core.MO_NORMS_DEFAULT, average_flat_sqm=58.8)
    assert inputs[KEY] == core.MO_NORMS_DEFAULT["clinic_gba_sqm_per_visit"]
    assert inputs[KEY] != core.DEFAULT_INPUTS[KEY]


def test_the_page_reads_the_default_from_the_engine() -> None:
    """Страница получает 27 подстановкой умолчаний движка: второй копии числа нет."""
    page_defaults = json.loads(re.search(
        r"const INPUT_DEFAULT=(\{.*?\});\n", core.PAGE).group(1))
    assert page_defaults[KEY] == core.DEFAULT_INPUTS[KEY] == 27
    # На странице о поликлинике не говорится, что нормы города нет.
    assert "норматива города для этого объекта нет" not in core.PAGE
    assert "У поликлиники норматива города нет" not in core.PAGE


def _open(playwright, tmp_path, saved: dict | None):
    import browser_launch

    html = core.PAGE.replace("__DEVELOPAID_VERSION__", "test")
    file = tmp_path / "page.html"
    file.write_text(html, encoding="utf-8")
    with playwright.sync_playwright() as pw:
        try:
            browser = browser_launch.launch(pw)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda exc: errors.append(str(exc)))
            tab.route("**/*", lambda route: route.abort()
                      if route.request.url.startswith("http") else route.continue_())
            if saved is not None:
                tab.add_init_script(
                    "localStorage.setItem('plato_v04', " + json.dumps(json.dumps(saved)) + ");")
            tab.goto(file.as_uri())
            tab.wait_for_function("() => typeof syncTep === 'function'", timeout=15000)
            got = tab.evaluate("""() => {
              inputs.social_mode = 'Строительство';
              inputs.clinic_capacity = 120; inputs.social_clinic_gba_sqm = 0; syncTep(false);
              return Number(inputs.social_clinic_norm_sqm||0);
            }""")
            tab.close()
        finally:
            browser.close()
    assert [item for item in errors if "Failed to fetch" not in item] == [], errors
    return got


def test_a_saved_project_keeps_its_own_number_in_the_browser(tmp_path) -> None:
    """Сохранённое состояние накладывается на умолчания, а не подменяется ими.

    Проект с вписанными 15 остаётся при 15; проект без этого ключа получает 27.
    """
    playwright = pytest.importorskip("playwright.sync_api")
    assert _open(playwright, tmp_path, {"inputs": {KEY: 15}}) == 15
    assert _open(playwright, tmp_path, {"inputs": {"clinic_capacity": 50}}) == 27
    assert _open(playwright, tmp_path, None) == 27

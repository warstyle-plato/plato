"""Правка Платона должна доезжать до вводных, а не только до текста ответа.

Кнопка «Применить в модель» рапортовала об успехе, но модель открывалась со
старыми цифрами. Причин было две, и обе молчаливые:

1. Имена в patch — переменные Платона, а не поля модели. «Основное
   строительство» у него одно, а полей два — наземное и подземное. Простой
   inputs.update(patch) писал ключ, которого движок не читает.
2. Страница применяла из calc_overrides фиксированный список: класс проекта,
   три цены и СМР из диалога бота. Всё остальное отбрасывалось молча.

Запуск: python3 -m pytest tests -q
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

CONTEXT = {
    "session": "s-1", "chat_id": 42,
    "inputs": {"main_above_th_per_sqm": 110.0, "main_under_th_per_sqm": 110.0,
               "purchase_price_mln": 6500.0},
    "tep": {}, "rates": [], "phasing": {}, "selected_view": "all",
    "session_data": {"cad": ["50:12:0010101:1"]},
}


@pytest.fixture
def applied(monkeypatch, tmp_path):
    monkeypatch.setattr(wrapper, "_STATE_DIR", tmp_path)
    monkeypatch.setattr(wrapper, "_PLATON_CONTEXT_BY_SESSION", {"s-1": json.loads(json.dumps(CONTEXT))})
    monkeypatch.setattr(wrapper, "_PLATON_LAST_URL", {})
    monkeypatch.setattr(wrapper, "_PLATON_PENDING", {42: {"session": "s-1", "proposal": {
        "patch": {"main_construction_cost_th_per_sqm": 150.0},
        "changes": [{"variable": "main_construction_cost_th_per_sqm",
                     "label": "Основное строительство, тыс. ₽/м² ГНС",
                     "old": 110.0, "new": 150.0}],
    }}})
    captured: dict = {}

    def fake_url(chat_id, cads, manual_tep=None, calc_overrides=None, mode=None):
        captured["overrides"] = calc_overrides or {}
        return "https://example.org/#telegram_session=s-new&mode=edit"

    monkeypatch.setattr(wrapper.core, "_telegram_web_app_url", fake_url)
    result = wrapper._apply_proposal(42)
    return result, captured, wrapper._PLATON_CONTEXT_BY_SESSION["s-1"]["inputs"]


def test_a_virtual_variable_lands_on_both_real_fields(applied):
    _, _, inputs = applied
    assert inputs["main_above_th_per_sqm"] == 150.0
    assert inputs["main_under_th_per_sqm"] == 150.0
    assert "main_construction_cost_th_per_sqm" not in inputs, \
        "в inputs записан ключ, которого движок не читает"


def test_the_new_link_carries_the_real_fields(applied):
    _, captured, _ = applied
    overrides = captured["overrides"]
    assert overrides.get("main_above_th_per_sqm") == 150.0
    assert overrides.get("main_under_th_per_sqm") == 150.0


def test_untouched_fields_do_not_leak_into_the_link(applied):
    _, captured, _ = applied
    assert "purchase_price_mln" not in captured["overrides"], \
        "в ссылку попало то, что Платон не менял"


# --- страница -------------------------------------------------------------

def page_function(name: str) -> str:
    source = wrapper.core.PAGE
    start = source.index(f"function {name}(")
    depth, index = 0, source.index("{", start)
    for position in range(index, len(source)):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
            if depth == 0:
                return source[start:position + 1]
    raise AssertionError(f"не найдена функция {name}")


def run_overrides(overrides: dict) -> dict:
    """Прогоняет настоящий код страницы в node — без копии логики в тесте."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    defaults = re.search(r"const INPUT_DEFAULT=(\{.*?\});", wrapper.core.PAGE, re.S).group(1)
    script = (
        f"const INPUT_DEFAULT={defaults};\n"
        "let inputs=structuredClone(INPUT_DEFAULT);\n"
        f"let telegramCalcOverrides={json.dumps(overrides, ensure_ascii=False)};\n"
        + page_function("applyTelegramCalcOverrides") + "\n"
        "applyTelegramCalcOverrides();\n"
        "console.log(JSON.stringify(inputs));\n"
    )
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_page_applies_any_real_field_from_the_link():
    inputs = run_overrides({"main_above_th_per_sqm": 150, "main_under_th_per_sqm": 150})
    assert inputs["main_above_th_per_sqm"] == 150
    assert inputs["main_under_th_per_sqm"] == 150


def test_the_page_accepts_zero_as_a_value():
    """Платон предлагает и цену покупки 0 — раньше ноль отбрасывался как пустой."""
    assert run_overrides({"purchase_price_mln": 0})["purchase_price_mln"] == 0


def test_the_page_ignores_names_that_are_not_model_fields():
    inputs = run_overrides({"main_construction_cost_th_per_sqm": 150, "выдумка": 1})
    assert "main_construction_cost_th_per_sqm" not in inputs
    assert "выдумка" not in inputs


def test_the_bot_dialog_smr_still_zeroes_double_counted_items():
    """Старая ставка из диалога включает благоустройство и резерв."""
    inputs = run_overrides({"smr_th_per_sqm": 150})
    assert inputs["main_above_th_per_sqm"] == 150
    assert inputs["landscaping_th_per_sqm"] == 0
    assert inputs["reserve_pct"] == 0
    assert "smr_th_per_sqm" not in inputs


def test_the_page_keeps_the_project_class():
    assert run_overrides({"project_class": "business"})["project_class"] == "business"

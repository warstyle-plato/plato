"""Отсутствующий ключ — не «снято»: чекбокс берёт своё умолчание.

Чекбокс рисовался по `!!inputs[id]`. Поля, которого нет в наборе, это
превращало в снятое состояние, а обратно со страницы уходил явный `false` —
умолчание `true` терялось безвозвратно.

Дороже всего это вышло на «ВРИ включена в банковский бюджет». Признак снят —
плата за смену ВРИ уходит из долгового финансирования, будто её платят
собственными деньгами: долг меньше на 1,8 млрд ₽, проценты меньше на 402 млн ₽,
и LLCR показывает 1,16x вместо настоящих 1,07x. Отчёт при этом выглядит
безупречно, и понять по нему, что признак потерян, нельзя.

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

core = wrapper.core

# Признаки с умолчанием «включено» — те, чья потеря молча меняет экономику.
DEFAULT_ON = ["vri_required", "vri_in_bank_budget"]


def render_line() -> str:
    match = re.search(r"if\(type==='checkbox'\)el\.checked=.*?;", core.PAGE)
    assert match, "строка отрисовки чекбокса не найдена"
    return match.group(0)


def checked_for(inputs: dict, field: str) -> bool:
    """Прогоняет настоящую строку отрисовки из PAGE."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    defaults = re.search(r"const INPUT_DEFAULT=(\{.*?\});", core.PAGE, re.S).group(1)
    script = (
        f"const INPUT_DEFAULT={defaults};\n"
        f"const inputs={json.dumps(inputs)};\n"
        f"const id={json.dumps(field)}, type='checkbox';\n"
        "const el={};\n"
        + render_line() + "\n"
        "console.log(JSON.stringify(el.checked));\n"
    )
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.parametrize("field", DEFAULT_ON)
def test_a_missing_key_falls_back_to_the_default(field):
    """Поля нет в наборе — берётся умолчание, а не «снято»."""
    assert core.DEFAULT_INPUTS[field] is True, "тест сторожит признак с умолчанием «включено»"
    assert checked_for({}, field) is True


@pytest.mark.parametrize("field", DEFAULT_ON)
def test_an_explicit_choice_still_wins(field):
    """Снятый пользователем признак остаётся снятым — это его решение."""
    assert checked_for({field: False}, field) is False
    assert checked_for({field: True}, field) is True


def test_losing_the_bank_budget_flag_moves_the_llcr():
    """Цена вопроса: та самая разница 1,16x против 1,07x."""
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(purchase_price_mln=700, land_rights_cost_mln=1276.304,
                  project_start="2027-01-01", ird_months=18,
                  apartment_price_th=650, commercial_price_th=650, parking_price_th=5000)

    inside = core.calculate(core.CalcRequest(inputs=inputs, tep=core.TEP_DEFAULT, rates=[]))
    outside = core.calculate(core.CalcRequest(
        inputs={**inputs, "vri_in_bank_budget": False}, tep=core.TEP_DEFAULT, rates=[]))

    assert outside["summary"]["llcr"] > inside["summary"]["llcr"], (
        "потерянный признак обязан быть виден в LLCR")
    assert (outside["report"]["financing"]["pf_limit"]
            < inside["report"]["financing"]["pf_limit"])

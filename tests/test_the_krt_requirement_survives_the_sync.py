"""Требование КРТ по соцобъектам вписывается руками и переживает пересчёт.

«В КРТ уже прописаны требования к СОШ, ДОО и поликлинике по местам и площади,
и они не совпадают с нормативными… может галочку ручной ввод? Сейчас меняешь
места в Экономике, он пересчитывает площадь, в ТЭПах меняешь вручную площадь,
он опять возвращает» (владелец, 03.09.2026).

Так и было: при каждой синхронизации код ставил норматив по ступени РНГП и
пересчитывал площадь как «места × норматив». Вписанное затиралось всегда,
кроме случая, когда площадь принесла выгрузка ГлавАПУ.

Приоритет теперь по полю: руками > документ лота КРТ > выгрузка ГлавАПУ >
норматив. Договор называет места и площадь — это обязательство, а норматив
отвечает на другой вопрос («сколько положено»), и по названным договором
полям он слабее.

Второе здесь же — про вкладку: перерисовка вводных случается ПОСРЕДИ ввода
(место ДОО дописывает площадь во вводные), и прежде она оставляла раскрытой
только первую группу. «Социальная нагрузка» схлопывалась после каждого числа.

Запуск: python3 -m pytest tests/test_the_krt_requirement_survives_the_sync.py -q
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

PAGE = core.PAGE


def _function(name: str) -> str:
    start = PAGE.index(f"function {name}(")
    depth, index, seen = 0, PAGE.index("{", start), False
    while index < len(PAGE):
        if PAGE[index] == "{":
            depth, seen = depth + 1, True
        elif PAGE[index] == "}":
            depth -= 1
            if seen and depth == 0:
                return PAGE[start:index + 1]
        index += 1
    raise AssertionError(f"не нашёл конец функции {name}")


def test_the_field_exists_and_defaults_to_the_norm() -> None:
    """Умолчание — норматив: ручной режим включает человек, а не мы за него."""
    assert core.DEFAULT_INPUTS["social_area_source"] == "norm"
    social = [group for group in core.FIELD_GROUPS if group[0] == "Социальная нагрузка"]
    assert social, "группа «Социальная нагрузка» пропала"
    names = {field[0] for field in social[0][1]}
    assert "social_area_source" in names


def _sync(source: str) -> dict:
    """Прогнать настоящую синхронизацию страницы на одном соцобъекте."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    program = (
        "const TEP_RATIOS=" + json.dumps(core.TEP_RATIOS) + ";\n"
        "const SOCIAL_AREA_STEPS="
        + json.dumps({kind: [list(pair) for pair in steps]
                      for kind, steps in core.MOSCOW_SOCIAL_AREA_PER_PLACE.items()},
                     default=lambda v: 1e12) + ";\n"
        + _function("socialAreaPerPlace") + "\n"
        # Договор КРТ: 1 100 мест и 14 300 м² — норматив на такой ёмкости даёт 13.
        f"const inputs={{social_area_source:{json.dumps(source)},"
        "school_places:1100,social_school_gba_sqm:14300,social_school_norm_sqm:11};\n"
        "const tep={school:{}};\n"
        "const row='school', unitsId='school_places',"
        " areaId='social_school_gba_sqm', normId='social_school_norm_sqm';\n"
        "const socialBuild=true;\n"
        "const glavapuSocialSpp=()=>0, glavapuSocialNp=()=>0;\n"
        "let inputsFilled=false;\n"
        # тот же кусок, что и на странице: ручной режим гасит норматив и пересчёт
        "const byHand=String(inputs.social_area_source||'norm')==='manual';\n"
        "const units=socialBuild?Number(inputs[unitsId]||0):0;\n"
        "const cityNorm=byHand?0:socialAreaPerPlace(row,units);\n"
        "if(cityNorm&&Number(inputs[normId]||0)!==cityNorm){inputs[normId]=cityNorm;inputsFilled=true}\n"
        "let area=socialBuild?Number(inputs[areaId]||0):0;\n"
        "const imported=glavapuSocialSpp(row), importedNp=glavapuSocialNp(row);\n"
        "if(!byHand&&socialBuild&&units>0&&Number(inputs[normId]||0)>0\n"
        "   &&(area<=0||(cityNorm&&!importedNp))){area=units*Number(inputs[normId]||0);"
        "inputs[areaId]=area;inputsFilled=true}\n"
        "tep[row].total_area=area;tep[row].units=units;\n"
        "process.stdout.write(JSON.stringify({area:inputs[areaId],"
        "norm:inputs[normId],tep:tep[row].total_area}));"
    )
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:800]
    return json.loads(done.stdout)


def test_by_hand_the_contract_numbers_stay() -> None:
    """14 300 м² по договору остаются, и норматив под них не подставляется."""
    got = _sync("manual")
    assert got["area"] == 14300, got
    assert got["norm"] == 11, "норматив переписан там, где решает договор"
    assert got["tep"] == 14300, "в ТЭП уехала не та площадь"


def test_by_the_norm_the_area_is_still_counted() -> None:
    """Умолчание не тронуто: без ручного режима площадь считается местами."""
    got = _sync("norm")
    assert got["norm"] == 13, "ступень РНГП для 1 100 мест — 13 м²/место"
    assert got["area"] == 1100 * 13, got


def test_the_page_itself_carries_the_same_gate() -> None:
    """Прогон выше повторяет код страницы — значит он обязан быть к ней привязан.

    Пересказ проверяет себя: разойдись страница со снимком, и он останется
    зелёным. Поэтому здесь сверяется САМА страница — что признак объявлен и
    что им закрыты ОБА места записи: и норматив, и площадь.
    """
    block = _function("syncTep")
    assert "const byHand=String(inputs.social_area_source||'norm')==='manual';" in block
    assert "const cityNorm=byHand?0:socialAreaPerPlace(row,units);" in block, (
        "норматив пишется мимо признака ручного ввода")
    assert "if(!byHand&&socialBuild&&units>0" in block, (
        "площадь пересчитывается мимо признака ручного ввода")


def test_a_redraw_keeps_the_open_group() -> None:
    """Перерисовка не схлопывает то, что человек раскрыл, и не теряет фокус."""
    body = _function("renderInputs")
    assert "wasOpen" in body, "раскрытые группы не запоминаются"
    assert "box.querySelectorAll('details[data-group]')" in body
    # Снимок делается ДО очистки узла — иначе он всегда пуст.
    assert body.index("wasOpen") < body.index("box.innerHTML=''")
    assert "back.focus()" in body, "фокус после перерисовки не возвращается"

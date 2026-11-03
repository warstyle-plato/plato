"""Квартир не бывает 412,94, и сумма очередей сходится со строкой проекта.

Владелец, 04.09.2026: «штуки квартир не могут быть дробными». Доли режут
метры, а штуки считаются: округлять каждую долю по отдельности нельзя — три
очереди по 412,94 дают 1239 при проектных 1238, и таблица честно показывает
расхождение с проектом.

Запуск: python3 -m pytest tests/test_units_are_whole_and_add_up.py -q
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
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


def _run(program: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:800]
    return json.loads(done.stdout)


def test_the_split_gives_whole_units_that_sum_to_the_project() -> None:
    """Наибольший остаток: числа целые, сумма равна строке проекта."""
    program = _function("phaseIntegerSplit") + "\n" + (
        "const cases=[[1238,[40,32,28]],[1361,[25,25,25,25]],[7,[33,33,34]],"
        "[0,[50,50]],[5,[100]]];"
        "process.stdout.write(JSON.stringify(cases.map(([total,shares])=>{"
        "const sum=shares.reduce((s,v)=>s+v,0);"
        "return {total:total,parts:phaseIntegerSplit(total,shares,sum)};})));"
    )
    for case in _run(program):
        parts = case["parts"]
        assert all(float(p).is_integer() for p in parts), f"дробные штуки: {parts}"
        assert sum(parts) == case["total"], f"{parts} не складываются в {case['total']}"


def test_a_queue_never_takes_more_than_the_project_has() -> None:
    """Ни одна доля не больше целого — иначе очередь строит чужие квартиры."""
    program = _function("phaseIntegerSplit") + "\n" + (
        "process.stdout.write(JSON.stringify("
        "phaseIntegerSplit(3,[97,1,1,1],100)));"
    )
    parts = _run(program)
    assert sum(parts) == 3 and max(parts) <= 3


def test_the_field_asks_for_a_whole_number() -> None:
    """Шаг поля штук — единица, а не «any»: округление на экране и в расчёте одно."""
    assert "const isCount=field==='units'" in PAGE
    assert "step=\"${isCount?'1':'any'}\"" in PAGE
    body = _function("setPhaseProductTep")
    assert "Math.round(asked)" in body, "вписанные руками штуки остаются дробными"
    assert "Math.floor(limit" in body, "ограничение остатком возвращает дробь"


def test_the_transfer_row_names_what_it_is_taken_from() -> None:
    """«Передаётся в м²» рядом с метрами И штуками не отвечает, из чего вычесть."""
    assert "передаётся, м² — из продаваемой площади" in PAGE
    assert "передаётся, шт. — из продаваемых мест" in PAGE


def test_a_social_object_has_no_transfer_cell() -> None:
    """Садик не отдают наполовину: продаваемой площади у него нет вовсе.

    С появлением ФОКа таких строк стало две породы: у соцобъекта передаётся
    весь объект, у ФОКа передача решается признаком «что с объектом дальше».
    Обе рисуются одинаково — «передаётся» не вводится руками, — и список у них
    один: `DERIVED_TRANSFER_PRODUCTS`. Второй список разошёлся бы с первым
    молча, и значение доехало бы мимо экрана.
    """
    assert "const SOCIAL_TEP_PRODUCTS=['kindergarten','school','clinic'];" in PAGE
    assert "const DERIVED_TRANSFER_PRODUCTS=SOCIAL_TEP_PRODUCTS.concat(['sports']);" in PAGE
    assert "передаётся городу целиком" in PAGE
    assert "DERIVED_TRANSFER_PRODUCTS.includes(k)\n    ? `<div class=\"phase-given-none\"" in PAGE, (
        "у соцобъекта по-прежнему рисуется поле ввода")
    setter = PAGE[PAGE.index("function setPhaseProductGiven("):]
    setter = setter[:setter.index("\nfunction ")]
    assert "if(DERIVED_TRANSFER_PRODUCTS.includes(key))return;" in setter, (
        "правило одно на отрисовку и на ввод — иначе значение доедет мимо экрана")

"""Встроенная коммерция следует за правкой жилья — пропорцией и вслух.

Владелец (09.09.2026): «Сделал расчет по тэп глав апу. Человек подтвердил что
дали 45000 квартир. Поменял вручную. Вроде бы машиноместа ври и соц платеж
поменялись верно. А почему коммерция первого этажа пропорционально не
изменилась?»

Не изменилась потому, что правка ячейки заполняет только СВОЮ строку по её
долям, а пересчёт по базе ГлавАПУ берёт встроенную коммерцию из таблицы как
ВВОДНУЮ. Места, соцплатёж и население считаются от квартир и жилой СПП — они и
поехали; коммерция осталась нормативной. Пропорция 94/6 при этом жила
литералами в четырёх местах и при правке одной строки не применялась вовсе.

Цена молчания не только в метрах: плата за ВРИ считается от жилой СПП ВМЕСТЕ
со встроенной (`vri_rate * (res_spp + built_in_spp)`), то есть её база
оставалась наполовину прежней, а выручка коммерции — тоже.

Решение владельца в тот же день: «Пересчитывать по 6/94 и называть это».

Запуск: python3 -m pytest tests/test_built_in_commercial_follows_the_flats.py -q
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
from tests import page_blocks  # noqa: E402

def _prelude(split):
    return "\n".join([
    "const TEP_RATIOS=" + json.dumps(core.TEP_RATIOS, ensure_ascii=False) + ";",
    "const MKD_SPP_SPLIT=" + json.dumps(split, ensure_ascii=False) + ";",
    "const TEP_SOCIAL_INPUTS={kindergarten:'social_dou_gba_sqm',"
    "school:'social_school_gba_sqm',clinic:'social_clinic_gba_sqm'};",
    "const TEP_ROW_INPUTS={};const TEP_ROW_SWITCH={};",
    "let inputs={},tep=" + json.dumps(core.TEP_DEFAULT, ensure_ascii=False) + ";",
    # Отрисовка и поход на сервер к ответу отношения не имеют: пересчёт строки
    # считается до них. Заглушка тут законна ровно потому, что она не отвечает
    # за проверяемую величину.
    "function renderTep(){}",
    "function renderInputs(){}",
    "function updateTepTotals(){}",
    "function calculate(){}",
    "function scheduleTepAutoRecalc(){}",
    "function landNum(v,d){return Number(v||0).toFixed(d||0)}",
    ])


def _run_page(tail: str, split=None):
    """Гоняет НАСТОЯЩИЙ `tepCellChanged`, добирая зависимости по именам.

    Список зависимостей не перечисляется: перечисленный, он отстаёт от
    страницы, и стенд падает на своей неполноте вместо своего утверждения.
    """
    prelude = _prelude(split or core.MKD_SPP_SPLIT)
    taken: list[str] = []
    bodies: list[str] = []
    for _ in range(60):
        script = prelude + "\n" + "\n".join(bodies) + "\n" + tail
        done = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        if done.returncode == 0:
            return json.loads(done.stdout), taken
        error = done.stderr
        if "ReferenceError" not in error or " is not defined" not in error:
            raise AssertionError(error[-2500:])
        name = error.split("ReferenceError: ")[1].split(" is not defined")[0].strip()
        if name in taken:
            raise AssertionError(f"{name} не разрешается\n{error[-1500:]}")
        bodies.append(page_blocks.piece(name))
        taken.append(name)
    raise AssertionError("зависимостей больше, чем разумно разрешать")


def _edit(field: str, value: float, split=None):
    tail = "\n".join([
        f"tepCellChanged('apartments',{field!r},{value});",
        "console.log(JSON.stringify({apartments:tep.apartments,"
        "commercial:tep.ground_commercial,"
        "note:(tepRefillNote.ground_commercial||null)}));",
    ])
    return _run_page(tail, split)


def test_the_flats_pull_the_built_in_commercial():
    """45 000 м² квартир по решению тянут за собой встроенную коммерцию."""
    shown, taken = _edit("saleable", 45000)
    assert "tepCellChanged" in taken, "стенд обязан гонять сам обработчик правки"

    was = float(core.TEP_DEFAULT["ground_commercial"]["gns"])
    living = float(shown["apartments"]["gns"])
    want = living / core.MKD_SPP_SPLIT["apartments"] * core.MKD_SPP_SPLIT["ground_commercial"]

    # Предохранитель: пример обязан двигать коммерцию, иначе утверждение ниже
    # проходит и на невыполненной правке.
    assert abs(want - was) > 100, "пример подобран так, что проверять нечего"
    assert shown["commercial"]["gns"] == pytest.approx(want, abs=0.2)
    # Остальные числа строки идут за ГНС её же долями.
    ratio = core.TEP_RATIOS["ground_commercial"]
    assert shown["commercial"]["total_area"] == pytest.approx(
        want * ratio["total_of_gns"], abs=0.2)
    assert shown["commercial"]["saleable"] == pytest.approx(
        want * ratio["saleable_of_gns"], abs=0.2)


def test_the_rescale_says_it_did_it():
    """Пересчитанное называется — и не красным."""
    shown, _ = _edit("saleable", 45000)
    note = shown["note"]
    assert note, "молча переписанная строка неотличима от невнимательности"
    assert "94/6" in note["text"], note
    assert note["tone"] == "", "сообщение о посчитанном — не жалоба, и красным не красится"


def test_the_message_and_the_metres_come_from_the_declared_split():
    """Доля в сообщении и в счёте — одна, объявленная, а не литерал в строке.

    Запрещать «94/6» поиском по исходнику нельзя: под запрет попадёт и
    объяснение, почему доля объявлена (первая версия этой проверки на нём и
    упала). Проверяется поведением — подменяем объявленную долю и смотрим, что
    за ней пошли ОБА: и метры, и подпись.
    """
    other = {"apartments": 0.90, "ground_commercial": 0.10}
    shown, _ = _edit("saleable", 45000, other)
    living = float(shown["apartments"]["gns"])
    assert shown["commercial"]["gns"] == pytest.approx(
        living / other["apartments"] * other["ground_commercial"], abs=0.2)
    assert "90/10" in shown["note"]["text"], shown["note"]


def test_an_empty_flat_area_does_not_wipe_the_commercial():
    """Стёртые квартиры — это «человек печатает», а не «коммерции нет»."""
    shown, _ = _edit("saleable", 0)
    assert shown["commercial"]["gns"] == pytest.approx(
        core.TEP_DEFAULT["ground_commercial"]["gns"])
    assert shown["note"] is None


def test_the_split_is_declared_once():
    """94/6 объявлена в движке и подставлена — рукописных копий нет."""
    assert core.MKD_SPP_SPLIT["apartments"] + core.MKD_SPP_SPLIT["ground_commercial"] == 1.0
    page = core.PAGE
    handwritten = re.findall(r"spp\s*\*\s*0\.(?:94|06)", page)
    assert not handwritten, f"на странице {len(handwritten)} рукописных долей СПП"
    source = Path(ROOT / "main_legacy.py").read_text(encoding="utf-8")
    literals = re.findall(r"(?:project_total_gns|total_spp|spp)\s*\*\s*0\.(?:94|06)", source)
    assert not literals, f"в движке {len(literals)} рукописных долей СПП"

def test_the_refill_button_pulls_it_too():
    """Кнопка «пересчитать строку» двигает жилую СПП — коммерция идёт за ней.

    Правило, закрытое в одном месте, соседнее не защищает: у строки квартир два
    пути правки — ячейка и кнопка, — и по второму жильё меняется ровно так же
    (вписана только продаваемая, ГНС считается из неё).
    """
    tail = "\n".join([
        "tep.apartments.gns=0;tep.apartments.total_area=0;",
        "tep.apartments.saleable=45000;",
        "refillTepRow('apartments');",
        "console.log(JSON.stringify({apartments:tep.apartments,"
        "commercial:tep.ground_commercial,"
        "note:(tepRefillNote.ground_commercial||null)}));",
    ])
    shown, taken = _run_page(tail)
    assert "refillTepRow" in taken, "стенд обязан гонять саму кнопку"
    living = float(shown["apartments"]["gns"])
    assert living == pytest.approx(45000 / core.TEP_RATIOS["apartments"]["saleable_of_gns"],
                                   abs=0.2)
    assert shown["commercial"]["gns"] == pytest.approx(
        living / core.MKD_SPP_SPLIT["apartments"] * core.MKD_SPP_SPLIT["ground_commercial"],
        abs=0.2)
    assert shown["note"], "пересчёт по кнопке тоже называется"

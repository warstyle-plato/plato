"""Движку подаёт страница, а не тест.

Подземный паркинг Мытищ — 2 723 машино-места — при трёх очередях превращался в
8 169. Причина оказалась не в делёжке: доли считались верно, а вводные очереди
уносили общее решение по машино-местам, и атомарный расчёт перетирал долю
итогом проекта.

Почему это пережило полторы тысячи тестов: фазовые тесты подавали движку
**чистый ТЭП**, где поля паркинга пусты. Живая страница подаёт другое — после
любого импорта ГлавАПУ `applyGlavapu` сам заполняет пару полей вызовом
`fillUndergroundFromTep()`. А единственный тест, который гонял настоящий
`applyGlavapu` через node, эту функцию и `getGlavapuUnderground` заглушал —
ровно те две, из-за которых всё и происходило.

Отсюда правило: **тест кормит движок тем же, чем кормит его страница.** Здесь
файл ГлавАПУ проходит настоящий путь целиком — разбор, `applyGlavapu` с живыми
функциями паркинга, — и полученные вводные уходят в расчёт с очередями.

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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

PRESETS = ROOT / "presets"


def page_function(name: str) -> str:
    start = core.PAGE.index(f"function {name}(")
    depth = 0
    for position in range(core.PAGE.index("{", start), len(core.PAGE)):
        if core.PAGE[position] == "{":
            depth += 1
        elif core.PAGE[position] == "}":
            depth -= 1
            if depth == 0:
                return core.PAGE[start:position + 1]
    raise AssertionError(f"не найдена функция {name}")


def live_import(preset_name: str) -> dict:
    """Прогоняет файл через настоящий applyGlavapu страницы.

    Функции паркинга — живые. Заглушить их значит проверить не тот путь,
    которым ходит человек."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    data = (PRESETS / preset_name).read_bytes()
    parsed = core.parse_glavapu_xlsx(data, preset_name)

    keys = re.search(r"(const TERRITORY_INPUT_KEYS=.*?)\nfunction resetTerritoryData",
                     core.PAGE, re.S)
    body = re.search(r"(function resetTerritoryData\(.*?)\nfunction getGlavapuUnderground",
                     core.PAGE, re.S)
    assert keys and body, "функции применения ГлавАПУ не найдены на странице"

    stubs = (
        "const document={getElementById:()=>({style:{},innerHTML:''})};\n"
        "const glavapuStatus={innerHTML:''};\n"
        "let phasing=null;let cadastralAnalysis=null;let moResult=null;\n"
        "function makeDefaultPhasing(){return {enabled:false,phase_count:1}}\n"
        "function applyRequiredSocialProgramFromGlavapu(){}\nfunction syncTep(){}\n"
        "function applyServerPresetProjectConfig(){return ''}\n"
        "function applyTelegramCalcOverrides(){}\nfunction renderInputs(){}\n"
        "function renderTep(){}\nfunction renderPhasing(){}\n"
        "function renderGlavapuPreview(){}\n"
        "async function calculate(){}\nasync function sendTelegramResult(){}\n"
        f"let inputs={json.dumps(core.DEFAULT_INPUTS)};\n"
        f"let tep={json.dumps(core.TEP_DEFAULT)};\nlet glavapuImport=null;\n")
    # Живые — не заглушённые: именно они заполняют пару полей паркинга.
    real = "\n".join(page_function(name) for name in (
        "getGlavapuUnderground", "undergroundAreaPerSpace",
        "repairParkingFromGlavapu", "fillUndergroundFromTep"))

    script = (f"const payload={json.dumps(parsed, ensure_ascii=False, default=str)};\n"
              + stubs + real + "\n" + keys.group(1) + "\n" + body.group(1)
              + "\n(async()=>{glavapuImport=payload;await applyGlavapu();"
                "console.log(JSON.stringify({inputs,tep}));})()")
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[:600]
    return json.loads(done.stdout)


def phasing(count: int) -> dict:
    return {"enabled": True, "mode": "phased", "phase_count": count, "user_enabled": True,
            "phase_gap_months": 12,
            "phases": [{"name": f"О{i+1}", "start_offset_months": 12 * i,
                        "construction_months": 30} for i in range(count)]}


@pytest.fixture(scope="module")
def mytishchi():
    return live_import("Мытищи_ТЭП.xlsx")


# --- страница действительно подаёт не то, что подавали тесты ---------------------

def test_the_import_fills_the_parking_fields(mytishchi):
    """Условие, при котором ломалось, создаёт сам импорт — не человек.

    Пока тесты подавали нули в этих полях, ветка, из-за которой всё и
    происходило, оставалась недостижимой."""
    assert mytishchi["inputs"]["underground_manual_spaces"] > 0
    assert mytishchi["inputs"]["underground_manual_gns_sqm"] > 0


def test_the_page_and_the_engine_see_one_parking(mytishchi):
    """Строка ТЭП и поле вводных обязаны говорить об одном паркинге."""
    spaces = float(mytishchi["inputs"]["underground_manual_spaces"])
    assert float(mytishchi["tep"]["underground_parking"]["units"]) == pytest.approx(
        spaces, abs=1.0)


# --- и с этими вводными очереди по-прежнему делят, а не множат --------------------

@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_the_queues_keep_the_imported_parking(mytishchi, count):
    """Главная проверка: свод очередей равен паркингу участка."""
    inputs, tep = mytishchi["inputs"], mytishchi["tep"]
    master = float(tep["underground_parking"]["units"])
    assert master > 0, "в файле нет подземного паркинга — тест проверял бы ноль"
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, rates=[], phasing=phasing(count)))
    total = next(item for item in bundle["consolidated"]["report"]["products"]
                 if item["key"] == "underground_parking")
    assert total["quantity"] == pytest.approx(master, abs=1.0)


@pytest.mark.parametrize("count", [2, 3, 4])
def test_the_project_area_does_not_grow_with_queues(mytishchi, count):
    """ГНС проекта — знаменатель удельных показателей: вырасти она с числом
    очередей, и себестоимость метра поехала бы вслед."""
    inputs, tep = mytishchi["inputs"], mytishchi["tep"]
    single = core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, rates=[], phasing=phasing(count)))
    assert bundle["consolidated"]["summary"]["project_gns_sqm"] == pytest.approx(
        single["summary"]["project_gns_sqm"], rel=1e-6)


@pytest.mark.parametrize("count", [2, 3])
def test_no_imported_product_is_multiplied(mytishchi, count):
    """То же правило на всех строках сразу — ради следующего продукта, который
    заведёт себе поле во вводных."""
    inputs, tep = mytishchi["inputs"], mytishchi["tep"]
    master = {row["key"]: row for row in
              core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))["tep"]["rows"]}
    total: dict[str, dict[str, float]] = {}
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, rates=[], phasing=phasing(count)))
    for phase in bundle["phases"]:
        for row in phase["result"]["tep"]["rows"]:
            bucket = total.setdefault(row["key"], {})
            for field in ("gns", "units"):
                bucket[field] = bucket.get(field, 0.0) + float(row.get(field) or 0.0)
    for key, row in master.items():
        for field in ("gns", "units"):
            expected = float(row.get(field) or 0.0)
            assert total.get(key, {}).get(field, 0.0) == pytest.approx(expected, abs=1.0), \
                f"{key}.{field}: очереди дают {total.get(key, {}).get(field)}, участок {expected}"


# --- вторая площадка, чтобы правило не оказалось про один файл --------------------

def test_the_rule_holds_for_another_site():
    project = live_import("Мишина_ТЭП.xlsx")
    inputs, tep = project["inputs"], project["tep"]
    master = float(tep["underground_parking"]["units"])
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, rates=[], phasing=phasing(3)))
    total = next(item for item in bundle["consolidated"]["report"]["products"]
                 if item["key"] == "underground_parking")
    assert total["quantity"] == pytest.approx(master, abs=1.0)

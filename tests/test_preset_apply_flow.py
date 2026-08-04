"""Предустановка с сервера доезжает до вводных — и переживает перезагрузку.

Пользователь загружал предустановку «Мишина», а вводные оставались дефолтными
(ВРИ 2 864,29 — умолчание движка, покупка 0): применённое состояние
сохранялось только в телеграм-потоке и кнопкой «Сохранить», любая
перезагрузка возвращала умолчания. Вторая ловушка: сохранённый проект не нёс
mappings, и повторное «Применить» сначала обнуляло территорию, а затем
применяло пустоту.

Тесты гоняют настоящие функции страницы через node — не их пересказ.

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

NODE = shutil.which("node")


def preset_payload() -> dict:
    """Ровно то, что отдаёт /presets/mishina: разбор файла с mappings."""
    data = (Path(__file__).resolve().parent.parent / "presets" / "Мишина_ТЭП.xlsx").read_bytes()
    payload = core.parse_glavapu_xlsx(data, "Мишина_ТЭП.xlsx")
    payload["source"]["preset_id"] = "mishina"
    payload["source"]["server_preset"] = True
    return payload


def apply_harness() -> str:
    """Настоящие resetTerritoryData/applyGlavapu/renderStoredGlavapu из PAGE."""
    keys = re.search(r"(const TERRITORY_INPUT_KEYS=.*?)\nfunction resetTerritoryData",
                     core.PAGE, re.S)
    body = re.search(r"(function resetTerritoryData\(.*?)\nfunction getGlavapuUnderground",
                     core.PAGE, re.S)
    assert keys and body, "функции применения ГлавАПУ не найдены на странице"
    return keys.group(1) + "\n" + body.group(1)


def run_flow(scenario_js: str) -> dict:
    if not NODE:
        pytest.skip("node недоступен")
    stubs = (
        "const document={getElementById:()=>({style:{},innerHTML:''})};\n"
        "const glavapuStatus={innerHTML:''};\n"
        "let phasing=null;let cadastralAnalysis=null;let moResult=null;\n"
        "const calls=[];\n"
        "function makeDefaultPhasing(){return {enabled:false,phase_count:1}}\n"
        "function applyRequiredSocialProgramFromGlavapu(){}\n"
        "function syncTep(){}\n"
        "function repairParkingFromGlavapu(){}\n"
        # Пара «места ↔ площадь» перезаполняется расчётом нового участка.
        "function fillUndergroundFromTep(){}\n"
        "function applyServerPresetProjectConfig(){return ''}\n"
        "function applyTelegramCalcOverrides(){}\n"
        "function renderInputs(){}\nfunction renderTep(){}\nfunction renderPhasing(){}\n"
        "function renderGlavapuPreview(){}\n"
        "async function calculate(){calls.push('calculate')}\n"
        "async function sendTelegramResult(){}\n"
        # Дефолты движка, из-за которых «непроехавшая» предустановка выглядела
        # как посчитанный проект: ВРИ 2 864,29 и нулевая покупка.
        "let inputs={purchase_price_mln:0,land_rights_cost_mln:2864.291514155844,"
        "social_compensation_mln:0,site_area_ha:0,kindergarten_places:0,school_places:0,"
        "clinic_capacity:0,social_dou_gba_sqm:0,social_school_gba_sqm:0,social_clinic_gba_sqm:0};\n"
        "let tep={apartments:{gns:0,total_area:0,useful:0,saleable:0,units:0},"
        "ground_commercial:{gns:0,total_area:0,useful:0,saleable:0,units:0},"
        "underground_parking:{gns:0,total_area:0,useful:0,saleable:0,transfer:0,units:0}};\n"
        "let glavapuImport=null;\n"
    )
    script = (
        f"const payload={json.dumps(preset_payload(), ensure_ascii=False)};\n"
        + stubs + apply_harness() + "\n"
        + scenario_js + "\n"
    )
    done = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_preset_lands_in_the_inputs():
    got = run_flow(
        "(async()=>{glavapuImport=payload;await applyGlavapu();\n"
        "console.log(JSON.stringify({vri:inputs.land_rights_cost_mln,\n"
        " comp:inputs.social_compensation_mln,area:inputs.site_area_ha,\n"
        " required:inputs.vri_required,mode:inputs.social_mode,\n"
        " saleable:tep.apartments.saleable,\n"
        " stored_mappings:Object.keys((inputs._glavapu_import.mappings||{}).inputs||{}).length>0}));})()"
    )
    assert got["vri"] == pytest.approx(1267.539)
    assert got["comp"] == pytest.approx(575.379)
    assert got["area"] == pytest.approx(0.651)
    assert got["required"] is True
    assert got["mode"] == "Денежная компенсация"
    assert got["saleable"] == pytest.approx(13920)
    assert got["stored_mappings"], "mappings не сохранены — повторное применение обнулит проект"


def test_a_reapply_after_reload_keeps_the_numbers():
    """Перезагрузка: renderStoredGlavapu поднимает файл из проекта, повторное
    «Применить» обязано дать те же числа, а не нули."""
    got = run_flow(
        "(async()=>{glavapuImport=payload;await applyGlavapu();\n"
        "glavapuImport=null;\n"  # перезагрузка страницы
        "renderStoredGlavapu();await applyGlavapu();\n"
        "console.log(JSON.stringify({vri:inputs.land_rights_cost_mln,\n"
        " comp:inputs.social_compensation_mln,saleable:tep.apartments.saleable}));})()"
    )
    assert got["vri"] == pytest.approx(1267.539)
    assert got["comp"] == pytest.approx(575.379)
    assert got["saleable"] == pytest.approx(13920)


def test_an_old_project_without_mappings_is_not_wiped():
    """Проект прежних версий mappings не нёс: применение обязано отказаться,
    а не обнулить территорию и применить пустоту."""
    got = run_flow(
        "(async()=>{glavapuImport=payload;await applyGlavapu();\n"
        "delete inputs._glavapu_import.mappings;\n"  # так сохраняли раньше
        "glavapuImport=null;renderStoredGlavapu();await applyGlavapu();\n"
        "console.log(JSON.stringify({vri:inputs.land_rights_cost_mln,\n"
        " saleable:tep.apartments.saleable,status:glavapuStatus.innerHTML}));})()"
    )
    assert got["vri"] == pytest.approx(1267.539), "территория обнулена пустым применением"
    assert got["saleable"] == pytest.approx(13920)
    assert "заново" in got["status"]


def test_the_page_applies_the_preset_in_one_click():
    """«Загрузить предустановку» применяет её сразу: двухшаговый сценарий
    заканчивался «загрузил, а в расчёте пусто»."""
    load = re.search(r"async function loadServerPreset\(\).*?\n\}", core.PAGE, re.S)
    assert load and "await applyGlavapu()" in load.group(0)


def test_every_recalculation_persists_the_state():
    """Состояние сохраняется каждым пересчётом: раньше — только в
    телеграм-потоке, и применённая предустановка не переживала перезагрузку."""
    calc = re.search(r"async function calculate\(\).*?\n return lastResult;", core.PAGE, re.S)
    assert calc, "calculate не найдена на странице"
    assert "if(telegramMode==='edit')persistLocalSilently()" not in calc.group(0)
    assert "persistLocalSilently();" in calc.group(0)

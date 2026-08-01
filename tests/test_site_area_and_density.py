"""Вкладка ТЭП знает площадь участка и плотность — с источником каждого числа.

Площадь участка приходит тремя путями: из калькулятора ГлавАПУ, из кадастра
(ЕГРН) или руками. Плотность для Москвы берётся из того же ГлавАПУ, для
площади из кадастра действует умолчание 30 000 м²/га, и всё перебивается
ручным вводом. Раньше этих полей на вкладке не было вовсе: площадь жила
внутри импорта, плотность не жила нигде, и сверить ГНС проекта с потенциалом
участка было негде.

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


def page_functions() -> str:
    """Вырезает из PAGE функции источников и эффективной плотности."""
    match = re.search(
        r"(function glavapuDensitySqmHa\(\).*?)\nfunction setSiteArea",
        core.PAGE, re.S,
    )
    assert match, "функции участка и плотности не найдены на странице"
    return match.group(1)


def run_page(inputs: dict, cadastral: bool = False) -> dict:
    if not NODE:
        pytest.skip("node недоступен")
    script = (
        f"const inputs={json.dumps(inputs)};\n"
        f"const cadastralAnalysis={'{}' if cadastral else 'null'};\n"
        + page_functions() + "\n"
        "console.log(JSON.stringify({\n"
        "  density: effectiveSiteDensity(),\n"
        "  densitySource: siteDensitySourceLabel(),\n"
        "  areaSource: siteAreaSourceLabel(),\n"
        "}));\n"
    )
    done = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# --- плотность -------------------------------------------------------------

def test_the_default_density_is_thirty_thousand():
    """Площадь из кадастра плотности не знает — действует умолчание."""
    got = run_page({"site_area_ha": 1.5, "_cadastral_analysis": {}}, cadastral=True)

    assert got["density"] == 30000
    assert "по умолчанию 30 000" in got["densitySource"]


def test_moscow_takes_the_density_from_glavapu():
    got = run_page({
        "site_area_ha": 2.0,
        "_glavapu_import": {"normalized": {"density_spp_th_sqm_ha": 25.0}},
    })

    assert got["density"] == 25000
    assert "ГлавАПУ" in got["densitySource"]


def test_a_manual_density_beats_every_source():
    got = run_page({
        "site_area_ha": 2.0,
        "site_density_sqm_per_ha": 42000,
        "_site_density_user_set": True,
        "_glavapu_import": {"normalized": {"density_spp_th_sqm_ha": 25.0}},
    })

    assert got["density"] == 42000
    assert got["densitySource"] == "введена вручную"


def test_the_mo_calculator_density_is_named_as_the_source():
    got = run_page({
        "site_area_ha": 3.0,
        "site_density_sqm_per_ha": 27000,
        "_mo_calc": {},
    })

    assert got["density"] == 27000
    assert "Подмосковья" in got["densitySource"]


def test_an_emptied_manual_density_returns_to_the_automatics():
    """Пустое поле — возврат к автоматике, а не плотность ноль."""
    got = run_page({
        "site_area_ha": 2.0,
        "site_density_sqm_per_ha": 0,
        "_glavapu_import": {"normalized": {"density_spp_th_sqm_ha": 20.0}},
    })

    assert got["density"] == 20000


# --- площадь ---------------------------------------------------------------

def test_the_area_names_its_source():
    assert run_page({"site_area_ha": 1.0, "_site_area_user_set": True})["areaSource"] \
        == "введена вручную"
    assert "ГлавАПУ" in run_page(
        {"site_area_ha": 1.0, "_glavapu_import": {"normalized": {}}})["areaSource"]
    assert "ЕГРН" in run_page(
        {"site_area_ha": 1.0, "_cadastral_analysis": {}}, cadastral=True)["areaSource"]
    assert run_page({})["areaSource"] == "не задана"


def test_a_manual_area_is_not_overwritten_by_the_cadastre():
    """Ручной ввод сильнее автоподстановки: строка заполнения проверяет флаг."""
    snippet = re.search(
        r"const cadArea=Number\(\(\(analysis\|\|\{\}\)\.territory\|\|\{\}\)\.area_ha\|\|0\);\s*\n\s*"
        r"if\(cadArea>0&&!inputs\._site_area_user_set&&!inputs\._glavapu_import\)"
        r"inputs\.site_area_ha=cadArea;",
        core.PAGE,
    )
    assert snippet, "кадастровая подстановка площади не найдена или не бережёт ручной ввод"


# --- сброс при смене территории --------------------------------------------

def test_the_density_of_the_old_site_does_not_survive_a_new_one():
    """Площадь и плотность — данные участка: смена территории их сбрасывает."""
    keys = re.search(r"const TERRITORY_INPUT_KEYS=\[(.*?)\];", core.PAGE, re.S).group(1)
    markers = re.search(r"const TERRITORY_MARKERS=\[(.*?)\];", core.PAGE, re.S).group(1)

    assert "'site_area_ha'" in keys
    assert "'site_density_sqm_per_ha'" in keys
    assert "'_site_area_user_set'" in markers
    assert "'_site_density_user_set'" in markers


# --- панель на вкладке -----------------------------------------------------

def test_the_tep_tab_carries_the_site_panel():
    for anchor in ("siteAreaHa", "siteDensity", "sitePotential", "siteUsage",
                   "Участок и плотность"):
        assert anchor in core.PAGE, f"на вкладке ТЭП нет «{anchor}»"


def test_the_potential_is_compared_with_the_above_ground_gns():
    """Плотность нормирует наземную поэтажную площадь — без подземного паркинга."""
    match = re.search(r"function renderSitePanel\(\).*?\n\}", core.PAGE, re.S)
    assert match
    assert "underground_parking" in match.group(0)


def test_glavapu_import_feeds_the_density(monkeypatch):
    """Импорт Москвы не оставляет плотность справочной."""
    snippet = re.search(
        r"const glavapuDensity=Number\(\(\(glavapuImport\.normalized\)\|\|\{\}\)"
        r"\.density_spp_th_sqm_ha\|\|0\)\*1000;",
        core.PAGE,
    )
    assert snippet, "ГлавАПУ-импорт не трогает плотность"


# --- расчёт ТЭП от плотности ------------------------------------------------

def run_apply(inputs: dict, tep: dict) -> dict:
    """Настоящая applyDensityToTep из PAGE — с заглушками окружения."""
    if not NODE:
        pytest.skip("node недоступен")
    match = re.search(r"(function applyDensityToTep\(\).*?)\nfunction setSiteArea",
                      core.PAGE, re.S)
    assert match, "applyDensityToTep не найдена на странице"
    script = (
        f"const inputs={json.dumps(inputs)};\n"
        f"const tep={json.dumps(tep)};\n"
        "const cadastralAnalysis=null;\n"
        "const shown=[];\n"
        "const document={getElementById:()=>({style:{},set innerHTML(v){shown.push(v)}})};\n"
        "const num=v=>String(Math.round(v));\n"
        "function renderTep(){}\n"
        "function calculate(){}\n"
        + re.search(r"(function glavapuDensitySqmHa\(\).*?)\nfunction siteAreaSourceLabel",
                    core.PAGE, re.S).group(1) + "\n"
        + match.group(1) + "\n"
        "applyDensityToTep();\n"
        "console.log(JSON.stringify({tep, shown}));\n"
    )
    done = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def blank_tep() -> dict:
    return {
        "apartments": {"gns": 0, "total_area": 0, "useful": 0, "saleable": 0},
        "ground_commercial": {"gns": 0, "total_area": 0, "useful": 0, "saleable": 0},
    }


def test_the_tep_is_built_from_area_and_density_in_any_region():
    """Никакого импорта и никакого региона — площадь и плотность руками."""
    got = run_apply({"site_area_ha": 2.0, "site_density_sqm_per_ha": 25000,
                     "_site_density_user_set": True}, blank_tep())

    spp = 2.0 * 25000
    apartments = got["tep"]["apartments"]
    commercial = got["tep"]["ground_commercial"]
    assert apartments["gns"] == pytest.approx(spp * 0.94)
    assert apartments["saleable"] == pytest.approx(spp * 0.94 * 0.65)
    assert commercial["gns"] == pytest.approx(spp * 0.06)
    assert commercial["saleable"] == pytest.approx(spp * 0.06 * 0.9)


def test_the_default_density_feeds_the_calculation_too():
    """Площадь из кадастра без плотности — считается по умолчанию 30 000."""
    got = run_apply({"site_area_ha": 1.0}, blank_tep())

    assert got["tep"]["apartments"]["gns"] == pytest.approx(30000 * 0.94)


def test_without_an_area_nothing_is_overwritten():
    tep = blank_tep()
    tep["apartments"]["gns"] = 5000
    got = run_apply({}, tep)

    assert got["tep"]["apartments"]["gns"] == 5000, "ТЭП затёрт без площади"
    assert any("площадь участка" in str(item) for item in got["shown"])

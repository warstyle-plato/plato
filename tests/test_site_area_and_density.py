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
# Нормативный путь (РНГП) — для ручного ТЭП, кадастра и калькулятора
# Подмосковья; долевой 94/6 — только для Москвы с ГлавАПУ, где нормативный
# расчёт делает сам калькулятор ГлавАПУ.

def run_apply(inputs: dict, tep: dict, extra_js: str = "") -> dict:
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
        + extra_js
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


NORM_STUBS = (
    "let moResult=null;\n"
    "function escapeHtml(v){return String(v)}\n"
    "function applyNormativeTep(){shown.push('NORM');return Promise.resolve({})}\n"
)


def test_a_manual_tep_is_recalculated_by_the_rngp_norms():
    """Ручной ввод площади и плотности — нормативный расчёт, а не доли 94/6:
    социалка, паркинг и офисы должны следовать за объёмом квартир."""
    got = run_apply({"site_area_ha": 2.0, "site_density_sqm_per_ha": 25000,
                     "_site_density_user_set": True}, blank_tep(), extra_js=NORM_STUBS)

    assert got["tep"] == blank_tep(), "ручной ТЭП пересчитан долями мимо нормативов"
    assert "NORM" in got["shown"], "нормативный пересчёт не вызван"
    assert any("нормативный ТЭП по РНГП" in str(item) for item in got["shown"])


def test_a_mo_project_goes_the_same_normative_way():
    """У проекта из калькулятора Подмосковья офисы на 92 тыс. м² и 7 700
    машино-мест переживали уменьшение жилья втрое — доли меняли только жильё."""
    got = run_apply(
        {"site_area_ha": 22.4, "site_density_sqm_per_ha": 8900,
         "_site_density_user_set": True,
         "_mo_calc": {"query": "50:12:0100131:497"}},
        blank_tep(), extra_js=NORM_STUBS)

    assert got["tep"] == blank_tep()
    assert "NORM" in got["shown"]


def test_moscow_with_glavapu_keeps_the_share_method():
    """Для Москвы нормативный расчёт делает ГлавАПУ — кнопка делит СПП 94/6."""
    got = run_apply({
        "site_area_ha": 2.0,
        "_glavapu_import": {"normalized": {"density_spp_th_sqm_ha": 25.0}},
    }, blank_tep(), extra_js=NORM_STUBS)

    spp = 2.0 * 25000
    apartments = got["tep"]["apartments"]
    commercial = got["tep"]["ground_commercial"]
    assert apartments["gns"] == pytest.approx(spp * 0.94)
    assert apartments["saleable"] == pytest.approx(spp * 0.94 * 0.65)
    assert commercial["gns"] == pytest.approx(spp * 0.06)
    assert commercial["saleable"] == pytest.approx(spp * 0.06 * 0.9)
    assert "NORM" not in got["shown"]


def test_the_default_density_feeds_the_calculation_too():
    """Площадь из кадастра без плотности — действует умолчание 30 000."""
    got = run_apply({"site_area_ha": 1.0}, blank_tep(), extra_js=NORM_STUBS)

    assert "NORM" in got["shown"]
    assert any("30 000" in str(item) or "30000" in str(item) for item in got["shown"])


def test_without_an_area_nothing_is_overwritten():
    tep = blank_tep()
    tep["apartments"]["gns"] = 5000
    got = run_apply({}, tep, extra_js=NORM_STUBS)

    assert got["tep"]["apartments"]["gns"] == 5000, "ТЭП затёрт без площади"
    assert any("площадь участка" in str(item) for item in got["shown"])
    assert "NORM" not in got["shown"]


def test_the_normative_potential_is_compared_with_saleable_apartments():
    """В нормативном режиме потенциал участка — м² квартир на га: сравнивать
    его с наземной ГНС бессмысленно, ГНС всегда в полтора раза больше."""
    panel = re.search(r"function renderSitePanel\(\).*?\n\}", core.PAGE, re.S).group(0)

    assert "inputs._glavapu_import" in panel
    assert "м² квартир / га" in panel
    assert re.search(r"normative\?Number\(\(tep\.apartments\|\|\{\}\)\.saleable\|\|0\)", panel), \
        "нормативный потенциал не сравнивается с продаваемой квартир"


def test_the_normative_recalc_carries_the_district():
    """Без округа плата за ВРИ берёт среднюю цену по области: на Мытищах это
    198 907 ₽ вместо 238 052 ₽ за метр — и плата занижается на четверть."""
    body = re.search(r"async function applyNormativeTep\(\).*?\n\}", core.PAGE, re.S).group(0)

    assert "inputs.mo_district" in body, "округ проекта не передаётся в расчёт"
    assert "district:district" in body.replace(" ", "")
    assert "inputs.mo_district=data.territory.district" in body.replace(" ", ""), \
        "определённый расчётом округ не запоминается в проекте"
    assert "mo_district='Городской округ Мытищи'" in core.PAGE, \
        "пресет Мытищ не несёт свой округ"


def test_the_normative_recalc_spares_the_manual_vri_payment():
    """Без кадастра плата за ВРИ не считается — введённая руками сумма
    не должна затираться нулём нормативного пересчёта."""
    body = re.search(r"async function applyNormativeTep\(\).*?\n\}", core.PAGE, re.S).group(0)

    assert "keepLand" in body
    assert "land_rights_cost_mln=keepLand" in body.replace(" ", "")


# --- одна величина, два окна -------------------------------------------------

def test_the_mo_fields_and_the_tep_panel_are_the_same_value():
    """Ввод в калькуляторе Подмосковья и на вкладке ТЭП обновляет оба окна."""
    bind = re.search(r"function bindMoParams\(\).*?\n\}", core.PAGE, re.S).group(0)
    assert "setSiteDensity(density.value)" in bind
    assert "setSiteArea(area.value)" in bind

    set_area = re.search(r"function setSiteArea\(value\).*?\n\}", core.PAGE, re.S).group(0)
    set_density = re.search(r"function setSiteDensity\(value\).*?\n\}", core.PAGE, re.S).group(0)
    assert "moArea" in set_area, "правка площади на ТЭП не доезжает в МО-блок"
    assert "moDensity" in set_density, "правка плотности на ТЭП не доезжает в МО-блок"

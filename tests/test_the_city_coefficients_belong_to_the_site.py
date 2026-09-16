"""К1, К2 и расстояние до станции принадлежат участку, а не аналитику.

Город считает их ПО ЭТОМУ участку: К1 — от его расстояния до рельсового
каркаса, К2 — по его району из приложения 3 к 945-ПП. Лежали они при этом в
предпосылках аналитика — то есть импорт нового участка их не чистил, и новая
площадка наследовала коэффициенты прежнего района. Выгрузка ГлавАПУ пишет их
только при значении больше нуля, значит площадка, которой город коэффициент не
назвал, молча оставалась с чужим.

Цена измерена здесь же, и это предохранитель проверки: если наследованный К2
норму не двигает, спор о списке не стоит ничего.

Две половины блока разъехались намеренно. «Площадь на 1 место» и «край
норматива» — методика, а не ответ города, и обнулять их нельзя буквально: ноль
метров на место делит на ноль, а пустой режим теряет выбор человека.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
import page_blocks  # noqa: E402

CITY_KEYS = ("parking_k1", "parking_k2", "parking_rail_distance_m")

# Браузерное окружение — это состояние стенда, а не кусок страницы: разрешитель
# на `document` честно отвечает «на странице нет такой функции».
PRELUDE = """
const document={getElementById:()=>null};
let inputs={parking_k1:0.2, parking_k2:0.2, parking_rail_distance_m:800,
            object_parking_area_per_space_sqm:35, parking_design_mode:'minimum',
            purchase_price_mln:7500};
let tep={};
let phasing=null;
let glavapuImport=null, cadastralAnalysis=null, moResult=null;
function makeDefaultPhasing(){return null}
"""

TAIL = """
resetTerritoryData();
console.log(JSON.stringify({
  k1:inputs.parking_k1, k2:inputs.parking_k2, dist:inputs.parking_rail_distance_m,
  per_space:inputs.object_parking_area_per_space_sqm,
  mode:inputs.parking_design_mode, price:inputs.purchase_price_mln,
  cleared:territoryCleared, note:territoryClearedNote()}));
"""


def imported() -> dict:
    """Состояние вводных после импорта участка — настоящей функцией страницы."""
    return page_blocks.run_json(PRELUDE, TAIL)


def test_the_import_clears_the_city_coefficients():
    got = imported()
    assert (got["k1"], got["k2"], got["dist"]) == (0, 0, 0), (
        "коэффициенты прежнего района пережили импорт нового участка: "
        f"К1 {got['k1']}, К2 {got['k2']}, расстояние {got['dist']}")


def test_the_cleared_coefficients_are_named_on_screen():
    # Молчаливое обнуление врёт не меньше молчаливого наследования: плашка
    # называет поле человеческим именем, а не ключом.
    got = imported()
    assert set(CITY_KEYS) <= set(got["cleared"]), got["cleared"]
    for word in ("К1 паркинга", "К2 паркинга", "расстояние до станции"):
        assert word in got["note"], got["note"]


def test_the_methodology_half_survives_the_import():
    # Гросс с рампами и край вилки РНГП — наша методика, и участок её не
    # отменяет. А обнулить их нельзя и буквально: ноль метров на место делит на
    # ноль, пустой режим теряет выбор человека.
    got = imported()
    assert got["per_space"] == 35, got["per_space"]
    assert got["mode"] == "minimum", got["mode"]


def test_the_server_clears_the_same_three_keys():
    # Список объявлен один раз — на странице; сервер читает его оттуда же, и
    # этим же путём чистят вводные перенос ГлавАПУ и скрининг КРТ.
    from developaid_v2_form import territory_input_keys

    keys = territory_input_keys(core)
    assert set(CITY_KEYS) <= set(keys), keys
    for key in ("object_parking_area_per_space_sqm", "parking_design_mode"):
        assert key not in keys, f"{key} — методика, а не данные участка"


def test_an_inherited_coefficient_would_move_the_norm():
    """Предохранитель: чужой К2 меняет норму, иначе спор о списке пустой."""
    def norm(k2: float) -> int:
        x = copy.deepcopy(core.DEFAULT_INPUTS)
        t = copy.deepcopy(core.TEP_DEFAULT)
        # Вводные и строка ТЭП говорят об объекте одно и то же — иначе это не
        # проект, а фикстура, на которой вопрос не решается.
        x["offices_enabled"] = True
        x["offices_gba_sqm"] = 100000.0
        x["offices_saleable_sqm"] = 85000.0
        t["offices"].update(gns=100000.0, total_area=94000.0,
                            useful=85000.0, saleable=85000.0)
        x["parking_k1"] = 0.0
        x["parking_k2"] = k2
        return int(core.apply_object_parking(x, t)["required_total"])

    upper, inherited = norm(0.0), norm(0.2)
    assert upper > inherited > 0, (upper, inherited)
    assert upper >= inherited * 3, (
        "наследованный К2 норму почти не двигает — проверка ничего не стоит: "
        f"{inherited} мест против {upper}")


def test_the_stand_notices_when_the_keys_leave_the_list(monkeypatch):
    """Диверсия: без трёх ключей в списке коэффициенты переживают импорт."""
    sabotaged = core.PAGE.replace(
        "\n 'parking_k1','parking_k2','parking_rail_distance_m'\n];",
        "\n];", 1)
    assert sabotaged != core.PAGE, "диверсия не попала в список"
    monkeypatch.setattr(core, "PAGE", sabotaged)
    got = imported()
    assert (got["k1"], got["k2"], got["dist"]) == (0.2, 0.2, 800), got

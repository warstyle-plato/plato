"""Расчётная потребность города видна при любой форме исполнения.

«В Москве всё падает в компенсацию, но места никуда справочно не заносятся»
(владелец, 02.09.2026). Компенсация посчитана ОТ потребности: в проекте не
оставалось ни одного числа о социалке, кроме суммы. Метры при этом не строятся
и в ГНС проекта не идут — показываются только мощности.

Рядом второе, из того же разговора: места, введённые руками, давали ноль
метров. Площадь считалась из мест и норматива только при импорте ГлавАПУ и
только в режиме «Строительство».
"""

import copy
import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def core():
    spec = importlib.util.spec_from_file_location("developaid_core", ROOT / "main_legacy.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["developaid_core"] = module
    spec.loader.exec_module(module)
    return module


def run(core, **over):
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(over)
    tep = copy.deepcopy(core.TEP_DEFAULT)
    return core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))


def test_compensation_still_shows_what_the_city_required(core):
    result = run(core, social_mode="Денежная компенсация", social_compensation_mln=1200.0,
                 kindergarten_places=0, school_places=0, clinic_capacity=0)
    need = result["summary"]["social_required"]
    assert need["available"] is True
    assert need["source"] == "norm"
    assert need["kindergarten_places"] > 0 and need["school_places"] > 0
    # Построенного нет — значит вся потребность закрывается деньгами.
    assert need["gap"]["school_places"] == need["school_places"]
    assert need["fully_built"] is False


def test_the_city_calculation_beats_our_norm(core):
    """Выгрузка ГлавАПУ считает потребность сама — её и показываем."""
    result = run(
        core, social_mode="Денежная компенсация", social_compensation_mln=900.0,
        _glavapu_import={"normalized": {
            "required_kindergarten_places": 250, "required_school_places": 900,
            "required_clinic_capacity": 120, "district": "Кунцево",
        }},
    )
    need = result["summary"]["social_required"]
    assert need["source"] == "glavapu"
    assert (need["kindergarten_places"], need["school_places"]) == (250.0, 900.0)


def test_the_region_uses_its_own_norm(core):
    """В области норматив свой, и он у движка уже есть — второй не заводим."""
    result = run(core, vri_region="mo", social_mode="Денежная компенсация",
                 social_compensation_mln=100.0, kindergarten_places=0, school_places=0)
    need = result["summary"]["social_required"]
    assert need["source"] == "mo_norm"
    assert need["school_places"] > 0


def test_no_apartments_is_not_zero_requirement(core):
    """«Считать не от чего» — не то же самое, что «потребности нет»."""
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update({"social_mode": "Денежная компенсация", "social_compensation_mln": 10.0})
    tep = copy.deepcopy(core.TEP_DEFAULT)
    for row in tep.values():
        row["saleable"] = 0.0
    need = core.social_required_program(inputs, tep)
    assert need["available"] is False
    assert "не от чего" in need["basis"]


def test_the_gap_is_named_in_the_mixed_mode(core):
    """При «Строительстве и компенсации» видно, что закрывают деньгами."""
    result = run(core, social_mode=core.SOCIAL_MODE_BOTH, social_compensation_mln=300.0,
                 kindergarten_places=100, school_places=0, clinic_capacity=0,
                 _glavapu_import={"normalized": {
                     "required_kindergarten_places": 250, "required_school_places": 900,
                     "required_clinic_capacity": 0, "district": "",
                 }})
    need = result["summary"]["social_required"]
    assert need["built"]["kindergarten_places"] == 100.0
    assert need["gap"]["kindergarten_places"] == 150.0
    # Школу движок подставляет из требования города сам, когда мест не задано,
    # — значит она строится целиком, и закрывать деньгами нечего.
    assert need["built"]["school_places"] == 900.0
    assert need["gap"]["school_places"] == 0.0


def _page_function(name: str, source: str) -> str:
    start = source.index(f"function {name}(")
    index, depth, opened = source.index("{", start), 0, False
    while index < len(source):
        if source[index] == "{":
            depth += 1
            opened = True
        elif source[index] == "}":
            depth -= 1
            if opened and depth == 0:
                return source[start:index + 1]
        index += 1
    raise AssertionError(f"функция {name} не закрылась")


def test_the_page_asks_the_engine_and_does_not_count_again(core):
    """Строку потребности рисует страница, а считает движок."""
    page = core.PAGE
    assert "r.summary.social_required" in page, "страница не читает потребность из результата"
    block = page[page.index("const socialNeedRow="):]
    block = block[: block.index("})();") + 5]
    assert "33" not in block and "moscow_social_places" not in block, \
        "потребность считается на странице второй раз"


def test_manual_places_get_their_area_and_gns(core, tmp_path):
    """Места руками — площадь и ГНС считаются, а не остаются нулём."""
    playwright = pytest.importorskip("playwright.sync_api")
    import browser_launch

    html = core.PAGE.replace("__DEVELOPAID_VERSION__", "test")
    file = tmp_path / "page.html"
    file.write_text(html, encoding="utf-8")
    with playwright.sync_playwright() as pw:
        try:
            browser = browser_launch.launch(pw)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda exc: errors.append(str(exc)))
            tab.route("**/*", lambda route: route.abort()
                      if route.request.url.startswith("http") else route.continue_())
            tab.goto(file.as_uri())
            tab.wait_for_function("() => typeof syncTep === 'function'", timeout=15000)
            rows = tab.evaluate("""() => {
              inputs.social_mode = 'Строительство и компенсация';
              inputs.kindergarten_places = 200;
              inputs.social_dou_gba_sqm = 0;
              inputs.school_places = 0;
              inputs.clinic_capacity = 0;
              syncTep(false);
              return {area: tep.kindergarten.total_area, gns: tep.kindergarten.gns,
                      units: tep.kindergarten.units,
                      norm: Number(inputs.social_dou_norm_sqm||0),
                      field: Number(inputs.social_dou_gba_sqm||0)};
            }""")
            tab.close()
        finally:
            browser.close()
    # Сеть в песочнице закрыта, и расчёт страницы честно не доходит до сервера:
    # это ошибка окружения, а не страницы. Всё остальное — поломка.
    assert [item for item in errors if "Failed to fetch" not in item] == [], errors
    assert rows["units"] == 200
    assert rows["area"] == pytest.approx(200 * rows["norm"]), "площадь не посчиталась из мест"
    assert rows["field"] == rows["area"], "посчитанная площадь не видна в поле"
    assert rows["gns"] > rows["area"], "ГНС соцобъекта осталась нулём"


def test_the_mixed_mode_is_not_cut_off_from_the_city_program(core):
    """Мешаный режим заполняет ТЭП наравне со «Строительством» — и потребность тоже."""
    block = _page_function("applyRequiredSocialProgramFromGlavapu", core.PAGE)
    assert "Строительство и компенсация" in block, \
        "мешаный режим по-прежнему выпадает из подстановки потребности"


def test_social_metres_do_not_reach_the_per_metre_articles(core):
    """ГНС соцобъекта в ТЭП есть, а статьи «на м² ГНС» её не берут."""
    source = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    line = re.search(r"core_above_gns = .+", source).group(0)
    assert "kindergarten" not in line and "school" not in line and "clinic" not in line

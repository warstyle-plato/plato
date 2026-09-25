"""Регрессия проекта «Проект»: свой паркинг офисника занимает существующую GBA.

22.09.2026 сравнение двух выгрузок одного проекта показало, что 1000 мест на
первых этажах отнимали 35 000 м² прямо из уже продаваемой площади. Это давало
ровно -25,104 млрд ₽ офисной выручки. Правило проекта другое:

    GBA_after = GBA - over_spaces * 25
    total = GBA_after * 94%
    saleable = total * 50%

Исходная GBA объекта не меняется; паркинг местами under/over не может её
увеличить. Подземные метры остаются отдельным CAPEX.
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402

GBA = 186_180.0
TOTAL = GBA * 0.94
SALEABLE = TOTAL * 0.50
SPACES = 2_778
OVER = 1_000
UNDER = SPACES - OVER


def _inputs(under: int, over: int) -> dict:
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update(
        offices_enabled=True,
        offices_gba_sqm=GBA,
        offices_saleable_sqm=SALEABLE,
        offices_parking_under_spaces=under,
        offices_parking_over_spaces=over,
        object_parking_area_per_space_sqm=35,
        object_parking_over_area_per_space_sqm=25,
        offices_parking_guest_pct=10,
        _parking_by_hand=["offices"],
    )
    return x


def _tep() -> dict:
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["offices"].update(
        gns=GBA,
        total_area=TOTAL,
        useful=SALEABLE,
        saleable=SALEABLE,
    )
    return t


def _product_revenue(result: dict, key: str) -> float:
    rows = result["report"]["products"]
    hit = [row for row in rows if row.get("key") == key]
    assert len(hit) == 1, (key, hit)
    return float(hit[0].get("revenue") or 0.0)


def test_project_reallocation_keeps_gba_and_recalculates_saleable_once() -> None:
    underground = _tep()
    overground = _tep()

    u = core.apply_object_parking(_inputs(SPACES, 0), underground)
    o = core.apply_object_parking(_inputs(UNDER, OVER), overground)

    assert underground["offices"]["gns"] == GBA
    assert overground["offices"]["gns"] == GBA
    assert u["own_units"] == o["own_units"] == SPACES

    footprint = OVER * 25
    expected_total = (GBA - footprint) * 0.94
    expected_saleable = expected_total * 0.50

    assert o["over_area_per_space_sqm"] == 25
    assert overground["offices"]["parking_over_gba_sqm"] == footprint
    assert overground["offices"]["total_area"] == pytest.approx(expected_total)
    assert overground["offices"]["saleable"] == pytest.approx(expected_saleable)
    assert overground["offices"]["parking_saleable_taken"] == pytest.approx(
        SALEABLE - expected_saleable)
    assert overground["offices"]["saleable"] == pytest.approx(75_754.6)

    # Повторный проход на той же копии ТЭП не вычитает первые этажи второй раз.
    core.apply_object_parking(_inputs(UNDER, OVER), overground)
    assert overground["offices"]["saleable"] == pytest.approx(expected_saleable)
    assert overground["offices"]["gns"] == GBA


def test_project_reallocation_keeps_parking_revenue_and_changes_only_office_quantity() -> None:
    under_result = core.calculate(core.CalcRequest(
        inputs=_inputs(SPACES, 0), tep=_tep(), rates=[]))
    over_result = core.calculate(core.CalcRequest(
        inputs=_inputs(UNDER, OVER), tep=_tep(), rates=[]))

    assert _product_revenue(over_result, "object_parking") == pytest.approx(
        _product_revenue(under_result, "object_parking"), rel=1e-12)

    office_under = _product_revenue(under_result, "offices")
    office_over = _product_revenue(over_result, "offices")
    assert office_over / office_under == pytest.approx(75_754.6 / 87_504.6, rel=1e-12)



def _four_phase_project() -> dict:
    return {
        "enabled": True,
        "mode": "phased",
        "user_enabled": True,
        "phase_count": 4,
        "phase_gap_months": 12,
        "phases": [
            {"name": f"О{i + 1}", "start_offset_months": i * 12,
             "construction_months": 24}
            for i in range(4)
        ],
        "discrete": {"offices": 3},
        "social_objects": [],
    }


def _product_row(result: dict, key: str) -> dict:
    hit = [row for row in result["report"]["products"] if row.get("key") == key]
    assert len(hit) == 1, (key, hit)
    return hit[0]


def test_phased_office_sells_the_saleable_left_after_first_floor_parking() -> None:
    """Очередь не должна печатать/продавать исходные метры после парковки.

    Контрольный расклад пользователя: 1 778 мест на первых этажах и 1 000
    подземных. При GBA 186 180 м² первые этажи занимают 44 450 м² GBA, поэтому
    офисная продаваемая падает с 87 504,6 до 66 613,1 м². До этой регрессии
    ТЭП уже показывал 66 613, а «Продажи и продукты» продолжали печатать
    исходные 87 505 из offices_saleable_sqm.
    """
    over = 1_778
    under = SPACES - over
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=_inputs(under, over),
        tep=_tep(),
        rates=[],
        phasing=_four_phase_project(),
    ))
    office_phase = bundle["phases"][2]["result"]
    office_tep = next(row for row in office_phase["tep"]["rows"]
                      if row["key"] == "offices")
    expected = SALEABLE * (GBA - over * 25) / GBA

    assert expected == pytest.approx(66_613.1)
    assert office_tep["saleable"] == pytest.approx(expected)
    assert _product_row(office_phase, "offices")["quantity"] == pytest.approx(expected)
    assert bundle["comparison"][2]["saleable_by_product"]["offices"] == pytest.approx(expected)

    consolidated_tep = next(row for row in bundle["consolidated"]["tep"]["rows"]
                            if row["key"] == "offices")
    consolidated_product = _product_row(bundle["consolidated"], "offices")
    assert consolidated_tep["saleable"] == pytest.approx(expected)
    assert consolidated_product["quantity"] == pytest.approx(expected)


def test_phased_office_cashflow_uses_adjusted_saleable_not_raw_input() -> None:
    """LLCR получает офисную выручку именно от остаточной площади.

    При одинаковом календаре и цене отношение офисной выручки должно ровно
    повторять отношение продаваемых метров. Это ловит возврат к сырой вводной
    87 504,6 м² внутри очередности.
    """
    over = 1_778
    adjusted = core.calculate_phased(core.PhasedCalcRequest(
        inputs=_inputs(SPACES - over, over), tep=_tep(), rates=[],
        phasing=_four_phase_project(),
    ))
    all_under = core.calculate_phased(core.PhasedCalcRequest(
        inputs=_inputs(SPACES, 0), tep=_tep(), rates=[],
        phasing=_four_phase_project(),
    ))
    adjusted_revenue = adjusted["comparison"][2]["revenue_by_product"]["offices"]
    all_under_revenue = all_under["comparison"][2]["revenue_by_product"]["offices"]
    expected_ratio = (GBA - over * 25) / GBA
    assert adjusted_revenue / all_under_revenue == pytest.approx(expected_ratio, rel=1e-12)


def test_phased_v4_book_office_revenue_matches_engine_after_parking_reallocation() -> None:
    """Excel не получает старую продаваемую хардом: формулы сходятся с движком."""
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    over = 1_778
    x = _inputs(SPACES - over, over)
    phasing = _four_phase_project()
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=copy.deepcopy(x), tep=_tep(), rates=[],
        phasing=copy.deepcopy(phasing),
    ))
    content, _, meta = core.build_project_workbook(
        copy.deepcopy(x), _tep(), [], copy.deepcopy(phasing),
        project_name="Паркинг офиса · очереди",
    )
    assert meta["missing"] == [], meta["missing"]

    book = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    sheet = book["КОНСОЛИДАТОР"]
    office_col = None
    for column in range(17, 40):
        title = sheet.cell(row=3, column=column).value
        if isinstance(title, str) and title.startswith("Выручка · Офисы"):
            office_col = column
            break
    assert office_col is not None, "в КОНСОЛИДАТОРЕ нет колонки выручки офисов"

    sys.setrecursionlimit(400000)
    evaluator = Evaluator(book)
    letter = openpyxl.utils.get_column_letter(office_col)
    engine_mln = bundle["comparison"][2]["revenue_by_product"]["offices"] / 1_000_000
    assert evaluator.cell("КОНСОЛИДАТОР", f"{letter}6") == pytest.approx(
        engine_mln, abs=1.0, rel=0.005)


def test_impossible_first_floor_layout_warns_instead_of_growing_gba() -> None:
    t = _tep()
    x = _inputs(0, 10_000)
    got = core.apply_object_parking(x, t)

    assert t["offices"]["gns"] == GBA
    assert t["offices"]["saleable"] == 0
    assert t["offices"]["parking_layout_overflow_sqm"] > 0
    assert got.get("warnings")
    assert "площадь объекта не увеличена" in got["note"]


def test_v4_book_uses_25sqm_footprint_before_saleable_ratio() -> None:
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    x = _inputs(UNDER, OVER)
    content, _, meta = core.build_project_workbook(
        x, _tep(), [], None, project_name="Проект")
    assert not [m for m in meta["missing"] if "паркинг объектов" in m], meta["missing"]

    book = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    params = book["Параметры модели"]
    objects = book["ОБЪЕКТЫ"]

    assert params["K160"].value == 25
    assert "K162*$K$160" in str(params["K26"].value)
    assert "$K$158" not in str(objects["B13"].value)

    sys.setrecursionlimit(400000)
    evaluator = Evaluator(book)
    assert evaluator.cell("ОБЪЕКТЫ", "B13") == pytest.approx(75_754.6)
    assert evaluator.cell("Параметры модели", "K168") == "OK"


def test_office_under_and_first_floor_places_can_have_different_sale_prices() -> None:
    same = _inputs(UNDER, OVER)
    same.update(
        parking_price_th=6_000,
        offices_parking_under_price_mln_per_space=6,
        offices_parking_over_price_mln_per_space=6,
    )
    split = _inputs(UNDER, OVER)
    split.update(
        parking_price_th=6_000,
        offices_parking_under_price_mln_per_space=6,
        offices_parking_over_price_mln_per_space=4,
    )

    same_result = core.calculate(core.CalcRequest(inputs=same, tep=_tep(), rates=[]))
    split_result = core.calculate(core.CalcRequest(inputs=split, tep=_tep(), rates=[]))

    same_revenue = _product_revenue(same_result, "object_parking")
    split_revenue = _product_revenue(split_result, "object_parking")
    weighted_mln = (UNDER * 6 + OVER * 4) / SPACES
    assert split_revenue / same_revenue == pytest.approx(weighted_mln / 6, rel=1e-12)


def test_parking_sale_price_fields_exist_only_for_sellable_office_garage() -> None:
    assert "offices_parking_under_price_mln_per_space" in core.DEFAULT_INPUTS
    assert "offices_parking_over_price_mln_per_space" in core.DEFAULT_INPUTS
    assert "retail_parking_under_price_mln_per_space" not in core.DEFAULT_INPUTS
    assert "retail_parking_over_price_mln_per_space" not in core.DEFAULT_INPUTS
    assert "sports_parking_under_price_mln_per_space" not in core.DEFAULT_INPUTS
    assert "sports_parking_over_price_mln_per_space" not in core.DEFAULT_INPUTS


def test_v4_book_uses_separate_office_parking_prices() -> None:
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    x = _inputs(UNDER, OVER)
    x.update(
        parking_price_th=6_000,
        offices_parking_under_price_mln_per_space=6,
        offices_parking_over_price_mln_per_space=4,
    )
    report = core.calculate(core.CalcRequest(inputs=dict(x), tep=_tep(), rates=[]))
    content, _, meta = core.build_project_workbook(
        dict(x), _tep(), [], None, project_name="Проект")
    assert not [m for m in meta["missing"] if "паркинг объектов" in m], meta["missing"]

    book = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    params = book["Параметры модели"]
    objects = book["ОБЪЕКТЫ"]

    assert params["K169"].value == 6
    assert params["K170"].value == 4
    formula = str(objects["D33"].value)
    assert "$K$169" in formula and "$K$170" in formula

    sys.setrecursionlimit(400000)
    evaluator = Evaluator(book)
    assert evaluator.cell("ОБЪЕКТЫ", "B33") == pytest.approx(
        _product_revenue(report, "object_parking") / 1_000_000, rel=1e-9)


def test_user_case_1778_first_floor_spaces_reaches_report_and_phasing() -> None:
    """1778 мест на первых этажах: в деньги и отчёт идут 66 613,1 м², не база 87 504,6."""
    user_under = 1_000
    user_over = 1_778
    expected = (GBA - user_over * 25) * 0.94 * 0.50

    x = _inputs(user_under, user_over)
    result = core.calculate(core.CalcRequest(
        inputs=copy.deepcopy(x), tep=_tep(), rates=[]))
    office = next(row for row in result["report"]["products"]
                  if row.get("key") == "offices")
    tep_office = next(row for row in result["tep"]["rows"]
                      if row.get("key") == "offices")

    assert expected == pytest.approx(66_613.1)
    assert tep_office["saleable"] == pytest.approx(expected)
    assert office["quantity"] == pytest.approx(expected)
    assert office["quantity"] != pytest.approx(SALEABLE)

    phasing = {
        "enabled": True,
        "phase_count": 3,
        "phase_gap_months": 12,
        "phases": [
            {"name": "О1", "start_offset_months": 0, "construction_months": 24},
            {"name": "О2", "start_offset_months": 12, "construction_months": 24},
            {"name": "О3", "start_offset_months": 24, "construction_months": 24},
        ],
        "social_objects": [],
        "discrete": {"offices": 3},
    }
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=copy.deepcopy(x), tep=_tep(), rates=[], phasing=phasing))

    phase_office = next(row for row in bundle["phases"][2]["result"]["report"]["products"]
                        if row.get("key") == "offices")
    consolidated_office = next(row for row in bundle["consolidated"]["report"]["products"]
                               if row.get("key") == "offices")

    assert phase_office["quantity"] == pytest.approx(expected)
    assert bundle["comparison"][2]["saleable_by_product"]["offices"] == pytest.approx(expected)
    assert consolidated_office["quantity"] == pytest.approx(expected)


def test_user_case_excel_keeps_base_input_but_sells_only_residual_office_area() -> None:
    """K24 — исходная база офиса; ОБЪЕКТЫ считает остаток после 1778 мест."""
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    user_under = 1_000
    user_over = 1_778
    expected = (GBA - user_over * 25) * 0.94 * 0.50
    x = _inputs(user_under, user_over)

    content, _, meta = core.build_project_workbook(
        copy.deepcopy(x), _tep(), [], None, project_name="Проект 1778/1000")
    assert not [m for m in meta["missing"] if "паркинг объектов" in m], meta["missing"]

    book = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    params = book["Параметры модели"]
    assert params["K24"].value == pytest.approx(SALEABLE)

    sys.setrecursionlimit(400000)
    evaluator = Evaluator(book)
    assert evaluator.cell("ОБЪЕКТЫ", "B13") == pytest.approx(expected)

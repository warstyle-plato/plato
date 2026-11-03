"""Real Excel variants match both authoritative product comparisons, including winners."""
import io

import pytest

from test_office_workbook import _project, core, openpyxl, ow, _row


@pytest.fixture(scope="module", params=("office", "retail", "mixed", "mixed_office_exits"))
def example(request):
    over = dict(offices_strategy="income", offices_rent_th_per_sqm_month=8)
    if request.param in ("retail", "mixed"):
        over.update(retail_enabled=True, retail_gba_sqm=15000., retail_saleable_sqm=11000.,
                    retail_strategy="income", retail_rent_th_per_sqm_month=7)
    if request.param == "retail":
        over["offices_enabled"] = False
    if request.param == "mixed_office_exits":
        over.update(offices2_enabled=True, offices2_gba_sqm=10000., offices2_saleable_sqm=6000.,
                    offices2_strategy="income", offices2_exit_mode="hold", offices2_rent_th_per_sqm_month=7)
    x, t = _project(**over)
    result = core._run_authoritative_model(x, t, [], {})["consolidated"]
    content, _, meta = core.build_project_workbook(x, t, [], {}, project_name="Синтетический пример")
    assert meta["missing"] == [] and meta["checks"] == ow.PASSED, meta
    return request.param, result, content, meta


def test_every_engine_variant_and_winner_is_in_the_formula_book(example):
    name, result, content, meta = example
    book = openpyxl.load_workbook(io.BytesIO(content))
    evaluator = ow.evaluate(book)
    assert ow.verdict(evaluator) == (ow.PASSED, [])
    assert len(meta["comparisons"]) == (2 if name == "mixed" else 1)
    for group in meta["comparisons"]:
        source = result["office_paths" if group["product"] == "offices" else "retail_paths"]
        assert [p["key"] for p in group["paths"]] == [p["key"] for p in source["paths"]]
        assert len(group["paths"]) == (6 if name == "mixed_office_exits" else 5)
        report = book[group["report"]]
        for column, (path, engine) in enumerate(zip(group["paths"], source["paths"]), start=2):
            assert evaluator.cell(report.title, f"{ow.L(column)}4") == engine["label"]
            for key, label, ratio in (("npv", "NPV проекта", False), ("revenue", "Выручка", False),
                                      ("net_profit", "Чистая прибыль", False), ("equity_peak", "Пик собственных денег", False),
                                      ("irr_project", "IRR проекта (до кредита)", True)):
                actual = evaluator.cell(report.title, f"{ow.L(column)}{_row(report, label)}")
                expected = ow._engine_number(engine.get(key), ratio)
                assert actual == pytest.approx(expected) if isinstance(expected, (int, float)) else actual == expected
            if engine["strategy"] == "income":
                for key, label, ratio in (("rent_revenue", "Доход аренды", False),
                                          ("stabilized_noi", "NOI года после заполнения", False),
                                          ("yield_on_cost", "Доходность на затраты", True),
                                          ("exit_value", "Стоимость здания при продаже или удержании", False),
                                          ("dscr_min", "DSCR кредита объекта — минимум", True)):
                    actual = evaluator.cell(report.title, f"{ow.L(column)}{_row(report, label)}")
                    expected = ow._engine_number(engine.get(key), ratio)
                    assert actual == pytest.approx(expected) if isinstance(expected, (int, float)) else actual == expected
        winner = next(p["label"] for p in source["paths"] if p["key"] == source["better"])
        assert evaluator.cell(report.title, f"B{_row(report, 'Выгоднее по NPV')}") == winner
        if source["exit_cap_pct"] is None:
            for column, path in enumerate(group["paths"], start=2):
                if path["key"].startswith("income"):
                    assert evaluator.cell(report.title, f"{ow.L(column)}{_row(report, 'Ставка капитализации')}") == ""
        # The audit's missing fifth variant really wins, so a four-way book fails here.
        if name == "office":
            assert source["better"] == "income_hold"
        if group["product"] == "standalone_retail":
            rent = next(p for p in source["paths"] if p["strategy"] == "income")
            assert rent["rent_revenue"] > 0 and rent["stabilized_noi"] > 0 and rent["loan_peak"] > 0


def test_cash_is_separate_and_each_group_has_its_own_formula_flows(example):
    _, _, content, meta = example
    book = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    formulas = openpyxl.load_workbook(io.BytesIO(content))
    used = set()
    for group in meta["comparisons"]:
        for path in group["paths"]:
            assert path["cf"] not in used
            used.add(path["cf"])
            sheet = book[path["cf"]]
            residual = sheet[f"B{_row(sheet, 'Оценка удержанного здания (не деньги)')}"].value
            assert residual >= 0
            if path["exit_override"] == "hold":
                assert residual > 0
            # Calculated cash remains formulas, not an engine snapshot.
            row = _row(sheet, "Выручка деньгами")
            assert formulas[sheet.title][f"D{row}"].value.startswith("=")
        report = formulas[group["report"]]
        assert report["B4"].alignment.wrap_text and report.row_dimensions[4].height >= 60


def test_tampering_with_the_winner_is_caught(example):
    _, result, content, meta = example
    book = openpyxl.load_workbook(io.BytesIO(content))
    group = meta["comparisons"][0]
    winner_key = result["office_paths" if group["product"] == "offices" else "retail_paths"]["better"]
    hold = next(p for p in group["paths"] if p["key"] == winner_key)
    sheet = book[hold["cf"]]
    sheet[f"B{_row(sheet, 'NPV проекта')}"] = -1e9
    verdict, bad = ow.verdict(ow.evaluate(book))
    assert verdict == ow.FAILED
    assert any("Лучший вариант" in label for _, label in bad)


def test_omitting_a_comparison_column_is_caught(example):
    _, _, content, meta = example
    book = openpyxl.load_workbook(io.BytesIO(content))
    group = meta["comparisons"][0]
    book[group["report"]]["F4"] = None
    verdict, bad = ow.verdict(ow.evaluate(book))
    assert verdict == ow.FAILED
    assert (group["title"], "Число вариантов сравнения") in bad

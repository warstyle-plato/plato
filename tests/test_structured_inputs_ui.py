from pathlib import Path

import pytest

import developaid_v2_form
import main as wrapper


ROOT = Path(__file__).resolve().parent.parent


def test_v2_loads_structured_input_assets():
    html = (ROOT / "frontend_v2" / "index.html").read_text(encoding="utf-8")
    routes = (ROOT / "developaid_v2.py").read_text(encoding="utf-8")
    worker = (ROOT / "frontend_v2" / "sw.js").read_text(encoding="utf-8")
    for asset in ("structured_inputs.css", "structured_inputs.js"):
        url = f"/v2/assets/{asset}"
        assert url in html
        assert url in routes
        assert url in worker
    assert html.index("/v2/assets/app.js") < html.index("/v2/assets/structured_inputs.js")


def test_pf_steps_are_a_table_not_the_transport_string():
    js = (ROOT / "frontend_v2" / "structured_inputs.js").read_text(encoding="utf-8")
    assert "Ступени ставки ПФ по покрытию" in js
    assert "Покрытие эскроу от" in js
    assert "Ставка ПФ" in js
    assert "400F00BVX003" in js
    assert "if (field.key === PF_STEPS_KEY)" in js


def test_text_fields_are_not_forced_to_number_anymore():
    js = (ROOT / "frontend_v2" / "structured_inputs.js").read_text(encoding="utf-8")
    assert "if (field.type !== 'text')" in js
    assert "control.type = 'text'" in js


def test_tep_ui_reads_ratios_from_engine_instead_of_copying_numbers():
    js = (ROOT / "frontend_v2" / "structured_inputs.js").read_text(encoding="utf-8")
    assert "BASE_TEP_TOTAL_PCT" not in js
    assert "BASE_TEP_SALEABLE_OF_TOTAL_PCT" not in js
    assert "form.defaults.tep_ratios" in js
    assert "defaultRatio(rowKey)" in js
    assert "Общая / ГНС" in js
    assert "Продаваемая / общей" in js
    assert "Вернуть пропорции DevelopAid из движка" in js

    description = developaid_v2_form.form_description(wrapper.core)
    assert description["defaults"]["tep_ratios"] == wrapper.core.TEP_RATIOS

    rows = {row["key"]: row for row in description["blocks"][0]["rows"]}
    apartments = rows["apartments"]["default_ratio"]
    assert apartments["total_pct"] == pytest.approx(90.0)
    assert apartments["saleable_of_total_pct"] == pytest.approx(65 / 90 * 100)
    assert "ГлавАПУ" in apartments["source"]

    offices = rows["offices"]["default_ratio"]
    assert offices["total_pct"] == pytest.approx(94.0)
    assert offices["saleable_of_total_pct"] == pytest.approx(60.0)


def test_storage_is_an_explicit_tep_product_and_reaches_excel_without_row_insertion():
    description = developaid_v2_form.form_description(wrapper.core)
    tep_rows = description["blocks"][0]["rows"]
    keys = [row["key"] for row in tep_rows]

    # Кладовые видны рядом с подземным паркингом, а не теряются ниже ОСЗ/МФЦ.
    underground = keys.index("underground_parking")
    assert keys[underground + 1] == "storage"
    storage = next(row for row in tep_rows if row["key"] == "storage")
    assert storage["label"] == "Кладовки"
    assert [field["key"] for field in storage["fields"]] == ["units"]
    assert "количество × цена" in storage["hint"].lower()

    # Движок уже считает выручку кладовых по количеству и цене. В новой книге
    # `base_column=7` означает колонку «Количество» в существующей таблице ТЭП,
    # поэтому для кладовых не требуется вставлять новую строку в старый шаблон.
    spec = wrapper.core._M2_PRODUCTS["storage"]
    assert spec["base_column"] == 7
    assert spec["price"] == "storage_price_th"
    assert spec["unit"] == "шт."
    assert spec["core"] is True
    assert "storage" in developaid_v2_form.PHASE_PRODUCT_KEYS
    assert "storage_price_th" in wrapper.core.DEFAULT_INPUTS

from pathlib import Path

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


def test_tep_ui_uses_90_then_70_and_engine_understands_it():
    js = (ROOT / "frontend_v2" / "structured_inputs.js").read_text(encoding="utf-8")
    assert "BASE_TEP_TOTAL_PCT = 90" in js
    assert "BASE_TEP_SALEABLE_OF_TOTAL_PCT = 70" in js
    assert "Общая / ГНС" in js
    assert "Продаваемая / общей" in js
    assert "isUntouchedEngineDefault" in js
    assert "hasFactualTepSource" in js
    assert "!hasFactualTepSource()" in js

    applied, warnings = wrapper.core.tep_ratios_applied("apartments:90/70")
    assert warnings == []
    assert applied["apartments"]["total_of_gns"] == 0.90
    assert applied["apartments"]["saleable_of_gns"] == 0.63

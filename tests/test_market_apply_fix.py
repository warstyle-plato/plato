from __future__ import annotations

import importlib


def test_market_apply_finds_dynamic_field_and_does_not_claim_false_success() -> None:
    module = importlib.import_module("main_registry")
    page = module.core.PAGE

    assert "function marketApartmentPriceField()" in page
    assert "data-field" in page
    assert "Стартовая цена квартир" in page
    assert "Цена не передана" in page
    assert "document.getElementById('apartment_price_th')" not in page


def test_market_apply_runs_calculation_only_after_field_accepts_value() -> None:
    module = importlib.import_module("main_registry")
    page = module.core.PAGE
    function = page.split("function applyMarketPrice(){", 1)[1].split("</script>", 1)[0]

    assert function.index("marketSetNativeValue(field,value)") < function.index("calculate()")
    assert function.index("Number(String(field.value") < function.index("calculate()")

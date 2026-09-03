"""Контроль сумм графика: 7 500 обязаны сойтись с платежами.

«Контроль сумм нужен. Чтобы 7500 было равно платежам но графику» (владелец,
03.09.2026). График долями сумму уже показывал, график суммами — нет: движок
относит разницу с ценой на дату сделки и говорит об этом в предупреждениях
расчёта, но читают их после, а ошибку делают в редакторе. Ограничение на входе
и сходимость итога — разные проверки, и первая не заменяет вторую.

Три ответа здесь разные, и путать их нельзя: сошлось, не сошлось на столько-то,
и «сверить не с чем» — цена не задана. Зелёная строка на пустой цене читается
как пройденная проверка.

Запуск: python3 -m pytest tests/test_the_schedule_sum_is_checked.py -q
"""

from __future__ import annotations

import importlib.util
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


def test_the_purchase_schedule_knows_its_price(core):
    """Сверять не с чем, пока поле цены не названо у самого графика."""
    opts = {item[0]: item for _g, items in core.FIELD_GROUPS for item in items}["purchase_schedule"][4]
    assert opts.get("total_field") == "purchase_price_mln", opts
    assert opts.get("total_label"), "разница названа без имени того, с чем сверяют"


def test_the_engine_still_names_the_gap_itself(core):
    """Проверка на входе не отменяет предупреждения расчёта — они о том же."""
    from datetime import date

    payments, warnings = core.purchase_payment_plan(
        7_500_000_000.0, "2500@0; 625@6", date(2026, 1, 1), date(2032, 1, 1))
    assert any("остаток" in one for one in warnings), warnings
    assert sum(amount for _when, amount in payments) == pytest.approx(7_500_000_000.0)


@pytest.fixture(scope="module")
def lines(core, tmp_path_factory):
    """Строка контроля, посчитанная настоящим кодом страницы в Chromium."""
    playwright = pytest.importorskip("playwright.sync_api")
    import browser_launch

    page = tmp_path_factory.mktemp("page") / "page.html"
    page.write_text(core.PAGE.replace("__DEVELOPAID_VERSION__", "test"), encoding="utf-8")
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
            tab.goto(page.as_uri())
            tab.wait_for_function("() => typeof scheduleTotalLine === 'function'", timeout=15000)
            got = tab.evaluate("""() => {
              const say = (price, schedule) => {
                inputs.purchase_price_mln = price;
                inputs.purchase_schedule = schedule;
                renderInputs();
                const box = document.getElementById('schedtotal_purchase_schedule');
                return box ? box.textContent : '';
              };
              const out = {};
              out.exact = say(7500, '2500@0; 625@6; 625@9; 625@12; 625@15; 625@18; 625@21; 625@24; 625@27');
              out.short = say(7500, '2500@0; 625@6');
              out.over = say(7500, '8000@0');
              out.no_price = say(0, '2500@0');
              out.shares = say(7500, '30%@0; 60%@6');
              // Цену правят соседним полем, а редактор при этом не
              // перерисовывается: строка от прежней цены выглядит верной.
              say(7500, '7500@0');
              inputs.purchase_price_mln = 9000;
              refreshGroupPeeks();
              const box = document.getElementById('schedtotal_purchase_schedule');
              out.after_price_edit = box ? box.textContent : '';
              return out;
            }""")
            tab.close()
        finally:
            browser.close()
    assert [item for item in errors if "Failed to fetch" not in item] == [], errors
    # Числа печатаются неразрывными пробелами — сравнивать надо то, что видно,
    # а не то, каким пробелом оно склеено.
    return {key: value.replace("\u00a0", " ") for key, value in got.items()}


def test_a_matching_schedule_says_so(lines):
    assert "сходится" in lines["exact"], lines["exact"]
    assert "7 500" in lines["exact"], lines["exact"]


def test_a_short_schedule_names_the_gap(lines):
    """3 125 при цене 7 500 — не хватает 4 375, и это сказано числом."""
    said = lines["short"]
    assert "не хватает" in said and "4 375" in said, said
    assert "дату сделки" in said, "не сказано, куда движок отнесёт остаток: " + said


def test_an_excess_is_named_too(lines):
    assert "лишних" in lines["over"] and "500" in lines["over"], lines["over"]


def test_an_unset_price_is_not_a_passed_check(lines):
    said = lines["no_price"]
    assert "Сверить не с чем" in said, said
    assert "сходится" not in said, said


def test_shares_are_still_checked(lines):
    assert "Сумма долей" in lines["shares"] and "должно быть 100%" in lines["shares"], lines["shares"]


def test_the_line_follows_the_price(lines):
    """Правка цены пересчитывает строку — иначе «сходится» устаревает молча."""
    said = lines["after_price_edit"]
    assert "9 000" in said and "не хватает 1 500" in said, said

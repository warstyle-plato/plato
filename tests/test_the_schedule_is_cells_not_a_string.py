"""График вводится ячейками, а не строкой через запятую.

«Реализация некрасивая — должны быть разные поля, а не одно поле, где через
запятую хрен пойми чего пишется» (владелец, 02.09.2026). График платежей за
покупку, профиль продаж объектов и лестница цены хранились и вводились одной
строкой «30%@0; 40%@6». Хранение осталось прежним — его читают и движок, и
книга, и второй формат развёл бы их, — а ввод стал таблицей: значение, единица
и срок отдельными ячейками, строки добавляются и убираются («график может
состоять и из двух платежей, и из десяти»).

Единица у графика одна на все строки: движок отказывается считать график,
смешавший доли и суммы, и переключатель сверху делает такую ошибку невозможной
по построению, а не ловит её после.

Запуск: python3 -m pytest tests/test_the_schedule_is_cells_not_a_string.py -q
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Лестница цены сюда не входит: у неё именованные поля этапов по строительной
# готовности — «как в квартирах блок Этап и процент» (владелец, 02.09.2026).
# График — это то, у чего срок задаётся самим человеком, а не готовностью.
SCHEDULES = (
    "purchase_schedule",
    "offices_sales_profile",
    "retail_sales_profile",
    "above_parking_sales_profile",
)


@pytest.fixture(scope="module")
def core():
    spec = importlib.util.spec_from_file_location("developaid_core", ROOT / "main_legacy.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["developaid_core"] = module
    spec.loader.exec_module(module)
    return module


def fields(core) -> dict[str, list]:
    out: dict[str, list] = {}
    for _group, items in core.FIELD_GROUPS:
        for item in items:
            out[item[0]] = item
    return out


def test_every_schedule_field_is_declared_a_schedule(core):
    known = fields(core)
    for name in SCHEDULES:
        assert name in known, f"поле {name} исчезло из FIELD_GROUPS"
        assert known[name][3] == "schedule", f"{name} по-прежнему вводится строкой"
        opts = known[name][4]
        assert isinstance(opts, dict) and opts.get("value") and opts.get("anchor"), name
        assert opts.get("when_label"), f"у {name} не названа колонка срока"


def test_the_purchase_schedule_is_asked_by_date(core):
    """«Ячейка суммы или доли и справа дата платежа» — про покупку сказано так."""
    opts = fields(core)["purchase_schedule"][4]
    assert opts["anchor"] == "project_start"
    assert opts["value"] == "money_or_share", "сумму за покупку вводить нечем"
    assert "ата" in opts["when_label"], opts["when_label"]


def test_the_storage_format_did_not_change(core):
    """Строку читают движок и книга — второй формат развёл бы их молча."""
    items, percent, warnings = core.parse_month_schedule("30%@0; 70%@6")
    assert items == [(30.0, 0), (70.0, 6)] and percent is True and warnings == []


def test_the_editor_adds_and_removes_rows(core, tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    import browser_launch

    page = tmp_path / "page.html"
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
            tab.wait_for_function("() => typeof renderScheduleEditor === 'function'", timeout=15000)
            got = tab.evaluate("""() => {
              inputs.purchase_schedule = '';
              renderInputs();
              scheduleAdd('purchase_schedule');
              scheduleEdit('purchase_schedule', 0, 'value', '30');
              scheduleAdd('purchase_schedule');
              scheduleEdit('purchase_schedule', 1, 'value', '70');
              scheduleEdit('purchase_schedule', 1, 'month', '6');
              const box = document.getElementById('sched_purchase_schedule');
              const html = box.innerHTML;
              const two = inputs.purchase_schedule;
              scheduleRemove('purchase_schedule', 1);
              // Второй график — профиль продаж объекта: срок у него месяцем от
              // старта продаж, а не датой, и рисоваться он обязан тем же
              // редактором. Один проверенный график ничего не говорит об остальных.
              inputs.offices_enabled = true;
              inputs.offices_sales_profile = '60%@0; 40%@12';
              renderInputs();
              const profile = document.getElementById('sched_offices_sales_profile');
              return {two, one: inputs.purchase_schedule,
                      cells: box.querySelectorAll('input').length,
                      has_date: html.includes('type="date"'),
                      says_sum: html.includes('Сумма долей'),
                      profile_cells: profile ? profile.querySelectorAll('input').length : -1,
                      profile_has_date: profile ? profile.innerHTML.includes('type="date"') : true};
            }""")
            tab.close()
        finally:
            browser.close()
    # Сеть в песочнице закрыта — расчёт страницы не доходит до сервера; это
    # ошибка окружения, а не страницы.
    assert [item for item in errors if "Failed to fetch" not in item] == [], errors
    assert got["two"] == "30%@0; 70%@6", got
    assert got["one"] == "30%@0", "строка не убралась"
    assert got["cells"] == 4, f"две строки — четыре ячейки, а вышло {got['cells']}"
    assert got["has_date"] is True, "у платежа за покупку нет даты"
    assert got["says_sum"] is True, "сумма долей не показана — график на 90% пройдёт молча"
    assert got["profile_cells"] == 4, "профиль продаж объекта рисуется не ячейками"
    assert got["profile_has_date"] is False, "у профиля продаж срок датой, а он от старта продаж"

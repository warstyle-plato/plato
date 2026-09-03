"""ГНС соцобъекта правится, а не только выводится из общей.

«Я там вбил общую площадь, но на самом деле это ГНС же в соцобъекте в КРТ
имелось в виду, а если тут меняю ГНС, то общая не меняется» (владелец,
03.09.2026). Во вводных у соцобъекта одно число — общая площадь, — а ГНС из
неё выводилась делением на долю. Обратного пути не было вовсе: соцстроки нет
ни в `TEP_RATIOS`, ни в `TEP_ROW_INPUTS`, поэтому правка ячейки ГНС жила до
первого `syncTep` и молча возвращалась к прежнему. Ячейка при этом выглядела
редактируемой — а это хуже запертой: человек правит и ждёт результата.

Решение о КРТ задаёт площадь «в габаритах наружных стен», то есть НАЗЕМНУЮ —
нашу ГНС, а не общую проектной документации. Поэтому ведущим обязано быть
любое из двух чисел, и какое из них чьё, сказано в самой строке.

Запуск: python3 -m pytest tests/test_the_social_area_pair_works_both_ways.py -q
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


def test_the_share_is_declared_once(core):
    """Доля берётся у движка: вторая копия разошлась бы с той, по которой считает syncTep."""
    page = core.PAGE
    assert page.count("(TEP_RATIOS.apartments||{}).total_of_gns") == 1, (
        "доля общей к ГНС снова объявлена в двух местах")
    assert "function socialTotalShare(" in page


@pytest.fixture(scope="module")
def got(core, tmp_path_factory):
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
            tab.wait_for_function("() => typeof tepCellChanged === 'function'", timeout=15000)
            out = tab.evaluate("""() => {
              inputs.social_mode = 'Строительство';
              // Режим «Требование КРТ»: город даёт места И площадь, и норматив
              // их не перебивает. В нормативном режиме площадь считается от
              // мест, и правка там заперта — это проверяется отдельно.
              inputs.social_area_source = 'manual';
              inputs.school_places = 1000;
              inputs.social_school_gba_sqm = 22220;
              syncTep(true);
              const before = {gns: tep.school.gns, total: tep.school.total_area};
              // Человек вписывает в ГНС ту площадь, что стоит в решении о КРТ.
              tepCellChanged('school', 'gns', '22220');
              const after = {gns: tep.school.gns, total: tep.school.total_area,
                             field: inputs.social_school_gba_sqm};
              // Пересчёт не имеет права вернуть прежнее: правка живёт во вводных.
              syncTep(true);
              const survived = {gns: tep.school.gns, total: tep.school.total_area};
              // И обратная сторона: ведущей может быть общая.
              tepCellChanged('school', 'total_area', '18000');
              const back = {gns: tep.school.gns, total: tep.school.total_area,
                            field: inputs.social_school_gba_sqm};
              const cells = tr => Array.from(tr.querySelectorAll('input'))
                .slice(0, 2).map(el => el.readOnly);
              const school = () => Array.from(document.querySelectorAll('#tepBody tr'))
                .find(tr => (tr.firstChild.textContent || '').includes('СОШ'));
              const open = cells(school());
              const note = school().firstChild.textContent;
              // Нормативный режим: площадь считается от мест, и ячейка заперта.
              inputs.social_area_source = 'norm';
              syncTep(true);
              const shut = cells(school());
              const shutNote = school().firstChild.textContent;
              return {before, after, survived, back, note, open, shut, shutNote};
            }""")
            tab.close()
        finally:
            browser.close()
    assert [item for item in errors if "Failed to fetch" not in item] == [], errors
    return out


def test_the_area_came_from_the_total_before(got):
    """Прежнее поведение: ГНС = общая ÷ 0,9 — 22 220 давали 24 688,9."""
    assert got["before"]["total"] == pytest.approx(22220, abs=0.5)
    assert got["before"]["gns"] == pytest.approx(24688.9, abs=1.0)


def test_the_cells_are_open_by_hand_and_shut_by_norm(got):
    """Редактируемая ячейка, которую перезапишет пересчёт, хуже запертой."""
    assert got["open"] == [False, False], got["open"]
    assert got["shut"] == [True, True], got["shut"]
    assert "норматив" in got["shutNote"].lower(), got["shutNote"]
    assert "Требование КРТ" in got["shutNote"], got["shutNote"]


def test_editing_the_gns_recomputes_the_total(got):
    """22 220 в ГНС — это 19 998 общей, а не прежние 22 220."""
    assert got["after"]["gns"] == pytest.approx(22220, abs=0.5), got["after"]
    assert got["after"]["total"] == pytest.approx(19998, abs=0.5), got["after"]
    assert got["after"]["field"] == pytest.approx(19998, abs=0.5), (
        "во вводные ушло не то число — правка не переживёт пересчёт")


def test_the_edit_survives_the_next_sync(got):
    """Ячейка, возвращающаяся к прежнему на пересчёте, хуже запертой."""
    assert got["survived"]["gns"] == pytest.approx(22220, abs=0.5), got["survived"]
    assert got["survived"]["total"] == pytest.approx(19998, abs=0.5), got["survived"]


def test_the_total_still_leads_too(got):
    """Любое из двух — ведущее: правило то же, что у трёх площадей продукта."""
    assert got["back"]["total"] == pytest.approx(18000, abs=0.5), got["back"]
    assert got["back"]["gns"] == pytest.approx(20000, abs=0.5), got["back"]


def test_the_row_says_which_number_is_which(got):
    """«В габаритах наружных стен» — это ГНС, и на экране это сказано."""
    assert "габаритах наружных стен" in got["note"], got["note"]

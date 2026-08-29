"""Сброс обнуляет участок, проверяет сам себя и называет уцелевшее.

«При сбросе проекта до сих пор не сбрасываются ТЭПы, полного обнуления нет всех
вкладок» (владелец, 27.08.2026), и снимок экрана после «Сбросить» (29.08.2026)
показал, почему: сброс ставил ТЭП УМОЛЧАНИЯ, а умолчание — это пример на
130 716,7 м² ГНС и 1 361 квартиру. Числа после сброса стояли те же, что до
него, и читалось это ровно так, как он и сказал.

Теперь предпосылки аналитика возвращаются к умолчаниям, а данные участка —
ТЭП, цена входа, площади объектов, соцнагрузка — обнуляются. Разделение то же,
что при импорте участка: метры принадлежат площадке, ставки и сроки — аналитику.

Поэтому после сброса состояние сверяется с тем, каким оно обязано быть, и
уцелевшее НАЗЫВАЕТСЯ. Пусто — значит пусто, а не «кажется, сработало».

Запуск: python3 -m pytest tests/test_the_reset_proves_itself.py -q
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "main_legacy.py").read_text(encoding="utf-8")


def _body(name: str, until: str) -> str:
    start = PAGE.index(name)
    return PAGE[start:PAGE.index(until, start)]


def test_the_wanted_state_is_declared_once() -> None:
    """Пока умолчаний было два, проверка честно жаловалась на поля, которые
    сброс сам же и ставит."""
    assert "function resetInputsWanted()" in PAGE
    reset = _body("function resetAll(){", "\n// Сброс, который проверяет сам себя")
    assert "inputs=resetInputsWanted()" in reset
    for gone in ("inputs.project_class='comfort'", "inputs.scenario_cost_multiplier=1"):
        assert gone not in reset, "вторая копия умолчаний вернулась в сброс"

    check = _body("function resetLeftovers(){", "\n}")
    assert "resetInputsWanted()" in check, "проверка сверяется с тем же выражением"


def test_the_leftovers_are_named_not_hinted() -> None:
    check = _body("function resetLeftovers(){", "\n}")
    assert "вводная «" in check and "ТЭП «" in check
    assert "лишняя вводная «" in check, "поле, которого в умолчаниях нет, — тоже след"

    caller = _body("function resetProject(){", "\nfunction resetTepControls(")
    assert "resetAll()" in caller and "left" in caller
    assert "Сброс оставил" in caller, "уцелевшее показывается человеку"


def test_a_late_calculation_does_not_refill_the_report() -> None:
    """Сброс перерисовывает поля, их onchange зовёт расчёт, а расчёт
    асинхронный: он возвращается уже после обнуления и заполняет отчёт заново.
    На сайте это скрыто перезагрузкой, в мини-приложении её нет."""
    assert "const startedAtReset=resetRun" in PAGE
    assert "if(startedAtReset!==resetRun){" in PAGE
    guard = PAGE[PAGE.index("if(startedAtReset!==resetRun){"):]
    guard = guard[:guard.index("\n }")]
    assert "lastResult=null" in guard and "blankResultSurfaces()" in guard


def test_the_reset_still_starts_the_page_over_outside_telegram() -> None:
    """У перезагрузки нет списка полей, и обойти его нечем — это и есть самый
    полный сброс. Исключение только для мини-приложения: бот открыл бы окно
    заново с той же сессией."""
    caller = _body("function resetProject(){", "\nfunction resetTepControls(")
    assert "location.replace(location.pathname)" in caller
    assert "isTelegramWebApp()" in caller
    assert "localStorage.removeItem('plato_v04')" in caller


def test_the_site_data_is_zeroed_and_the_assumptions_are_not() -> None:
    """Умолчание ТЭП — это пример, а не пустой проект."""
    assert "function resetTepWanted()" in PAGE
    body = _body("function resetTepWanted(){", "\n}")
    for field in ("gns", "total_area", "useful", "saleable", "transfer", "units"):
        assert f"'{field}'" in body, f"поле {field} остаётся примером"
    assert "want[row][field]=0" in body

    wanted = _body("function resetInputsWanted(){", "\n}")
    assert "TERRITORY_INPUT_KEYS.forEach" in wanted, \
        "цена входа и площади объектов принадлежат участку"
    assert "cloneValue(INPUT_DEFAULT)" in wanted, "ставки и сроки — предпосылки аналитика"

    reset = _body("function resetAll(){", "\n// Сброс, который проверяет сам себя")
    assert "tep=resetTepWanted()" in reset
    assert "tep=cloneValue(TEP_DEFAULT)" not in reset, "сброс снова ставит пример"

    check = _body("function resetLeftovers(){", "\n}")
    assert "resetTepWanted()" in check, "проверка сверяется с тем же выражением"
    assert "Object.keys(TEP_DEFAULT)" not in check


def test_the_reset_really_empties_the_table_in_a_browser(tmp_path) -> None:
    """Поведение решает браузер, а не строка в исходнике: на `cloneValue` мы
    это уже проходили — зелёный node отвечал за движок, который ведёт себя
    иначе. Без Chromium — пропуск, а не зелёный прогон на пустом месте."""
    import pytest

    play = pytest.importorskip("playwright.sync_api")
    import sys as _sys

    _sys.path.insert(0, str(ROOT))
    import browser_launch
    from fastapi.testclient import TestClient

    import main_registry

    page = tmp_path / "classic.html"
    page.write_text(TestClient(main_registry.app).get("/classic").text, encoding="utf-8")
    with play.sync_playwright() as pw:
        try:
            browser = browser_launch.launch(pw)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page()
            tab.route("**/*", lambda route: route.abort()
                      if route.request.url.startswith("http") else route.continue_())
            tab.goto(page.resolve().as_uri())
            tab.wait_for_timeout(600)
            before = tab.evaluate("()=>tep.apartments.gns")
            got = tab.evaluate(
                "()=>{const left=resetAll();return {left,"
                " gns:tep.apartments.gns, units:tep.apartments.units,"
                " parking:tep.underground_parking.gns,"
                " price:inputs.purchase_price_mln, offices:inputs.offices_gba_sqm,"
                " cls:inputs.project_class,"
                " row:(()=>{const r=Array.from(document.querySelectorAll('tr'))"
                "  .find(x=>x.textContent.trim().startsWith('Квартиры'));"
                "  return r?Array.from(r.querySelectorAll('input')).map(i=>i.value):[]})()}}")
        finally:
            browser.close()

    assert before > 0, "до сброса ТЭП должен быть непустым — иначе проверка ни о чём"
    assert got["gns"] == 0 and got["units"] == 0 and got["parking"] == 0
    assert got["price"] == 0 and got["offices"] == 0, "данные участка остались"
    assert got["cls"] == "comfort", "класс — предпосылка, он возвращается к умолчанию"
    assert got["left"] == [], f"сброс сам сообщил об уцелевшем: {got['left']}"
    # И на экране, а не только в памяти: человек смотрит на ячейки.
    assert got["row"] and got["row"][0] == "0" and got["row"][1] == "0"

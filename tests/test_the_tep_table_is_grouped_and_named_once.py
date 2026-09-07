"""Таблица ТЭП разложена по разделам, а имя продукта объявлено один раз.

«Можно ли таблицы ввода данных сделать более стильными и систематизированные…
особенно таблицы ТЭПов тяжеловаты и визуально не структурированы» и «без
хаотичной топонимики» (владелец, 06.09.2026).

Измерено до правки: двенадцать строк одним списком — дом, отдельно стоящие
объекты и то, что уходит городу, вперемешку; а имя продукта было написано
руками ПЯТЬ раз, и копии разошлись — жильё было «Квартиры» и «Жильё», кладовые
«Кладовые» и «Кладовки», ФОК — «ФОК», «ФОК / спорт» и «ФОК / спортивный
объект», садик — «ДОУ» в таблице и «ДОО» в требованиях КРТ на том же экране.

Третье, что нашлось по дороге и стоит дороже вёрстки: подвал таблицы
складывал ГНС ПО ВСЕМ строкам, то есть строительный объём, и подписывал его
именем ГНС. Движок с 04.09.2026 считает иначе — `project_gns_sqm` наземная, —
и сравнить итог таблицы с ГНС из отчёта было нельзя.

Запуск: python3 -m pytest tests/test_the_tep_table_is_grouped_and_named_once.py -q
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def test_the_product_name_is_declared_once() -> None:
    """Рукописных карт имён на странице нет: имя берётся у `TEP_DEFAULT`.

    Запрещается МЕСТО, а не слово: сам `TEP_DEFAULT` приезжает JSON'ом с
    двойными кавычками, и под запрет он не попадает. Карта, написанная руками
    в скрипте, пишет ключ без кавычек — её и ищем.
    """
    page = core.PAGE
    handwritten = re.findall(r"\{\s*apartments\s*:\s*['\"]", page)
    assert not handwritten, (
        f"на странице {len(handwritten)} рукописных карт имён продукта — "
        "они разойдутся с объявлением в движке")
    assert "function productName(" in page, "имя продукта негде взять"
    # Читатели имени пользуются одной функцией, а не своими литералами.
    assert page.count("function productName(") == 1


def test_every_product_has_one_name_everywhere() -> None:
    """Одно имя на продукт — и оно то, что объявлено в движке."""
    page = core.PAGE
    for key, row in core.TEP_DEFAULT.items():
        label = row["label"]
        assert label, key
    # Разошедшиеся варианты, из-за которых правило и записано.
    for gone in ("'Жильё'", "'Кладовки'", "'ФОК / спорт'", "'Коммерция 1 эт.'"):
        assert gone not in page, f"вернулось второе имя продукта: {gone}"
    # Садик зовётся ДОО — термин РНГП и договоров КРТ. Текст шаблона ПЛАТО это
    # правило не трогает: там имена блоков написаны владельцем, и по ним книга
    # ищет свои строки.
    visible = [m for m in re.finditer("ДОУ", page)
               if "//" not in page[page.rfind("\n", 0, m.start()):m.start()]]
    assert not visible, "«ДОУ» осталось на экране рядом с «ДОО»"


def test_the_groups_cover_every_product() -> None:
    """Продукт, не попавший ни в один список, остаётся в таблице.

    Раздел, объявленный пустым, — остаточный: иначе тринадцатый продукт исчезал
    бы с экрана молча, а молча исчезнувшая строка читается как её отсутствие.
    """
    named: set[str] = set()
    empty = 0
    for _title, keys in core.TEP_GROUPS:
        named |= set(keys)
        if not keys:
            empty += 1
    assert empty == 1, "остаточный раздел должен быть ровно один"
    assert named <= set(core.TEP_DEFAULT), "раздел называет продукт, которого нет"
    assert set(core.MKD_PRODUCTS) <= named and set(core.STANDALONE_PRODUCTS) <= named


TABLE_STATE = """() => {
  const tb = document.querySelector('.teptable');
  const rows = [...tb.querySelectorAll('tbody tr')].map(tr => ({
    kind: tr.className || 'row',
    head: (tr.cells[0].innerText || '').split('\\n')[0].trim()}));
  const foot = tb.querySelector('tfoot');
  return {
    rows,
    gns_total: foot.querySelector('#tg').textContent.trim(),
    under_note: (document.getElementById('tepUndergroundNote') || {}).textContent || '',
    tep: JSON.parse(JSON.stringify(tep))};
}"""


@pytest.fixture(scope="module")
def screen(tmp_path_factory):
    play = pytest.importorskip("playwright.sync_api")
    import browser_launch

    page_file = tmp_path_factory.mktemp("tep") / "page.html"
    page_file.write_text(core.PAGE, encoding="utf-8")
    with play.sync_playwright() as pw:
        try:
            browser = browser_launch.launch(pw)
        except Exception as exc:  # pragma: no cover — образ без Chromium
            pytest.skip(f"Chromium недоступен: {exc}")
        tab = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors: list[str] = []
        # Сеть в проверке закрыта нарочно, и «Failed to fetch» — это наш же
        # обрыв запроса, а не поломка страницы: считать его ошибкой значит
        # красить проверку в красное на верном коде.
        tab.on("pageerror", lambda e: None if "Failed to fetch" in str(e)
               else errors.append(str(e)))
        tab.route("**/*", lambda r: r.abort()
                  if r.request.url.startswith("http") else r.continue_())
        tab.goto(page_file.as_uri())
        tab.wait_for_timeout(1200)
        tab.evaluate("openTab('tep')")
        tab.wait_for_timeout(400)
        yield tab, errors
        browser.close()


def test_the_table_is_split_into_named_sections(screen) -> None:
    """Разделы видно, и подытог стоит там, где продуктов больше одного."""
    tab, errors = screen
    state = tab.evaluate(TABLE_STATE)
    heads = [r["head"] for r in state["rows"] if r["kind"] == "tep-group"]
    subs = [r["head"] for r in state["rows"] if r["kind"] == "tep-sub"]
    assert len(heads) >= 3, f"разделов не видно: {heads}"
    assert any("многоквартирный" in s.lower() for s in subs), subs
    # Раздел из одних нулей подытога не получает: шесть нулей в строке — шум.
    assert not any("отдельно стоящие" in s.lower() for s in subs), (
        "подытог нарисован там, где считать нечего")
    assert not errors, errors


def test_the_total_gns_is_the_above_ground_one(screen) -> None:
    """Итог ГНС — то же число, что считает движок, а не строительный объём."""
    tab, _ = screen
    state = tab.evaluate(TABLE_STATE)
    shown = float(state["gns_total"].replace(" ", "").replace(" ", "")
                  .replace(",", "."))
    report = core._run_authoritative_model(
        json.loads(json.dumps(core.DEFAULT_INPUTS)), state["tep"], [], {})
    summary = report["consolidated"]["summary"]
    assert abs(shown - summary["project_gns_sqm"]) < 1.0, (
        f"в подвале {shown}, у движка {summary['project_gns_sqm']}")
    # Подземная и объём стройки названы рядом — иначе исчезли бы с экрана.
    # Говорит это подпись под таблицей (`tepUndergroundNote`), и она одна:
    # второе такое утверждение в клетке итога было бы тем же дважды.
    assert "Подземная часть" in state["under_note"], state["under_note"]
    assert "Строительный объём" in state["under_note"]
    volume = summary["construction_volume_sqm"]
    assert abs(shown - summary["project_gns_sqm"]) < abs(shown - volume), (
        "в клетке ГНС стоит строительный объём")

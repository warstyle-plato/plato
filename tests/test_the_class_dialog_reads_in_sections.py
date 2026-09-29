"""Окно «Настройки классов» разложено по разделам с понятными подписями.

Владелец (29.09.2026): окно — «не структурированный набор вводных», строки
подряд без смысла; «Площадь на 1 место на первых этажах, м²/место = 25»
читалось как «место за 25 рублей». Теперь строки идут разделами карты движка
(`CLASS_DIALOG_SECTIONS`), а подпись строки называет объект и величину.

Проверяется отрисованное окно — Chromium на живой странице. Ключ строки
берётся из её поля ввода (`setClassBase('<класс>','<ключ>',…)`), а не из
новой разметки: на прежней вёрстке без разделов тест падает, а не ломается.

Запуск: python3 -m pytest tests/test_the_class_dialog_reads_in_sections.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main as wrapper  # noqa: E402

core = wrapper.core
PORT = 18979
SECTION_ORDER = ["flats", "build", "norms", "parking", "objects"]

READ = r"""() => {
  renderClassDialog();
  const box = document.getElementById('classDialogBody');
  const rows = [];
  let section = null;
  for (const tr of box.querySelectorAll('table tr')) {
    if (tr.classList.contains('class-section')) {
      const th = tr.querySelector('th'), s = getComputedStyle(th);
      section = tr.dataset.section;
      rows.push({kind: 'section', section, title: th.innerText,
                 bg: s.backgroundColor, color: s.color,
                 size: parseFloat(s.fontSize), weight: Number(s.fontWeight)});
      continue;
    }
    const input = tr.querySelector('input');
    const m = input && /setClassBase\('[a-z]+','([a-z0-9_]+)'/.exec(
      input.getAttribute('onchange') || '');
    if (!m) continue;
    const td = tr.querySelector('td'), s = getComputedStyle(td);
    rows.push({kind: 'row', section, key: m[1],
               label: td.innerText.replace(/\s+/g, ' ').trim(),
               size: parseFloat(s.fontSize)});
  }
  // Список полей окна — тем же правилом, что и до разделов.
  const keys = Object.keys(PROJECT_CLASS_PRESETS[Object.keys(PROJECT_CLASS_PRESETS)[0]])
    .filter(k => k !== 'label' && fieldInProject(k));
  return {rows, keys};
}"""


@pytest.fixture(scope="module")
def dialog():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    import browser

    path = browser.chromium_or_skip()
    errors: list[str] = []
    out: dict = {}
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1300, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(base, wait_until="domcontentloaded")
            page.evaluate("localStorage.removeItem('plato_v04')")
            page.reload(wait_until="domcontentloaded")
            page.wait_for_function("typeof openClassDialog==='function'")
            page.evaluate("delete inputs.object_instances")
            page.evaluate("openClassDialog()")
            out["plain"] = page.evaluate(READ)
            # Экземпляр офиса приносит свои строки — в раздел объектов.
            page.evaluate("addObjectInstance('offices')")
            out["office2"] = page.evaluate(READ)
            page.close()
    out["errors"] = errors
    return out


def _layout_labels() -> dict[str, str]:
    return {row["key"]: row["label"] for section in core.class_dialog_layout()
            for row in section["rows"]}


def test_the_map_covers_every_class_field_once() -> None:
    fields = [k for k in core.PROJECT_CLASS_PRESETS["comfort"] if k != "label"]
    placed = [row["key"] for section in core.class_dialog_layout()
              for row in section["rows"]]
    assert len(placed) == len(set(placed)), placed
    assert sorted(placed) == sorted(fields), set(fields) ^ set(placed)
    assert [s["id"] for s in core.class_dialog_layout()] == SECTION_ORDER


def test_an_instance_takes_the_section_and_label_of_its_type() -> None:
    by_key = {row["key"]: (section["id"], row["label"])
              for section in core.class_dialog_layout() for row in section["rows"]}
    for obj in core.STANDALONE_OBJECTS:
        if not obj.family or obj.rate_price not in by_key:
            continue
        section, label = by_key[obj.rate_price]
        assert section == "objects", (obj.key, section)
        assert label.startswith(obj.group_label + ":"), label


@pytest.mark.parametrize("case", ["plain", "office2"])
def test_every_row_sits_in_exactly_one_section(dialog, case) -> None:
    assert dialog["errors"] == [], dialog["errors"]
    got = dialog[case]
    rows = [r for r in got["rows"] if r["kind"] == "row"]
    assert rows, "в окне классов нет строк — мерить нечего"
    # Ни одной строки вне раздела: на прежней вёрстке section здесь null.
    assert all(r["section"] in SECTION_ORDER for r in rows), \
        [(r["key"], r["section"]) for r in rows if r["section"] not in SECTION_ORDER]
    # Ни одна строка не потеряна и не задвоена против списка полей окна.
    keys = [r["key"] for r in rows]
    assert len(keys) == len(set(keys)), keys
    assert sorted(keys) == sorted(got["keys"]), set(keys) ^ set(got["keys"])


@pytest.mark.parametrize("case", ["plain", "office2"])
def test_sections_follow_the_map_order_and_each_once(dialog, case) -> None:
    heads = [r["section"] for r in dialog[case]["rows"] if r["kind"] == "section"]
    assert heads == SECTION_ORDER, heads
    # Строки раздела идут подряд под своим заголовком.
    seen = [r["section"] for r in dialog[case]["rows"] if r["kind"] == "row"]
    order = [s for i, s in enumerate(seen) if i == 0 or seen[i - 1] != s]
    assert order == SECTION_ORDER, order


def test_the_section_heading_stands_out(dialog) -> None:
    got = dialog["plain"]["rows"]
    heads = [r for r in got if r["kind"] == "section"]
    assert heads, "в окне нет заголовков разделов"
    row_size = max(r["size"] for r in got if r["kind"] == "row")
    for head in heads:
        assert head["title"].strip(), head
        # Тёмная полоса и белый текст, крупнее и жирнее строк.
        rgb = [int(float(x)) for x in head["bg"].split("(")[1].rstrip(")").split(",")[:3]]
        assert max(rgb) < 60, head
        assert head["color"].startswith("rgb(255, 255, 255"), head
        assert head["size"] > row_size and head["weight"] >= 700, (head, row_size)


def test_the_labels_name_the_object_and_the_quantity(dialog) -> None:
    labels = _layout_labels()
    rows = {r["key"]: r["label"] for r in dialog["office2"]["rows"] if r["kind"] == "row"}
    for key, text in rows.items():
        assert text.startswith(labels[key]), (key, text)
        unit = core.class_field_unit(key)
        assert unit and unit in text, (key, text)
    # Та самая жалоба: «место на первых этажах = 25» без объекта и величины.
    garage = rows["object_parking_over_area_per_space_sqm"]
    assert "Площадь на 1 место на первых этажах" not in garage, garage
    assert "ОСЗ" in garage and "машино-мест" in garage, garage
    assert rows["offices2_price_th_per_sqm"].startswith("МФОЦ / офисы 2:"), rows


def test_a_project_without_the_instance_hides_its_rows(dialog) -> None:
    """Правило #579 не сломано разделами: строк чужого экземпляра нет."""
    plain = {r["key"] for r in dialog["plain"]["rows"] if r["kind"] == "row"}
    assert "offices2_price_th_per_sqm" not in plain
    office2 = {r["key"] for r in dialog["office2"]["rows"] if r["kind"] == "row"}
    assert {"offices2_price_th_per_sqm", "offices2_cost_th_per_sqm"} <= office2

"""Плитка показывает отобранное — так и подписана.

Владелец (01.09.2026): «в КРТ осталось 58 объектов, как так». В каталоге при
этом 577, и под таблицей честно написано: «Скрыто фильтром: 400 без объёма под
задачу; 119 уже в реализации». Но крупная плитка говорит просто «проектов» —
её читают первой, а мелкую строку под таблицей уже нет.

Число, названное не тем именем, выглядит посчитанным, и проверить его нечем:
ровно та ошибка, что ловится в отчётах («по такому-то плану» под числом из
другого источника). Отбор — это отбор, и он назван.

Запуск: python3 -m pytest tests/test_the_tile_says_it_is_filtered.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import ui  # noqa: E402

ROWS = [
    {"slug": f"s{i}", "name": f"Площадка {i}", "okrug": "САО", "district": "Сокол",
     "status": "Планируемый", "area_ha": 1.0, "total_gfa_sqm": 1000,
     "housing_gfa_sqm": 800 if i < 3 else 0, "jobs": 10}
    for i in range(6)
]


def test_the_tile_names_the_selection_and_the_whole(tmp_path):
    pw = pytest.importorskip("playwright.sync_api")
    import browser_launch

    file = tmp_path / "auctions.html"
    file.write_text(ui.auctions_page(None), encoding="utf-8")
    with pw.sync_playwright() as play:
        try:
            browser = browser_launch.launch(play)
        except Exception as exc:  # образ без Chromium — не поломка страницы
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page(viewport={"width": 1440, "height": 900})
            tab.goto(file.as_uri())
            tab.wait_for_timeout(300)
            tab.evaluate("()=>document.getElementById('tabKrt')?.click()")
            got = tab.evaluate(
                """rows=>{
                  state.krt=rows;
                  state.krtFiltered=rows.slice(0,2);
                  renderKrt();
                  const part={count:document.getElementById('krtCount').textContent,
                              note:document.getElementById('krtCountNote').textContent};
                  state.krtFiltered=rows;
                  renderKrt();
                  return {part:part,
                          whole:{count:document.getElementById('krtCount').textContent,
                                 note:document.getElementById('krtCountNote').textContent}};
                }""", ROWS)
            tab.close()
        finally:
            browser.close()

    assert got["part"]["count"] == "2", "плитка показывает не отобранное"
    assert "в отборе" in got["part"]["note"], \
        "отобранное число подписано так, будто это весь каталог"
    assert "6" in got["part"]["note"], "не сказано, сколько всего в каталоге"
    # Ничего не скрыто — лишней оговорки быть не должно.
    assert got["whole"]["note"] == "проектов", \
        "подпись про отбор стоит там, где отбора нет"

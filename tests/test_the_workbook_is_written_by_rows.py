"""Лист книги трогают строкой, а не ячейкой — и это меряется счётом проходов.

Лист v4 весит мегабайт, и каждая запись через `_v4_set_cell` — проход
регуляркой по всему листу. Пока таких проходов сотни, это незаметно; блок
приобъектного паркинга (06.09.2026) сделал их пять тысяч, и сборка книги
подорожала с 3,2 до 15,0 секунды при том же числе формул (79 984 → 81 509,
+1,9%). Платил за это весь набор: книгу собирают три десятка файлов проверок, и
полный прогон на CI вырос с 40 минут до 74 — «почему 1:20 идут теперь
проверки» (владелец, 08.09.2026).

Ровно от этой болезни в файле уже жил `_v4_set_cells` со своим объяснением —
и соседний блок его не применил. Правило, закрытое в одном месте, соседнее не
защищает; поэтому здесь сторож, а не запись в памяти.

Меряется то, что дорого: сколько раз сборка прошла по листу целиком. Времени
проверка не меряет намеренно — оно зависит от машины, и такой сторож врал бы в
обе стороны.

Запуск: python3 -m pytest tests/test_the_workbook_is_written_by_rows.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

# Проходов по листу на одну сборку. Потолок с запасом: сейчас их около 860,
# до правки было 5 243. Упёрлись — значит новый блок пишет ячейку за ячейкой, и
# лечится это `_v4_set_cells` (запись пачкой) и `_v4_row_formulas` (чтение
# строки), а не поднятием потолка.
SCAN_CEILING = 1400

# Сколько ЛИСТА прочитано за сборку — проходы, умноженные на их длину. Счёт
# проходов на этот вопрос не отвечает: 08.09.2026 сетку книги протянули со 120
# месяцев до 180, лист вырос в полтора раза, и каждый проход подорожал с 2,64 до
# 3,99 мс при НЕИЗМЕННОМ числе проходов. Прогон на CI вырос с 74 минут до 108
# при тех же 5026 проверках — то есть сторож, считающий проходы, этого не видел
# вовсе. Сейчас 0,48 ГБ на сборку, до правки было 1,69.
BYTES_CEILING_GB = 0.80


def _scans(monkeypatch) -> dict[str, int]:
    counts = {"_v4_set_cell": 0, "_v4_cell_formula": 0}
    for name in counts:
        original = getattr(core, name)

        def wrapped(*args, _name=name, _original=original, **kwargs):
            counts[_name] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(core, name, wrapped)
    core.build_project_workbook(
        json.loads(json.dumps(core.DEFAULT_INPUTS)), core.TEP_DEFAULT, [], {},
        project_name="П")
    return counts


def test_the_sheet_is_scanned_per_row_not_per_cell(monkeypatch) -> None:
    """Сборка не ходит по листу тысячами проходов."""
    counts = _scans(monkeypatch)
    total = sum(counts.values())
    assert total <= SCAN_CEILING, (
        f"проходов по листу {total} при потолке {SCAN_CEILING}: "
        f"{counts}. Значит блок пишет ячейку за ячейкой — переведите его на "
        "`_v4_set_cells` и `_v4_row_formulas`, а не поднимайте потолок")


def _scanned_bytes(monkeypatch) -> tuple[int, int]:
    """Сколько байт листа прочитано за сборку и сколькими проходами."""
    state = {"bytes": 0, "calls": 0}
    for name in ("_v4_set_cell", "_v4_cell_formula", "_v4_set_cells",
                 "_v4_row_formulas", "_v4_set_or_insert_cell", "_v4_ensure_row"):
        original = getattr(core, name)

        def wrapped(xml, *args, _original=original, **kwargs):
            state["bytes"] += len(xml)
            state["calls"] += 1
            return _original(xml, *args, **kwargs)

        monkeypatch.setattr(core, name, wrapped)
    core.build_project_workbook(
        json.loads(json.dumps(core.DEFAULT_INPUTS)), core.TEP_DEFAULT, [], {},
        project_name="П")
    return state["bytes"], state["calls"]


def test_the_sheet_is_not_re_read_by_the_gigabyte(monkeypatch) -> None:
    """Мерится то, что дорого: проходы, умноженные на ширину сетки.

    Проходов может стать меньше, а сборка подорожать — так и вышло, когда лист
    стал шире. Это единственная мера, которая ловит обе беды сразу.
    """
    scanned, calls = _scanned_bytes(monkeypatch)
    gb = scanned / 1e9
    assert gb <= BYTES_CEILING_GB, (
        f"за сборку прочитано {gb:.2f} ГБ листа за {calls} проходов при потолке "
        f"{BYTES_CEILING_GB} ГБ. Блок ходит по всему листу на каждую ячейку — "
        "переведите его на `_v4_set_cells` и `_v4_row_formulas`. Потолок не "
        "поднимают: за ним стоит время прогона всего набора")


def test_the_batch_writers_are_actually_used(monkeypatch) -> None:
    """Пачечная запись не осталась объявленной без читателей.

    Потолок проходов можно было бы удержать и случайно — тем, что блок просто
    не дописался. Здесь утверждается второе: пачки в сборке РАБОТАЮТ.
    """
    used = {"cells": 0, "rows": 0}
    for key, name in (("cells", "_v4_set_cells"), ("rows", "_v4_row_formulas")):
        original = getattr(core, name)

        def wrapped(*args, _key=key, _original=original, **kwargs):
            used[_key] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(core, name, wrapped)
    core.build_project_workbook(
        json.loads(json.dumps(core.DEFAULT_INPUTS)), core.TEP_DEFAULT, [], {},
        project_name="П")
    assert used["cells"] > 20, used
    assert used["rows"] > 10, used

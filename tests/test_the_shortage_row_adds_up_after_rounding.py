"""Строка таблицы нехватки сходится и после округления.

«Я всё так же не понимаю, почему сумма трёх крайних столбцов не равна
первому» (владелец, 03.09.2026, экран). Сервер держит равенство по построению,
а на экране каждая ячейка округлялась до десятых отдельно: 286,8 + 111,8 +
260,0 = 658,6 при потребности 658,5. Финансист читает это как «не сходится» —
и прав: строка, которая не складывается, неотличима от ошибки счёта.

Проверяется тем же кодом страницы через node, а не пересказом.

Запуск: python3 -m pytest tests/test_the_shortage_row_adds_up_after_rounding.py -q
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from shutil import which

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from developaid_monitor_page import MONITOR_PAGE  # noqa: E402

# Строки с экрана владельца, в рублях: потребность, своё, резерв, не покрыто.
SCREEN = [
    (658_5e5, 286_8e5, 111_8e5, 260_0e5),
    (43_1e5, 21_6e5, 0.0, 21_4e5),
    (206_5e5, 11_1e5, 26_6e5, 168_8e5),
    (100_3e5, 26_5e5, 36_0e5, 37_8e5),
]


def _row_parts_source() -> str:
    match = re.search(r"const rowParts=\(total,parts\)=>\{.*?return \{total:t\*1e6,parts:ps\.map\(v=>v\*1e6\)\}\};",
                      MONITOR_PAGE, re.S)
    assert match, "на странице нет rowParts"
    return match.group(0)


def test_the_page_renders_the_row_through_the_reconciler() -> None:
    assert "rowParts(n.need,[n.own_limit,n.from_reserve,n.shortage])" in MONITOR_PAGE


def test_every_row_adds_up_after_rounding() -> None:
    if not which("node"):
        pytest.skip("node недоступен")
    # Дрейф округления уходит в остаток «не покрыто»; ноль остаётся нулём, а
    # не становится «−0,1» — тогда разница уходит в самое крупное слагаемое.
    script = _row_parts_source() + f"""
const rows={json.dumps([[t, [a, b, c]] for t, a, b, c in SCREEN])};
const out=rows.map(([t,p])=>rowParts(t,p));
out.push(rowParts(100.04e6,[100.06e6,0,0]));
console.log(JSON.stringify(out));
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    rows = json.loads(result.stdout)
    for row in rows:
        shown = [round(v / 1e6, 1) for v in row["parts"]]
        assert round(sum(shown), 1) == round(row["total"] / 1e6, 1), (shown, row["total"])
        assert all(v >= 0 for v in shown), shown
    # Ноль резерва остался нулём; дрейф ушёл в «не покрыто» (260 → 259,9).
    # Последняя строка: остаток нулевой, минус недопустим — дрейф в «своём».
    assert [round(v / 1e6, 1) for v in rows[-1]["parts"]] == [100.0, 0.0, 0.0]
    assert [round(v / 1e6, 1) for v in rows[0]["parts"]] == [286.8, 111.8, 259.9]
    assert [round(v / 1e6, 1) for v in rows[1]["parts"]] == [21.6, 0.0, 21.5]
    # Строка, сходившаяся и без правки, не тронута.
    assert [round(v / 1e6, 1) for v in rows[2]["parts"]] == [11.1, 26.6, 168.8]

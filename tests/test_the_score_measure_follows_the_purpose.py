"""Меру балла задаёт «Назначение», а отдельного списка задач больше нет.

Список «Ищем: жильё / потенциал / деловую застройку» дублировал два соседних
фильтра — «Статус» и «Назначение» — и вдобавок ОТБИРАЛ по умолчанию: на живом
каталоге он молча срезал 519 площадок из 577, и владелец увидел 58 при
непоставленных фильтрах (01.09.2026: «убери этот фильтр, он дублирует другие —
про статус и про назначение»).

Два органа управления на один вопрос однажды разойдутся, и оба будут выглядеть
верными. Остался один: «Назначение» и отбирает, и говорит, чем мерить объём.
Ничего не выбрано — меряем жильём, это и был прежний смысл.

Шкала при этом осталась прежней: якоря самого каталога (десятый и девяностый
процентили по объёму), полнота ТЭП баллов не прибавляет, а ограничивает.

Запуск: python3 -m pytest tests/test_the_score_measure_follows_the_purpose.py -q
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.ui import auctions_page  # noqa: E402

SITES = [
    {"slug": "big", "name": "Крупное жильё", "status": "Планируемый", "okrug": "САО",
     "total_gfa_sqm": 500000, "housing_gfa_sqm": 450000, "business_gfa_sqm": 50000,
     "area_ha": 20, "jobs": 900},
    {"slug": "mid", "name": "Среднее жильё", "status": "Планируемый", "okrug": "САО",
     "total_gfa_sqm": 120000, "housing_gfa_sqm": 95000, "business_gfa_sqm": 25000,
     "area_ha": 5, "jobs": 300},
    {"slug": "office", "name": "Деловая площадка", "status": "Планируемый", "okrug": "ЗАО",
     "total_gfa_sqm": 300000, "housing_gfa_sqm": 0, "business_gfa_sqm": 300000,
     "area_ha": 8, "jobs": 5200},
    {"slug": "blank", "name": "Без объёмов", "status": "Планируемый", "okrug": "ВАО",
     "total_gfa_sqm": 0, "housing_gfa_sqm": 0, "business_gfa_sqm": 0,
     "area_ha": 2, "jobs": 0},
]


def _scores(purpose: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    page = auctions_page()
    script = page[page.rindex("<script>") + len("<script>"):page.rindex("</script>")]

    def block(head: str, close: str) -> str:
        start = script.index(head)
        return script[start:script.index(close, start) + len(close)]

    def func(name: str) -> str:
        start = script.index(f"function {name}(")
        depth = 0
        for position in range(script.index("{", start), len(script)):
            if script[position] == "{":
                depth += 1
            elif script[position] == "}":
                depth -= 1
                if depth == 0:
                    return script[start:position + 1]
        raise AssertionError(name)

    program = "\n".join([
        # Ось назначения стала флажковой: мера балла читает выбранный набор.
        f"const state={{krtPick:{{purpose:new Set({json.dumps([purpose] if purpose else [])})}}}};",
        f"const SITES={json.dumps(SITES, ensure_ascii=False)};",
        "const fmtArea=v=>String(v);",
        block("const KRT_SCALE=", "};"),
        func("krtVolumeShare"),
        func("krtTaskProfile"),
        # Величина строки известна или нет — один ответ на всю страницу.
        func("krtBroken"),
        func("krtNumber"),
        func("krtFit"),
        "console.log(JSON.stringify(Object.fromEntries("
        "SITES.map(x=>[x.slug,krtFit(x).score]))));",
    ])
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:600]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_the_task_selector_is_gone():
    page = auctions_page()
    assert "krtProfile" not in page, "список задач вернулся и снова дублирует соседей"
    assert 'id="krtPurposeOptions"' in page and 'id="krtStageOptions"' in page, \
        "отбирать теперь нечем"


def test_the_purpose_sets_the_measure():
    housing = _scores("")
    # Значение оси теперь её ключ, а не имя поля ТЭП.
    business = _scores("business")
    assert business["office"] > business["mid"], \
        "деловое назначение не поднимает деловую площадку"
    assert housing["mid"] > housing["office"], \
        "без выбора меряем жильём — жилая площадка обязана быть выше"


def test_the_scale_is_not_a_wall_of_hundreds():
    scores = _scores("")
    assert scores["big"] > scores["mid"], "объём не различает площадки"
    assert scores["big"] < 100, "крупная площадка упирается в потолок шкалы"
    assert scores["mid"] < 75, "средняя по каталогу площадка не может быть «Высокой»"
    # Площадка без объёмов — это «не знаем»: выше «Среднего» она не поднимается.
    assert scores["blank"] <= 45

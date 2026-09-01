"""Задача в списке КРТ отбирает площадки, а не красит балл.

«Этот фильтр туфта, они ничего не дают» (владелец, 01.09.2026), и на живом
каталоге это подтвердилось дважды. Балл был сложен из постоянных прибавок —
профиль +30, полнота ТЭП ×3, масштаб +5, — и 163 площадки из 263 выходили
«Высокими» при медиане 92 и двадцати штуках ровно по сто. А два жилищных
профиля считали ровно один и тот же балл: они различались одной строкой в
подсказке.

Теперь шкала стоит на якорях самого каталога (десятый процентиль и девяностый
по объёму), а задача — это ОТБОР: «готовое к старту» оставляет те, куда ещё
можно войти, «потенциал» — всё жильё вместе с занятым, «деловая» — площадки с
нежилым объёмом. Скрытое считается и называется под таблицей.

Запуск: python3 -m pytest tests/test_the_task_filter_actually_selects.py -q
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

# Каталог-образец: разные объёмы, доли и стадии. Числа взяты по порядку
# величины из живого реестра krt.mos.ru (263 площадки, 01.09.2026): медиана
# жилого объёма около 95 тыс. м², девяностый процентиль около 400 тыс.
SITES = [
    {"slug": "big", "name": "Крупное жильё", "status": "Планируемый", "okrug": "САО",
     "total_gfa_sqm": 500000, "housing_gfa_sqm": 450000, "business_gfa_sqm": 50000,
     "area_ha": 20, "jobs": 900},
    {"slug": "mid", "name": "Среднее жильё", "status": "Планируемый", "okrug": "САО",
     "total_gfa_sqm": 120000, "housing_gfa_sqm": 95000, "business_gfa_sqm": 25000,
     "area_ha": 5, "jobs": 300},
    {"slug": "taken", "name": "Занятое жильё", "status": "В реализации", "okrug": "ЮАО",
     "total_gfa_sqm": 600000, "housing_gfa_sqm": 560000, "business_gfa_sqm": 40000,
     "area_ha": 30, "jobs": 800},
    {"slug": "office", "name": "Деловая площадка", "status": "Планируемый", "okrug": "ЗАО",
     "total_gfa_sqm": 300000, "housing_gfa_sqm": 0, "business_gfa_sqm": 300000,
     "area_ha": 8, "jobs": 5200},
    {"slug": "blank", "name": "Без объёмов", "status": "Планируемый", "okrug": "ВАО",
     "total_gfa_sqm": 0, "housing_gfa_sqm": 0, "business_gfa_sqm": 0,
     "area_ha": 2, "jobs": 0},
]


def _run(profile: str) -> dict:
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
        f"const PROFILE={json.dumps(profile)};",
        f"const SITES={json.dumps(SITES, ensure_ascii=False)};",
        "const $=()=>({value:PROFILE});",
        "const fmtArea=v=>String(v);",
        block("const KRT_SCALE=", "};"),
        func("krtVolumeShare"),
        func("krtFit"),
        """
        const kept=SITES.filter(x=>{
          const wanted=PROFILE==='business'?Number(x.business_gfa_sqm):Number(x.housing_gfa_sqm);
          if(!(wanted>0))return false;
          if(PROFILE==='housing_ready'&&String(x.status||'').toLowerCase().includes('реализац'))return false;
          return true;});
        console.log(JSON.stringify({kept:kept.map(x=>x.slug),
          scores:Object.fromEntries(SITES.map(x=>[x.slug,krtFit(x).score]))}));
        """,
    ])
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:600]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_each_task_keeps_its_own_set():
    ready = _run("housing_ready")["kept"]
    pipeline = _run("housing_pipeline")["kept"]
    business = _run("business")["kept"]
    assert ready == ["big", "mid"], "«готовое к старту» пускает занятую площадку"
    assert "taken" in pipeline, "«потенциал» обязан показывать и занятое жильё"
    assert business == ["big", "mid", "taken", "office"], "деловая задача отбирает по нежилому"
    assert ready != pipeline, "две задачи оставляют один и тот же список"


def test_the_scale_is_not_a_wall_of_hundreds():
    """Полнота ТЭП и сам факт профиля больше баллов не дают."""
    scores = _run("housing_ready")["scores"]
    assert scores["big"] > scores["mid"], "объём под задачу не различает площадки"
    assert scores["big"] < 100, "крупная площадка упирается в потолок шкалы"
    assert scores["mid"] < 75, "средняя по каталогу площадка не может быть «Высокой»"
    # Площадка без объёмов — это «не знаем»: выше «Среднего» она не поднимается.
    assert scores["blank"] <= 45


def test_the_business_task_reorders_the_list():
    housing = _run("housing_pipeline")["scores"]
    business = _run("business")["scores"]
    assert business["office"] > business["mid"], "деловая задача не поднимает деловую площадку"
    assert housing["mid"] > housing["office"], "жилищная задача не отличает жильё"

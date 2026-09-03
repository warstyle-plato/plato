"""Балл КРТ различает площадки, а не красит весь список в «Низкое».

«Фильтры ни к черту» (владелец, 02.09.2026, снимок экрана): у четырёх площадок
подряд стояло 23, 22, 21 и 17 — «расчёт снял 73%, 60%, 70%, 80%». Скрининг
считает при нулевой цене входа и на общих предпосылках, и на них почти у каждой
площадки LLCR ниже 1,20x, а маржа ниже 15%: снижение мерило наши предпосылки, а
не площадку, и одинаково гасило весь каталог.

Шкала снижения теперь снимается с самого каталога — десятый и девяностый
процентили посчитанных строк, то же правило, что уже применено к шкале объёма.
Абсолютный пол остаётся один и назван: LLCR ниже 1,00x значит, что долг не
обслуживается даже при бесплатной земле.
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

from tests.test_krt_score_is_lowered_not_replaced import SITE, page_functions  # noqa: E402


def scores(rows: dict[str, dict]) -> dict[str, dict]:
    """Посчитать балл каждой площадки в присутствии всего каталога."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    sites = {slug: dict(SITE, slug=slug, name=slug) for slug in rows}
    body = (
        "const state={krtModels:{},krtRank:" + json.dumps(rows)
        + ",krtRequirements:{},krtPress:{}};\n"
        "const document={getElementById:()=>({value:'housing_ready'})};\n"
        "const $=()=>({value:'housing_ready'});\n"
        "function fmtArea(v){return String(v)}\n"
        + page_functions()
        + "\nconst out={};"
        + f"const sites={json.dumps(sites)};"
        + "Object.keys(sites).forEach(s=>{out[s]=krtScore(sites[s])});"
        "console.log(JSON.stringify(out));"
    )
    done = subprocess.run([node, "-e", body], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:800]
    return json.loads(done.stdout)


def catalogue(count: int = 20) -> dict[str, dict]:
    """Каталог, где ВСЕ площадки ниже абсолютных порогов, но между собой разные."""
    rows: dict[str, dict] = {}
    for index in range(count):
        share = index / (count - 1)
        rows[f"s{index}"] = {
            "project_llcr_x": round(1.00 + share * 0.18, 3),   # 1,00 … 1,18 — все ниже 1,20
            "margin_pct": round(1.0 + share * 12.0, 2),        # 1 … 13% — все ниже 15
            "weakest_phase_llcr_x": round(0.90 + share * 0.09, 3),
            "entry_capacity_rub_per_sqm": 10000,
        }
    return rows


def test_the_weak_and_the_strong_stop_looking_alike():
    got = scores(catalogue())
    worst, best = got["s0"]["score"], got["s19"]["score"]
    assert best > worst, "лучшая площадка каталога не отличается от худшей"
    # Прежняя абсолютная шкала снимала с обеих почти всё: разница была в
    # единицы баллов при разнице показателей в разы.
    assert best - worst >= 20, f"шкала почти не различает: {worst} против {best}"
    assert got["s19"]["cut"] <= 15, f"верх каталога снижен на {got['s19']['cut']}%"


def test_the_reason_says_the_scale_is_the_catalogues():
    """Подпись называет порог и своё число: слово «ниже» само по себе не сравнимо.

    Прежде стояло «ниже каталога» — и стояло у 137 площадок из 153, потому что
    нулевая точка шкалы это ДЕВЯНОСТЫЙ процентиль, а не середина. Читалось это
    как приговор большинству, а сказано было «не в верхней десятой части».
    """
    got = scores(catalogue())
    labels = " ".join(item["label"] for item in got["s0"]["cuts"])
    assert "ниже верхней десятой части каталога" in labels, labels
    assert "ниже каталога" not in labels, labels
    # Своё число и порог стоят рядом — иначе сравнивать не с чем.
    assert "1,16x" in labels and "1x" in labels, labels


def test_a_project_that_cannot_service_debt_is_still_cut():
    """Относительная шкала не имеет права спрятать абсолютно плохое."""
    rows = catalogue()
    rows["dead"] = {"project_llcr_x": 0.72, "margin_pct": -9.0,
                    "weakest_phase_llcr_x": 0.60, "entry_capacity_rub_per_sqm": None}
    got = scores(rows)
    labels = " ".join(item["label"] for item in got["dead"]["cuts"])
    assert "долг не обслуживается" in labels, labels
    assert "в убытке" in labels, labels
    # Пол — ОТДЕЛЬНАЯ строка, а не поднятие относительной: написанный как
    # `Math.max(points, 20)`, он проваливался в максимум правила и не
    # срабатывал ровно там, где нужен, — у самой плохой площадки.
    assert got["dead"]["score"] < got["s0"]["score"], (
        "относительная шкала снова прячет абсолютно плохое")


def test_a_short_catalogue_keeps_the_absolute_scale():
    """Три строки — не распределение: процентиль по ним был бы выдумкой."""
    rows = {key: value for key, value in list(catalogue().items())[:3]}
    got = scores(rows)
    labels = " ".join(item["label"] for item in got["s0"]["cuts"])
    assert "ниже каталога" not in labels, labels

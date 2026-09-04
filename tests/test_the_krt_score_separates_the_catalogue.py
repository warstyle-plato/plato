"""Балл КРТ различает площадки, а не красит весь список в «Низкое».

«Фильтры ни к черту» (владелец, 02.09.2026): у четырёх площадок подряд стояло
23, 22, 21 и 17 — «расчёт снял 73%, 60%, 70%, 80%». Ответом тогда стала
шкала по процентилям каталога — и она красила список так же: нулевая точка
это девяностый процентиль, девять площадок из десяти снижены всегда, и на
проде 04.09.2026 «Низкое» стояло у 151 посчитанной площадки из 155 («баллы
в КРТ по-моему так и считаются плохо как и раньше»).

Красил же список не порог, а СЛОЖЕНИЕ: LLCR, маржа и слабейшая очередь — одно
явление, и три снижения за него снимали 60–95% у площадки, которая на каждом
лишь чуть ниже цели. Снижение теперь одно — самое большое из трёх, по порогам
банка (1,20x и 15% — цель, 0,90x и ноль — дно); абсолютный пол остаётся и
назван: LLCR ниже 1,00x значит, что долг не обслуживается даже при бесплатной
земле.
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
    """Каталог, где ВСЕ площадки ниже цели банка, но между собой разные."""
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
    # Три сложенных снижения давали разницу в единицы баллов при разнице
    # показателей в разы; одно снижение — разницу в десятки.
    assert best - worst >= 15, f"шкала почти не различает: {worst} против {best}"
    assert got["s19"]["cut"] <= 10, f"почти целевой проект снижен на {got['s19']['cut']}%"
    # Чуть ниже цели — не «Низкое»: у каждой площадки ровно одно снижение за
    # экономику, а не три.
    assert got["s0"]["cut"] <= 35, got["s0"]["cuts"]
    assert sum(1 for c in got["s0"]["cuts"] if "ниже цели банка" in c["label"]) == 1


def test_the_reason_names_the_banks_target_not_the_catalogue():
    """Подпись называет порог и своё число; порог — банка, не каталога."""
    got = scores(catalogue())
    labels = " ".join(item["label"] for item in got["s0"]["cuts"])
    assert "ниже цели банка" in labels, labels
    assert "каталога" not in labels, labels
    assert "1,2x" in labels and "1x" in labels, labels


def test_a_project_that_cannot_service_debt_is_still_cut():
    """Пол абсолютный и стоит ОТДЕЛЬНОЙ строкой."""
    rows = catalogue()
    rows["dead"] = {"project_llcr_x": 0.72, "margin_pct": -9.0,
                    "weakest_phase_llcr_x": 0.60, "entry_capacity_rub_per_sqm": None}
    got = scores(rows)
    labels = " ".join(item["label"] for item in got["dead"]["cuts"])
    assert "долг не обслуживается" in labels, labels
    assert "в убытке" in labels, labels
    assert got["dead"]["score"] < got["s0"]["score"]


def test_the_score_does_not_move_when_neighbours_are_recounted():
    """Балл площадки — про неё, а не про то, кого пересчитали рядом."""
    rows = catalogue()
    alone = scores({"s5": rows["s5"]})["s5"]
    together = scores(rows)["s5"]
    assert alone["score"] == together["score"] and alone["cut"] == together["cut"]

"""Класс проекта — это и класс его офисника (владелец, 27.09.2026).

Комфорт — офисы B и ниже, бизнес — B+ и A−, элитный — A и выше. Себестоимость
здания офиса идёт за классом шкалой 175 / 200 / 225 тыс ₽/м² GBA, и её по-
прежнему можно поправить руками. Прежде она стояла одним числом 200 на все
классы: офис A строился по цене офиса B.

Запуск: python3 -m pytest tests/test_the_office_class_follows_the_project_class.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import page_blocks  # noqa: E402
import main_legacy as core  # noqa: E402


def test_the_scale_is_the_owner_scale() -> None:
    scale = {key: core.PROJECT_CLASS_PRESETS[key]["offices_cost_th_per_sqm"]
             for key in ("comfort", "business", "elite")}
    assert scale == {"comfort": 175, "business": 200, "elite": 225}
    # Умолчания и есть комфорт.
    assert core.DEFAULT_INPUTS["offices_cost_th_per_sqm"] == 175


def test_a_hand_rate_is_named_as_a_deviation() -> None:
    """Правка руками сильнее класса и называется вслух, а не молча."""
    rows = core.project_class_deviations(
        {"project_class": "business", "offices_cost_th_per_sqm": 240})["rows"]
    row = next(one for one in rows if one["field"] == "offices_cost_th_per_sqm")
    assert (row["base"], row["actual"]) == (200.0, 240.0)


def test_the_class_preview_names_the_office_class() -> None:
    prelude = ("const box={textContent:''};\n"
               "const document={getElementById:id=>id==='projectClassPreview'?box:null};\n"
               "let inputs={project_class:'business',offices_enabled:true};\n")
    out, _ = page_blocks.run(prelude, "renderProjectClassPreview();"
                             "process.stdout.write(box.textContent);")
    assert "офисы класса B+ и A−" in out
    assert "себес. 200" in out

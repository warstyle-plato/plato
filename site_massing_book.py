"""Пятно застройки, этажность и подземные уровни — формулами книги.

Методика та же, что у движка (`engine/site_massing.py`): пятно = участок −
двор − проезды − открытые стоянки − отступы; средняя этажность = наземная ГНС ÷
пятно; уровни = вверх(подземная площадь ÷ (контур × коэффициент)); надбавка за
глубину — средневзвешенная по площадям уровней. Здесь один список строк и одни
формулы на обе книги — жилую v4 и нежилую: две копии одной методики разошлись
бы молча.

Формулы пишутся через `ref(key)` — ссылку на ячейку строки в книге, которая
блок у себя разместила. Вводные (`INPUT`) книга заполняет числами движка,
расчётные (`FORMULA`) — формулами отсюда.
"""

from __future__ import annotations

from typing import Callable

INPUT, FORMULA = "input", "formula"

# (ключ, подпись, вид). Порядок — порядок строк в книге.
ROWS: tuple[tuple[str, str, str], ...] = (
    ("site_sqm", "Площадь участка, м²", INPUT),
    ("yard_sqm", "Двор: озеленение и площадки, м²", INPUT),
    ("driveways_pct", "Проезды, тротуары и пожарные проезды, % участка", INPUT),
    ("setback_m", "Отступ от границ участка, м", INPUT),
    ("surface_parking_sqm", "Открытые стоянки, м² земли", INPUT),
    ("footprint_manual_sqm", "Пятно застройки вручную, м² (0 — оценка)", INPUT),
    ("above_gns_sqm", "Наземная ГНС проекта, м²", INPUT),
    ("underground_sqm", "Площадь подземной части, м²", INPUT),
    ("use_factor", "Полезная часть подземного контура, доля", INPUT),
    ("levels_manual", "Подземных уровней вручную (0 — по расчёту)", INPUT),
    ("markup2_pct", "Надбавка к ставке за второй подземный уровень, %", INPUT),
    ("markup3_pct", "Надбавка к ставке за третий уровень и ниже, %", INPUT),
    ("rate_by_hand", "Ставка подземной части задана вручную (Да — без надбавок)", INPUT),
    ("setbacks_sqm", "Отступы, м² (полоса по периметру квадрата той же площади)", FORMULA),
    ("footprint_estimate_sqm", "Пятно застройки — оценка по балансу, м²", FORMULA),
    ("footprint_sqm", "Пятно застройки, м²", FORMULA),
    ("average_storeys", "Средняя этажность", FORMULA),
    ("contour_sqm", "Подземный контур (участок без отступов), м²", FORMULA),
    ("capacity_sqm", "Помещается на одном уровне, м²", FORMULA),
    ("underground_levels", "Подземных уровней", FORMULA),
    ("slab_sqm", "Площадь уровня при раскладке, м²", FORMULA),
    ("level1_sqm", "Уровень −1, м²", FORMULA),
    ("level2_sqm", "Уровень −2, м²", FORMULA),
    ("level3_sqm", "Уровни −3 и ниже, м²", FORMULA),
    ("depth_factor", "Множитель ставки подземной части за глубину", FORMULA),
)

YES = "Да"
NO = "Нет"


def formulas(ref: Callable[[str], str]) -> dict[str, str]:
    """Формулы расчётных строк (без «=») через ссылки `ref(key)`."""
    r = ref
    return {
        "setbacks_sqm": (f"IF(AND({r('site_sqm')}>0,{r('setback_m')}>0),{r('site_sqm')}"
                         f"-MAX(0,SQRT({r('site_sqm')})-2*{r('setback_m')})^2,0)"),
        "footprint_estimate_sqm": (f"MAX(0,{r('site_sqm')}-{r('yard_sqm')}"
                                   f"-{r('site_sqm')}*{r('driveways_pct')}/100"
                                   f"-{r('surface_parking_sqm')}-{r('setbacks_sqm')})"),
        "footprint_sqm": (f"IF({r('footprint_manual_sqm')}>0,{r('footprint_manual_sqm')},"
                          f"{r('footprint_estimate_sqm')})"),
        "average_storeys": (f"IF({r('footprint_sqm')}>0,{r('above_gns_sqm')}"
                            f"/{r('footprint_sqm')},0)"),
        "contour_sqm": f"MAX(0,{r('site_sqm')}-{r('setbacks_sqm')})",
        "capacity_sqm": f"{r('contour_sqm')}*{r('use_factor')}",
        "underground_levels": (f"IF({r('underground_sqm')}<=0,0,IF({r('levels_manual')}>0,"
                               f"INT({r('levels_manual')}),IF({r('capacity_sqm')}>0,"
                               f"ROUNDUP({r('underground_sqm')}/{r('capacity_sqm')}-0.000000001,0),0)))"),
        # Верхние уровни заполняются до вместимости; не помещается (или
        # вместимости нет) — площадь делится поровну.
        "slab_sqm": (f"IF({r('underground_levels')}<=0,0,IF(OR({r('capacity_sqm')}<=0,"
                     f"{r('capacity_sqm')}*{r('underground_levels')}<{r('underground_sqm')}),"
                     f"{r('underground_sqm')}/{r('underground_levels')},{r('capacity_sqm')}))"),
        "level1_sqm": (f"IF({r('underground_levels')}>=1,"
                       f"MIN({r('slab_sqm')},{r('underground_sqm')}),0)"),
        "level2_sqm": (f"IF({r('underground_levels')}>=2,MIN({r('slab_sqm')},"
                       f"{r('underground_sqm')}-{r('level1_sqm')}),0)"),
        "level3_sqm": (f"IF({r('underground_levels')}>=3,{r('underground_sqm')}"
                       f"-{r('level1_sqm')}-{r('level2_sqm')},0)"),
        "depth_factor": (f"IF(OR({r('rate_by_hand')}=\"{YES}\",{r('underground_sqm')}<=0,"
                         f"{r('underground_levels')}<=0),1,({r('level1_sqm')}"
                         f"+{r('level2_sqm')}*(1+{r('markup2_pct')}/100)"
                         f"+{r('level3_sqm')}*(1+{r('markup3_pct')}/100))"
                         f"/{r('underground_sqm')})"),
    }


def input_values(massing: dict, inputs: dict) -> dict[str, object]:
    """Вводные блока — числа движка (`site_massing`), а ручные поля — как заданы."""
    def num(key: str) -> float:
        try:
            return float(inputs.get(key) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    return {
        "site_sqm": float(massing.get("site_sqm") or 0.0),
        "yard_sqm": float(massing.get("yard_sqm") or 0.0),
        "driveways_pct": float(massing.get("driveways_pct") or 0.0),
        "setback_m": float(massing.get("setback_m") or 0.0),
        "surface_parking_sqm": float(massing.get("surface_parking_sqm") or 0.0),
        "footprint_manual_sqm": max(0.0, num("building_footprint_sqm")),
        "above_gns_sqm": float(massing.get("above_gns_sqm") or 0.0),
        "underground_sqm": float(massing.get("underground_sqm") or 0.0),
        "use_factor": float(massing.get("underground_use_factor") or 0.0),
        "levels_manual": float(int(max(0.0, num("underground_levels")))),
        "markup2_pct": _markup(massing, 2),
        "markup3_pct": _markup(massing, 3),
        "rate_by_hand": YES if massing.get("underground_rate_by_hand") else NO,
    }


def _markup(massing: dict, level: int) -> float:
    return float(massing.get(f"underground_level{level}_markup_pct") or 0.0)

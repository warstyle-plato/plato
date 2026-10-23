"""Пятно застройки, этажность и подземные уровни — формулами книги.

Методика та же, что у движка (`engine/site_massing.py`): пятно = участок −
двор по норме − проезды − открытые стоянки − отступы, не больше процента
застройки (без него — 30 %) и не меньше наземной ГНС ÷ предел этажности (без
предела — 25); средняя этажность = наземная ГНС ÷
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

# Выше этого здание расчёт не ставит, когда предел участка не задан
# (владелец 22.10.2026); движок читает это же число.
STOREYS_LIMIT_DEFAULT = 25
# Процент застройки участка, когда градплан или ПЗЗ его не задают (владелец
# 22.10.2026, экспертное умолчание).
COVERAGE_PCT_DEFAULT = 30.0

# (ключ, подпись, вид). Порядок — порядок строк в книге.
ROWS: tuple[tuple[str, str, str], ...] = (
    ("site_sqm", "Площадь участка, м²", INPUT),
    ("objects_plot_sqm", "Участки школы, детского сада и отдельных нежилых зданий, м²", INPUT),
    ("yard_sqm", "Двор на участке по норме региона, м²", INPUT),
    ("driveways_pct", "Проезды, тротуары и пожарные проезды, % участка", INPUT),
    ("setback_m", "Отступ от границ участка, м", INPUT),
    ("surface_parking_sqm", "Открытые стоянки, м² земли", INPUT),
    ("footprint_manual_sqm", "Пятно застройки вручную, м² (0 — оценка)", INPUT),
    ("above_gns_sqm", "Наземная ГНС жилых домов, м² (без отдельных зданий)", INPUT),
    ("underground_sqm", "Площадь подземной части, м²", INPUT),
    ("use_factor", "Полезная часть подземного контура, доля", INPUT),
    ("levels_manual", "Подземных уровней вручную (0 — по расчёту)", INPUT),
    ("markup2_pct", "Надбавка к ставке за второй подземный уровень, %", INPUT),
    ("markup3_pct", "Надбавка к ставке за третий уровень и ниже, %", INPUT),
    ("rate_by_hand", "Ставка подземной части задана вручную (Да — без надбавок)", INPUT),
    ("max_storeys", "Предельная этажность участка (0 — не задана)", INPUT),
    ("coverage_pct", "Процент застройки участка, % (0 — без ограничения)", INPUT),
    ("setbacks_sqm", "Отступы, м² (полоса по периметру квадрата той же площади)", FORMULA),
    ("residential_site_sqm", "Жилая территория (участок без участков отдельных зданий), м²",
     FORMULA),
    ("footprint_estimate_sqm", "Пятно застройки — оценка по балансу, м²", FORMULA),
    ("coverage_sqm", "Пятно по проценту застройки, м²", FORMULA),
    ("landscaping_room_sqm", "Помещается благоустройства (без проездов, стоянок и отступов, "
     "с кровлей стилобата), м²", FORMULA),
    ("footprint_sqm", "Пятно застройки, м² (не меньше наземной ГНС ÷ предел этажности)", FORMULA),
    ("footprint_shortage_sqm", "Не хватает земли: пятно больше свободного места, м²", FORMULA),
    ("average_storeys", "Средняя этажность", FORMULA),
    ("contour_sqm", "Подземный контур (участок без отступов), м²", FORMULA),
    ("capacity_sqm", "Помещается на одном уровне, м²", FORMULA),
    ("underground_levels", "Подземных уровней", FORMULA),
    ("slab_sqm", "Площадь уровня при раскладке, м²", FORMULA),
    ("level1_sqm", "Уровень −1, м²", FORMULA),
    ("level2_sqm", "Уровень −2, м²", FORMULA),
    ("level3_sqm", "Уровни −3 и ниже, м²", FORMULA),
    ("depth_factor", "Множитель ставки подземной части за глубину", FORMULA),
    ("over_limit", "Этажность выше предельной", FORMULA),
)

# Ключ вводной блока в книге: поле движка, если вводная — его число, иначе
# служебное имя книги (`massing_…`). По ключу книга ставит формат числа, а
# проверки охвата находят поле.
# Проценты движка (15 = 15 %) книга держит тем же числом, а формат процента
# показал бы 1 500 % — у них служебный ключ и формат «0.0», а поле движка
# названо в пояснении (`PERCENT_FIELDS`).
PERCENT_FIELDS: dict[str, str] = {
    "coverage_pct": "site_coverage_max_pct",
    "driveways_pct": "site_driveways_pct",
    "markup2_pct": "underground_level2_markup_pct",
    "markup3_pct": "underground_level3_markup_pct",
}
ENGINE_FIELDS: dict[str, str] = {
    "setback_m": "site_setback_m",
    "footprint_manual_sqm": "building_footprint_sqm",
    "use_factor": "underground_contour_use_factor",
    "levels_manual": "underground_levels",
    "max_storeys": "max_storeys_allowed",
}
BOOK_KEYS: dict[str, str] = {
    key: ENGINE_FIELDS.get(key, f"massing_{key}") for key, _, kind in ROWS if kind == INPUT}
# Служебные ключи книги, чьи вводные — метры.
PERCENT_KEYS = tuple(f"massing_{key}" for key in PERCENT_FIELDS)
AREA_KEYS = ("massing_site_sqm", "massing_objects_plot_sqm", "massing_yard_sqm",
             "massing_surface_parking_sqm",
             "massing_above_gns_sqm", "massing_underground_sqm")

YES = "Да"
NO = "Нет"


def formulas(ref: Callable[[str], str]) -> dict[str, str]:
    """Формулы расчётных строк (без «=») через ссылки `ref(key)`."""
    r = ref
    cap = f"IF({r('max_storeys')}>0,{r('max_storeys')},{STOREYS_LIMIT_DEFAULT})"
    # Жилой баланс — на жилой территории; полоса отступа — её доля.
    home = r("residential_site_sqm")
    home_setbacks = f"{r('setbacks_sqm')}*{home}/MAX({r('site_sqm')},0.000001)"
    # Пятно — меньшее из процента застройки и остатка участка, но не меньше
    # наземной ГНС ÷ предел этажности.
    base = f"MIN({r('coverage_sqm')},{r('footprint_estimate_sqm')})"
    return {
        "setbacks_sqm": (f"IF(AND({r('site_sqm')}>0,{r('setback_m')}>0),{r('site_sqm')}"
                         f"-MAX(0,SQRT({r('site_sqm')})-2*{r('setback_m')})^2,0)"),
        "residential_site_sqm": f"MAX(0,{r('site_sqm')}-{r('objects_plot_sqm')})",
        "footprint_estimate_sqm": (f"MAX(0,{home}-{r('yard_sqm')}"
                                   f"-{home}*{r('driveways_pct')}/100"
                                   f"-{r('surface_parking_sqm')}-{home_setbacks})"),
        # Остаток участка дал бы здание выше предела (без предела — порог) —
        # пятно по пределу.
        # Потолок площади благоустройства в смете — не меньше двора по норме.
        "landscaping_room_sqm": (f"IF({r('site_sqm')}>0,MAX({r('yard_sqm')},{home}"
                                 f"-{home}*{r('driveways_pct')}/100"
                                 f"-{r('surface_parking_sqm')}-{home_setbacks}),0)"),
        "coverage_sqm": (f"IF({r('coverage_pct')}>0,{home}*{r('coverage_pct')}/100,"
                         f"{home})"),
        "footprint_sqm": (f"IF({r('footprint_manual_sqm')}>0,{r('footprint_manual_sqm')},"
                          f"IF(AND({r('site_sqm')}>0,{r('above_gns_sqm')}>0,"
                          f"OR({base}<=0,{r('above_gns_sqm')}"
                          f"/MAX({base},0.000001)>{cap}+0.000000001)),"
                          f"{r('above_gns_sqm')}/{cap},{base}))"),
        # Пятно (по пределу или заданное руками) больше свободного места —
        # двору по норме не хватает этой площади.
        "footprint_shortage_sqm": (f"IF({r('site_sqm')}>0,"
                                   f"MAX(0,{r('footprint_sqm')}-{r('footprint_estimate_sqm')}),0)"),
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
        "over_limit": (f"IF(AND({r('max_storeys')}>0,{r('average_storeys')}>{r('max_storeys')}),"
                       f"\"{YES}\",\"{NO}\")"),
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
        "objects_plot_sqm": float(massing.get("objects_plot_sqm") or 0.0),
        "above_gns_sqm": float(massing.get("residential_gns_sqm",
                                           massing.get("above_gns_sqm")) or 0.0),
        "underground_sqm": float(massing.get("underground_sqm") or 0.0),
        "use_factor": float(massing.get("underground_use_factor") or 0.0),
        "levels_manual": float(int(max(0.0, num("underground_levels")))),
        "markup2_pct": _markup(massing, 2),
        "markup3_pct": _markup(massing, 3),
        "rate_by_hand": YES if massing.get("underground_rate_by_hand") else NO,
        "max_storeys": float(massing.get("max_storeys_allowed") or 0.0),
        "coverage_pct": float(massing.get("coverage_pct") or 0.0),
    }


def _markup(massing: dict, level: int) -> float:
    return float(massing.get(f"underground_level{level}_markup_pct") or 0.0)

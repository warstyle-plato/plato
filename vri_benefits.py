"""Льготы по плате за смену ВРИ в Москве — посчитанные по проекту.

Две льготы, обе срезают плату за смену ВРИ под МКД:

* **за создание МПТ** (1874-ПП) — по каждому нежилому объекту проекта. Правило
  объявлено один раз, в `mpt_calculator`: категория, Кмест по району и
  приоритетным кварталам, ТТК как условие, пороги площади, Кзатр квартала.
  Здесь только сборка: какие объекты проекта, какая у них площадь, где участок.
* **за передачу жилых помещений в собственность города** — площадь передаваемых
  квартир × 190,46 млн ₽ на тыс. м² (константа `uupss_flats` калькулятора
  ГлавАПУ; калькулятор включает её галочкой).

Решение «применить» остаётся за человеком: здесь считается предложение и
рядом с ним — рабочие места, как на листе «МПТ» калькулятора. Экономика
модели от этого модуля не меняется, пока человек не внесёт сумму в льготу.

Льготы считаются всегда, когда в проекте есть нежилые объекты или передача
квартир, а не по флажку: льгота, о которой не сказали, — это деньги, о которых
не узнали (владелец, 06.10.2026).
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Iterable

import mpt_calculator

# Акт, к которому относятся «приложение 3, таблица 1…» в основании Кмест:
# `mpt_calculator` пишет пункт без акта, а в карточке проекта акт нужен.
MPT_ACT = "1874-ПП"
MPT_ACT_TITLE = ("Постановление Правительства Москвы от 31.12.2019 № 1874-ПП «О мерах по "
                 "реализации инвестиционных проектов по созданию мест приложения труда на "
                 "территории города Москвы»")
# Карточка документа на mos.ru (ДЭПР), найдена поиском mos.ru 06.10.2026.
MPT_ACT_URL = "https://www.mos.ru/depr/documents/view/273915220/"
MPT_APPENDIX = "прил. 3 (коэффициенты места расположения МПТ — Кмест)"

# Кзатр калькулятора ГлавАПУ (его код, константы constant_cost и
# index_of_changes_costs_building): база 2026 года 166,23078 × 1,2036 × индекс
# квартала. 1,2036 = 166,23078 / 138,11132 — переход с базы 2025 года на базу
# 2026-го, то есть база умножена на свой же индекс второй раз. Считаем по
# приказу (решение владельца, 06.10.2026), расхождение подписываем.
GLAVAPU_KZATR_EXTRA = 1.2036
GLAVAPU_KZATR_EXTRA_BASIS = "166,23078 / 138,11132 — переход с базы Кзатр 2025 года на базу 2026-го"

# Калькулятор ГлавАПУ: льгота за передачу = площадь (тыс. м²) × uupss_flats.
TRANSFER_RATE_MLN_PER_THS_SQM = 190.46
TRANSFER_SOURCE = ("калькулятор ГлавАПУ: «Передача жилых помещений в собственность города "
                   "Москвы» — площадь, тыс. м² × 190,46 (uupss_flats)")

# Рабочие места — нормы калькулятора ГлавАПУ (лист «МПТ»): НП, м² на одно
# место, с округлением вниз; соцобъекты — мест на 1000 мест / посещений.
JOB_NORM_SQM = {
    "office": 32.0, "retail": 45.0, "hotel": 90.0, "industrial": 90.0,
    "catering": 27.0, "services": 18.0, "leisure": 50.0, "sport": 27.0,
    "built_in": 32.0, "healthcare": 32.0,
}
JOB_PER_1000_PLACES = {"kindergarten": 100.0, "school": 118.0, "clinic": 150.0}
JOB_SOURCE = "нормы калькулятора ГлавАПУ (лист «МПТ»): НП, м² на одно рабочее место"

# Продукт модели → (категория 1874-ПП, норма мест). Явная карта: торговля по
# приложению 3 идёт в графу делового управления, но мест на метр у неё меньше.
PRODUCT_RULE: dict[str, tuple[str | None, str]] = {
    "offices": ("office", "office"),
    "standalone_retail": ("office", "retail"),
    "above_parking": (None, ""),
}
# ФОК / медцентр — назначение задаёт сам объект.
SPORTS_PURPOSE_RULE = {"sport": ("sport", "sport"), "healthcare": ("mededu", "healthcare")}
SOCIAL_KEYS = ("kindergarten", "school", "clinic")
SOCIAL_LABELS = {"kindergarten": "ДОО", "school": "СОШ", "clinic": "Поликлиника"}
BUILT_IN_KEY = "ground_commercial"

# НП из ГНС, когда общей площади у строки нет: коэффициент калькулятора.
NP_OF_GNS = 0.9


def _num(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _sqm(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def territory_of(inputs: dict[str, Any]) -> dict[str, Any]:
    """Район, ТТК и квартал участка — из разбора кадастра, затем из выгрузки.

    Отсутствие — это не «вне ТТК» и не «Москва»: то, чего нет, отдаётся как
    None, и отказ называет недостающее.
    """
    analysis = (inputs or {}).get("_cadastral_analysis") or {}
    territory = analysis.get("territory") or {}
    coefficients = analysis.get("coefficients") or {}
    normalized = ((inputs or {}).get("_glavapu_import") or {}).get("normalized") or {}
    district = str(territory.get("district") or normalized.get("district") or "").strip()
    inside: Any = territory.get("inside_ttc")
    source_ttk = "разбор кадастра (insideTTC)" if inside is not None else ""
    if inside is None and (inputs or {}).get("parking_inside_ttk") not in (None, ""):
        inside = bool(inputs.get("parking_inside_ttk"))
        source_ttk = "вводные проекта: parking_inside_ttk"
    numbers = analysis.get("recognized") or analysis.get("requested") or []
    quarter = str(territory.get("cadastral_quarter") or normalized.get("cadastral_quarter")
                  or "").strip()
    cadastral = str(numbers[0]).strip() if numbers else quarter
    return {"district": district, "inside_ttc": inside, "ttk_source": source_ttk,
            "cadastral": cadastral, "quarter": quarter,
            "district_source": ("разбор кадастра" if territory.get("district")
                                else "выгрузка ГлавАПУ" if normalized.get("district") else "")}


def _np_of(row: dict[str, Any]) -> tuple[float, str]:
    total = _num(row.get("total_area"))
    if total > 0:
        return total, "общая площадь строки ТЭП"
    gns = _num(row.get("gns"))
    return gns * NP_OF_GNS, f"ГНС × {NP_OF_GNS:g} (общей площади у строки нет)"


def compute(inputs: dict[str, Any], tep: dict[str, Any],
            objects: Iterable[dict[str, Any]], *, today: date | None = None) -> dict[str, Any]:
    """Льготы и рабочие места проекта.

    `objects` — нежилые объекты проекта из реестра движка:
    {key, product, label, enabled, purpose}.
    """
    inputs = inputs or {}
    tep = tep or {}
    today = today or date.today()
    region = str(inputs.get("vri_region") or "msk").strip().lower()
    result: dict[str, Any] = {"applicable": region not in ("mo", "область"),
                              "rows": [], "jobs_total": 0, "mpt_mln": 0.0,
                              "transfer_mln": 0.0, "total_mln": 0.0, "notes": []}
    if not result["applicable"]:
        result["reason"] = "льготы 1874-ПП и за передачу квартир городу — московские; проект в области"
        return result
    place = territory_of(inputs)
    result["territory"] = place
    quarter = mpt_calculator.quarter_of(today)
    kzatr = mpt_calculator.kzatr_for_quarter(quarter)
    if kzatr is None:
        kzatr = mpt_calculator.KZATR_BASE
        result["notes"].append(f"Кзатр для {quarter} не опубликован — принят базовый "
                               f"{mpt_calculator.KZATR_BASE} (с 01.01.2026)")
    result["kzatr"] = {"value": kzatr, "quarter": quarter}
    result["act"] = {"short": MPT_ACT, "title": MPT_ACT_TITLE, "url": MPT_ACT_URL}
    glavapu_kzatr = round(kzatr * GLAVAPU_KZATR_EXTRA, 2)
    result["kzatr"]["glavapu"] = glavapu_kzatr
    result["kzatr"]["source"] = mpt_calculator.KZATR_SOURCE

    candidates: list[tuple[str, str, str | None, str, float | None]] = []
    for obj in objects:
        key = str(obj.get("key") or "")
        if obj.get("enabled") is False:
            continue
        product = str(obj.get("product") or key)
        if product == "sports":
            category, norm = SPORTS_PURPOSE_RULE.get(str(obj.get("purpose") or "sport"),
                                                     ("sport", "sport"))
        else:
            category, norm = PRODUCT_RULE.get(product, (None, ""))
        candidates.append((key, str(obj.get("label") or key), category, norm, None))
    built_in = tep.get(BUILT_IN_KEY)
    if isinstance(built_in, dict) and _num(built_in.get("gns")) > 0:
        candidates.append((BUILT_IN_KEY, str(built_in.get("label") or "Коммерция 1 этажа"),
                           None, "built_in", None))
    for key in SOCIAL_KEYS:
        row = tep.get(key)
        if isinstance(row, dict) and _num(row.get("gns")) > 0:
            candidates.append((key, str(row.get("label") or SOCIAL_LABELS[key]), "mededu",
                               "", _num(row.get("units"))))

    for key, label, category, norm, places in candidates:
        row = tep.get(key)
        if not isinstance(row, dict) or _num(row.get("gns")) <= 0:
            continue
        area, area_origin = _np_of(row)
        item: dict[str, Any] = {"key": key, "label": label, "category": category,
                                "category_label": mpt_calculator.CATEGORY_LABELS.get(category or "", ""),
                                "area_sqm": round(area, 1), "area_origin": area_origin,
                                "jobs": 0, "jobs_basis": "", "benefit_mln": 0.0,
                                "potential_mln": 0.0, "kmest": None, "kmest_source": "",
                                "blockers": [], "warnings": []}
        if key in SOCIAL_KEYS:
            per = JOB_PER_1000_PLACES[key]
            if places and places > 0:
                item["jobs"] = math.ceil(places * per / 1000.0)
                item["jobs_basis"] = f"{places:g} мест × {per:g} / 1000 ({JOB_SOURCE})"
            else:
                item["jobs_basis"] = "нет числа мест — рабочие места не посчитаны"
        elif norm:
            per = JOB_NORM_SQM[norm]
            item["jobs"] = int(area // per)
            item["jobs_basis"] = f"{_sqm(area)} м² / {per:g} м² на место ({JOB_SOURCE})"
        if category is None:
            item["blockers"].append(
                "встроенные помещения МКД льготу за МПТ не дают" if key == BUILT_IN_KEY
                else "для этого объекта льгота за МПТ не предусмотрена")
        elif not place["district"]:
            item["blockers"].append("нет района участка — Кмест по приложению 3 не определить "
                                    "(нужен разбор кадастра или выгрузка ГлавАПУ)")
        elif place["inside_ttc"] is None:
            item["blockers"].append("неизвестно положение участка относительно ТТК — "
                                    "условие п. 1.2 не проверить")
        else:
            try:
                got = mpt_calculator.calculate_mpt_benefit(mpt_calculator.MptInput(
                    category=category, district=place["district"], area_sqm=area,
                    cadastral_number=place["cadastral"] if str(place["cadastral"]).startswith("77:") else "",
                    ttk_position="inside" if place["inside_ttc"] else "outside",
                    kzatr=kzatr, kzatr_quarter=quarter), today=today)
            except mpt_calculator.MptCalculationError as exc:
                item["blockers"].append(str(exc))
            else:
                item.update(benefit_mln=round(got.benefit_rub / 1e6, 3),
                            potential_mln=round(got.potential_benefit_rub / 1e6, 3),
                            kmest=got.kmest,
                            kmest_source=f"{MPT_ACT}, " + got.kmest_source.replace(
                                "Приложение 3", MPT_APPENDIX, 1),
                            blockers=list(got.blockers), warnings=list(got.warnings))
        result["rows"].append(item)
        result["jobs_total"] += int(item["jobs"])
        result["mpt_mln"] = round(result["mpt_mln"] + item["benefit_mln"], 3)

    apartments = tep.get("apartments") if isinstance(tep.get("apartments"), dict) else {}
    transfer = _num((apartments or {}).get("transfer"))
    if transfer > 0:
        result["transfer_mln"] = round(transfer / 1000.0 * TRANSFER_RATE_MLN_PER_THS_SQM, 3)
        result["transfer"] = {"area_sqm": transfer, "source": TRANSFER_SOURCE,
                              "area_origin": "ТЭП проекта: «Квартиры», передаваемая площадь"}
    result["total_mln"] = round(result["mpt_mln"] + result["transfer_mln"], 3)

    gross = _num(inputs.get("land_rights_cost_mln"))
    result["gross_mln"] = gross
    if result["total_mln"] > 0 and gross > 0 and result["total_mln"] > gross:
        result["notes"].append("льготы больше платы за ВРИ проекта — к оплате останется ноль, "
                               "остаток льготы не переносится")
    if result["mpt_mln"] > 0:
        ours_text = f"{kzatr:.2f}".replace(".", ",")
        theirs_text = f"{glavapu_kzatr:.2f}".replace(".", ",")
        result["notes"].append(
            f"Кзатр по приказу — {ours_text} ({quarter}). Калькулятор ГлавАПУ берёт "
            f"≈{theirs_text}: ту же базу 2026 года ещё раз умножает на 1,2036 "
            f"({GLAVAPU_KZATR_EXTRA_BASIS}), и его льгота за МПТ выходит на "
            f"{(GLAVAPU_KZATR_EXTRA - 1) * 100:.0f}% выше. Считаем по приказу.")
    if result["total_mln"] > 0:
        result["notes"].append("калькулятор ГлавАПУ срезает льготами только плату за МКД; "
                               "в проекте плата одной суммой — этот потолок здесь не проверен")
    mode = str(inputs.get("vri_relief_mode") or "none").strip().lower()
    current = _num(inputs.get("vri_relief_mln")) if mode == "amount" else None
    result["suggestion"] = {
        "amount_mln": result["total_mln"],
        "applied": current is not None and abs(current - result["total_mln"]) < 0.001,
        "current_mode": mode,
        "current_mln": current,
    }
    return result

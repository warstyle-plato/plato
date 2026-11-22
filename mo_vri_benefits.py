"""Предварительная оценка оснований Ксу* МО; общий расчёт для страницы и модели.

1310-ПП определяет основания, а 1860-ПП в редакции 932-ПП и 933-ПП —
оценку инвестиционных объектов. Денежная оценка не подтверждает право на Ксу*.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

RATE_SOURCE = "https://mosreg.ru/download/document/1366988"
METHOD_SOURCE = "https://mosoblpravo.ru/postanovlenie/2026/08/07/n-932-pp/"
RESETTLEMENT_SOURCE = "https://mosoblpravo.ru/postanovlenie/2025/12/30/n-1865-pp/"
ESTIMATE_NOTE = "Предварительная оценка по основаниям 1310-ПП. Применение Ксу* требует подтверждения обязательств и соглашения с областью."
INVESTMENT_TYPES = {
    "industry": ("Промышленное производство", 100000),
    "light_industrial": ("Лайт-индастриал", 90000),
    "office": ("Административно-деловой объект", 190000),
    "hotel_3": ("Гостиница 3★", 110000),
    "hotel_4": ("Гостиница 4★", 180000),
    "hotel_5": ("Гостиница 5★", 240000),
    "sport_hall": ("Спорт: универсальный зал", 120000),
    "sport_pool": ("Спорт: бассейн", 90000),
    "sport_ice": ("Спорт: ледовая арена", 110000),
    "sport_padel": ("Спорт: падел-корты", 60000),
}
GROUNDS = {"kindergarten": "Детский сад", "school": "Школа",
           "resettlement": "Переселение из аварийного жилья",
           "victims": "Возмещение пострадавшим дольщикам", "investment": "Инвестиционное соглашение"}


def number(value: Any, label: str, *, required: bool = True) -> Decimal | None:
    if value is None or value == "":
        if required:
            raise ValueError(f"Укажите {label}.")
        return None
    if isinstance(value, bool):
        raise ValueError(f"{label}: требуется число.")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"{label}: требуется число.") from None
    if not result.is_finite() or result < 0 or result > Decimal("1e15"):
        raise ValueError(f"{label}: требуется конечное число от 0 до 10¹⁵.")
    return result


def money(value: Decimal) -> float:
    if not value.is_finite() or value > Decimal("1e18"):
        raise ValueError("Расчётная сумма превышает допустимый предел 10¹⁸ ₽; проверьте площадь, ставку и индекс.")
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def catalog() -> dict:
    return {"schema": 1, "grounds": GROUNDS,
            "investment_types": [{"key": k, "label": v[0], "rub_per_sqm": v[1]}
                                 for k, v in INVESTMENT_TYPES.items()],
            "rate_source": RATE_SOURCE, "method_source": METHOD_SOURCE,
            "rates_date": "2026-08-07", "rates_vat": "без НДС"}


def estimate(config: dict, *, inputs: dict, tep: dict, social_needs: dict | None = None,
             market_prices: dict | None = None) -> dict:
    """Отсутствующие данные оставляют строку незавершённой; они не равны нулю."""
    if not isinstance(config, dict) or type(config.get("schema")) is not int or config.get("schema") != 1:
        raise ValueError("Неизвестная версия расчёта льгот 1310-ПП.")
    rows = config.get("rows", [])
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("Укажите не более 100 обязательств.")
    result = {"rows": [], "total_rub": None, "known_subtotal_rub": 0.0,
              "complete": True, "basis": "Предварительная оценка по основаниям 1310-ПП"}
    total = Decimal(0)
    seen: set[str] = set()
    social_seen: set[str] = set()
    for pos, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError("Обязательство должно быть строкой расчёта.")
        identity = str(row.get("id") or "")
        if not identity or identity in seen:
            raise ValueError("У каждого обязательства должен быть отдельный идентификатор.")
        seen.add(identity)
        kind = row.get("kind")
        if not isinstance(kind, str) or kind not in GROUNDS:
            raise ValueError("Неизвестное основание уменьшения платы.")
        out = {"id": identity, "kind": kind, "label": GROUNDS[kind], "amount_rub": None,
               "complete": False, "formula": "", "notes": [], "source": "1310-ПП, п. 5.1"}
        try:
            if kind in ("kindergarten", "school"):
                if kind in social_seen:
                    raise ValueError("Мощность школ или садов указывайте одной суммой: повторный зачёт не допускается.")
                social_seen.add(kind)
                need = number(row.get("required_places"), "нормативную потребность", required=False)
                if need is None:
                    need = number((social_needs or {}).get(kind), "нормативную потребность по РНГП")
                planned = number(row.get("planned_places"), "проектную мощность", required=False)
                if planned is None:
                    planned = number(inputs.get(kind + "_places"), "проектную мощность")
                surplus = max(Decimal(0), planned - need)
                qualifies = planned > need * Decimal("1.1")
                eligible = number(row.get("eligible_places"), "зачётную мощность", required=False)
                if eligible is None:
                    eligible = surplus if qualifies else Decimal(0)
                    out["notes"].append("Предварительно учтена разница проектной и нормативной мощности после проверки порога >10%. Зачётную мощность уточните по ДоКРТ/соглашению.")
                if eligible > surplus or (eligible > 0 and not qualifies):
                    raise ValueError("Зачётная мощность превышает профицит или не выполнен порог более 10%.")
                out.update(required_places=float(need), planned_places=float(planned),
                           surplus_places=float(surplus), eligible_places=float(eligible), qualifies=qualifies)
                if eligible == 0:
                    amount = Decimal(0)
                    out["formula"] = "Превышение не больше 10%: уменьшение по этому основанию не рассчитано"
                else:
                    rate = number(row.get("rub_per_place"), "стоимость одного засчитываемого места", required=False)
                    if rate is None:
                        rate = number(inputs.get(kind + "_cost_mln_per_place"), "стоимость места в проекте") * 1000000
                        out["notes"].append("Ставка взята из бюджета проекта; это оценка, а не нормативная ставка МО для Ксу*.")
                        out["valuation_basis"] = "Ставка строительства из проекта"
                    else:
                        out["valuation_basis"] = str(row.get("valuation_basis") or "Ставка места введена пользователем")
                    amount = eligible * rate
                    out.update(unit_rate_rub=float(rate), formula=f"{eligible} мест × {rate} ₽/место")
            elif kind == "resettlement":
                area = number(row.get("area_sqm"), "аварийную площадь для переселения, м²")
                rate = number(row.get("rub_per_sqm"), "стоимость метра", required=False)
                district = str(row.get("district") or "").strip()
                if rate is None:
                    if not district:
                        raise ValueError("Выберите муниципалитет переселения: по нему определяется цена метра.")
                    price = (market_prices or {}).get(district)
                    if not isinstance(price, dict) or price.get("basis") != "округ":
                        raise ValueError("Для муниципалитета переселения нет точной ставки КЦТ; укажите подтверждённую стоимость метра.")
                    rate = number(price.get("price"), "цену метра по муниципалитету")
                    out["valuation_basis"] = str(price.get("document") or "Справочник КЦТ МО")
                else:
                    out["valuation_basis"] = str(row.get("valuation_basis") or "Стоимость метра введена пользователем")
                amount = area * rate
                out.update(unit_rate_rub=float(rate), formula=f"{area} м² × {rate} ₽/м²", source=RESETTLEMENT_SOURCE)
                out["notes"].append("Предварительная оценка по формуле Со = Об × Цм, п. 24.12 положения КРТ. Применимая к Ксу* стоимость и объём переселения подтверждаются ДоКРТ; эти же метры нельзя повторно зачесть во ВРИ.")
            elif kind == "victims":
                amount = number(row.get("amount_rub"), "сумму возмещения пострадавшим гражданам")
                out["formula"] = "Сумма возмещения по обязательствам ДоКРТ"
                out["notes"].append("Основание относится к предусмотренным п. 5.1(1) пострадавшим гражданам и соглашениям с муниципалитетом, не к любой выплате дольщику.")
            else:
                object_type = row.get("object_type")
                if not isinstance(object_type, str) or object_type not in INVESTMENT_TYPES:
                    raise ValueError("Выберите тип инвестиционного объекта.")
                label, base_rate = INVESTMENT_TYPES[object_type]
                area = number(row.get("area_sqm"), "общую площадь объекта, м²")
                index_mode = row.get("index_mode", "base")
                if index_mode not in ("base", "indexed"):
                    raise ValueError("Выберите уровень цен.")
                index = Decimal(1) if index_mode == "base" else number(row.get("price_index"), "накопленный индекс Ки")
                if index <= 0:
                    raise ValueError("Индекс Ки должен быть больше нуля.")
                if index_mode == "indexed" and not str(row.get("index_basis") or "").strip():
                    raise ValueError("Укажите период и источник накопленного индекса Росстата.")
                uplift = row.get("municipality_uplift", False)
                if not isinstance(uplift, bool):
                    raise ValueError("Признак повышающего коэффициента должен быть логическим.")
                factor = Decimal("1.2") if uplift else Decimal(1)
                if uplift and not str(row.get("uplift_basis") or "").strip():
                    raise ValueError("Укажите основание включения муниципалитета в перечень для коэффициента 1,2.")
                amount = area * base_rate * index * factor
                out.update(label=label, unit_rate_rub=base_rate, price_index=float(index),
                           municipality_factor=float(factor), source=RATE_SOURCE,
                           formula=f"{area} м² × {base_rate} ₽/м² × {index} × {factor}",
                           valuation_basis="933-ПП, без НДС; 1860-ПП, п. 9 в редакции 932-ПП")
                out["notes"].append("Уровень цен 07.08.2026, без индексации" if index_mode == "base"
                                    else "Индекс Ки: " + str(row["index_basis"]))
                out["notes"].append("Статус инвестиционного проекта и соответствие объекта требованиям соглашения проверяются отдельно.")
            out.update(amount_rub=money(amount), complete=True)
            total += Decimal(str(out["amount_rub"]))
        except ValueError as error:
            out["error"] = str(error)
            result["complete"] = False
        result["rows"].append(out)
    result["known_subtotal_rub"] = money(total)
    result["total_rub"] = money(total) if result["complete"] else None
    result["has_resettlement"] = any(row["kind"] == "resettlement" for row in result["rows"])
    return result

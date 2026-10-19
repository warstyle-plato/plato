"""Регион проекта — поле `vri_region`, и отвечает о нём ОДИН предикат.

Прежде поле знало только Москву и область, и любое другое значение читалось
как Москва: участок из Екатеринбурга молча получал московскую рассрочку платы
за ВРИ, льготы 1874-ПП и парковку по 2118-ПП. Третий регион — «другой»: норм
его у нас нет, и московские правила к нему не применяются (решение владельца
19.10.2026). Пустое поле — умолчание вводных, Москва; непонятное значение — не
Москва: чужие нормы хуже, чем честное «норм нет».

Движок читает этот модуль через `project_region` (engine/inputs.py), страница —
через `classRegion`; корневые модули (льготы ВРИ, презентация) — отсюда же.
"""

from __future__ import annotations

from typing import Any

MOSCOW = "msk"
MOSCOW_OBLAST = "mo"
OTHER = "other"

LABELS: dict[str, str] = {
    MOSCOW: "Москва", MOSCOW_OBLAST: "Московская область", OTHER: "Другой регион"}

# Кадастровый округ (первые две цифры номера) по региону. Новая Москва — НАО и
# ТАО — носит областные номера 50:21, 50:26, 50:27, поэтому 50 само по себе
# Москву от области не отличает; а вот чужой номер — точно не Москва и не
# область.
CADASTRAL_DISTRICTS: frozenset[str] = frozenset({"77", "50"})

_ALIASES: dict[str, str] = {
    "msk": MOSCOW, "77": MOSCOW, "москва": MOSCOW, "moscow": MOSCOW,
    "mo": MOSCOW_OBLAST, "50": MOSCOW_OBLAST, "мо": MOSCOW_OBLAST,
    "область": MOSCOW_OBLAST, "московская область": MOSCOW_OBLAST,
    "подмосковье": MOSCOW_OBLAST, "мособласть": MOSCOW_OBLAST, "region": MOSCOW_OBLAST,
    "other": OTHER, "другой": OTHER, "другой регион": OTHER,
}


def region_code(value: Any) -> str:
    """Значение поля `vri_region` → `msk`, `mo` или `other`."""
    raw = str(value or "").strip().lower()
    if not raw:
        return MOSCOW
    return _ALIASES.get(raw, OTHER)


def region_of(inputs: dict[str, Any] | None) -> str:
    return region_code((inputs or {}).get("vri_region"))


def outside_moscow_region(cadastral_number: Any) -> bool:
    """Номер из округа не Москвы и не области — проект «другого региона»."""
    district = str(cadastral_number or "").strip()[:3]
    return len(district) == 3 and district[2] == ":" and district[:2].isdigit() \
        and district[:2] not in CADASTRAL_DISTRICTS

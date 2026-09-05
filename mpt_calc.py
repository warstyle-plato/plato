from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal

K_ZATR_2026 = 166.23078
RULESET_REVIEWED_AT = date(2026, 8, 8)
REGULATION = "Постановление Правительства Москвы от 31.12.2019 № 1874-ПП"
K_ZATR_SOURCE = "Приказ ДИПП Москвы от 10.03.2026 № ДИПП-ПР-33/26"

Scenario = Literal["new", "reconstruction", "ons"]


@dataclass(frozen=True)
class MPTInput:
    mpt_area_sqm: float
    k_location: float
    k_term: float = 1.0
    scenario: Scenario = "new"
    readiness_percent: float = 0.0
    excluded_area_sqm: float = 0.0
    object_type: str = ""


@dataclass(frozen=True)
class MPTResult:
    benefit_rub: float
    eligible_area_sqm: float
    benefit_per_sqm_rub: float
    k_zatr: float
    k_location: float
    k_term: float
    ons_factor: float
    calculation_date: str
    formula: str
    warnings: tuple[str, ...]
    regulation: str = REGULATION
    k_zatr_source: str = K_ZATR_SOURCE
    ruleset_reviewed_at: str = RULESET_REVIEWED_AT.isoformat()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _validate(inp: MPTInput) -> None:
    if inp.mpt_area_sqm <= 0:
        raise ValueError("Площадь МПТ должна быть больше нуля")
    if inp.excluded_area_sqm < 0:
        raise ValueError("Исключаемая площадь не может быть отрицательной")
    if inp.excluded_area_sqm > inp.mpt_area_sqm:
        raise ValueError("Исключаемая площадь не может превышать площадь МПТ")
    if not 0 <= inp.k_location <= 1:
        raise ValueError("Кмест должен быть в диапазоне от 0 до 1")
    if inp.k_term not in {1.0, 1.05, 1.1}:
        raise ValueError("Ксрок должен быть 1,00; 1,05 или 1,10")
    if inp.scenario not in {"new", "reconstruction", "ons"}:
        raise ValueError("Неизвестный сценарий расчёта")
    if not 0 <= inp.readiness_percent <= 100:
        raise ValueError("Готовность ОНС должна быть от 0 до 100%")
    if inp.scenario != "ons" and inp.readiness_percent:
        raise ValueError("Коэффициент готовности применяется только к ОНС")


def calculate_mpt_benefit(inp: MPTInput, *, calculation_date: date | None = None) -> MPTResult:
    """Calculate the MPT benefit under Moscow Government Decree No. 1874-PP.

    `mpt_area_sqm` is the total MPT area used in the formula. For reconstruction,
    pass the increase in total area. `excluded_area_sqm` is intentionally explicit:
    location/function-specific eligibility rules are not guessed by the engine.
    """
    _validate(inp)

    eligible_area = inp.mpt_area_sqm - inp.excluded_area_sqm
    if eligible_area <= 0:
        raise ValueError("Расчётная площадь МПТ должна быть больше нуля")

    ons_factor = 1.0
    if inp.scenario == "ons":
        ons_factor = 1.0 - inp.readiness_percent / 100.0

    benefit_per_sqm = 1000.0 * K_ZATR_2026 * inp.k_location * inp.k_term * ons_factor
    benefit = eligible_area * benefit_per_sqm

    warnings: list[str] = []
    if inp.k_location == 0:
        warnings.append("Кмест = 0: расчётная льгота равна нулю.")
    if inp.excluded_area_sqm:
        warnings.append(
            "Из расчёта исключена площадь, заданная пользователем. "
            "Проверьте её состав по действующей редакции 1874-ПП."
        )
    if inp.scenario == "reconstruction":
        warnings.append("Для реконструкции в площадь МПТ должен передаваться только прирост общей площади.")
    if inp.scenario == "ons":
        warnings.append("Для ОНС готовность должна подтверждаться сведениями ЕГРН.")

    formula = "1000 × Sмпт × Кзатр × Кмест × Ксрок"
    if inp.scenario == "ons":
        formula += " × (1 − Кгт/100)"

    return MPTResult(
        benefit_rub=round(benefit, 2),
        eligible_area_sqm=round(eligible_area, 2),
        benefit_per_sqm_rub=round(benefit_per_sqm, 2),
        k_zatr=K_ZATR_2026,
        k_location=inp.k_location,
        k_term=inp.k_term,
        ons_factor=round(ons_factor, 6),
        calculation_date=(calculation_date or date.today()).isoformat(),
        formula=formula,
        warnings=tuple(warnings),
    )

"""Ground lease: one source for planning inputs, accruals and disclosures.

Actual/Actual within each lease/regime year is a planning convention, not a
statutory payment calendar. No missing input is converted to a zero rate.
"""
from __future__ import annotations

import calendar
import math
import re
from collections import defaultdict
from datetime import date
from typing import Any

import project_types
import project_regions

PRESETS = {
    "msk_mkd_3_2": {
        "label": "Москва: обычный режим п. 3.2 (подтверждён договором)",
        "region": "msk", "rates": [1.5, 1.5, 3, 5, 7, 8], "tail_rate_pct": 10,
        "short_source": "273-ПП, п. 3.2",
        "source": "273-ПП, пп. 3.1, 3.2, 3.2.1, 3.2.3; редакция 25.03.2026",
        "url": "https://meganorm.ru/mega_doc/dop1/89/postanovlenie_pravitelstva_moskvy_ot_20_02_2013_N_99-pp_red/0/postanovlenie_pravitelstva_moskvy_ot_25_04_2006_N_273-pp_red.html",
        "condition": "Режим пп. 3.1–3.2 подтверждён договором/допсоглашением. Не общий тариф для торгов, КРТ и льготных договоров.",
    },
    "msk_mkd_arch_confirmed": {
        "label": "Москва: подтверждены архитектурные условия п. 3.5(2)",
        "region": "msk", "rates": [1.35, 1.35, 2.7, 4.5, 6.3, 7.2], "tail_rate_pct": 9,
        "short_source": "273-ПП, п. 3.5(2)",
        "source": "273-ПП, п. 3.5(2), требования 305-ПП; редакция 25.03.2026",
        "url": "https://meganorm.ru/mega_doc/dop1/89/postanovlenie_pravitelstva_moskvy_ot_20_02_2013_N_99-pp_red/0/postanovlenie_pravitelstva_moskvy_ot_25_04_2006_N_273-pp_red.html",
        "condition": "Требования 305-ПП и обращение в ДГИ подтверждены. Не применяется только по названию проекта.",
    },
    "mo_housing_new_2026": {
        "label": "Подмосковье: новый обычный договор под жильё (ст. 14)",
        "region": "mo", "rates": [6], "tail_rate_pct": 6,
        "short_source": "23/96-ОЗ, ст. 14",
        "source": "23/96-ОЗ, ст. 14 ч. 5 и приложение, редакция 15.06.2026 (256/2025-ОЗ)",
        "url": "https://meganorm.ru/mega_doc/dop1/99/postanovlenie_administratsii_munitsipalnogo_obrazovaniya/0/zakon_moskovskoy_oblasti_ot_07_06_1996_N_23_96-oz_red_ot_15.html",
        "condition": "Договор после 01.01.2026, областная или неразграниченная земля, без торгов и вне специальных правил КРТ. Подтверждён обычный жилой ВРИ без более высокой ставки смешанного использования; исключены специальные случаи граждан (ИЖС/сад). Старые и муниципальные договоры — вручную. Проверено по сводному тексту указанной редакции.",
    },
}
CONVENTION = "Плановое начисление по фактическим дням: Москва и ручной режим — год аренды; МО — календарный год. Это не установленный законом график оплаты."


def page_spec() -> dict[str, Any]:
    return {"presets": PRESETS, "convention": CONVENTION}


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def excluded_input_vat_articles(result: dict[str, Any]) -> tuple[str, ...]:
    """Land tax has no input VAT. Unclassified land-use costs cannot prove
    a deduction; that conservative exclusion is disclosed by the importer.
    """
    return ("land_tax", "land_use_other") + (() if result.get("vat_treatment") == "taxable" else ("land_rent",))


def construction_cutoff(housing_rve: date, object_dates: dict[str, date], *, pure_nonres: bool = False) -> date:
    """Common-parcel assumption, not a change of the housing PF/RVE date."""
    dates = list(object_dates.values())
    return max(dates) if pure_nonres and dates else max([housing_rve, *dates])


def qualify_scope(result: dict[str, Any], social_dates: dict[str, date]) -> dict[str, Any]:
    """A social programme does not prove that its other parcel is leased."""
    result["unlinked_social_dates"] = {key: value.isoformat() for key, value in social_dates.items()}
    result["scope_complete"] = True
    cutoff = _date(result.get("rve"))
    termination = _date(result.get("termination_date"))
    late = cutoff and any(value > cutoff for value in social_dates.values())
    if (late and result.get("status") != "not_applicable" and result.get("cutoff_origin") != "manual"
            and not (termination and termination <= cutoff)):
        reason = "Уточните охват арендуемой земли: поздние соцобъекты могут находиться на другом участке. Можно указать подтверждённую дату последнего ввода на этой земле."
        result["scope_complete"] = False
        result["financial_complete"] = False
        result["financial_missing"] = [*result.get("financial_missing", []), reason]
        result["financial_missing_codes"] = list(dict.fromkeys([*result.get("financial_missing_codes", []), "scope"]))
        result["status"] = "preliminary" if result.get("complete") else "incomplete"
    return result


def _number(raw: Any) -> float | None:
    if raw is None or raw == "" or isinstance(raw, bool):
        return None
    try:
        value = float(str(raw).replace(",", "."))
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _date(raw: Any) -> date | None:
    try:
        return raw if isinstance(raw, date) else date.fromisoformat(str(raw))
    except (ValueError, TypeError):
        return None


def _anniversary(anchor: date, offset: int) -> date:
    year = anchor.year + offset
    return date(year, anchor.month, min(anchor.day, calendar.monthrange(year, anchor.month)[1]))


def _next_month(day: date) -> date:
    return date(day.year + (day.month == 12), day.month % 12 + 1, 1)


def _add_months(anchor: date, offset: int) -> date:
    month = anchor.month - 1 + offset
    year = anchor.year + month // 12
    return date(year, month % 12 + 1, min(anchor.day, calendar.monthrange(year, month % 12 + 1)[1]))


def _payment_schedule(raw: Any, start: date, end: date, amount: float) -> tuple[dict[date, float], list[str]]:
    """Existing site's amount/share@month pattern, strictly reconciled.

    No normalisation, silent residual or shifting outside dates. The shared
    UI schedule editor displays its offsets as dates from project_start.
    """
    schedule: dict[date, float] = defaultdict(float)
    if not isinstance(raw, str) or not raw.strip():
        return {}, ["Не задан ручной график оплаты аренды."]
    parts = [part.strip() for part in raw.split(";") if part.strip()]
    if len(parts) > 500:
        return {}, ["В графике аренды больше 500 платежей."]
    kinds = set()
    parsed = []
    for part in parts:
        found = re.fullmatch(r"([0-9]+(?:[.,][0-9]+)?)\s*(%)?\s*@\s*([0-9]+)", part)
        if not found:
            return {}, ["График аренды не распознан: ожидаются суммы или доли и даты из редактора."]
        value, percent, offset = found.groups()
        kinds.add(bool(percent))
        if int(offset) > 1200:
            return {}, ["Дата платежа аренды выходит за допустимый горизонт."]
        when = _add_months(start, int(offset))
        if not start <= when < end:
            return {}, ["Платёж аренды находится за расчётным горизонтом; дата не перенесена автоматически."]
        parsed.append((when, float(value.replace(",", ".")), bool(percent)))
    if len(kinds) != 1:
        return {}, ["Нельзя смешивать суммы и доли в графике аренды."]
    is_percent = True in kinds
    wanted = 100 if is_percent else amount / 1e6
    if abs(sum(value for _, value, _ in parsed) - wanted) > (1e-7 if is_percent else 0.0000005):
        return {}, ["График оплаты аренды не сходится с рассчитанной потребностью; суммы не подогнаны."]
    for when, value, _ in parsed:
        schedule[when.replace(day=1)] += amount * value / 100 if is_percent else value * 1e6
    return dict(schedule), []


def build(inputs: dict[str, Any], project_start: date, rve: date,
          project_end: date | None = None) -> dict[str, Any]:
    """Known accrual parts are usable; unknown total is always None.

    All returned date keys are ISO strings, suitable for saved/public API.
    The engine converts only monthly keys to date. Post-RVE unknowns are
    separate from completeness of the owner's construction-period question.
    """
    x = inputs or {}
    end = project_end or rve
    derived_rve = rve
    raw_manual_cutoff = x.get("land_rent_manual_cutoff")
    manual_cutoff = _date(raw_manual_cutoff) if raw_manual_cutoff else None
    invalid_manual_cutoff = bool(raw_manual_cutoff) and (manual_cutoff is None or not 1900 <= manual_cutoff.year <= 2200)
    if manual_cutoff is not None and not invalid_manual_cutoff:
        rve = manual_cutoff
        end = max(end, rve)
    mode = str(x.get("land_rent_mode") or "unspecified")
    out: dict[str, Any] = {
        "schema_version": 1, "status": "incomplete", "complete": False,
        "financial_complete": False, "total": None, "known_total": 0.0,
        "construction_total": None, "cash_total": 0.0, "monthly": {}, "accrual_monthly": {},
        "annual_rows": [], "missing": [], "notes": [], "financial_missing": [], "financial_missing_codes": ["inputs"], "source": "",
        "convention": CONVENTION, "cash_schedule_estimated": True,
        "scope": "До сценарного ввода; после ввода — отдельный режим",
        "scope_complete": True,
        "after_rve_mode": str(x.get("land_rent_after_rve_mode") or "unknown"),
        "base_origin": _mapping(x.get("_field_origin")).get("inputs.land_rent_cadastral_mln"),
        "mode": mode, "project_start": project_start.isoformat(),
        "housing_applicable": not project_types.without_housing(x),
        "region": project_regions.region_of(x),
        "region_origin": _mapping(x.get("_field_origin")).get("inputs.vri_region"),
        "rve": rve.isoformat(), "project_end": end.isoformat(),
        "derived_rve": derived_rve.isoformat(), "cutoff_origin": "manual" if manual_cutoff else "derived",
        "cutoff_basis": "Подтверждённая пользователем дата последнего ввода на арендуемой земле" if manual_cutoff else "Последний ввод основных объектов общего участка",
        "cutoff_field_origin": _mapping(x.get("_field_origin")).get("inputs.land_rent_manual_cutoff"),
    }
    missing = out["missing"]
    if mode == "not_applicable" or x.get("land_right", "ownership") == "ownership":
        out.update(status="not_applicable", complete=True, financial_complete=True,
                   total=0.0, construction_total=0.0, cash_schedule_estimated=False,
                   source="Аренда не применяется: выбранное право собственности" if mode == "unspecified" else "По выбранному пользователем режиму аренда не применяется", financial_missing_codes=[])
        return out
    if mode == "unspecified":
        missing.append("Для арендуемой земли не заданы кадастровая база, дата и годовые ставки аренды.")
        return out
    if invalid_manual_cutoff:
        missing.append("Не распознана подтверждённая дата последнего ввода на арендуемой земле.")
    if mode not in ("manual", *PRESETS):
        missing.append("Режим аренды не распознан. Выберите ставки по договору.")
        return out
    preset = PRESETS.get(mode)
    if preset:
        if not out["housing_applicable"]:
            missing.append("Жилищная предустановка аренды не применяется к гостинице или нежилому проекту. Задайте условия аренды по договору вручную.")
        if x.get("land_rent_preset_confirmed") is not True:
            missing.append("Подтвердите применимость выбранного норматива к договору.")
        if out["region"] != preset["region"]:
            missing.append("Выбранный норматив аренды не соответствует региону проекта.")
        if preset["region"] == "msk" and (x.get("_krt_site") or x.get("land_rent_grant_basis") in ("auction", "krt", "special")):
            missing.append("Для КРТ, аукциона или специального договора задайте подтверждённые ставки вручную; обычный московский режим автоматически не применяется.")
        if mode == "mo_housing_new_2026":
            contract_date = _date(x.get("land_rent_contract_date"))
            if contract_date is None or contract_date <= date(2026, 1, 1):
                missing.append("Для нового режима МО нужен договор после 01.01.2026; иной договор считайте по его условиям.")
            if x.get("land_rent_public_scope") not in ("regional", "undelimited"):
                missing.append("Режим МО применим только к областной или неразграниченной земле.")
            if x.get("_krt_site") or x.get("land_rent_grant_basis") != "ordinary_nonauction":
                missing.append("Специальный КРТ или аукцион не наследует обычную ставку МО.")
            if x.get("land_rent_mo_cadastral_unchanged") is not True:
                missing.append("Для этого режима МО подтвердите постоянную кадастровую стоимость в сценарии. Её изменение требует отдельного расчёта по основанию изменения.")
        out["source"] = preset["source"]
        out["source_url"] = preset["url"]
    else:
        out["source"] = str(x.get("land_rent_source") or "Ставки введены по договору пользователем")
    vat = "public_exempt" if preset else str(x.get("land_rent_vat_treatment") or "unknown")
    out["vat_treatment"] = vat
    tax_unknown = vat not in ("public_exempt", "taxable")
    if tax_unknown:
        out["notes"].append("Уточните НДС по договору аренды; входной вычет пока не включён.")
    base_kind = str(x.get("land_rent_base_kind") or "cadastral_percent")
    out["base_kind"] = base_kind
    out["base_origin"] = _mapping(x.get("_field_origin")).get("inputs.land_rent_cadastral_mln" if base_kind == "cadastral_percent" else "inputs.land_rent_annual_base_mln")
    base = _number(x.get("land_rent_cadastral_mln" if base_kind == "cadastral_percent" else "land_rent_annual_base_mln"))
    if base_kind not in ("cadastral_percent", "annual_amount") or (preset and base_kind != "cadastral_percent"):
        missing.append("Для выбранного режима не подтверждена база аренды.")
    if base is None or base <= 0:
        missing.append("Укажите стоимость именно арендуемой земли" + (" (кадастровую)." if base_kind == "cadastral_percent" else " — годовую сумму по договору."))
    anchor = _date(x.get("land_rent_regime_start"))
    if anchor is None:
        missing.append("Укажите начало срока аренды или строительного режима из договора/допсоглашения.")
    elif not 1900 <= anchor.year <= 2200 or (end.year - anchor.year) > 100:
        missing.append("Дата режима аренды вне поддерживаемого столетнего горизонта.")
    if (project_start > rve and manual_cutoff is None) or rve > end:
        missing.append("Даты проекта, ввода и горизонта аренды не согласованы.")
    relation = str(x.get("land_rent_first_year_relation") or "regular_only")
    if relation not in ("regular_only", "full_year_in_vri"):
        missing.append("Не распознан учёт первого года аренды.")
    if relation == "full_year_in_vri" and x.get("land_rent_first_year_confirmed") is not True:
        missing.append("Исключить первый год можно только после подтверждения, что вся его аренда уже включена в ВРИ.")
    termination_raw = x.get("land_rent_termination_date")
    termination = _date(termination_raw) if termination_raw else None
    out["termination_date"] = termination.isoformat() if termination else None
    if termination_raw and termination is None:
        missing.append("Не распознана подтверждённая дата прекращения аренды.")
    if missing:
        return out
    assert anchor is not None and base is not None
    out["financial_missing_codes"] = []
    rates: dict[int, float | None] = {}
    if preset:
        rates = {i + 1: float(value) for i, value in enumerate(preset["rates"])}
        tail = "preset"
    else:
        raw_rates = x.get("land_rent_rates") or []
        if not isinstance(raw_rates, list) or len(raw_rates) > 100:
            missing.append("Не распознана таблица годовых ставок аренды.")
            return out
        for row in raw_rates:
            if not isinstance(row, dict) or isinstance(row.get("year"), bool):
                missing.append("В таблице аренды не указан год режима.")
                continue
            year = _number(row.get("year"))
            if year is None or not year.is_integer() or not 1 <= year <= 100 or int(year) in rates:
                missing.append("Годы аренды должны быть целыми, без повторов, от 1 до 100.")
                if year is not None and year.is_integer() and int(year) in rates:
                    rates[int(year)] = None
                continue
            rates[int(year)] = _number(row.get("rate_pct"))
        tail = str(x.get("land_rent_tail_rule") or "unknown")
        if tail not in ("unknown", "repeat_last"):
            missing.append("Выберите правило продолжения ставок после последнего заданного года.")
    accrual: dict[date, float] = defaultdict(float)
    indices: dict[int, float | None] = {}
    if mode == "mo_housing_new_2026":
        raw_indices = x.get("land_rent_calendar_indices") or []
        if not isinstance(raw_indices, list) or len(raw_indices) > 100:
            missing.append("Не распознана таблица календарных индексов МО.")
            raw_indices = []
        for entry in raw_indices:
            if not isinstance(entry, dict):
                missing.append("Не распознана строка календарного индекса МО.")
                continue
            iy = _number(entry.get("year"))
            if iy is None or not iy.is_integer() or not 1900 <= iy <= 2200 or int(iy) in indices:
                missing.append("Календарные годы индексации МО должны быть целыми и без повторов.")
                if iy is not None and iy.is_integer() and int(iy) in indices:
                    indices[int(iy)] = None
                continue
            indices[int(iy)] = _number(entry.get("index_pct"))
        out["calendar_indices"] = [dict(year=y, index_pct=value) for y, value in sorted(indices.items())]
        out["indices_origin"] = x.get("land_rent_indices_origin")
        out["notes"].append("МО: базовый Кд 6%; индексация с 1 января года после заключения договора. Кадастровая стоимость в этом сценарии постоянна.")
        origins = _mapping(x.get("land_rent_indices_origin"))
        assumed = [y for y, value in sorted(indices.items()) if value is not None and
                   (y > date.today().year or _mapping(origins.get(str(y)) or origins.get(y)).get("source") == "forecast")]
        out["assumptions"] = (["Индексы на " + ", ".join(map(str, assumed)) + " гг. заданы пользователем для сценария; это не подтверждение будущего нормативного размера аренды."] if assumed else [])
        out["notes"].extend(out["assumptions"])

    def calendar_factor(year: int) -> float | None:
        if mode != "mo_housing_new_2026":
            return 1.0
        factor = 1.0
        for iy in range(contract_date.year + 1, year + 1):
            index = indices.get(iy)
            if index is None:
                reason = f"Не задан календарный индекс МО на {iy} год."
                if reason not in missing:
                    missing.append(reason)
                return None
            factor *= 1 + index / 100
        return factor

    construction_known = 0.0
    boundary = min(rve, termination) if termination else rve
    for offset in range(max(0, project_start.year - anchor.year - 1), max(0, boundary.year - anchor.year) + 1):
        year = offset + 1
        year_start, year_end = _anniversary(anchor, offset), _anniversary(anchor, offset + 1)
        lo, hi = max(project_start, year_start), min(boundary, year_end)
        if lo >= hi:
            continue
        rate = rates.get(year)
        rate_source = "Ставка договора" if not preset else out["source"]
        if year not in rates and preset:
            rate = float(preset["tail_rate_pct"])
            rate_source += "; продолжение после последнего года таблицы"
        elif year not in rates and tail == "repeat_last" and rates and year > max(rates):
            rate = rates[max(rates)]
            rate_source = "Явное правило: продолжать последнюю ставку"
        included = relation == "full_year_in_vri" and year == 1
        annual = None if rate is None else base * 1e6 * rate / 100
        row = {"year": year, "start": year_start.isoformat(), "end": year_end.isoformat(),
               "overlap_start": lo.isoformat(), "overlap_end": hi.isoformat(),
               "days": (hi - lo).days, "year_days": (year_end - year_start).days,
               "rate_pct": rate, "annual_amount": annual, "amount": None,
               "included_in_vri": included, "source": rate_source}
        if included:
            row["amount"] = 0.0
        elif annual is None:
            missing.append(f"Не задана ставка за {year}-й год аренды.")
        else:
            row["amount"] = 0.0
            row["known_amount"] = 0.0
            row["calendar_segments"] = []
            month = lo
            while month < hi:
                finish = min(hi, _next_month(month))
                factor = calendar_factor(month.year)
                denominator = (366 if calendar.isleap(month.year) else 365) if mode == "mo_housing_new_2026" else (year_end-year_start).days
                amount = None if factor is None else annual * factor * (finish - month).days / denominator
                if amount is None:
                    row["amount"] = None
                else:
                    accrual[month.replace(day=1)] += amount
                    construction_known += amount
                    row["known_amount"] += amount
                    if row["amount"] is not None:
                        row["amount"] += amount
                if mode == "mo_housing_new_2026":
                    row["calendar_segments"].append({"start": month.isoformat(), "end": finish.isoformat(),
                        "calendar_year": month.year, "index_factor": factor, "amount": amount})
                month = finish
        out["annual_rows"].append(row)
    out["construction_total"] = None if missing else construction_known
    premium_required = bool(preset and preset["region"] == "msk" and any(row["year"] == 1 for row in out["annual_rows"]))
    premium_status = str(x.get("land_rent_premium_status") or "unknown")
    premium_source = str(x.get("land_rent_premium_source") or "").strip()
    out["premium"] = {"required": premium_required, "status": premium_status,
                      "source": premium_source, "vri_amount_mln": _number(x.get("land_rights_cost_mln"))}
    if premium_required:
        if premium_status == "in_vri":
            if not premium_source or not (_number(x.get("land_rights_cost_mln")) or 0) > 0:
                out["financial_missing"].append("Подтвердите состав положительной суммы ВРИ: включена ли в неё повышенная часть первого года по приложению 8 к 273-ПП.")
        elif premium_status == "not_applicable" and premium_source:
            pass
        else:
            out["financial_missing"].append("Обычная аренда первого года рассчитана. Повышенная часть по приложению 8 к 273-ПП требует отдельного подтверждения состава ВРИ или основания неприменения.")
        if out["financial_missing"]:
            out["financial_missing_codes"].append("premium")
    after_unknown = False
    after_start = max(rve, project_start, anchor)
    after_end = min(end, termination) if termination else end
    if after_start < after_end:
        after_unknown = True
        out["notes"].append("Аренда после ввода требует отдельного расчёта и не считается прекращённой по одной дате ввода.")
    out["post_rve_unknown"] = after_unknown
    out["complete"] = not missing
    out["known_total"] = sum(accrual.values())
    out["total"] = out["known_total"] if out["complete"] and not after_unknown else None
    out["accrual_monthly"] = {m.isoformat(): value for m, value in sorted(accrual.items())}
    payments = dict(accrual)
    payment_mode = str(x.get("land_rent_payment_mode") or "monthly_estimate")
    if payment_mode == "manual":
        if out["construction_total"] is None:
            out["notes"].append("Ручной график оплаты не применён: строительная аренда ещё не определена полностью.")
        else:
            manual, errors = _payment_schedule(x.get("land_rent_payment_schedule"), project_start, end, out["known_total"])
            if errors:
                out["notes"].extend(errors)
            else:
                payments = manual
                out["cash_schedule_estimated"] = False
    elif payment_mode != "monthly_estimate":
        out["notes"].append("Не распознан порядок оплаты аренды; показано плановое начисление.")
    out["monthly"] = {m.isoformat(): value for m, value in sorted(payments.items())}
    out["cash_total"] = sum(payments.values())
    out["financial_complete"] = out["complete"] and not after_unknown and not out["cash_schedule_estimated"] and not tax_unknown and not out["financial_missing"]
    out["financial_missing_codes"] = list(dict.fromkeys([*out["financial_missing_codes"],
        *(["inputs"] if missing else []), *(["post_rve"] if after_unknown else []),
        *(["vat"] if tax_unknown else []), *(["payments"] if out["cash_schedule_estimated"] else [])]))
    out["status"] = "complete" if out["financial_complete"] else "preliminary" if out["complete"] else "incomplete"
    if out["cash_schedule_estimated"]:
        out["notes"].append("Плановое начисление; сроки оплаты уточняются по договору. Для Москвы первый год может оплачиваться единовременно по п. 3.2.2.")
    return out


def disclosure(result: dict[str, Any]) -> str:
    """One concise qualifier for UI, documents and investment conclusions."""
    if result.get("financial_complete"):
        return ""
    if result.get("financial_missing"):
        return "Предварительный расчёт: " + str(result["financial_missing"][0])
    missing = result.get("missing") or []
    if missing:
        return "Предварительный расчёт: аренда земли не определена полностью. " + str(missing[0])
    if result.get("post_rve_unknown"):
        return "Предварительный расчёт: аренда земли после ввода требует отдельного расчёта."
    if result.get("vat_treatment") not in ("public_exempt", "taxable"):
        return "Предварительный расчёт: налоговые условия аренды земли не подтверждены."
    return "Предварительный расчёт: аренда земли включена по плановому начислению; уточните сроки оплаты по договору."

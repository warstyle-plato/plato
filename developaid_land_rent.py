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


def phase_land_shares(phases: list[dict[str, Any]], gns: list[float]) -> tuple[list[float], str]:
    """Share of the leased parcel under each queue: its land area when every
    queue has one, otherwise its floor area (GNS). Equal shares only when
    neither is known; the basis is returned for the disclosure."""
    areas = [_number((cfg or {}).get("site_area_ha")) for cfg in phases]
    if areas and all(a is not None and a > 0 for a in areas):
        total = sum(areas)
        return [a / total for a in areas], "area"
    total = sum(max(0.0, float(g or 0.0)) for g in gns)
    if len(gns) == len(phases) and total > 0:
        return [max(0.0, float(g or 0.0)) / total for g in gns], "gns"
    return [1 / len(phases)] * len(phases), "equal"


PHASE_SHARE_BASIS = {
    "area": "пропорционально площади участка каждой очереди",
    "gns": "пропорционально площади зданий каждой очереди, потому что площадь участка очередей не указана",
    "equal": "поровну, потому что не известны ни площадь участка очередей, ни площадь их зданий",
}


def phase_release(rves: list[date], cutoff: date) -> list[date]:
    """Date each queue's land leaves the lease: its commissioning. The last
    queue holds the parcel until the common cutoff (objects on the parcel
    may finish later); the workbook repeats this rule cell by cell."""
    latest = max(rves)
    return [cutoff if r == latest else min(r, cutoff) for r in rves]


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


def vri_premium(x: dict[str, Any]) -> dict[str, Any]:
    """Whether the first-year raised part (273-PP app. 8) is inside the VRI fee.

    Our VRI fee — the GlavAPU import or the calculation for the parcel — is
    built from the app. 8 rent coefficient and base costs, so such a fee
    already contains that part. Only a fee typed by hand needs the owner's
    answer; a free-text "source" is no longer asked.
    """
    fee = _number(x.get("land_rights_cost_mln")) or 0.0
    origin = _mapping(_mapping(x.get("_field_origin")).get("inputs.land_rights_cost_mln"))
    typed = origin.get("source") == "manual"
    if fee > 0 and not typed:
        where = "из расчёта ГлавАПУ" if origin.get("source") == "glavapu" else "рассчитана по участку"
        return {"status": "in_vri", "derived": True,
                "source": f"Плата за смену ВРИ {where} по ставкам приложения 8 к 273-ПП; повышенная часть первого года аренды в неё уже входит."}
    status = str(x.get("land_rent_premium_status") or "unknown")
    if status == "in_vri" and fee > 0:
        return {"status": status, "derived": False,
                "source": "Вы подтвердили, что вписанная вручную плата за смену ВРИ включает повышенную часть первого года."}
    if status == "not_applicable":
        return {"status": status, "derived": False,
                "source": "Вы подтвердили, что повышенная часть первого года к договору не применяется."}
    return {"status": "separate_required" if status == "separate_required" else "unknown", "derived": False, "source": ""}


def build(inputs: dict[str, Any], project_start: date, rve: date,
          project_end: date | None = None, *, cadastral_switch: date | None = None,
          phase_land: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Known accrual parts are usable; unknown total is always None.

    All returned date keys are ISO strings, suitable for saved/public API.
    The engine converts only monthly keys to date. Post-RVE unknowns are
    separate from completeness of the owner's construction-period question.

    ``cadastral_switch`` — the VRI change date: from it the base is the
    cadastral value after the change. ``phase_land`` — queues' shares of the
    parcel with the dates their land leaves the lease (``phase_release``).
    """
    x = inputs or {}
    end = project_end or rve
    derived_rve = rve
    release = [(float(p["share"]), _date(p["rve"])) for p in (phase_land or [])]
    phased = len(release) > 1
    if phased:
        rve = max(r for _, r in release)
        end = max(end, rve)
    raw_manual_cutoff = None if phased else x.get("land_rent_manual_cutoff")
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
        "derived_rve": derived_rve.isoformat(),
        "cutoff_origin": "phases" if phased else "manual" if manual_cutoff else "derived",
        "cutoff_basis": ("Даты ввода взяты из настроек очередей: аренда уменьшается по мере ввода каждой очереди" if phased else
                         "Дата ввода последнего здания на участке, которую вы указали" if manual_cutoff else
                         "Расчётная дата ввода последнего основного здания на участке"),
        "cutoff_field_origin": _mapping(x.get("_field_origin")).get("inputs.land_rent_manual_cutoff"),
        "assumptions": [],
    }
    missing = out["missing"]
    # Unconfirmed but not contradicted conditions: the rent is counted and
    # the result is preliminary, instead of silently leaving it out of costs.
    preliminary: list[tuple[str, str]] = []
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
    contract_date = None
    if preset:
        if not out["housing_applicable"]:
            missing.append("Ставки аренды под жильё не подходят для гостиницы или нежилого проекта. Введите ставки из договора аренды вручную.")
        if x.get("land_rent_preset_confirmed") is not True:
            preliminary.append(("conditions", "Ставки аренды взяты из правил региона, договор с ними ещё не сверен. Если в договоре другие ставки, введите их вручную."))
        if out["region"] != preset["region"]:
            missing.append("Выбранные правила аренды относятся к другому региону, а не к региону проекта.")
        if preset["region"] == "msk" and (x.get("_krt_site") or x.get("land_rent_grant_basis") in ("auction", "krt", "special")):
            missing.append("Для участка КРТ, участка с торгов или особого договора обычные московские ставки не действуют. Введите ставки из договора вручную.")
        if mode == "mo_housing_new_2026":
            contract_date = _date(x.get("land_rent_contract_date"))
            if contract_date is not None and contract_date <= date(2026, 1, 1):
                missing.append("Ставка 6% действует для договоров, заключённых после 1 января 2026 года. Для более раннего договора введите его ставки вручную.")
            scope = x.get("land_rent_public_scope")
            if scope in (None, ""):
                preliminary.append(("conditions", "Не указано, чья земля. Ставка 6% действует для земли Московской области и государственной земли, которая не разграничена."))
            elif scope not in ("regional", "undelimited"):
                missing.append("Ставка 6% действует только для земли Московской области и неразграниченной государственной земли. Для муниципальной и другой земли введите ставки из договора.")
            grant = x.get("land_rent_grant_basis")
            if x.get("_krt_site") or grant not in (None, "", "ordinary_nonauction"):
                missing.append("Для участка КРТ или участка с торгов обычная ставка Московской области не действует. Введите ставки из договора вручную.")
            elif grant in (None, ""):
                preliminary.append(("conditions", "Не указано, как предоставлен участок. Ставка 6% действует для обычного договора без торгов и не для КРТ."))
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
        missing.append("Укажите кадастровую стоимость арендуемой земли." if base_kind == "cadastral_percent" else "Укажите годовую сумму аренды по договору.")
    raw_anchor = x.get("land_rent_regime_start")
    anchor = _date(raw_anchor) if raw_anchor not in (None, "") else None
    if raw_anchor in (None, ""):
        anchor = project_start
        out["regime_start_assumed"] = True
        preliminary.append(("regime_start", f"Дата начала аренды по договору не указана, поэтому принят старт проекта {anchor:%d.%m.%Y}. Укажите дату из договора, если она другая."))
    if anchor is None:
        missing.append("Не распознана дата начала аренды по договору.")
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
    out["regime_start"] = anchor.isoformat() if anchor else None
    if mode == "mo_housing_new_2026" and contract_date is None and anchor is not None:
        contract_date = anchor
        if anchor <= date(2026, 1, 1):
            missing.append("Ставка 6% действует для договоров после 1 января 2026 года. Укажите дату договора: начало аренды раньше этой даты.")
        else:
            preliminary.append(("conditions", f"Дата договора не указана: индексация считается от начала аренды {anchor:%d.%m.%Y}."))
    # VRI change: before the change date the base is the current cadastral
    # value, from it — the value after the change (owner's decision).
    target = _number(x.get("land_rent_cadastral_target_mln")) if base_kind == "cadastral_percent" else None
    switch = cadastral_switch if target and base and target > 0 and abs(target - base) > 1e-9 else None
    out["cadastral_switch"] = ({"date": switch.isoformat(), "current_mln": base, "target_mln": target,
                                "origin": _mapping(x.get("_field_origin")).get("inputs.land_rent_cadastral_target_mln")}
                               if switch else None)
    if target and target > 0 and base and abs(target - base) > 1e-9 and switch is None:
        out["notes"].append("Кадастровая стоимость после смены ВРИ не применена: в проекте нет платы за смену ВРИ, поэтому нет и даты смены.")
    if cadastral_switch and base_kind == "cadastral_percent" and not (target and target > 0):
        preliminary.append(("cadastral_change", "Кадастровая стоимость участка после смены ВРИ не указана, поэтому аренда и после смены ВРИ считается от нынешней стоимости. Впишите новую стоимость, когда она станет известна."))
    if switch and mode == "mo_housing_new_2026":
        preliminary.append(("cadastral_change", "После смены ВРИ ставка 6% считается от новой кадастровой стоимости, индексация продолжается без перерыва. Порядок индексации новой стоимости зависит от основания её изменения — сверьте с договором."))
    if missing:
        return out
    assert anchor is not None and base is not None
    out["financial_missing_codes"] = []
    for code, text in preliminary:
        if text not in out["financial_missing"]:
            out["financial_missing"].append(text)
        out["financial_missing_codes"].append(code)
        if code == "regime_start":
            out["assumptions"].append(text)
    out["financial_missing_codes"] = list(dict.fromkeys(out["financial_missing_codes"]))
    shares_release = release if phased else [(1.0, None)]
    breaks = sorted({r for _, r in shares_release if r} | ({switch} if switch else set()))

    def weighted(a: date, b: date, only: int | None = None) -> float:
        """Base (mln) × days still leased on [a, b): queues not yet
        commissioned, the cadastral value valid at each day."""
        cuts = [a, *[c for c in breaks if a < c < b], b]
        items = shares_release if only is None else [shares_release[only]]
        total = 0.0
        for u, v in zip(cuts, cuts[1:]):
            share = sum(s for s, r in items if r is None or r > u)
            total += share * (target if switch and u >= switch else base) * (v - u).days
        return total
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
        out["notes"].append("Московская область: аренда — 6% кадастровой стоимости в год, с 1 января года после заключения договора сумма индексируется."
                            + (" После смены ВРИ ставка считается от новой кадастровой стоимости." if switch else ""))
        origins = _mapping(x.get("land_rent_indices_origin"))
        assumed = [y for y, value in sorted(indices.items()) if value is not None and
                   (y > date.today().year or _mapping(origins.get(str(y)) or origins.get(y)).get("source") == "forecast")]
        if assumed:
            text = "Индексы на " + ", ".join(map(str, assumed)) + " гг. — ваш прогноз для сценария, а не утверждённый размер аренды."
            out["assumptions"].append(text)
            out["notes"].append(text)

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
                amount = None if factor is None else 1e6 * rate / 100 * factor * weighted(month, finish) / denominator
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
    premium = vri_premium(x)
    out["premium"] = {"required": premium_required, **premium,
                      "vri_amount_mln": _number(x.get("land_rights_cost_mln"))}
    if premium_required and not premium["source"]:
        out["financial_missing"].append("В первый год аренды в Москве к обычной ставке добавляется повышенная часть. Плата за смену ВРИ вписана вручную или не задана, поэтому неизвестно, входит ли эта часть в неё. Укажите это в разделе «Первый год, ВРИ и график оплаты».")
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
    if phased:
        # Each month's rent is split among the queues still on the lease (not
        # yet commissioned, including the ones not yet started) by their
        # weight in that month; a manual payment schedule — by accrual totals.
        # The workbook repeats the same month fractions cell by cell.
        def fractions(month: date) -> list[float]:
            a, b = max(month, project_start), min(_next_month(month), boundary)
            whole = weighted(a, b) if a < b else 0.0
            return [weighted(a, b, only=i) / whole if whole else share for i, (share, _) in enumerate(release)]
        split = {m: fractions(m) for m in sorted(accrual)}
        phase_accrual = [{m: accrual[m] * f[i] for m, f in split.items()} for i in range(len(release))]
        known = out["known_total"]
        phase_cash = phase_accrual if out["cash_schedule_estimated"] else [
            {m: v * (sum(b.values()) / known if known else share) for m, v in sorted(payments.items())}
            for b, (share, _) in zip(phase_accrual, release)]
        out["phase_accrual_monthly"] = [{m.isoformat(): v for m, v in b.items()} for b in phase_accrual]
        out["phase_monthly"] = [{m.isoformat(): v for m, v in b.items()} for b in phase_cash]
        out["phase_land"] = [{"share": share, "rve": r.isoformat(), "accrual_total": sum(b.values()),
                              "cash_total": sum(c.values())}
                             for (share, r), b, c in zip(release, phase_accrual, phase_cash)]
        cash = out["cash_total"]
        out["phase_shares"] = [p["cash_total"] / cash if cash else share for p, (share, _) in zip(out["phase_land"], release)]
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

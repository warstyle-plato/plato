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
from urllib.parse import urlparse

import normatives_registry
import project_types
import project_regions

PRESETS = {
    "msk_mkd_3_2": {
        "label": "Москва: обычный режим п. 3.2 (подтверждён договором)",
        "region": "msk", "rates": [1.5, 1.5, 3, 5, 7, 8], "tail_rate_pct": 10,
        "short_source": "273-ПП, п. 3.2",
        "source": "273-ПП, пп. 3.1, 3.2, 3.2.1, 3.2.3; редакция 25.03.2026",
        "normative_id": "moscow-273pp-land-rent",
        "condition": "Режим пп. 3.1–3.2 подтверждён договором/допсоглашением. Не общий тариф для торгов, КРТ и льготных договоров.",
    },
    "msk_mkd_arch_confirmed": {
        "label": "Москва: подтверждены архитектурные условия п. 3.5(2)",
        "region": "msk", "rates": [1.35, 1.35, 2.7, 4.5, 6.3, 7.2], "tail_rate_pct": 9,
        "short_source": "273-ПП, п. 3.5(2)",
        "source": "273-ПП, п. 3.5(2), требования 305-ПП; редакция 25.03.2026",
        "normative_id": "moscow-273pp-land-rent",
        "condition": "Требования 305-ПП и обращение в ДГИ подтверждены. Не применяется только по названию проекта.",
    },
    "mo_housing_new_2026": {
        "label": "Подмосковье: новый обычный договор под жильё (ст. 14)",
        "region": "mo", "rates": [6], "tail_rate_pct": 6,
        "short_source": "23/96-ОЗ, ст. 14",
        "source": "23/96-ОЗ, ст. 14 ч. 5 и приложение, редакция 15.06.2026 (256/2025-ОЗ)",
        "normative_id": "mo-23-96oz-land-rent",
        "condition": "Договор после 01.01.2026, областная или неразграниченная земля, без торгов и вне специальных правил КРТ. Подтверждён обычный жилой ВРИ без более высокой ставки смешанного использования; исключены специальные случаи граждан (ИЖС/сад). Старые и муниципальные договоры — вручную. Проверено по сводному тексту указанной редакции.",
    },
}
# Ссылка на акт — из реестра нормативной базы (/normatives): там страница
# самого акта на портале органа власти и сводный текст, по которому сверена
# редакция.
for _preset in PRESETS.values():
    _link = normatives_registry.official_link(_preset["normative_id"])
    _preset["url"] = _link["url"]
    _preset["url_label"] = (_preset["short_source"].split(",")[0] + " на "
                            + urlparse(_link["url"]).hostname.removeprefix("www.")) if _link["url"] else ""
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


def queue_total_area(tep: dict[str, Any], *, skip: tuple[str, ...] = ()) -> tuple[float | None, list[str]]:
    """«Общая площадь» объектов очереди — сумма колонки ``total_area`` строк
    её ТЭП. Каждая строка ТЭП — свой объект, подытогов в ТЭП нет, поэтому
    встроенная часть не считается дважды. Строка, у которой есть здание
    (ГНС, места или продаваемые метры), а общей площади нет, — неизвестность,
    а не ноль: её подпись возвращается, сумма — ``None``. ``skip`` — строки,
    которые в очереди не строятся (соцобъекты при денежной компенсации)."""
    total, missing = 0.0, []
    for key, row in (tep or {}).items():
        if key in skip or not isinstance(row, dict):
            continue
        area = _number(row.get("total_area"))
        if area is not None and area > 0:
            total += area
        elif any((_number(row.get(col)) or 0) > 0 for col in ("gns", "units", "saleable")):
            missing.append(str(row.get("label") or key))
    return (None if missing else total), missing


def phase_land_shares(phases: list[dict[str, Any]], total_areas: list[float | None] | None,
                      gns: list[float]) -> tuple[list[float], str]:
    """Share of the leased parcel under each queue (owner's rule, 11.11.2026):
    its land area when every queue has one, otherwise the total area of its
    objects (``queue_total_area``). Until both are known the split is only
    preliminary: by floor area, or equal when nothing is known; the basis is
    returned for the disclosure and the ``phase_shares`` completeness code."""
    areas = [_number((cfg or {}).get("site_area_ha")) for cfg in phases]
    if areas and all(a is not None and a > 0 for a in areas):
        total = sum(areas)
        return [a / total for a in areas], "area"
    known = list(total_areas or [])
    if len(known) == len(phases) and all(a is not None and a >= 0 for a in known) and sum(known) > 0:
        total = sum(known)
        return [a / total for a in known], "total_area"
    total = sum(max(0.0, float(g or 0.0)) for g in gns)
    if len(gns) == len(phases) and total > 0:
        return [max(0.0, float(g or 0.0)) / total for g in gns], "gns_preliminary"
    return [1 / len(phases)] * len(phases), "equal_preliminary"


PHASE_SHARE_BASIS = {
    "area": "пропорционально площади участка каждой очереди",
    "total_area": "пропорционально общей площади объектов каждой очереди, потому что площадь участка указана не у каждой очереди",
    "gns_preliminary": "предварительно по ГНС очередей, потому что не известны ни площадь участка очередей, ни общая площадь их объектов",
    "equal_preliminary": "предварительно поровну, потому что не известны ни площадь участка очередей, ни площадь их объектов",
}


def phase_release(rves: list[date], cutoff: date,
                  overrides: list[Any] | None = None) -> tuple[list[date], list[str]]:
    """Date each queue's land leaves the lease: its commissioning. The last
    queue holds the parcel until the common cutoff (objects on the parcel
    may finish later); the workbook repeats this rule cell by cell.

    ``overrides`` — the date the owner typed for the rent only
    (``land_rent_release_date`` of a queue). It moves the queue's land out of
    the investment calculation and changes neither its commissioning nor
    its PF or sales. Returns the dates and their origin per queue
    (``derived`` / ``manual`` / ``invalid``: an unreadable date keeps the
    derived one and is named)."""
    latest = max(rves)
    out, origins = [], []
    for i, r in enumerate(rves):
        derived = cutoff if r == latest else min(r, cutoff)
        raw = (overrides or [None] * len(rves))[i] if i < len(overrides or []) else None
        typed = _date(raw) if raw else None
        if raw and (typed is None or not 1900 <= typed.year <= 2200):
            out.append(derived); origins.append("invalid")
        elif typed is not None:
            out.append(typed); origins.append("manual")
        else:
            out.append(derived); origins.append("derived")
    return out, origins


def describe_phase_land(result: dict[str, Any], *, basis: str,
                        areas: list[tuple[float | None, list[str]]] | None,
                        site_areas: list[Any], names: list[str], commissioning: list[date],
                        release_origin: list[str], social_skipped: bool = False,
                        derived_release: list[date] | None = None) -> dict[str, Any]:
    """Name the basis of each queue's share and the origin of its exit date.

    A preliminary split (``gns_preliminary`` / ``equal_preliminary``) keeps
    the common rent intact but moves money between queues, so it is named as
    incomplete with the queues and TEP rows whose total area is missing."""
    result["phase_share_basis"] = basis
    result["phase_share_basis_text"] = PHASE_SHARE_BASIS[basis]
    result["allocation_policy"] = (
        "Аренда общего участка посчитана один раз. Пока очередь не введена (в том числе пока она ещё не начата), "
        "её земля в аренде, и аренда за каждый месяц делится между такими очередями "
        + PHASE_SHARE_BASIS[basis] + ". Это модельное распределение, не подтверждение банковского покрытия.")
    known = list(areas or [])
    for i, item in enumerate(result.get("phase_land") or []):
        area, missing = known[i] if i < len(known) else (None, [])
        item.update({
            "name": names[i] if i < len(names) else f"О{i+1}",
            "commissioning": commissioning[i].isoformat() if i < len(commissioning) else None,
            "release_origin": release_origin[i] if i < len(release_origin) else "derived",
            # Дата по экономике: к ней возвращает очищенное поле очереди.
            "derived_rve": (derived_release[i].isoformat() if derived_release and i < len(derived_release)
                            else item.get("rve")),
            "site_area_ha": _number(site_areas[i]) if i < len(site_areas) else None,
            "total_area": area, "total_area_missing": list(missing),
        })
    if result.get("status") == "not_applicable":
        return result
    reasons, codes = [], []
    if basis in ("gns_preliminary", "equal_preliminary"):
        gaps = []
        for i, name in enumerate(names):
            area, missing = known[i] if i < len(known) else (None, [])
            if area is None:
                gaps.append(name + (" (нет общей площади: " + ", ".join(missing) + ")" if missing else " (ТЭП ещё не собран)"))
            elif area == 0:
                gaps.append(name + " (общая площадь объектов равна нулю)")
        tail = "; ".join(gaps) if gaps else "площадь участка очередей не указана"
        reasons.append("Доли земли очередей посчитаны " + PHASE_SHARE_BASIS[basis]
                       + ". Укажите площадь участка каждой очереди или общую площадь объектов: " + tail + ".")
        codes.append("phase_shares")
    bad = [names[i] for i, origin in enumerate(release_origin) if origin == "invalid" and i < len(names)]
    if bad:
        reasons.append("Не распознана дата выхода земли из аренды у очереди " + ", ".join(bad)
                       + "; взята дата её ввода.")
        codes.append("phase_release")
    if social_skipped:
        result["phase_share_note"] = "Соцобъекты при денежной компенсации не строятся и в общую площадь очереди не входят."
    if reasons:
        result["financial_complete"] = False
        result["financial_missing"] = [*result.get("financial_missing", []), *reasons]
        result["financial_missing_codes"] = list(dict.fromkeys([*result.get("financial_missing_codes", []), *codes]))
        result["status"] = "preliminary" if result.get("complete") else "incomplete"
    return result


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


PREMIUM_PROOF_KEYS = {"schema", "included_in_vri", "fee_mln", "method", "land_right", "source"}
# Те же способы, что у ``norms.vri_fee_rent_premium`` (``VRI_PREMIUM_METHODS``).
PREMIUM_PROOF_METHODS = ("glavapu_baseline_rescale", "vri_manual_payment")
PREMIUM_PROOF_MODES = ("msk_mkd_3_2", "msk_mkd_arch_confirmed")


def vri_premium(x: dict[str, Any]) -> dict[str, Any]:
    """Use an explicit owner decision or amount-bound source semantics.

    A positive fee, a coefficient or an origin label does not establish its
    composition. Evidence is bound to the amount, the calculation method and
    the lease right, and holds only for a Moscow housing lease regime where
    appendix 8 is part of the first year. Missing, stale or misfit evidence
    remains unknown; a misfit is named in ``misfit``.
    """
    fee = _number(x.get("land_rights_cost_mln")) or 0.0
    origin = _mapping(_mapping(x.get("_field_origin")).get("inputs.land_rights_cost_mln"))
    status = str(x.get("land_rent_premium_status") or "unknown")
    if status == "in_vri" and fee > 0:
        return {"status": status, "derived": False,
                "source": "Вы подтвердили, что плата за смену ВРИ включает повышенную часть первого года."}
    if status == "not_applicable":
        return {"status": status, "derived": False,
                "source": "Вы подтвердили, что повышенная часть первого года к договору не применяется."}
    if status == "separate_required":
        return {"status": status, "derived": False, "source": "Вы указали, что повышенная часть первого года оплачивается отдельно; её сумма ещё не определена."}
    proof = _mapping(origin.get("rent_premium"))
    proof_fee = _number(proof.get("fee_mln"))
    source = proof.get("source")
    if not (set(proof) == PREMIUM_PROOF_KEYS
            and type(proof.get("schema")) is int and proof["schema"] == 2
            and type(proof.get("included_in_vri")) is bool
            and proof.get("method") in PREMIUM_PROOF_METHODS and proof.get("land_right") == "lease"
            and fee > 0 and proof_fee is not None and math.isclose(proof_fee, fee, rel_tol=0, abs_tol=1e-9)
            and isinstance(source, str) and source.strip()):
        return {"status": "unknown", "derived": False, "source": ""}
    # Доказательство верно для того права и режима, под которые плата
    # посчитана. Ставка приложения 8 входит в первый год по абзацу первому
    # п. 3.2.1 (и п. 3.5(1).1) — для участка в аренде под жилой дом в
    # московском режиме договора. Иначе вопрос остаётся у владельца.
    misfit = ("участок сейчас не в аренде" if x.get("land_right") != "lease" else
              "в проекте нет жилья, а повышенная часть по приложению 8 считается для жилого дома"
              if project_types.without_housing(x) else
              "режим договора аренды не московский обычный (п. 3.2.1 или 3.5(1))"
              if str(x.get("land_rent_mode") or "") not in PREMIUM_PROOF_MODES else "")
    if misfit:
        return {"status": "unknown", "derived": False, "source": "",
                "misfit": f"Расчёт платы за ВРИ не подтверждает состав первого года: {misfit}."}
    return {"status": "in_vri" if proof["included_in_vri"] else "separate_required", "derived": True,
            "source": source.strip(), "evidence": dict(proof)}


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
    # Allocate within each rate/index/exclusion segment, before month totals
    # lose that information. Payments and every consumer reuse these amounts.
    phase_accrual = [defaultdict(float) for _ in release]
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
                    month_key = month.replace(day=1)
                    accrual[month_key] += amount
                    if phased:
                        whole = weighted(month, finish)
                        for i, own in enumerate(phase_accrual):
                            own[month_key] += amount * weighted(month, finish, only=i) / whole if whole else 0.0
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
    if premium_required and premium["status"] not in ("in_vri", "not_applicable"):
        out["financial_missing"].append(
            "Повышенная часть первого года аренды оплачивается отдельно; её сумма ещё не определена."
            if premium["status"] == "separate_required" else
            "В первый год аренды в Москве к обычной ставке добавляется повышенная часть. Состав платы за смену ВРИ не подтверждён. "
            + (premium["misfit"] + " " if premium.get("misfit") else "")
            + "Укажите, входит ли эта часть в неё, в разделе «Первый год, ВРИ и график оплаты».")
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
        # A manual payment schedule follows each queue's exact accrued
        # obligation, not a second monthly base-times-days approximation.
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


def sum_state(result: dict[str, Any]) -> dict[str, Any]:
    """Whether the rent sum itself is determined, and if not, why.

    The one answer for every reader: the row «Аренда земли участка» of the page
    and the title of «Инвестиционное решение». A payment schedule by the plan
    accrual and unconfirmed VAT leave the sum determined. A missing input, the
    rent after commissioning or an unconfirmed condition that changes the sum
    (`financial_missing`: rates, the first-year premium, the cadastral value
    after the VRI change, the scope, the land shares of the phases) do not.
    """
    if result.get("status") == "not_applicable":
        return {"known": True, "reason": ""}
    known = bool(result.get("complete")) and result.get("total") is not None and not result.get("financial_missing")
    if known:
        return {"known": True, "reason": ""}
    reasons = [*(result.get("missing") or []), *(result.get("financial_missing") or [])]
    if not reasons and result.get("post_rve_unknown"):
        reasons = ["Аренда после ввода требует отдельного расчёта."]
    return {"known": False, "reason": str(reasons[0]) if reasons else "Сумма аренды не определена."}


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

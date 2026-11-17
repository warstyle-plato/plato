"""Cadastral rent bases from accepted, saved land data; no remote lookups.

Estimates are scenarios, never an assertion that a new value is in ЕГРН.
The land UPKS is an explicit input, independent of VRI payment parameters.
"""
from __future__ import annotations

import copy
import math
import re

import project_regions


def positive(value):
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) and result > 0 else None
    except (ValueError, TypeError):
        return None


AUTO_KINDS = {"land_rent_egrn", "land_rent_estimate", "land_rent_official_egrn"}
FORMULA = "КСрасч = Σ (площадь арендуемого участка, м² × целевой земельный УПКС, ₽/м²)"
METHODOLOGY = {
    "text": "Сценарная оценка жилой земли по УПКС целевого ВРИ, группы и территории последней применимой ГКО. Приказ Росреестра от 04.08.2021 № П/0336 (ред. № П/0288/24, № П/0327/25), пп. 60.1.2(7), 72. Индивидуальные отличия требуют обоснованных корректировок показателя. Для других видов использования применимость метода определяет бюджетное учреждение; официальную новую КС оно определяет по ст. 16 закона № 237-ФЗ.",
    "url": "http://publication.pravo.gov.ru/document/0001202112200041",
    "as_of": "2026-11-17",
}


def mapping(value):
    return value if isinstance(value, dict) else {}


def accepted_territory(x):
    """Mirror the page's one applied-source and project-region gate.

    An empty mappings object is present in valid saved ГлавАПУ records and
    is truthy in JavaScript. Test its type/presence, not Python's bool({}).
    Parcel values alone never establish that a territory was applied.
    """
    accepted = []
    gl = mapping(x.get("_glavapu_import"))
    normalized = gl.get("normalized")
    recognized = gl.get("recognized") if isinstance(gl.get("recognized"), list) else []
    if (isinstance(gl.get("mappings"), dict) and isinstance(normalized, dict)
            and (normalized.get("cadastral_quarter") or recognized)):
        accepted.append({"region": "msk", "numbers": [n for n in recognized
            if isinstance(n, str) and re.fullmatch(r"\d{2}:\d{2}:\d{6,8}:\d+", n)]})
    mo = mapping(mapping(x.get("_mo_calc")).get("vri")).get("parcels")
    mo = mo if isinstance(mo, list) else []
    mo_numbers = [str(p.get("cadastral_number") or "") for p in mo if isinstance(p, dict)
        and re.fullmatch(r"\d{2}:\d{2}:\d{6,8}:\d+", str(p.get("cadastral_number") or ""))]
    if mo_numbers:
        accepted.append({"region": "mo", "numbers": mo_numbers, "parcels": mo})
    other = mapping(x.get("_other_region"))
    if isinstance(other.get("numbers"), list) and other["numbers"] and other.get("region"):
        accepted.append({"region": "other", "numbers": other["numbers"]})
    if len(accepted) != 1 or accepted[0]["region"] != project_regions.region_of(x):
        return None
    return accepted[0]


def parcels(x):
    """Only parcels of the accepted territory, using the same IDs as the UI."""
    territory = accepted_territory(x)
    if territory is None:
        return []
    region = territory["region"]
    # ГлавАПУ stores recognized table cells here, not just parcel numbers.
    # Match the browser's explicit cadastral-number filter; never treat a
    # recognized metric dict as the identity of a parcel.
    numbers = territory["numbers"]
    lookup = mapping(x.get("_land_lookup")).get("results") or []
    raw = territory["parcels"] if region == "mo" else [p for p in lookup if isinstance(p, dict)
        and p.get("found") and p.get("kind") == "land"
        and (not numbers or p.get("cadastral_number") in numbers)] if region == "msk" else []
    rows, seen = [], set()
    for p in raw:
        if not isinstance(p, dict):
            continue
        number = str(p.get("cadastral_number") or "")
        if not re.fullmatch(r"\d{2}:\d{2}:\d{6,8}:\d+", number) or number in seen:
            continue
        seen.add(number)
        current = positive(p.get("cadastral_value_rub")) if region == "mo" else None
        current = current / 1e6 if current else positive(p.get("cadastral_value_mln"))
        target = positive(p.get("cadastral_value_new_rub")) if region == "mo" else None
        rows.append(dict(number=number, current_mln=current,
            area_sqm=positive(p.get("area_sqm")), target_mln=target / 1e6 if target else None,
            upks_rub_sqm=positive(p.get("upks_target")), source_date=p.get("cadastral_value_date") or ""))
    if region == "msk":
        for number in numbers:
            if number not in seen:
                rows.append(dict(number=number, current_mln=None, area_sqm=None,
                    target_mln=None, upks_rub_sqm=None, source_date=""))
    return rows


def automatic(x, key):
    origin = mapping(mapping(x.get("_field_origin")).get("inputs." + key))
    if origin:
        if origin.get("source") == "manual":
            return False
        return origin.get("kind") in AUTO_KINDS or str(origin.get("text") or "").startswith("ЕГРН принятого арендуемого участка")
    # Unlabelled saved values may be owner-confirmed. Never replace them.
    return x.get(key) in (None, "")


def prepare(inputs):
    x = copy.deepcopy(inputs or {})
    if x.get("land_right") != "lease" or x.get("land_rent_base_kind", "cadastral_percent") != "cadastral_percent":
        return x
    region = project_regions.region_of(x)
    # Other-region calculations stay outside this estimator. An invalid
    # source/region gate still has to detach any previous automatic bases.
    if region not in ("msk", "mo") and accepted_territory(x) is not None:
        return x
    all_rows = parcels(x)
    excluded = set(x.get("land_rent_parcels_excluded") or [])
    rows = [r for r in all_rows if r["number"] not in excluded]
    origins = dict(mapping(x.get("_field_origin")))
    x["_field_origin"] = origins
    def fill(key, field, kind, text):
        if not automatic(x, key):
            return
        x[key] = round(sum(r[field] for r in rows), 6) if rows and all(r[field] is not None for r in rows) else None
        origins["inputs." + key] = dict(source="document" if kind == "land_rent_egrn" else "calculated",
            kind=kind, text=text + ": " + ", ".join(r["number"] for r in rows))
    fill("land_rent_cadastral_mln", "current_mln", "land_rent_egrn", "Из ЕГРН: сумма кадастровой стоимости арендуемых участков")
    params = {str(p.get("number")): p for p in x.get("land_rent_cadastral_parameters", []) if isinstance(p, dict)}
    for row in rows:
        p = params.get(row["number"], {})
        if region == "msk":
            area = positive(p.get("area_sqm")) if "area_sqm" in p else row["area_sqm"]
            upks = positive(p.get("upks_rub_sqm"))
            row.update(area_sqm=area, upks_rub_sqm=upks,
                target_mln=area * upks / 1e6 if area and upks else None,
                source=str(p.get("source") or ""), source_date=str(p.get("source_date") or ""),
                target_use=str(p.get("target_use") or ""), valuation_territory=str(p.get("valuation_territory") or ""))
        else:
            row["source"] = "Расчёт МО: целевой земельный УПКС из применённого расчёта ВРИ"
            # The ЕГРН date belongs to the current base, not to this estimate.
            row["source_date"] = ""
    x["_land_rent_cadastral_estimate"] = dict(formula=FORMULA, region=region, parcels=rows,
        methodology=METHODOLOGY if region == "msk" else None,
        total_mln=sum(r["target_mln"] for r in rows) if rows and all(r["target_mln"] is not None for r in rows) else None)
    fill("land_rent_cadastral_target_mln", "target_mln", "land_rent_estimate", "Расчётная будущая КС (не ЕГРН), площадь × целевой земельный УПКС")
    x["_land_rent_cadastral_estimate"]["applied"] = (automatic(x, "land_rent_cadastral_target_mln") and
        mapping(origins.get("inputs.land_rent_cadastral_target_mln")).get("kind") == "land_rent_estimate")
    target_key = "inputs.land_rent_cadastral_target_mln"
    if not automatic(x, "land_rent_cadastral_target_mln"):
        origin = mapping(origins.get(target_key))
        metadata = ("land_rent_cadastral_target_kind", "land_rent_cadastral_target_source",
                    "land_rent_cadastral_target_source_date")
        # Older saved manual evidence is authoritative too. New editor fields
        # may refine it, but their absence must not erase its text or date.
        if origin and not any(key in x for key in metadata):
            return x
        kind = x.get("land_rent_cadastral_target_kind") or origin.get("value_type") or "manual_confirmed"
        label = {"official_egrn": "Официальная новая КС из ЕГРН", "estimate": "Ручная оценка будущей КС (не ЕГРН)",
                 "manual_confirmed": "Подтверждённая вручную КС после смены ВРИ"}.get(kind, "КС после смены ВРИ, введённая вручную")
        origins[target_key] = {**origin, "source": "manual", "kind": "manual",
            "text": label + (": " + str(x["land_rent_cadastral_target_source"]) if x.get("land_rent_cadastral_target_source") else ""),
            "value_type": kind, "source_date": x.get("land_rent_cadastral_target_source_date", origin.get("source_date"))}
    return x

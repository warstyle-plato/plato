"""Verify extracted facts against the document before building an engine patch.

The model supplies candidates, never proof. This module does no project maths.
"""
from __future__ import annotations

import math
import re
from typing import Any

_NUMBER = re.compile(r"(?<![\d:])[-+]?(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,]\d+)?(?![\d:])")
_CADASTRE = re.compile(r"(?<!\d)\d{2}:\d{2}:\d{5,8}:\d+(?!\d)")
_MAGNITUDE = r"(?:млрд|миллиард[а-я]*|млн|миллион[а-я]*|тыс|тысяч[а-я]*)\.?"
_UNIT = re.compile(r"^\s*(?:(?:" + _MAGNITUDE + r"\s*)?"
                   r"(?:руб[а-я]*\.?|₽|RUB\b|м\s*[²2]|кв\.?\s*м\.?)|"
                   r"га\b|гект[а-я]*|машино[- ]?мест[а-я]*|м/м|мест[а-я]*|шт\.?|"
                   r"пос\.?\s*/\s*смен[а-я]*|посещ[а-я]*)(?![a-zа-я])", re.I)


def _dimension(unit: str) -> str:
    normalized = _flat(unit)
    if re.search(r"м\s*[²2]|кв\.?\s*м\.?|\bга\b|гект", normalized):
        return "area"
    if re.search(r"руб|₽|\brub\b", normalized):
        return "money"
    if re.search(r"пос\.?\s*/\s*смен|посещ", normalized):
        return "visits"
    if re.search(r"мест|шт|м/м", normalized):
        return "count"
    return "unknown"


def _flat(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _area_basis(quote: str, number: re.Match, unit_end: int, whole_house_marks) -> str:
    """Bind area labels to this amount, without borrowing a neighbour's label."""
    previous, following = 0, len(quote)
    for other in _NUMBER.finditer(quote):
        unit = _UNIT.match(quote[other.end():])
        if unit is None or _dimension(unit.group()) != "area":
            continue
        end = other.end()+unit.end()
        if end <= number.start():
            previous = max(previous,end)
        elif other.start() >= unit_end:
            following = min(following,other.start())
    before = quote[previous:number.start()]
    prefix = re.split(r"[;|]",before)[-1]
    # A label immediately following the preceding amount's dash belongs to
    # that amount. Without a separating clause its ownership is ambiguous.
    if previous and not re.search(r"[;|]",before) and re.match(r"\s*[—–:=\-(]",prefix):
        prefix = ""
    after = quote[unit_end:following]
    postfix = re.split(r"[;|]",after)[0]
    if (not re.match(r"\s*[—–:=\-(]",postfix)
            or (following < len(quote) and not re.search(r"[;|]",after))):
        postfix = ""

    def label_basis(label):
        text = _flat(label)
        if not text:
            return ""
        saleable = bool(re.search(
            r"(?:продаваем[а-яё]*|реализуем[а-яё]*)\s+(?:[а-яё]+\s+){0,2}площад[а-яё]*"
            r"|площад[а-яё]*\s+(?:продаваем[а-яё]*|реализуем[а-яё]*)",text))
        gross = bool(re.search(r"\b(?:гнс|спп)\b",text))
        project = bool(re.search(r"\b(?:гнс|спп|площад[а-яё]*)\s+(?:в\s+гнс\s+)?(?:всего\s+)?проект[а-яё]*",text))
        house = any(mark in text for mark in whole_house_marks)
        apartment = bool(re.search(r"\bквартир[а-яё]*",text))
        if saleable:
            return "saleable_area"
        if project:
            return "unscoped_project_area"
        if house:
            return "residential_house"
        if apartment:
            return "apartments_gns"
        return "unscoped_project_area" if gross else ""

    bases = {basis for label in (prefix,postfix) if (basis := label_basis(label))}
    if len(bases) > 1:
        return "ambiguous_area_basis"
    return next(iter(bases),"unscoped_project_area")


def validate(extraction: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    import document_intake as di

    body = _flat(document.get("text"))
    fields, refused = [], list(extraction.get("unverified") or [])
    notes = list(extraction.get("notes") or [])
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in extraction.get("fields") or []:
        row = dict(item)
        key = str(row.get("key") or "")
        quote = str(row.get("quote") or "").strip()
        parts = [part.strip() for part in quote.split("|") if part.strip()]
        why = ""
        if key not in di.INTAKE_KEYS:
            why = "неизвестное поле модели"
        elif not parts or not all(_flat(part) in body for part in parts):
            why = "цитата не найдена в прочитанной части документа"
        elif key == "cadastral_numbers":
            raw = row.get("value")
            values = raw if isinstance(raw, list) else [raw]
            numbers = list(dict.fromkeys(n for v in values for n in _CADASTRE.findall(str(v))))
            cited = set(_CADASTRE.findall(quote))
            if not numbers or not set(numbers).issubset(cited):
                why = "кадастровый номер не подтверждён цитатой"
            else:
                row["value"] = numbers
        else:
            value, problem = di.to_field_number(key, row.get("value"), row.get("unit") or "")
            if problem or value is None or not math.isfinite(value) or value < 0:
                why = problem or "нужно конечное неотрицательное число"
            elif key not in di._MONEY_FIELDS | di._AREA_SQM_FIELDS | {"site_area_ha"} and value != int(value):
                why = "количество мест должно быть целым числом"
            else:
                # Read the source number WITH ITS OWN unit. A model-provided
                # unit cannot turn the source's 400 RUB into 400 million RUB.
                matched = False
                source_match = None
                for match in _NUMBER.finditer(quote):
                    suffix_match = _UNIT.match(quote[match.end():])
                    suffix = suffix_match.group() if suffix_match else ""
                    tail = quote[match.end() + suffix_match.end():] if suffix_match else ""
                    if suffix_match and re.match(
                            r"\s*(?:/|(?:за|на|в)\s+(?:(?:1|один|одну)\s+)?"
                            r"(?:м\s*[²2]|кв\.?\s*м|га\b|гектар|сотк|мест|год|месяц|сутк|час|челов))",
                            tail, re.I):
                        continue  # a rate per area/time is not a total amount
                    expected = ("money" if key in di._MONEY_FIELDS else
                                "area" if key in di._AREA_SQM_FIELDS | {"site_area_ha"} else
                                "visits" if key == "clinic_capacity" else "count")
                    if _dimension(suffix) != expected:
                        continue
                    number, error = di.to_field_number(key, match.group(), suffix)
                    if (not error and number is not None and math.isfinite(number)
                            and math.isclose(number, value, rel_tol=1e-10, abs_tol=1e-8)):
                        matched = True
                        source_match = match
                        source_unit_end = match.end()+suffix_match.end()
                        break
                if not matched:
                    why = "число или его единица не совпадает с цитатой"
        if not why and key in {"apartments_gns_sqm", "residential_spp_sqm"}:
            kind = ""
            basis = _area_basis(quote,source_match,source_unit_end,di._WHOLE_HOUSE_MARKS)
            if basis == "saleable_area":
                kind = "saleable_area"
                why = ("Это продаваемая площадь, а поле модели принимает ГНС. Перенос не выполнен; "
                       "исходное значение сохранено в примечаниях.")
            elif basis == "ambiguous_area_basis":
                kind = basis
                why = ("Подписи выбранной площади противоречат друг другу. Перенос не выполнен; "
                       "исходное значение сохранено в примечаниях.")
            elif basis != ("residential_house" if key == "residential_spp_sqm" else "apartments_gns"):
                kind = "unscoped_project_area"
                why = ("Подпись выбранного числа не подтверждает назначение площади для этого поля. "
                       "Перенос не выполнен; исходное значение сохранено в примечаниях.")
            if kind:
                from teaser_card import quote_page
                page = quote_page(str(document.get("text") or ""), quote)
                row["refusal_code"] = kind
                row["source_fact"] = {"kind": kind, "value": row.get("value"),
                    "unit": row.get("unit"), "quote": quote, "page": page}
                row["page"] = page
                note = (f"В источнике, стр. {page}" if page is not None else "В источнике")
                note += f": «{quote}». {why}"
                if note not in notes:
                    notes.append(note)
        if why:
            refused.append({**row, "reason": why})
        else:
            row["source_checked"] = True
            grouped.setdefault(key, []).append(row)

    conflicts = list(extraction.get("conflicts") or [])
    for key, rows in grouped.items():
        if key == "cadastral_numbers":
            row = dict(rows[0])
            row["value"] = list(dict.fromkeys(n for r in rows for n in r["value"]))
            row["quote"] = " | ".join(dict.fromkeys(r["quote"] for r in rows))
            fields.append(row)
            continue
        unique = {}
        for row in rows:
            number, _ = di.to_field_number(key, row.get("value"), row.get("unit") or "")
            unique.setdefault(number, row)
        if len(unique) > 1:
            conflicts.append({"key": key, "fields": list(unique.values())})
        else:
            fields.append(rows[0])
    questions = []
    for question in extraction.get("questions") or []:
        item = dict(question)
        if item.get("requires_manual"):
            item["source_quote"] = ""
            questions.append(item)
            continue
        quote = str(item.get("quote") or "")
        candidate_text = " ".join([str(item.get("question") or "")] +
            [str(o.get("value") or "") + " " + str(o.get("unit") or "") + " " + str(o.get("label") or "")
             for o in item.get("choices") or []])
        numbers = [di.to_number(m.group()) for m in _NUMBER.finditer(candidate_text)]
        cited_numbers = {di.to_number(m.group()) for m in _NUMBER.finditer(quote)}
        cited_amounts = {r["mln"] for r in di.question_amounts(quote)}
        wrong_amount = any(r["mln"] not in cited_amounts for r in di.question_amounts(candidate_text))
        wrong_option = False
        for option in di.question_card(item)["options"]:
            if option.get("value") and option.get("target") in di.INTAKE_KEYS:
                proof = validate({"fields": [{"key": option["target"], "value": option["value"],
                    "unit": di.INTAKE_UNITS.get(option["target"], ""), "quote": quote}]}, document)
                wrong_option = wrong_option or not proof["fields"]
        if any(n is not None and n != 0 for n in numbers) and (
                not quote or _flat(quote) not in body or
                any(n not in cited_numbers for n in numbers if n is not None) or wrong_amount or wrong_option):
            # A classification click is not consent to a fabricated amount or
            # payment schedule. Remove all model-suggested numbers and ask for
            # the actual manual amount, keeping only the choice of destination.
            item["question"] = ("Уточните сумму и решение: " + di.INTAKE_LABELS.get(
                str(item.get("key") or ""), "куда отнести обязательство из документа"))
            item["requires_manual"] = True
            choices = item.get("choices") or [{"label": o} for o in item.get("options") or []]
            item["choices"] = [{"label": _NUMBER.sub("…", str(o.get("label") or "")),
                                "value": None, "unit": ""} for o in choices]
            item["options"] = [o["label"] for o in item["choices"]]
            item["source_quote"] = ""
        elif quote and _flat(quote) in body:
            item["source_quote"] = quote
        questions.append(item)
    return {**extraction, "fields": fields, "conflicts": conflicts, "notes": notes,
            "questions": questions, "unverified": refused}

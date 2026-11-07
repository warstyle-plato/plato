"""Verify extracted facts against the document before building an engine patch.

The model supplies candidates, never proof. This module does no project maths.
"""
from __future__ import annotations

import math
import re
from typing import Any

_NUMBER = re.compile(r"(?<![\d:])[-+]?(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,]\d+)?(?![\d:])")
_CADASTRE = re.compile(r"(?<!\d)\d{2}:\d{2}:\d{5,8}:\d+(?!\d)")
_UNIT = re.compile(r"^\s*(?:млрд\.?|миллиард\w*|млн\.?|миллион\w*|"
                   r"(?:тыс\.?|тысяч\w*)\s*(?:руб\w*\.?|₽|м\s*[²2]|кв\.?\s*м\.?)?|"
                   r"руб\w*\.?|₽|га\b|гект\w*|м\s*[²2]|кв\.?\s*м\.?|"
                   r"машино[- ]?мест\w*|м/м|мест\w*|шт\.?|пос\.?\s*/\s*смен\w*|посещ\w*)", re.I)


def _dimension(unit: str) -> str:
    normalized = _flat(unit)
    if re.search(r"м\s*[²2]|кв\.?\s*м\.?|\bга\b|гект", normalized):
        return "area"
    if re.search(r"млрд|миллиард|млн|миллион|руб|₽", normalized):
        return "money"
    if re.search(r"пос\.?\s*/\s*смен|посещ", normalized):
        return "visits"
    if re.search(r"мест|шт|м/м", normalized):
        return "count"
    return "unknown"


def _flat(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def validate(extraction: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    import document_intake as di

    body = _flat(document.get("text"))
    fields, refused = [], list(extraction.get("unverified") or [])
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
                for match in _NUMBER.finditer(quote):
                    suffix_match = _UNIT.match(quote[match.end():])
                    suffix = suffix_match.group() if suffix_match else ""
                    expected = ("money" if key in di._MONEY_FIELDS else
                                "area" if key in di._AREA_SQM_FIELDS | {"site_area_ha"} else
                                "visits" if key == "clinic_capacity" else "count")
                    if _dimension(suffix) != expected:
                        continue
                    number, error = di.to_field_number(key, match.group(), suffix)
                    if (not error and number is not None and math.isfinite(number)
                            and math.isclose(number, value, rel_tol=1e-10, abs_tol=1e-8)):
                        matched = True
                        break
                if not matched:
                    why = "число или его единица не совпадает с цитатой"
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
    return {**extraction, "fields": fields, "conflicts": conflicts,
            "questions": questions, "unverified": refused}

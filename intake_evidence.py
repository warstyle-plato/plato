"""Verify extracted facts against the document before building an engine patch.

The model supplies candidates, never proof. This module does no project maths.
"""
from __future__ import annotations

import math
import re
from typing import Any

_NUMBER = re.compile(r"(?<![\d:])[-+]?(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,]\d+)?(?![\d:])")
_CADASTRE = re.compile(r"(?<!\d)\d{2}:\d{2}:\d{5,8}:\d+(?!\d)")
_UNIT = re.compile(r"^\s*(?:млрд\.?|миллиард\w*|млн\.?|миллион\w*|тыс\.?|тысяч\w*|"
                   r"руб\w*\.?|₽|га\b|гект\w*|м\s*[²2]|кв\.?\s*м\.?|мест\w*|шт\.?)", re.I)


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
    return {**extraction, "fields": fields, "conflicts": conflicts,
            "unverified": refused}

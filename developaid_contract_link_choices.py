"""The owner's choice of ГПР lines for a position of the «Расчёт договорной стоимости».

A choice belongs to the position, not to one file: its number, name and unit
find it in every edition (owner's decision 3А). It holds in a newer edition only
while each chosen line is still a work line of the schedule in force under the
same code and name; otherwise the proposal comes back with the reason, never a
silent link to a renamed or removed line. Shares by duration are recomputed
from the current dates; only shares entered by hand are kept as entered, scaled to add
up to exactly one (33,33 % three times is the whole position).
"""
from __future__ import annotations

import math
import re

import developaid_contract_schedule_links as links

MANUAL_NOTE = "Доли строк заданы вручную."


class LinkChoiceProblem(ValueError):
    """A controlled, safe message that may be returned to an authenticated user."""


def _same(left, right):
    return re.sub(r"\s+", " ", str(left or "")).strip().casefold() == \
        re.sub(r"\s+", " ", str(right or "")).strip().casefold()


def _whole(shares):
    """Shares that add up to exactly one: 33,33 % three times must not lose a part of the position."""
    total = sum(shares)
    return [share / total for share in shares]


def _reasons(reasons: dict) -> str:
    return "; ".join(reasons.values())


def decide(item: dict, schedule: dict | None, lines: list[str] | None, shares: list[float] | None,
           decided_at: str) -> dict:
    """A stored choice for the proposed `item`; `lines` None confirms the proposal itself."""
    current = {line["code"]: line for line in links.leaves(schedule)}
    bad = links.unfit(schedule)
    if not current:
        if bad:
            raise LinkChoiceProblem("В графике нет строки работы, с которой можно связать позицию: "
                                    + _reasons(bad) + ".")
        raise LinkChoiceProblem("Сначала загрузите график производства работ этой или прежней редакции.")
    if lines is None:
        if item["status"] != "proposed":
            raise LinkChoiceProblem(f"У позиции {item.get('number') or item['index'] + 1} нет предложенной связи: "
                                    "выберите строки графика.")
        codes = [line["code"] for line in item["lines"]]
    else:
        codes = list(dict.fromkeys(str(code) for code in lines))
    if not codes:
        raise LinkChoiceProblem("Выберите хотя бы одну строку графика.")
    refused = {code: bad[code] for code in codes if code not in current and code in bad}
    if refused:
        raise LinkChoiceProblem("С этой строкой графика позицию связать нельзя: " + _reasons(refused)
                                + ". Исправьте график или выберите другую строку.")
    unknown = [code for code in codes if code not in current]
    if unknown:
        raise LinkChoiceProblem(f"Строк {', '.join(unknown)} нет среди работ действующего графика: выберите "
                                "строку работы со сроками, а не заголовок раздела.")
    if shares is not None:
        if (len(shares) != len(codes) or not all(isinstance(s, (int, float)) and math.isfinite(s) and s > 0
                                                 for s in shares) or abs(sum(shares) - 100) > 0.05):
            raise LinkChoiceProblem("Доли строк должны быть больше нуля и в сумме давать 100 %.")
        shares = _whole(shares)
    return {"position": {key: item.get(key) for key in ("number", "name", "unit")},
            "lines": [{"code": code, "name": current[code]["name"]} for code in codes],
            "shares": shares, "origin": "manual" if shares is not None else "duration",
            "chosen": lines is not None, "decided_at": decided_at}


def apply(result: dict, choices: dict, schedule: dict | None) -> dict:
    """Proposals of `links.propose` with the owner's choices laid over them."""
    current = {line["code"]: line for line in links.leaves(schedule)}
    bad = links.unfit(schedule)
    for item in result["positions"]:
        choice = choices.get(item["key"])
        if not choice:
            continue
        refused = {line["code"]: bad[line["code"]] for line in choice["lines"] if line["code"] in bad}
        if refused:
            item["carry"] = ("Подтверждённая ранее связь не применена: строка есть в графике, но "
                             + _reasons(refused) + ". Исправьте график или выберите другую строку.")
            continue
        gone = [line for line in choice["lines"]
                if line["code"] not in current or not _same(current[line["code"]]["name"], line["name"])]
        if gone:
            item["carry"] = ("Подтверждённая ранее связь не перенесена: в действующем графике нет строки "
                             + ", ".join(f"{line['code']} «{line['name']}»" for line in gone)
                             + ". Подтвердите связь заново.")
            continue
        chosen = [current[line["code"]] for line in choice["lines"]]
        manual = choice["origin"] == "manual"
        item.update(status="confirmed", lines=links.linked(chosen, _whole(choice["shares"]) if manual else None),
                    reason="", suggested=[], fix=None, origin=choice["origin"], chosen=choice["chosen"], decided_at=choice["decided_at"],
                    assumption=(MANUAL_NOTE if manual else links.SHARE_ASSUMPTION) if len(chosen) > 1 else "")
    result.update(links.summary(result["positions"], schedule))
    return result

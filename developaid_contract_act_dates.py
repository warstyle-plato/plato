"""Dates of the KS-6a periods named by an act only («КС-2 № 2»).

A cumulative KS-6a may head its periods with the number of the act КС-2 and no
dates. Such a period gets its dates from the act itself (owner's decision А):

1. the reporting period of the act КС-2 with that number in the contract card;
2. otherwise the date of the act in the closing summary of the register row —
   the day the act was signed, not the end of the work, and labelled so;
3. otherwise the period stays without a date: its volume is left out of the fact
   and the reason says which act is missing.

Two acts with one number and different periods, or two summary dates of one act,
date nothing: which is right is not known. The money of a period in the KS-6a is
compared with the total of its act; a difference is a warning, not a correction.
A work enters the fact only when every period with its volume is dated and the
volumes of its periods add up to its cumulative total.
"""
from __future__ import annotations

import re

# Only an explicit act number: «КС-2 № 3», «Акт № 3» or a label that is the number alone («№ 3»).
# «Период № 3», «Этап № 2» and the date of «КС-2 от 15.03.2026» are no act numbers.
_NUMBER = re.compile(r"КС\s*-?\s*2\b[^№\d]*№\s*(\d+)|\bакт\w*\s+№\s*(\d+)|^\s*№\s*(\d+)\s*$", re.I)
_QUANTITY = 1e-6


def number(label) -> str | None:
    """The act number of a KS-6a period label («КС-2 № 3» → "3"); None for a period named otherwise."""
    match = _NUMBER.search(str(label or ""))
    return next(g for g in match.groups() if g).lstrip("0") or "0" if match else None


def _act_number(value) -> str | None:
    digits = re.findall(r"\d+", str(value or ""))
    return digits[-1].lstrip("0") or "0" if digits else None


def _shown(iso):
    return ".".join(reversed(iso.split("-"))) if iso else "—"


def _money(value):
    return f"{value:,.2f}".replace(",", " ").replace(".", ",") + " ₽"


def _differs(one, other):
    return abs(one - other) > max(1.0, abs(other) * 1e-6)


def _dates(n: str, records: list[dict], summary: list[dict]) -> dict:
    """Dates of the act `n`: from the card's КС-2, else the summary, else none with the reason."""
    out = {"number": n, "start": None, "end": None, "basis": "", "source": {}, "act_amount": None,
           "warnings": [], "reason": ""}
    pdfs = [r for r in records if _act_number((r.get("act") or {}).get("number")) == n]
    noted = [a for a in summary if _act_number(a.get("number")) == n]
    read = [r for r in pdfs if r["act"].get("finish")]
    periods = sorted({(r["act"].get("start"), r["act"]["finish"]) for r in read}, key=lambda p: p[1])
    if len(periods) > 1:
        out["reason"] = (f"в карточке несколько актов КС-2 № {n} с разными отчётными периодами ("
                         + "; ".join(f"{_shown(a)} — {_shown(b)}" for a, b in periods)
                         + "): какой из них верный, не ясно")
        return out
    if periods:
        record = read[0]
        act = record["act"]
        out.update(start=act.get("start"), end=act["finish"], act_amount=act.get("total"),
                   basis=f"Отчётный период из акта КС-2 № {n}",
                   source={"filename": record.get("filename") or "", "title": record.get("title") or ""})
        for other in noted:
            if other.get("date") and act.get("date") and other["date"] != act["date"]:
                out["warnings"].append(f"В сводной акт № {n} датирован {_shown(other['date'])}, а в PDF акта — "
                                       f"{_shown(act['date'])}: взят PDF акта.")
            if other.get("amount") is not None and act.get("total") is not None \
                    and _differs(act["total"], other["amount"]):
                out["warnings"].append(f"В сводной сумма акта № {n} — {_money(other['amount'])}, а в PDF акта — "
                                       f"{_money(act['total'])}.")
        return out
    if pdfs:
        out["warnings"].append(f"В акте КС-2 № {n} из карточки не прочитан отчётный период: "
                               "дата взята из сводной по закрытию.")
    dated = sorted({a["date"] for a in noted if a.get("date")})
    if len(dated) > 1:
        out["reason"] = (f"в сводной по закрытию у акта № {n} несколько дат ({', '.join(map(_shown, dated))}): "
                         "какая верная, не ясно")
        return out
    if dated:
        act = next(a for a in noted if a.get("date"))
        out.update(end=dated[0], act_amount=act.get("amount"), source=act.get("source") or {},
                   basis=(f"Дата подписания акта № {n} из сводной по закрытию, а не окончание работ: отчётного "
                          f"периода в карточке нет — загрузите PDF акта КС-2 № {n}"))
        return out
    out["reason"] = (f"в карточке договора нет акта КС-2 № {n}, и в сводной по закрытию его тоже нет"
                     if not pdfs else
                     f"в акте КС-2 № {n} не прочитан отчётный период, а в сводной по закрытию этого акта нет")
    return out


def resolve(found: dict | None, records: list[dict]) -> dict | None:
    """`found` (`fact.acts`) with the works whose periods the acts date moved from unread into the fact.

    `records` are the documents in the contract card. The result carries
    `act_dates`: one row per act-named period of the KS-6a with its dates,
    where they come from and the checks of its money.
    """
    if found is None or found.get("problem"):
        return found
    labels = {}
    for work in found.get("unread") or []:
        for period in work.get("periods") or []:
            n = number(period["label"]) if not period.get("end") else None
            if n and (period.get("quantity") or period.get("amount")):
                labels.setdefault(n, period["label"])
    acts = [r for r in records if r.get("act")]
    dates = {n: _dates(n, acts, found.get("summary_acts") or []) for n in labels}
    for n, row in dates.items():
        row["label"] = labels[n]
        row["ks6_amount"] = (found.get("period_amounts") or {}).get(labels[n])
        if row["ks6_amount"] is not None and row["act_amount"] is not None \
                and _differs(row["ks6_amount"], row["act_amount"]):
            row["warnings"].append(f"Сумма периода «{labels[n]}» в КС-6а — {_money(row['ks6_amount'])}, а по акту — "
                                   f"{_money(row['act_amount'])}: проверьте ведомость.")
    result = {**found, "acts": list(found.get("acts") or []), "items": list(found.get("items") or []),
              "unread": [], "act_dates": sorted(dates.values(), key=lambda r: int(r["number"]))}
    for work in found.get("unread") or []:
        reason, dated = _dated(work, dates)
        if reason is not None:
            result["unread"].append({**work, "reason": reason})
            continue
        result["items"].append({"item": work["item"], "number": work["number"], "name": work["name"],
                                "unit": work["unit"], "plan_quantity": work.get("plan_quantity")})
        result["acts"].extend({"number": work["number"], "name": work["name"], "unit": work["unit"],
                               "quantity": period.get("quantity") or None, "act_amount": period.get("amount"),
                               "start": period["start"], "end": period["end"], "label": period["label"],
                               "item": work["item"], "dated_by": period.get("dated_by") or "",
                               "source": period.get("source") or work.get("source") or {}} for period in dated)
    result["works"] = len(result["items"])
    return result


def _dated(work: dict, dates: dict):
    """(None, dated periods with volume) of a work the acts date, else (why it stays out of the fact, None)."""
    periods = work.get("periods") or []
    if work.get("reported_quantity") is None or not any(
            number(p["label"]) in dates for p in periods if not p.get("end")):
        return work.get("reason") or "", None
    out = []
    for period in periods:
        if not period.get("quantity") and not period.get("amount"):
            continue  # A sum without a volume is dated too and goes to review in the fact.
        if period.get("end"):
            out.append(period)
            continue
        row = dates.get(number(period["label"]) or "")
        if row is None or not row["end"]:
            why = row["reason"] if row else "период назван не номером акта КС-2"
            return f"Период «{period['label']}» без даты: {why}. Его объём в факт не входит.", None
        out.append({**period, "start": row["start"], "end": row["end"], "dated_by": row["basis"]})
    total = sum(p["quantity"] for p in periods if p.get("quantity"))
    if abs(total - work["reported_quantity"]) > max(_QUANTITY, abs(work["reported_quantity"]) * 1e-7):
        return (f"Объёмы периодов КС-6а в сумме {total:g}, а накопительный итог работы — "
                f"{work['reported_quantity']:g}: требуется сверка ведомости."), None
    return None, out

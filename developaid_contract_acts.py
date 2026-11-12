"""Acts КС-2 of the contract card: one act in force per number and the volumes accumulated since the start.

Owner's decisions of 12.11.2026 (see docs/contract_schedule_control.md):

1. The fact of the works is read from the positions of the acts КС-2: each act adds
   its volumes to those of the earlier acts, from the start of the construction.
2. An act number loaded twice with different content: the later act (by the date of
   the act, then by the upload) is in force; the earlier one stays in the card and is
   shown as replaced. The same content in another file is one act, counted once.
3. An act is dated by the end of its reporting period. Without the period it is dated
   by the date of the act, and every result built on it is preliminary.

An act without a read number stands on its own: whether it repeats another is not known.
"""
from __future__ import annotations

import re
from math import fsum

PRELIMINARY = "Период выполнения неизвестен; для расчёта использована дата акта."


def number(act: dict | None) -> str | None:
    """The act's number as digits without leading zeros («№ 07» → "7"); None when it was not read."""
    digits = re.findall(r"\d+", str((act or {}).get("number") or ""))
    return digits[-1].lstrip("0") or "0" if digits else None


def _shown(iso):
    return ".".join(reversed(iso.split("-"))) if iso else "—"


def _name(text):
    return " ".join(str(text or "").split()).lower()


def _content(act: dict) -> tuple:
    return (act.get("start"), act.get("finish"), act.get("date"),
            round(act["total"], 2) if act.get("total") is not None else None,
            tuple((p.get("number"), _name(p.get("name")), p.get("unit"), round(p["quantity"], 6),
                   round(p["amount"]["total"], 2)) for p in act.get("positions") or []))


def _label(record: dict) -> str:
    act = record["act"]
    return f"акт КС-2 № {act.get('number') or 'без номера'} от {_shown(act.get('date'))} (файл «{record.get('filename') or ''}»)"


def in_force(records: list[dict]) -> dict:
    """The acts in force and, for every other act of the same number, why it is not.

    Returns {"acts": [record, …], "replaced": {sha256: note}, "notes": {sha256: note}}:
    `replaced` names the act that replaced the record or that it copies, `notes` tells the
    act in force which earlier edition it replaced.
    """
    acts = sorted((r for r in records if r.get("act")),
                  key=lambda r: (r["act"].get("date") or "", r.get("uploaded_at") or "", r.get("sha256") or ""))
    groups: dict[str, list[dict]] = {}
    alone = []
    for record in acts:
        n = number(record["act"])
        if n is None:
            alone.append(record)
        else:
            groups.setdefault(n, []).append(record)
    out = {"acts": list(alone), "replaced": {}, "notes": {}}
    for n, group in groups.items():
        current = group[-1]
        out["acts"].append(current)
        earlier = []
        for record in group[:-1]:
            if _content(record["act"]) == _content(current["act"]):
                out["replaced"][record.get("sha256")] = (
                    f"Тот же акт КС-2 № {n} загружен ещё и файлом «{current.get('filename') or ''}»: "
                    "его объёмы учтены один раз.")
                continue
            earlier.append(record)
            out["replaced"][record.get("sha256")] = (
                f"Заменён: в карточке есть более поздняя редакция акта КС-2 № {n} — {_label(current)}. "
                "В накоплении объёмов действует она, этот файл сохранён в карточке.")
        if earlier:
            out["notes"][current.get("sha256")] = (
                f"Действует вместо прежней редакции акта № {n}: " + "; ".join(_label(r) for r in earlier) + ".")
    out["acts"].sort(key=lambda r: (r["act"].get("finish") or r["act"].get("date") or "", r.get("sha256") or ""))
    return out


def _day(act: dict):
    """(date the act's volumes count from, preliminary) or (None, None) when it has no date at all."""
    if act.get("finish"):
        return act["finish"], False
    if act.get("date"):
        return act["date"], True
    return None, None


def accumulated(records: list[dict], cut: str) -> dict:
    """Volumes of the acts in force by position of the act up to `cut`, from the start of the construction.

    An act counts on the end of its reporting period (or the date of the act, preliminary);
    an act that ends after `cut` is not counted on `cut`. A position is one number, name,
    unit and kind of volume (work or materials): different units are never added together.
    """
    chosen = in_force(records)
    positions: dict[tuple, dict] = {}
    acts, excluded, later = [], [], 0
    for record in chosen["acts"]:
        act = record["act"]
        day, preliminary = _day(act)
        row = {"number": act.get("number"), "date": act.get("date"), "start": act.get("start"),
               "finish": act.get("finish"), "day": day, "preliminary": bool(preliminary),
               "sha256": record.get("sha256"), "title": record.get("title") or "",
               "filename": record.get("filename") or "", "positions": len(act.get("positions") or [])}
        if day is None:
            excluded.append({**row, "reason": "у акта не прочитаны ни отчётный период, ни дата составления: "
                                              "его объёмы в накопление не вошли"})
            continue
        if not act.get("positions"):
            excluded.append({**row, "reason": "в акте не прочитаны позиции с объёмами: его объёмы в накопление "
                                              "не вошли"})
            continue
        if cut and day > cut:
            later += 1
            continue
        acts.append(row)
        for p in act["positions"]:
            key = (p.get("number") or "", _name(p.get("name")), p.get("unit") or "", p.get("quantity_basis") or "work")
            found = positions.setdefault(key, {
                "number": key[0], "name": p.get("name") or "", "unit": key[2], "basis": key[3],
                "section": p.get("section"), "group": p.get("group"), "parts": []})
            found["parts"].append({"act": act.get("number"), "day": day, "preliminary": bool(preliminary),
                                   "quantity": p["quantity"], "amount": p["amount"]["total"]})
    out = []
    for item in positions.values():
        parts = item["parts"]
        out.append({**item, "quantity": fsum(x["quantity"] for x in parts),
                    "amount": fsum(x["amount"] for x in parts),
                    "preliminary": any(x["preliminary"] for x in parts)})
    preliminary = any(a["preliminary"] for a in acts)
    return {"cut": cut, "acts": acts, "positions": out, "excluded": excluded, "later": later,
            "replaced": chosen["replaced"], "notes": chosen["notes"], "preliminary": preliminary,
            "note": PRELIMINARY if preliminary else ""}

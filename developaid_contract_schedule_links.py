"""Proposed links from positions of the «Расчёт договорной стоимости» to ГПР lines.

A position and a schedule line are compared by three signs read from their
names: the building (корпус, автостоянка), the part (под- or надземная) and the
kind of work (вертикальные конструкции, плиты перекрытия, лестницы …). A line
inherits building and part from its headings; a position from its group and
section, when its own name is silent. A floor named by the position narrows
the lines to that floor.

A position whose signs are all read gets every leaf line with the same signs.
Spread over several lines, its cost is divided by their duration, and this is
labelled as an assumption (owner's decision 2А). Anything less certain is a
review item with its reason, never a guess: several buildings, an unread kind,
no line. A position of a supplementary agreement with clear signs and no line
is additional scope without a term (3А) and stays outside the accumulated plan.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re

# Order matters: the first kind found in the name wins.
_KINDS = (
    ("piles", "оголовки свай", r"свай"),
    ("preparation", "бетонная подготовка", r"бетонн\w*\s+подготовк"),
    ("screed", "стяжка", r"стяжк"),
    ("insulation", "гидроизоляция", r"изоляц"),
    ("foundation", "фундаментная плита", r"фундаментн\w*\s+плит|ростверк|армирование\s+фп"),
    ("stairs", "лестницы", r"лестни"),
    ("ramp", "пандус", r"пандус"),
    ("vertical", "стены, колонны и пилоны", r"вертикальн\w*\s+конструкц|\bстен|колонн|пилон"),
    ("slab", "плиты перекрытия и покрытия", r"плит\w*\s+(?:перекр|перект|покрыт)|перекрыти|перектыти"),
    ("crane", "башенные краны", r"башенн\w*\s+кран"),
    ("site", "организация площадки", r"мобилизац|организаци\w*\s+строительн"),
)
_PART = ((r"надземн|выше\s+отм", "above"), (r"подземн|ниже\s+отм|автостоянк|паркинг", "below"))
_BUILDING_LIST = re.compile(r"корпус\w*\s*((?:№?\s*\d+\s*(?:,|и)?\s*)+)", re.I)
_BUILDING_SHORT = re.compile(r"(?<![\wА-яЁё])К\s?(\d+)(?![\wА-яЁё])")
_FLOOR = re.compile(r"(?<![-−–\d])(\d+)\s*-?\s*(?:ого|го|ый|ой|й)?\s+этаж", re.I)
# Work of the whole site: a position and a line that both name no building belong together.
_SITE_WIDE = {"site"}
_SIDE = {"above": "надземной", "below": "подземной"}
SHARE_ASSUMPTION = ("Стоимость позиции разделена между строками графика пропорционально их длительности: "
                    "это допущение, а не данные расчёта.")


def _text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def kind(name):
    low = _text(name).lower()
    return next(((key, label) for key, label, pattern in _KINDS if re.search(pattern, low)), (None, None))


def buildings(name):
    text = _text(name)
    found = set()
    for match in _BUILDING_LIST.finditer(text):
        found |= {f"корпус {n}" for n in re.findall(r"\d+", match[1])}
    found |= {f"корпус {n}" for n in _BUILDING_SHORT.findall(text)}
    if re.search(r"автостоянк|паркинг", text, re.I):
        found.add("автостоянка")
    return found


def part(name):
    low = _text(name).lower()
    return next((value for pattern, value in _PART if re.search(pattern, low)), None)


def floors(name):
    return {int(n) for n in _FLOOR.findall(_text(name))}


def _first(read, *names):
    """The first non-empty sign, from the most specific name to the broadest."""
    for name in names:
        value = read(name)
        if value:
            return value
    return None


def _days(line):
    start, finish = dt.date.fromisoformat(line["start"]), dt.date.fromisoformat(line["finish"])
    return (finish - start).days + 1


def duration_shares(lines):
    total = sum(_days(line) for line in lines)
    return [_days(line) / total for line in lines]


def position_key(position):
    """One position in every edition: its number, name and unit, not its place in a file."""
    identity = [_text(position.get("number")), _text(position.get("name")).casefold(),
                _text(position.get("unit")).casefold()]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest()


def leaves(schedule):
    """Dated work lines of the schedule: headings sum their works and take no position."""
    lines = (schedule or {}).get("lines") or []
    parents = {line.get("parent") for line in lines}
    return [line for line in lines if line["code"] not in parents and line.get("start") and line.get("finish")]


def summary(positions, schedule):
    """Lines no position is linked to and the count of every status."""
    used = {line["code"] for p in positions if p["status"] in ("confirmed", "proposed") for line in p["lines"]}
    unlinked = [{"code": s["line"]["code"], "name": s["line"]["name"]}
                for s in _line_signs((schedule or {}).get("lines") or []) if s["line"]["code"] not in used]
    counts = {status: sum(1 for p in positions if p["status"] == status)
              for status in ("confirmed", "proposed", "review", "extra")}
    return {"lines_without_positions": unlinked, "counts": counts}


def _codes(signs, shown=4):
    codes = [s["line"]["code"] for s in signs]
    rest = len(codes) - shown
    return ", ".join(codes[:shown]) + (f" и ещё {rest}" if rest > 0 else "")


def _line_signs(lines):
    by_code = {line["code"]: line for line in lines}
    parents = {line["parent"] for line in lines if line.get("parent")}
    signs = []
    for line in lines:
        if line["code"] in parents:
            continue
        chain, code = [], line["code"]
        while code in by_code:
            chain.append(by_code[code]["name"])
            code = by_code[code].get("parent")
        signs.append({"line": line, "kind": kind(line["name"])[0], "buildings": _first(buildings, *chain) or set(),
                      "part": _first(part, *chain), "floors": floors(line["name"]),
                      # A heading named by the numbering but absent from the schedule (4.1 without 4).
                      "missing": code})
    return signs


def propose(estimate, schedule, *, agreement=False):
    """Links of every position of `estimate` to leaf lines of `schedule`."""
    lines = [line for line in (schedule or {}).get("lines") or []]
    signs = _line_signs(lines)
    positions = []
    for index, position in enumerate(estimate.get("positions") or []):
        group = (position.get("group") or {}).get("name")
        names = (position.get("name"), group, position.get("section"))
        key, label = kind(position.get("name"))
        if key is None:
            key, label = kind(group)
        where = _first(buildings, *names) or set()
        side = _first(part, *names)
        floor = floors(position.get("name"))
        item = {"index": index, "key": position_key(position), "number": position.get("number"),
                "name": position.get("name"), "unit": position.get("unit"), "section": position.get("section"),
                "amount": (position.get("amount") or {}).get("total"), "quantity": position.get("quantity"),
                "kind": label, "buildings": sorted(where), "part": side, "lines": [], "status": "review",
                "reason": "", "assumption": ""}
        positions.append(item)
        if not lines:
            item["reason"] = ("График производства работ этой или прежней редакции не загружен: "
                              "сопоставить позицию не с чем.")
            continue
        if key is None:
            item["reason"] = "Вид работ по названию позиции не определён."
            continue
        if not where and key not in _SITE_WIDE:
            item["reason"] = "Корпус или автостоянка в позиции не названы."
            continue
        if len(where) > 1:
            item["reason"] = ("Позиция относится к нескольким объектам (" + ", ".join(sorted(where))
                              + "): как разделить её между ними, расчёт не говорит.")
            continue
        alike = [s for s in signs if s["kind"] == key and s["buildings"] == where
                 and (not floor or s["floors"] & floor)
                 and s["line"].get("start") and s["line"].get("finish")]
        found = [s for s in alike if s["part"] == side] if side else alike
        unsure = [s for s in alike if s["part"] is None] if side else []
        place = next(iter(where), "вся площадка")
        if side and not found and unsure:
            headings = sorted({s["missing"] for s in unsure if s["missing"]})
            item["reason"] = (("Строки графика {} подходят" if len(unsure) > 1 else "Строка графика {} подходит")
                              .format(_codes(unsure)) + " по объекту "
                              f"«{place}» и виду работ, но в графике не сказано, подземная это часть или надземная"
                              + (f": строки пронумерованы под разделом {', '.join(headings)}, а самого раздела в графике нет" if headings
                                 else "") + ".")
            continue
        if not side and len({s["part"] for s in found}) > 1:
            item["reason"] = (f"Позиция не говорит, подземная это часть или надземная, а строки «{label}» "
                              f"для объекта «{place}» есть в графике в обеих частях.")
            continue
        if not found:
            if agreement:
                item.update(status="extra", reason="Дополнительный объём без срока: в графике нет строки "
                                                   "для этой работы, в накопленный план позиция не входит.")
            else:
                item["reason"] = (f"В графике нет строки «{label}» для объекта «{place}»"
                                  + (f" в {_SIDE[side]} части" if side else "") + ".")
            continue
        item["status"] = "proposed"
        item["lines"] = linked([s["line"] for s in found])
        if len(found) > 1:
            item["assumption"] = SHARE_ASSUMPTION
    return {"positions": positions, **summary(positions, schedule)}


def linked(lines, shares=None):
    shares = duration_shares(lines) if shares is None else shares
    return [{"code": line["code"], "name": line["name"], "start": line["start"], "finish": line["finish"],
             "share": share} for line, share in zip(lines, shares)]

"""Proposed links from positions of the «Расчёт договорной стоимости» to ГПР lines.

A position and a schedule line are compared by three signs read from their
names: the building (корпус, автостоянка), the part (под- or надземная) and the
kind of work (вертикальные конструкции, плиты перекрытия, лестницы …). A line
inherits building and part from its headings; a position from its group and
section, when its own name is silent. A floor named by the position narrows
the lines to that floor.

A position numbered and named like a line of the schedule (4.1 «(В-3) Витражная
система …» in both) gets that line; so does a position under a heading of the
estimate numbered and named like a line. Such a match decides alone: a number
repeated in the schedule, or a line of another building or part, is a review item, not
a link by the kind of work. A repeated number is linked by the owner's hand, the line
named alike ticked in advance; a line of another building carries the schedule's object
as a `fix` the owner may take for the whole estimate at once. Otherwise a position whose signs are all read gets
every leaf line with the same signs.
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
from collections import Counter

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
    try:
        start, finish = dt.date.fromisoformat(line["start"]), dt.date.fromisoformat(line["finish"])
    except (KeyError, TypeError, ValueError):
        return 0
    return max(0, (finish - start).days + 1)


def duration_shares(lines):
    days = [_days(line) for line in lines]
    if not days or any(value <= 0 for value in days):
        raise ValueError("У строки графика нет корректного срока: проверьте даты начала и окончания.")
    return [value / sum(days) for value in days]


def position_key(position):
    """One position in every edition: its number, name and unit, not its place in a file."""
    identity = [_text(position.get("number")), _text(position.get("name")).casefold(),
                _text(position.get("unit")).casefold()]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest()


def leaves(schedule):
    """Dated work lines of the schedule: headings sum their works and take no position."""
    lines = (schedule or {}).get("lines") or []
    parents = {line.get("parent") for line in lines}
    ambiguous = _ambiguous_codes(lines)
    return [line for line in lines if line["code"] not in parents
            and line["code"] not in ambiguous and _days(line) > 0]


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


def _words(name):
    return re.findall(r"[0-9a-zа-я]+", _text(name).casefold().replace("ё", "е"))


def _same_name(one, other, words=6):
    """The first words of the shorter name run on in the other: a schedule cuts long names short."""
    one, other = _words(one), _words(other)
    short, long = sorted((one, other), key=len)
    head = short[:words]
    return bool(head) and any(long[i:i + len(head)] == head for i in range(len(long) - len(head) + 1))


def _numbered(position, signs, lines):
    """Leaf lines numbered and named like the position, else like the heading it is numbered under.

    Returns those lines and how many lines of the schedule carry that number; nothing when
    neither the position nor its heading is in the schedule by number and name.
    """
    group = position.get("group") or {}
    for number, name in ((position.get("number"), position.get("name")), (group.get("number"), group.get("name"))):
        number = _text(number).rstrip(".")
        found = [s for s in signs if number and printed(s["line"]) == number and _same_name(s["line"]["name"], name)]
        if found:
            return found, [line for line in lines if printed(line) == number]
    return [], []


def printed(line):
    """The number printed in the schedule: a repeated one gets its own code from the reader."""
    return line.get("printed") or line["code"]


def _places(where):
    return ", ".join(sorted(where))


def _ambiguous_codes(lines):
    """Legacy parses can reuse an identity; neither it nor its children are safe links.

    Do not renumber a saved parse without its PDF: existing owner choices use
    these identities, and a repeated heading's child cannot recover its parent.
    """
    repeated = {code for code, count in Counter(line["code"] for line in lines).items() if count > 1}
    while True:
        children = {line["code"] for line in lines if line.get("parent") in repeated}
        if children <= repeated:
            return repeated
        repeated.update(children)


def _line_signs(lines):
    ambiguous = _ambiguous_codes(lines)
    by_code = {line["code"]: line for line in lines if line["code"] not in ambiguous}
    parents = {line["parent"] for line in lines if line.get("parent")}
    signs = []
    for line in lines:
        if line["code"] in parents or line["code"] in ambiguous:
            continue
        chain, code, seen = [], line["code"], set()
        while code in by_code and code not in seen:
            seen.add(code)
            chain.append(by_code[code]["name"])
            code = by_code[code].get("parent")
        # A schedule by buildings names the building in an unnumbered title over its lines.
        chain.append(line.get("section"))
        signs.append({"line": line, "kind": kind(line["name"])[0], "buildings": _first(buildings, *chain) or set(),
                      "part": _first(part, *chain), "floors": floors(line["name"]),
                      # A heading named by the numbering but absent from the schedule (4.1 without 4).
                      "missing": code})
    return signs


def propose(estimate, schedule, *, agreement=False):
    """Links of every position of `estimate` to leaf lines of `schedule`."""
    lines = [line for line in (schedule or {}).get("lines") or []]
    signs = _line_signs(lines)
    ambiguous = _ambiguous_codes(lines)
    ambiguous_reason = ("В сохранённом разборе графика повторяются коды строк: "
                        + ", ".join(sorted(ambiguous))
                        + ". Связь по этим кодам неоднозначна: нужен повторный разбор исходного PDF. "
                        "Прежние связи с такими строками не применяются.") if ambiguous else ""
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
                "reason": "", "assumption": "", "suggested": [], "fix": None}
        positions.append(item)
        if not lines:
            item["reason"] = ("График производства работ этой или прежней редакции не загружен: "
                              "сопоставить позицию не с чем.")
            continue
        numbers = {_text(position.get("number")).rstrip("."),
                   _text((position.get("group") or {}).get("number")).rstrip(".")}
        if any(line["code"] in ambiguous and printed(line) in numbers for line in lines):
            item["reason"] = ambiguous_reason
            continue
        same, numbered = _numbered(position, signs, lines)
        if same:
            line = same[0]["line"]
            there = same[0]["buildings"]
            repeated = len(numbered)
            if repeated > 1:
                # Owner's decision А: the owner picks the line; the line named alike is only ticked in advance.
                lines_word = "строки" if repeated % 10 in (2, 3, 4) and repeated % 100 not in (12, 13, 14) else "строк"
                alike = [s["line"]["code"] for s in same]
                item["suggested"] = alike
                item["reason"] = (f"В графике {repeated} {lines_word} с номером {printed(line)}: "
                                  + "; ".join(f"«{x['code']}» {_text(x['name'])[:60]}" for x in numbered)
                                  + ". По номеру связь не определить: выберите строку вручную"
                                  + (f" — по названию подходит «{alike[0]}»" if len(alike) == 1 else "")
                                  + ". Подрядчика попросите исправить нумерацию графика.")
            elif where and there and where != there:
                item["reason"] = (f"Строка графика {line['code']} совпадает с позицией по номеру и названию, но в "
                                  f"графике она относится к объекту «{_places(there)}», а в расчёте позиция стоит "
                                  f"в разделе объекта «{_places(where)}».")
                # Which object is right is the owner's answer: one button takes the schedule's object.
                if _days(line) > 0:
                    item["fix"] = {"lines": [line["code"]], "object": _places(there), "estimate": _places(where)}
            elif side and same[0]["part"] and side != same[0]["part"]:
                item["reason"] = (f"Строка графика {line['code']} совпадает с позицией по номеру и названию, но в "
                                  f"графике она относится к {_SIDE[same[0]['part']]} части, а в расчёте позиция стоит "
                                  f"в {_SIDE[side]} части.")
            elif not (line.get("start") and line.get("finish")):
                item["reason"] = f"У строки графика {line['code']} нет дат начала и окончания."
            elif _days(line) <= 0:
                item["reason"] = (f"У строки графика {line['code']} нет корректного срока: "
                                  "проверьте даты начала и окончания.")
            else:
                item.update(status="proposed", lines=linked([line]))
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
                 and (not floor or s["floors"] & floor)]
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
            if ambiguous:
                item["reason"] = ambiguous_reason
            elif agreement:
                item.update(status="extra", reason="Дополнительный объём без срока: в графике нет строки "
                                                   "для этой работы, в накопленный план позиция не входит.")
            else:
                item["reason"] = (f"В графике нет строки «{label}» для объекта «{place}»"
                                  + (f" в {_SIDE[side]} части" if side else "") + ".")
            continue
        if any(_days(s["line"]) <= 0 for s in found):
            item["reason"] = (f"У строк графика {_codes(found)} нет корректного срока: "
                              "проверьте даты начала и окончания.")
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

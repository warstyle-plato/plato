"""Что не будет израсходовано до ввода — и о чём можно просить банк.

«Потребность в отдельных статьях уже не будет израсходована, если заключён
договор по этой статье и он в рамках лимита, но с учётом ГУ этот лимит никогда
не будет использован полностью до РнВ, а значит можно попросить банк
перераспределить остаток в другую главу» (владелец, 30.08.2026).

У неизрасходованного две половины, и они разной надёжности.

**Свободное от договоров** — `лимит − заключено` по статье. Берётся прямо из
РСС (`read_estimate`: смета, заключено, оплачено, выполнено), сшивать ничего не
надо. Строки РСС идут деревом, и сумма по всем кодам считает главу дважды —
свободное складывается только по листьям.

**Гарантийные удержания** — часть уже заключённого, которая до ввода не уйдёт.
Здесь сшивка, и она непрямая. Номером договора не сшить: в РСС стоит договор с
генподрядчиком (СП Менеджмент), а реестр ГУ ведёт он сам, и в нём его договоры
с субподрядчиками — этих номеров в РСС нет вовсе. Сшивается по ЛИЦУ: заказчик
строки реестра ищется среди подрядчиков РСС, и если он там один со своей
статьёй — сумма ложится на неё. Основание — слова владельца (30.08.2026): ГУ,
удержанные с генподрядчика, ПРИМЕРНО равны сумме ГУ по его договорам с
субчиками. Значит это оценка, а не выписка из договора с ним, и так и
подписано: выданная за измеренную, она читалась бы как основание для разговора
с банком.

Что не сшилось — стоит отдельной строкой с именем и суммой. Подрядчик, стоящий
в РСС на нескольких статьях, не делится пропорционально: разложить ГУ долями
значит выдать выдуманное число за посчитанное, а разговор с банком идёт про
конкретную главу. Удержание без даты выплаты — «срок не назван», а не «после
ввода»: своя сумма, в перераспределение не идёт.

Источником статья считается не по одному свободному лимиту. «Перераспределение
лимитов внутри банковской РСС можно рассматривать только там, где работы
завершены или завершатся судя по актированию, договор заключён и очевидно
нового скорее всего не будет» (владелец, 01.09.2026). Первая версия называла
«не будет выбрано» всё свободное подряд — и первыми в списке стояли резервы
2.8/2.9, у которых договоров нет по построению («Резервы разве не будут
выбраны???»), а за ними статьи, по которым договор ещё не заключён вовсе.

Ничего сверх этого здесь не считается: лимиты, потребность, структурный
дефицит и сроки считает дашборд, и второго счёта тех же величин тут нет.
"""

from __future__ import annotations

import datetime
from typing import Any

import developaid_monitor_crew as crew

__all__ = ["unspent"]


def _day(value: Any) -> datetime.date | None:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        return None


def _root(code: str) -> str:
    return str(code or "").split(".")[0]


def _leaves(rows: list[dict[str, Any]]) -> set[str]:
    """Коды, у которых нет детей. По ним и только по ним складывается сумма."""
    codes = {str(row.get("code") or "") for row in rows if row.get("code")}
    parents = {code.rsplit(".", 1)[0] for code in codes if "." in code}
    return {code for code in codes if code not in parents}


def _codes_of_parties(contracts: dict[str, Any] | None,
                      roots: tuple[str, ...]) -> list[tuple[str, set[str]]]:
    """Пара «подрядчик РСС → его статьи». Из реестра договоров, как есть."""
    found: dict[str, tuple[str, set[str]]] = {}
    for row in ((contracts or {}).get("rows") or []):
        name = str(row.get("contractor") or "").strip()
        code = str(row.get("estimate_code") or "").strip()
        if not name or not code or _root(code) not in roots:
            continue
        key = crew.name_key(name)
        title, codes = found.get(key, (name, set()))
        codes.add(code)
        found[key] = (title, codes)
    return [(title, codes) for title, codes in found.values()]


def _match(who: str, parties: list[tuple[str, set[str]]]) -> tuple[str, set[str]] | None:
    for title, codes in parties:
        if crew.same_party(who, title):
            return title, codes
    return None


def _retention_by_code(retention: dict[str, Any] | None,
                       contracts: dict[str, Any] | None,
                       horizon: Any,
                       roots: tuple[str, ...]) -> dict[str, Any]:
    """Развести остаток ГУ по статьям через лицо, а не через номер договора."""
    blank: dict[str, Any] = {
        "by_code": {}, "matched": 0.0, "unsplit": [], "unmatched": [],
        "unmatched_total": 0.0, "unsplit_total": 0.0, "undated": 0.0,
        "paid_before_horizon": 0.0, "known": False, "reason": "",
    }
    rows = (retention or {}).get("rows") or []
    if not rows:
        return {**blank, "reason": "реестр ГУ не загружен"}
    parties = _codes_of_parties(contracts, roots)
    if not parties:
        return {**blank,
                "reason": "в РСС нет реестра договоров — статью для ГУ назвать нечем"}
    edge = _day(horizon)
    if edge is None:
        return {**blank,
                "reason": "горизонт стройки не определён — «после ввода» не от чего отсчитывать"}

    # Сначала копим по лицу: одна строка реестра — один субподряд, а просить у
    # банка перераспределение будут по статье генподрядчика.
    per_party: dict[str, dict[str, Any]] = {}
    undated = before = 0.0
    for row in rows:
        left = float(row.get("left") or 0.0)
        if left <= 0:
            continue
        due = _day(row.get("due"))
        if due is None:
            undated += left
            continue
        if due <= edge:
            before += left
            continue
        # Реестр бывает двух видов: наш (контрагент — подрядчик РСС) и
        # генподрядчика (подрядчик РСС стоит в «Заказчике»). Пробуем обе
        # стороны, не угадывая вид файла заранее.
        who = str(row.get("customer") or "").strip()
        hit = _match(who, parties) if who else None
        if hit is None:
            who = str(row.get("counterparty") or "").strip()
            hit = _match(who, parties) if who else None
        name = hit[0] if hit else (str(row.get("customer") or "")
                                   or str(row.get("counterparty") or "")).strip()
        item = per_party.setdefault(
            name or "без имени",
            {"name": name or "без имени", "left": 0.0,
             "codes": sorted(hit[1]) if hit else [], "known": hit is not None})
        item["left"] += left

    by_code: dict[str, float] = {}
    matched = 0.0
    unsplit: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    for item in per_party.values():
        if not item["known"]:
            unmatched.append(item)
        elif len(item["codes"]) == 1:
            code = item["codes"][0]
            by_code[code] = by_code.get(code, 0.0) + item["left"]
            matched += item["left"]
        else:
            unsplit.append(item)
    return {
        "by_code": by_code,
        "matched": matched,
        "unsplit": sorted(unsplit, key=lambda item: -item["left"]),
        "unsplit_total": sum(item["left"] for item in unsplit),
        "unmatched": sorted(unmatched, key=lambda item: -item["left"]),
        "unmatched_total": sum(item["left"] for item in unmatched),
        "undated": undated,
        "paid_before_horizon": before,
        "known": True,
        "reason": "",
    }


# Договор считается закрытым актами, когда принято не меньше этой доли его
# суммы. Порог назван на экране: число без порога читается как измеренное.
CLOSED_BY_ACTS_SHARE = 0.9


def unspent(estimate: dict[str, Any], *,
            contracts: dict[str, Any] | None = None,
            retention: dict[str, Any] | None = None,
            horizon: Any = None,
            needy: list[dict[str, Any]] | None = None,
            programme_left: dict[str, float] | None = None,
            roots: tuple[str, ...] = ("2", "3"),
            retention_roots: tuple[str, ...] = ("2",),
            not_articles: frozenset[str] | set[str] = frozenset({"2.8", "2.9"})) -> dict[str, Any]:
    """Постатейно: откуда лимит можно просить и кому его не хватает.

    Источником перераспределения статья считается только там, где «работы
    завершены или завершатся судя по актированию, договор заключён и очевидно
    нового скорее всего не будет» (владелец, 01.09.2026). То есть:
    договор есть, акты закрыли не меньше `CLOSED_BY_ACTS_SHARE` его суммы —
    или по программе РСС после среза статья не тратит ничего. Статья без
    договора источником не считается: свободный лимит у неё есть, но новые
    договоры по ней ещё придут. Резерв 2.8/2.9 — не статья вовсе: у него нет
    договоров по построению, и «не будет выбран» о нём неверно — он гасит
    нехватку других. Гарантийные удержания относятся только к главе 2: в
    главе 3 подрядных договоров с удержанием нет.

    `needy` — статьи, которым своего лимита не хватает; их считает водопад
    дашборда, здесь они только названы рядом с источниками: перераспределять
    есть куда, и это вторая половина ответа.
    """
    rows = (estimate or {}).get("rows") or []
    leaves = {str(row.get("code") or "") for row in rows if row.get("is_leaf")} or _leaves(rows)
    gu = _retention_by_code(retention, contracts, horizon, retention_roots)
    programme_left = programme_left or {}

    sources: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for row in rows:
        code = str(row.get("code") or "")
        if not code or _root(code) not in roots or code not in leaves:
            continue
        if code in not_articles:
            continue
        limit = float(row.get("estimate") or 0.0)
        contracted = float(row.get("contracted") or 0.0)
        completed = float(row.get("completed") or 0.0)
        deferred = float(gu["by_code"].get(code) or 0.0)
        free = max(0.0, limit - contracted)
        if free <= 0 and deferred <= 0:
            continue
        acts_share = (completed / contracted) if contracted > 0 else None
        left = programme_left.get(code)
        item = {
            "code": code,
            "name": str(row.get("article") or ""),
            "limit": limit,
            "contracted": contracted,
            "completed": completed,
            "acts_share": acts_share,
            "paid": float(row.get("paid") or 0.0),
            "free": free,
            "retention_deferred": deferred,
            "programme_left": left,
        }
        if contracted <= 0:
            item["reason"] = "договора нет — новые договоры по статье ещё придут"
            # ГУ без договора в РСС не бывает; свободный лимит — не источник.
            excluded.append(item)
            continue
        closed = acts_share is not None and acts_share >= CLOSED_BY_ACTS_SHARE
        # «Нового не будет» проверяется программой РСС: если после среза она
        # планирует по статье больше, чем осталось выплатить по заключённым
        # договорам, — новые договоры ожидаются, и свободный лимит уйдёт на них.
        # Реклама с договорами, принятыми на 91%, по актам выглядит закрытой, а
        # тратится до конца продаж — программа это и показывает.
        remainder = max(0.0, contracted - float(row.get("paid") or 0.0))
        new_expected = left is not None and left > remainder + 0.01 * max(limit, 1.0)
        if closed and not new_expected:
            item["basis"] = (f"принято по актам {acts_share * 100:.0f}% договора"
                             + (", по программе РСС после среза новых трат нет"
                                if left is not None
                                else "; программа РСС по статье не прочитана — судим по актам"))
            item["unspent"] = free + deferred
            sources.append(item)
        elif deferred > 0:
            # Договор ещё в работе, но удержанное по актам до ввода не
            # выплатится в любом случае — источником идёт только оно.
            item["basis"] = "только ГУ: договор в работе, удержанное до ввода не выплатится"
            item["free_in_work"] = free
            item["free"] = 0.0
            item["unspent"] = deferred
            sources.append(item)
        else:
            if not closed:
                item["reason"] = f"в работе: принято по актам {acts_share * 100:.0f}% договора"
            else:
                item["reason"] = ("по программе РСС после среза ещё "
                                  f"{left / 1e6:,.1f} млн — больше остатка по договорам "
                                  f"({remainder / 1e6:,.1f} млн): новые траты ожидаются"
                                  ).replace(",", " ")
            excluded.append(item)
    sources.sort(key=lambda item: -item["unspent"])
    excluded.sort(key=lambda item: -(item["free"] + item["retention_deferred"]))
    free_total = sum(item["free"] for item in sources)
    deferred_total = sum(item["retention_deferred"] for item in sources)

    need_rows = []
    for row in (needy or []):
        need_rows.append({
            "code": str(row.get("code") or ""),
            "name": str(row.get("name") or ""),
            "need": float(row.get("need_total") or 0.0),
            "own_limit": float(row.get("opening_limit") or 0.0),
            "from_reserve": float(row.get("reserve_take") or 0.0),
            "shortage": float(row.get("unfunded_take") or 0.0),
            "from": row.get("first_reserve_month"),
        })
    need_rows.sort(key=lambda item: -item["shortage"])
    shortage_total = sum(item["shortage"] for item in need_rows)
    total = free_total + deferred_total
    return {
        "sources": sources,
        "excluded": excluded,
        "free_total": free_total,
        "retention_deferred_total": deferred_total,
        "total": total,
        "excluded_free_total": sum(item["free"] for item in excluded),
        "criterion": (f"договор заключён, по актам принято не меньше "
                      f"{CLOSED_BY_ACTS_SHARE * 100:.0f}% его суммы, и программа РСС "
                      "после среза не планирует по статье больше, чем осталось "
                      "выплатить по договорам"),
        # ГУ генподрядчика в его статью кладётся оценкой, и это сказано вслух.
        "retention_is_estimate": bool(gu["by_code"]),
        "retention": {key: gu[key] for key in
                      ("known", "reason", "matched", "unsplit", "unsplit_total",
                       "unmatched", "unmatched_total", "undated",
                       "paid_before_horizon")},
        "needy": need_rows[:20],
        "shortage_total": shortage_total,
        "covers": total >= shortage_total if shortage_total > 0 else None,
    }

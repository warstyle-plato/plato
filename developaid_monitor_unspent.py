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


def unspent(estimate: dict[str, Any], *,
            contracts: dict[str, Any] | None = None,
            retention: dict[str, Any] | None = None,
            horizon: Any = None,
            needy: dict[str, float] | None = None,
            roots: tuple[str, ...] = ("2", "3")) -> dict[str, Any]:
    """Постатейно: лимит, заключено, свободное и отложенное в ГУ.

    `needy` — статьи, которым своего лимита не хватает; их считает водопад
    дашборда, здесь они только называются рядом: перераспределять есть куда, и
    это вторая половина ответа.
    """
    rows = (estimate or {}).get("rows") or []
    leaves = _leaves(rows)
    gu = _retention_by_code(retention, contracts, horizon, roots)

    items: list[dict[str, Any]] = []
    free_total = 0.0
    for row in rows:
        code = str(row.get("code") or "")
        if not code or _root(code) not in roots:
            continue
        limit = float(row.get("estimate") or 0.0)
        contracted = float(row.get("contracted") or 0.0)
        deferred = float(gu["by_code"].get(code) or 0.0)
        free = max(0.0, limit - contracted) if code in leaves else 0.0
        if free <= 0 and deferred <= 0:
            continue
        free_total += free
        items.append({
            "code": code,
            "name": str(row.get("article") or ""),
            "limit": limit,
            "contracted": contracted,
            "paid": float(row.get("paid") or 0.0),
            "free": free,
            "retention_deferred": deferred,
            "unspent": free + deferred,
            "leaf": code in leaves,
        })
    items.sort(key=lambda item: -item["unspent"])
    deferred_total = sum(float(value) for value in gu["by_code"].values())
    return {
        "articles": items,
        "free_total": free_total,
        "retention_deferred_total": deferred_total,
        "total": free_total + deferred_total,
        # ГУ генподрядчика в его статью кладётся оценкой, и это сказано вслух.
        "retention_is_estimate": bool(gu["by_code"]),
        "retention": {key: gu[key] for key in
                      ("known", "reason", "matched", "unsplit", "unsplit_total",
                       "unmatched", "unmatched_total", "undated",
                       "paid_before_horizon")},
        "needy": [{"code": code, "shortage": float(value)}
                  for code, value in sorted((needy or {}).items(),
                                            key=lambda pair: -float(pair[1]))
                  if float(value) > 0][:20],
    }

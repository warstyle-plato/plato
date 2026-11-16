"""Сверка сохранённых КРТ с конкретным сбором, без выдачи памяти за рынок."""
from __future__ import annotations

import re
from typing import Any

from auction_search.parsing import deadline_is_current



def lot_url_key(url: str) -> str:
    """У Росэлторга /procedure/ID и /procedure/ID/1 — один лот."""
    match = re.fullmatch(r"https://(?:www\.)?roseltorg\.ru/procedure/(\d+)(?:/(\d+))?/?", url)
    if match:
        return f"https://www.roseltorg.ru/procedure/{match[1]}/{match[2] or '1'}"
    return url

def expected_lots(known: dict[str, Any]) -> list[dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    for slug, entry in known.items():
        for lot in (entry or {}).get("lots") or []:
            url = str(lot.get("url") or "")
            if not url or not deadline_is_current(lot.get("deadline")):
                continue
            row = by_url.setdefault(lot_url_key(url), {**lot, "url": lot_url_key(url), "slugs": []})
            if slug not in row["slugs"]:
                row["slugs"].append(slug)
    return list(by_url.values())


def reconcile(expected: list[dict[str, Any]], collected: list[dict[str, Any]],
              checks: dict[str, Any], *, source: str = "all") -> dict[str, Any]:
    actual = {lot_url_key(str((row.get("source") or {}).get("lot_url") or row.get("url") or "")): row
              for row in collected}
    checks = {lot_url_key(url): check for url, check in checks.items()}
    rows = []
    for old in expected:
        url = old["url"]
        lot = actual.get(lot_url_key(url))
        check = checks.get(lot_url_key(url)) or {}
        state, reason = check.get("state", "unread"), check.get("reason", "")
        if lot is not None:
            if lot.get("main_selection", True):
                state, reason = "included", "Есть в основной подборке"
            else:
                state = "excluded"
                reason = "; ".join((lot.get("quality") or {}).get("reasons") or
                                   (lot.get("screening") or {}).get("exclusion_reasons") or
                                   ["Не прошёл условия основной подборки"])
        elif state == "collected":
            state = "excluded"
            reason = "Карточка прочитана, но не прошла условия основной подборки"
        elif not reason:
            reason = ("Карточка не прочитана в выбранном наборе источников"
                      if source not in {"all", "roseltorg", "ros"}
                      else "Карточка не прочитана в этом сборе; актуальность не подтверждена")
        rows.append({"url": url, "name": old.get("address") or old.get("title") or url,
                     "slugs": old["slugs"], "saved_deadline": old.get("deadline"),
                     "state": state, "reason": reason})
    return {"expected": len(rows), "included": sum(r["state"] == "included" for r in rows),
            "rows": rows}

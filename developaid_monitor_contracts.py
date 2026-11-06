"""A source-backed contract view, not another financial register.

RSS is the primary monetary source. Cumulative books add quantities and a
separately identified closing register; yearly book totals never become the
full price of a contract. The caller must authenticate before calling here.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import importlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import developaid_actuals as actuals
import developaid_monitor as monitor


class ContractProblem(ValueError):
    """A controlled, safe message that may be returned to an authenticated user."""


def _date(value: Any) -> str | None:
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError:
        parsed = actuals._date(value)
        return parsed.isoformat() if parsed else None


def _cut(value: str) -> str:
    value = value or dt.date.today().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ContractProblem("Дата среза нужна в виде ГГГГ-ММ-ДД.")
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError:
        raise ContractProblem("Проверьте дату среза.") from None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        value = value.replace("\xa0", "").replace(" ", "").replace(",", ".")
        if not value or value.startswith(("=", "#")):
            return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _norm(value: Any) -> str:
    value = str(value or "").casefold().replace("ё", "е")
    return re.sub(r"\s+", " ", re.sub(r'[«»“”"]', "", value)).strip()


def _contract_number(value: Any) -> str:
    # Strip only explicit decoration. Punctuation within a number is identity:
    # 12/3 and 123 must not silently become the same contract.
    value = re.split(r"\s+от\s+", str(value or ""), maxsplit=1, flags=re.I)[0]
    value = re.sub(r"^\s*(?:договор\b\s*)?№?\s*", "", value, flags=re.I)
    return re.sub(r"\s+", "", value).casefold().replace("ё", "е")


def _base_key(item: dict) -> tuple[str, str, str]:
    return (_norm(item.get("customer")), _norm(item.get("contractor")),
            _contract_number(item.get("contract")))


def _source(value: Any, label: str = "") -> dict:
    source = dict(value) if isinstance(value, dict) else {}
    if label:
        source.setdefault("label", label)
    return source


def _warnings(values) -> list[str]:
    out = []
    for value in values or []:
        if isinstance(value, dict):
            value = value.get("message") or value.get("detail") or value.get("code")
        if isinstance(value, str) and value and value not in out:
            out.append(value)
    return out


def _archive(project: str, cut: str) -> dict | None:
    try:
        ledgers = importlib.import_module("developaid_monitor_ledgers")
    except ModuleNotFoundError as exc:
        if exc.name != "developaid_monitor_ledgers":
            raise
        return None
    return ledgers.latest_snapshot(project, cut)


def _read_rss(project: str, cut: str) -> tuple[list[dict], str | None, list[str]]:
    path = monitor._latest(project, "estimate", ".xlsx", cut)
    if path is None:
        return [], None, []
    day = path.stem
    try:
        parsed = actuals.read_contracts(path)
        # The legacy reader deliberately converts empty monetary cells to 0.
        # Restore availability from its very same source cells for this view.
        raw = list(actuals._sheet(path, actuals._CONTRACTS_SHEET))
    except (KeyError, ValueError, OSError):
        return [], day, ["Реестр договоров в выбранном снимке РСС не прочитан."]
    source_rows = []
    for row_number, row in enumerate(raw, 1):
        if row_number < actuals._CONTRACTS_FIRST_ROW:
            continue
        get = lambda index: row[index] if index < len(row) else None
        if not str(get(1) or "").strip() and not actuals._money(get(7)):
            continue
        source_rows.append((row_number, row))
    if len(source_rows) != len(parsed.get("rows") or []):
        return [], day, ["Строки реестра договоров РСС неоднозначны; денежные значения не объединены."]
    header = {i: _norm(v) for r in raw[:actuals._CONTRACTS_FIRST_ROW-1]
              for i, v in enumerate(r) if v is not None}
    deadline_cols = [i for i, text in header.items()
                     if text in {"срок исполнения", "срок договора", "срок выполнения работ",
                                 "дата исполнения", "дата окончания работ", "срок окончания работ",
                                 "дата завершения работ", "окончание работ"}]
    date_cols = [i for i, text in header.items() if text in {"дата договора", "дата заключения договора"}]
    out = []
    for item, (row_number, raw_row) in zip(parsed.get("rows") or [], source_rows):
        if _norm(item.get("contractor")).startswith(("итого", "всего")):
            continue
        row = dict(item, kind="rss", customer="", source_date=day)
        row["amount"] = _number(raw_row[7]) if len(raw_row) > 7 else None
        row["completed"] = _number(raw_row[11]) if len(raw_row) > 11 else None
        row["contract_date"] = (_date(raw_row[date_cols[0]]) if len(date_cols) == 1
                                and len(raw_row) > date_cols[0] else None)
        if not row["contract_date"] and re.search(r"\sот\s", row.get("contract", ""), re.I):
            row["contract_date"] = _date(row["contract"])
        row["deadline"] = (_date(raw_row[deadline_cols[0]]) if len(deadline_cols) == 1
                           and len(raw_row) > deadline_cols[0] else None)
        row["source"] = {"label": "Реестр договоров РСС", "filename": path.name,
                         "sheet": actuals._CONTRACTS_SHEET, "row": row_number}
        out.append(row)
    return out, day, []


def _groups(entries: list[dict], project: str) -> list[tuple[str, list[dict]]]:
    buckets: dict[tuple, list[dict]] = {}
    for ordinal, item in enumerate(entries):
        base = _base_key(item)
        # Missing identity does not authorize a join, even if names coincide.
        key = base if base[1] and base[2] else (*base, "unresolved", ordinal)
        buckets.setdefault(key, []).append(item)
    result = []
    for base, items in buckets.items():
        dates = sorted({_date(x.get("contract_date")) for x in items
                        if _date(x.get("contract_date"))})
        partitions = {date: [] for date in dates} if len(dates) > 1 else {"": []}
        for item in items:
            date = _date(item.get("contract_date")) if len(dates) > 1 else ""
            partitions.setdefault(date or "", []).append(item)
        for date, grouped in partitions.items():
            if not grouped:
                continue
            identity = json.dumps([monitor._resolved_slug(project), base, date],
                                  ensure_ascii=False, separators=(",", ":"))
            identifier = hashlib.sha256(identity.encode()).hexdigest()
            if len(dates) > 1:
                grouped = [dict(item, warnings=_warnings(item.get("warnings")) + [
                    "Один номер договора встречается с разными датами; записи не объединены."])
                    for item in grouped]
            result.append((identifier, grouped))
    return result


def _rss_money(items: list[dict], warnings: list[str]) -> tuple[float | None, float | None]:
    rows = [x for x in items if x.get("kind") == "rss"]
    # Exact duplicates, including the article, do not multiply a contract.
    unique = {}
    for row in rows:
        key = json.dumps({k: row.get(k) for k in
                          ("amount", "completed", "estimate_code", "subject", "article_name")},
                         ensure_ascii=False, sort_keys=True)
        unique[key] = row
    rows = list(unique.values())
    if len(rows) > 1:
        totals = [r for r in rows if re.search(r"итого\s+по\s+договору|всего\s+по\s+договору",
                                             str(r.get("subject") or ""), re.I)]
        rows = totals if len(totals) == 1 else rows
    if len(rows) > 1:
        warnings.append("Договор разбит на несколько строк РСС. Полная сумма и выполнение требуют сверки; строки не сложены.")
        return None, None
    if not rows:
        return None, None
    amount, completed = _number(rows[0].get("amount")), _number(rows[0].get("completed"))
    if amount is not None and amount < 0:
        warnings.append("Отрицательная сумма договора в РСС требует проверки.")
        amount = None
    return amount, completed


def _summary_money(items: list[dict], cut: str, warnings: list[str]) -> tuple[float | None, float | None]:
    rows = [r for r in items if r.get("kind") == "summary"]
    if not rows:
        return None, None
    amount_rows = []
    for row in rows:
        versions = row.get("amount_versions") or []
        if versions:
            for version in versions:
                amount_rows.append({"amount": version.get("amount"),
                                    "amount_date": version.get("date")})
        else:
            amount_rows.append(row)
    candidates = [r for r in amount_rows if not _date(r.get("amount_date"))
                  or _date(r.get("amount_date")) <= cut]
    dated = [r for r in candidates if _date(r.get("amount_date"))]
    if dated and len(dated) == len(candidates):
        latest = max(_date(r.get("amount_date")) for r in dated)
        candidates = [r for r in dated if _date(r.get("amount_date")) == latest]
    values = {_number(r.get("amount")) for r in candidates}
    amount = next(iter(values)) if len(values) == 1 else None
    if len(values) > 1:
        warnings.append("В сводной несколько несогласованных сумм договора; сумма не выбрана автоматически.")
    if amount is not None and amount < 0:
        amount = None
        warnings.append("Отрицательная сумма договора в сводной требует проверки.")
    acts = [act for row in rows for act in row.get("acts") or []]
    if not acts:
        return amount, None
    by_key = {}
    uncertain = False
    for act in acts:
        date, value = _date(act.get("date")), _number(act.get("amount"))
        if date and date > cut:
            continue
        if date is None or value is None:
            uncertain = True
            continue
        number = _norm(act.get("number"))
        source = act.get("source") or {}
        key = (number, date) if number else ("source", date, json.dumps(source, sort_keys=True))
        if key in by_key and by_key[key] != value:
            uncertain = True
        by_key[key] = value
    if uncertain:
        warnings.append("Акты без даты, суммы или с конфликтующими значениями требуют сверки; выполнение не посчитано.")
        return amount, None
    return amount, sum(by_key.values())


def _physical(item: dict, ledger: dict) -> dict:
    result = {k: item.get(k) for k in
              ("position", "name", "scope", "unit", "plan_quantity", "completed_quantity",
               "material_quantity", "planned_amount", "completed_amount", "periods")}
    result["source"] = _source(item.get("source") or ledger.get("source"), "Накопительная КС-6а")
    result["period_year"] = ledger.get("period_year")
    result["warnings"] = _warnings(item.get("warnings"))
    plan, fact = _number(result["plan_quantity"]), _number(result["completed_quantity"])
    result["plan_quantity"], result["completed_quantity"] = plan, fact
    result["material_quantity"] = _number(result["material_quantity"])
    result["completion_ratio"] = fact / plan if plan is not None and plan > 0 and fact is not None else None
    if plan is None or plan <= 0:
        result["warnings"].append("Нет положительного полного объёма этой позиции; процент не определён.")
    if fact is not None and fact < 0:
        result["warnings"].append("Отрицательное выполнение требует проверки.")
    if result["completion_ratio"] is not None and result["completion_ratio"] > 1.000001:
        result["warnings"].append("Выполнение превышает объём позиции; требуется сверка.")
    return result


def _terms_path(project: str) -> Path:
    return monitor._project_dir(project) / "cumulative_terms.json"


def _read_terms(project: str) -> dict:
    try:
        data = json.loads(_terms_path(project).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (ValueError, OSError):
        raise ContractProblem("Сохранённые сроки договоров не прочитаны; проверьте хранилище проекта.") from None
    if not isinstance(data, dict):
        raise ContractProblem("Сохранённые сроки договоров имеют неверный формат.")
    return data


def build(project: str, cut: str = "") -> dict:
    """Read current source snapshots; never mutate finance or physical GPR."""
    cut = _cut(cut)
    if not str(project or "").strip():
        raise ContractProblem("Выберите проект.")
    rss, rss_day, warnings = _read_rss(project, cut)
    snapshot = _archive(project, cut)
    archive_day = (snapshot or {}).get("taken_at")
    if snapshot and (not _date(archive_day) or _date(archive_day) > cut):
        warnings.append("Дата накопительного архива не подтверждена или позже среза; архив не включён в этот срез.")
        snapshot, archive_day = None, None
    entries = list(rss)
    for kind, key in (("summary", "summary_contracts"), ("ledger", "ledgers")):
        for original in (snapshot or {}).get(key) or []:
            entries.append(dict(original, kind=kind, source_date=archive_day))
    terms = _read_terms(project)
    rows = []
    for identifier, items in _groups(entries, project):
        first = items[0]
        row_warnings = _warnings([v for x in items for v in x.get("warnings") or []])
        if not _base_key(first)[1] or not _base_key(first)[2]:
            row_warnings.append("Не хватает контрагента или номера договора; запись не объединена с другими источниками.")
        amount, completed = _rss_money(items, row_warnings)
        summary_amount, summary_completed = _summary_money(items, cut, row_warnings)
        rss_items = [x for x in items if x.get("kind") == "rss"]
        summary_items = [x for x in items if x.get("kind") == "summary"]
        primary = rss_items[0] if rss_items else (summary_items[0] if summary_items else first)
        if not rss_items:
            amount, completed = summary_amount, summary_completed
        elif summary_items and any(a is not None and b is not None and abs(a-b) > 0.01
                                   for a, b in ((amount, summary_amount), (completed, summary_completed))):
            row_warnings.append("РСС и сводная дают разные денежные значения. Основной показатель оставлен по РСС; источники требуют сверки.")
        if not rss_items and not summary_items:
            row_warnings.append("В накопительной указан объём отдельного года или листа. Полная сумма договора и процент актирования не подтверждены.")
        if amount is None:
            row_warnings.append("Нет подтверждённой полной суммы договора.")
        if completed is None:
            row_warnings.append("Нет подтверждённой суммы актированного выполнения на дату среза.")
        ratio = completed / amount if amount is not None and amount > 0 and completed is not None else None
        if ratio is not None and (ratio < 0 or ratio > 1.000001):
            row_warnings.append("Актированное выполнение выходит за пределы суммы договора; требуется сверка.")
        deadlines = {_date(x.get("deadline")) for x in items if _date(x.get("deadline"))}
        deadline = next(iter(deadlines)) if len(deadlines) == 1 else None
        deadline_source = {"label": "Срок из источника"} if deadline else None
        if len(deadlines) > 1:
            row_warnings.append("В источниках указаны разные сроки договора; срок не выбран автоматически.")
        manual = terms.get(identifier)
        if isinstance(manual, dict) and _date(manual.get("deadline")):
            deadline = _date(manual["deadline"])
            deadline_source = {"label": "Указан вручную", "note": str(manual.get("note") or ""),
                               "updated_at": manual.get("updated_at")}
        physical = [_physical(item, ledger) for ledger in items if ledger.get("kind") == "ledger"
                    for item in ledger.get("items") or []]
        row = {"id": identifier, "contractor": str(first.get("contractor") or ""),
               "customer": str(first.get("customer") or ""),
               "contract": str(first.get("contract") or ""),
               "contract_date": next((_date(x.get("contract_date")) for x in items
                                      if _date(x.get("contract_date"))), None),
               "subject": str(next((x.get("subject") for x in items if x.get("subject")), "")),
               "amount": amount, "completed": completed, "completion_ratio": ratio,
               "remaining": amount-completed if amount is not None and completed is not None else None,
               "deadline": deadline, "deadline_source": deadline_source,
               "deadline_passed": bool(deadline and deadline < cut),
               "source": _source(primary.get("source"), "Реестр договоров"),
               "source_date": primary.get("source_date"), "warnings": _warnings(row_warnings),
               "requires_reconciliation": bool(row_warnings),
               "physical_items": physical,
               "sources": [_source(x.get("source")) for x in items],
               "financial_sources": ([{"label": "РСС", "amount": amount, "completed": completed,
                                        "source_date": rss_day}] if rss_items else [])
                  + ([{"label": "Сводная по закрытию", "amount": summary_amount,
                       "completed": summary_completed, "source_date": archive_day}] if summary_items else []),
               "scope": sorted({str(item.get("scope") or "") for item in physical if item.get("scope")}),
               "performance_basis": "Актированное выполнение в рублях; не оплата и не физическая готовность"}
        rows.append(row)
    # A missing customer cannot silently match a named customer in another book.
    by_party_number = {}
    for row in rows:
        by_party_number.setdefault((_norm(row["contractor"]), _contract_number(row["contract"])), []).append(row)
    for group in by_party_number.values():
        if len(group) > 1 and len({_norm(x["customer"]) for x in group}) > 1:
            for row in group:
                row["warnings"].append("Номер и контрагент встречаются у разных или неуказанных заказчиков; записи оставлены раздельно.")
    rows.sort(key=lambda r: (_norm(r["contractor"]), _norm(r["customer"]), _norm(r["contract"]), r["id"]))
    return {"cut": cut, "source_date": max(filter(None, (rss_day, archive_day)), default=None),
            "rows": rows, "snapshots": {"rss": rss_day, "cumulative": archive_day,
                                         "cumulative_id": (snapshot or {}).get("snapshot_id")},
            "warnings": _warnings(warnings + _warnings((snapshot or {}).get("warnings"))),
            "performance_basis": "Актированное выполнение в рублях; не оплата и не физическая готовность"}


def set_term(project: str, contract_id: str, deadline: str, note: str = "") -> dict:
    """Save one explicit contractual deadline, independently of GPR dates."""
    if not re.fullmatch(r"[0-9a-f]{64}", str(contract_id or "")):
        raise ContractProblem("Выберите договор из списка.")
    if not str(project or "").strip():
        raise ContractProblem("Выберите проект.")
    if not isinstance(deadline, str) or (deadline and (
            _date(deadline) != deadline or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", deadline))):
        raise ContractProblem("Срок договора нужен в виде ГГГГ-ММ-ДД.")
    if not isinstance(note, str) or len(note) > 500:
        raise ContractProblem("Пояснение к сроку должно быть не длиннее 500 символов.")
    if contract_id not in {r["id"] for r in build(project)["rows"]}:
        raise ContractProblem("Договор не найден в текущих данных выбранного проекта.")
    path = _terms_path(project)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    import fcntl
    fd = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        data = _read_terms(project)
        if deadline:
            record = {"deadline": deadline, "note": note,
                      "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}
            data[contract_id] = record
        else:
            data.pop(contract_id, None)
            record = {"deadline": None, "note": ""}
        temp_fd, temporary = tempfile.mkstemp(prefix=".terms-", dir=path.parent)
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as output:
                json.dump(data, output, ensure_ascii=False, allow_nan=False)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return {"contract_id": contract_id, **record}

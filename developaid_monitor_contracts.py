"""A source-backed contract view, not another financial register.

Contracts explicitly identified by uploaded cumulative headers or labelled
closing-summary sections belong to this view. RSS can enrich an exact identity;
the RSS closing/payment column never supplies cumulative completion.
Yearly book totals never become a full contract price. Authenticate first.
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
import developaid_monitor_contract_risk as contract_risk
from developaid_monitor_ledgers import amount_basis as _amount_basis
from developaid_monitor_ledgers import basis_metadata_current as _basis_metadata_current


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


def _contract_number(value: Any, *, reference: bool = False) -> str:
    # Strip only explicit decoration. Punctuation within a number is identity:
    # 12/3 and 123 must not silently become the same contract.
    value = re.split(r"\s+от\s+", str(value or ""), maxsplit=1, flags=re.I)[0]
    if reference and "№" in value:
        # «Договор подряда № 12/3» and «№12/3» name the same number: the number
        # is what follows the sign, whatever words describe the document.
        value = value.split("№", 1)[1]
    value = re.sub(r"^\s*(?:договор\b\s*)?№?\s*", "", value, flags=re.I)
    return re.sub(r"\s+", "", value).casefold().replace("ё", "е")


# Full and abbreviated legal forms are one party; nothing else is merged.
_LEGAL_FORMS = (
    ("общество с ограниченной ответственностью", "ооо"),
    ("публичное акционерное общество", "пао"),
    ("открытое акционерное общество", "оао"),
    ("закрытое акционерное общество", "зао"),
    ("непубличное акционерное общество", "ао"),
    ("акционерное общество", "ао"),
    ("индивидуальный предприниматель", "ип"),
)


def _party_norm(value: Any) -> str:
    text = _norm(value)
    for full, short in _LEGAL_FORMS:
        text = re.sub(r"(?<![а-я])" + full + r"(?![а-я])", short, text)
    text = re.sub(r"\s+", " ", text).strip()
    words = text.split()
    forms = {short for _, short in _LEGAL_FORMS}
    # The source register also uses «НУР ООО». Move an explicit suffix only
    # when no leading form exists: a final word inside an already qualified
    # company name must remain part of that name. Persisted ids use _base_key.
    if len(words) > 1 and words[0] not in forms and words[-1] in forms:
        text = ' '.join([words[-1], *words[:-1]])
    return text


def _base_key(item: dict) -> tuple[str, str, str]:
    # Persisted contract ids own manual deadlines and work links. Keep the
    # original header identity stable; RSS comparison rules must not rekey or
    # silently merge existing cumulative contracts.
    return (_norm(item.get("customer")), _norm(item.get("contractor")),
            _contract_number(item.get("contract")))


def _reference_key(item: dict) -> tuple[str, str, str]:
    """Compare external references without changing cumulative identity."""
    return (_party_norm(item.get("customer")), _party_norm(item.get("contractor")),
            _contract_number(item.get("contract"), reference=True))


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


def _basis(value: Any) -> str:
    return value if value in {"with_vat", "without_vat"} else "unspecified"


def _archive(project: str, cut: str) -> dict | None:
    try:
        ledgers = importlib.import_module("developaid_monitor_ledgers")
    except ModuleNotFoundError as exc:
        if exc.name != "developaid_monitor_ledgers":
            raise
        return None
    snapshot = ledgers.latest_snapshot(project, cut)
    if not snapshot:
        return snapshot
    if snapshot.get("identity_schema") == 4 and all(
            re.fullmatch(r"[0-9a-f]{64}", str(x.get("file_sha256") or ""))
            and isinstance(x.get("identity_source"), dict)
            and isinstance(x.get("party_evidence"), dict) for x in snapshot.get("ledgers") or []):
        return snapshot
    # Previously imported archives remain usable without a second upload.
    # Re-read their immutable, hash-verified original bytes with the fixed
    # header parser; do not rewrite snapshots, dates, financial data or GPR.
    identifier = str(snapshot.get("snapshot_id") or "")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}-[0-9a-f]{64}", identifier):
        raw = ledgers._root(project) / (identifier + ".zip")
        if raw.is_file():
            with raw.open("rb") as handle:
                data = handle.read(ledgers.MAX_ARCHIVE_BYTES+1)
            if len(data) > ledgers.MAX_ARCHIVE_BYTES:
                raise ContractProblem("Сохранённый архив накопительных превышает допустимый размер.")
            if hashlib.sha256(data).hexdigest() != identifier[11:]:
                raise ContractProblem("Исходный архив накопительных не совпадает с сохранённым отпечатком.")
            try:
                parsed = ledgers.parse_archive(data, snapshot.get("filename") or "")
            except ledgers.LedgerProblem:
                raise ContractProblem("Сохранённый архив накопительных не прочитан; проверьте исходный файл.") from None
            return {**snapshot, **parsed, "identity_schema": 4}
    safe_ledgers = []
    for item in snapshot.get("ledgers") or []:
        if isinstance(item.get("party_evidence"), dict):
            safe_ledgers.append(item)
            continue
        # The earlier parser chose the last party label. Without the original
        # bytes we cannot establish whether it hid contradictory candidates.
        evidence = {field: [{"raw": str(item[field]), "value": str(item[field]),
                             "origin": "unverified_saved_header",
                             "source": (item.get("identity_source") or {}).get(field)
                                       or item.get("source") or {}}] if item.get(field) else []
                    for field in ("customer", "contractor")}
        safe_ledgers.append({**item, "customer": "", "contractor": "",
            "party_evidence": evidence, "identity_warnings": [*(item.get("identity_warnings") or []),
                "Исходный ZIP недоступен: повторяющиеся поля сторон в сохранённой шапке не проверены. Стороны договора не подтверждены."]})
    return {**snapshot, "ledgers": safe_ledgers, "warnings": [*(snapshot.get("warnings") or []),
        "Сохранённый исходный ZIP недоступен: точная привязка уточнения шапки к файлу не подтверждена; отпечаток не выдуман."]}


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
    # A column keeps every label of every header row: the production sheet has
    # a group row above the labels and a column-number row (1, 2, 3, …) below
    # them, and a last-row-wins map lost «Дата договора» to the number «4».
    header: dict[int, set[str]] = {}
    for r in raw[:actuals._CONTRACTS_FIRST_ROW-1]:
        for i, v in enumerate(r):
            if v is not None and str(v).strip():
                header.setdefault(i, set()).add(_norm(v))
    deadline_cols = [i for i, texts in header.items()
                     if texts & {"срок исполнения", "срок договора", "срок выполнения работ",
                                 "дата исполнения", "дата окончания работ", "срок окончания работ",
                                 "дата завершения работ", "окончание работ"}]
    date_cols = [i for i, texts in header.items() if texts & {"дата договора", "дата заключения договора"}]
    customers = {}
    for header_row in raw[:actuals._CONTRACTS_FIRST_ROW-1]:
        for index, value in enumerate(header_row):
            text = str(value or "").strip()
            labelled = re.match(r"^(?:заказчик|генподрядчик)\s*:\s*(.+)$", text, re.I)
            candidate = labelled.group(1) if labelled else (
                str(next((v for v in header_row[index+1:] if v is not None and str(v).strip()), ""))
                if _norm(value) in {"заказчик", "генподрядчик"} else "")
            if candidate:
                customers[_norm(candidate)] = candidate
    customer = next(iter(customers.values())) if len(customers) == 1 else ""
    # «Not found» and «several different» are different facts: an unknown
    # customer may be completed by the other attributes, a contradictory
    # header may not.
    customer_conflict = sorted(customers.values()) if len(customers) > 1 else []
    amount_header = " ".join(str(row[7] or "") for row in raw[:8] if len(row) > 7)
    closing_header = " / ".join(str(row[11] or "") for row in raw[:8] if len(row) > 11)
    full_price_labelled = bool(re.search(r"(?:сумма|стоимость|цена).*догов", _norm(amount_header)))
    notes = []
    if not full_price_labelled:
        notes.append("Колонка H листа «Реестр договоров» РСС подписана «" + (amount_header.strip() or "без подписи")
                     + "», а не «сумма договора»; полная сумма договора из РСС не взята.")
    if not date_cols:
        notes.append("В листе «Реестр договоров» РСС нет колонки «Дата договора»; дата берётся только из текста "
                     "«№ … от ДД.ММ.ГГГГ» в колонке договора.")
    if customer_conflict:
        notes.append("В шапке листа «Реестр договоров» РСС названы разные заказчики: "
                     + ", ".join(customer_conflict) + "; строки РСС к договорам не присоединяются.")
    elif not customer:
        notes.append("В шапке листа «Реестр договоров» РСС заказчик не указан; строки РСС сопоставляются "
                     "по подрядчику, номеру и дате договора.")
    out = []
    for item, (row_number, raw_row) in zip(parsed.get("rows") or [], source_rows):
        if _norm(item.get("contractor")).startswith(("итого", "всего")):
            continue
        row = dict(item, kind="rss", customer=customer, source_date=day,
                   customer_conflict=bool(customer_conflict))
        row["amount"] = _number(raw_row[7]) if len(raw_row) > 7 and full_price_labelled else None
        row["completed"] = _number(raw_row[11]) if len(raw_row) > 11 else None
        row["amount_basis"] = _amount_basis(" ".join(str(r[7] or "") for r in raw[:8] if len(r) > 7))
        row["completed_basis"] = _amount_basis(" ".join(str(r[11] or "") for r in raw[:8] if len(r) > 11))
        row["contract_date"] = (_date(raw_row[date_cols[0]]) if len(date_cols) == 1
                                and len(raw_row) > date_cols[0] else None)
        if not row["contract_date"] and re.search(r"\sот\s", row.get("contract", ""), re.I):
            row["contract_date"] = _date(row["contract"])
        row["deadline"] = (_date(raw_row[deadline_cols[0]]) if len(deadline_cols) == 1
                           and len(raw_row) > deadline_cols[0] else None)
        row["source"] = {"label": "Реестр договоров РСС", "filename": path.name,
                         "sheet": actuals._CONTRACTS_SHEET, "row": row_number,
                         "amount_cell": f"H{row_number}", "completed_cell": f"L{row_number}",
                         "amount_header": amount_header, "completed_header": closing_header,
                         "completed_label": "Показатель столбца L реестра РСС; вид закрывающего документа не подтверждён"}
        out.append(row)
    return out, day, notes


def _groups(entries: list[dict], project: str) -> list[tuple[str, list[dict]]]:
    buckets: dict[tuple, list[dict]] = {}
    for ordinal, item in enumerate(entries):
        base = _base_key(item)
        # Missing identity does not authorize a join, even if names coincide.
        key = base if base[1] and base[2] else (*base, "unresolved", ordinal)
        buckets.setdefault(key, []).append(item)
    result = []
    for base, items in buckets.items():
        partitions = {}
        for item in items:
            # A known date is always part of identity, even when the old and
            # reissued contracts occur in two different source snapshots.
            date = _date(item.get("contract_date")) or _source_date_key(item)
            partitions.setdefault(date, []).append(item)
        for date, grouped in partitions.items():
            if not grouped:
                continue
            identity = json.dumps([monitor._resolved_slug(project), base, date],
                                  ensure_ascii=False, separators=(",", ":"))
            identifier = hashlib.sha256(identity.encode()).hexdigest()
            if len(partitions) > 1:
                grouped = [dict(item, warnings=_warnings(item.get("warnings")) + [
                    "Даты одноимённых договоров различаются или отсутствуют; записи не объединены."])
                    for item in grouped]
            result.append((identifier, grouped))
    return result


def _rss_money(items: list[dict], warnings: list[str]) -> tuple[float | None, float | None, str, str]:
    rows = [x for x in items if x.get("kind") == "rss"]
    # Exact duplicates, including the article, do not multiply a contract.
    unique = {}
    for row in rows:
        key = json.dumps({k: row.get(k) for k in
                          ("amount", "completed", "estimate_code", "subject", "article_name",
                           "amount_basis", "completed_basis")},
                         ensure_ascii=False, sort_keys=True)
        unique[key] = row
    rows = list(unique.values())
    if len(rows) > 1:
        totals = [r for r in rows if re.search(r"итого\s+по\s+договору|всего\s+по\s+договору",
                                             str(r.get("subject") or ""), re.I)]
        rows = totals if len(totals) == 1 else rows
    if len(rows) > 1:
        warnings.append("Договор разбит на несколько строк РСС. Полная сумма и выполнение требуют сверки; строки не сложены.")
        return None, None, "unspecified", "unspecified"
    if not rows:
        return None, None, "unspecified", "unspecified"
    amount, completed = _number(rows[0].get("amount")), _number(rows[0].get("completed"))
    if amount is not None and amount < 0:
        warnings.append("Отрицательная сумма договора в РСС требует проверки.")
        amount = None
    return amount, completed, _basis(rows[0].get("amount_basis")), _basis(rows[0].get("completed_basis"))


def _summary_money(items: list[dict], cut: str, warnings: list[str]) -> tuple[float | None, float | None, str, str]:
    rows = [r for r in items if r.get("kind") == "summary"]
    if not rows:
        return None, None, "unspecified", "unspecified"
    amount_rows = []
    for row in rows:
        if any(_date(version.get('date')) and _date(version.get('date')) > cut
               for version in row.get('reported_amount_versions') or []):
            warnings.append('Итоговая цена сводной включает допсоглашение позже среза; текущая полная сумма не подтверждена.')
            amount_rows.append({'amount': None, 'amount_date': None,
                                'amount_scope': 'full_contract', 'amount_basis': row.get('amount_basis')})
            continue
        versions = row.get("amount_versions") or []
        if versions:
            for version in versions:
                amount_rows.append({"amount": version.get("amount"),
                                    "amount_date": version.get("date"),
                                    "amount_scope": version.get("scope"),
                                    "amount_basis": version.get("amount_basis")})
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
    price_bases = {_basis(r.get("amount_basis")) for r in candidates}
    explicit_price_bases = price_bases - {"unspecified"}
    amount_basis = ("conflicting" if len(explicit_price_bases) > 1 or any(r.get('amount_basis') == 'conflicting' for r in candidates) else
                    next(iter(explicit_price_bases)) if explicit_price_bases else "unspecified")
    if amount_basis == "conflicting":
        warnings.append("В источниках суммы договора различаются базы НДС; денежный процент требует сверки.")
    # An amendment amount with unknown semantics invalidates the current full
    # price. It must not disappear from the candidates and revive an old price.
    if any(r.get("amount_scope") not in {None, "", "full_contract"} for r in candidates):
        amount = None
        warnings.append("Сумма допсоглашения не подтверждена как полная новая цена договора; действующая сумма требует сверки.")
    if len(values) > 1:
        warnings.append("В сводной несколько несогласованных сумм договора; сумма не выбрана автоматически.")
    if amount is not None and amount < 0:
        amount = None
        warnings.append("Отрицательная сумма договора в сводной требует проверки.")
    acts = [act for row in rows for act in row.get("acts") or []]
    if not acts:
        return amount, None, amount_basis, "unspecified"
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
        evidence = (value, 'conflicting' if act.get('amount_basis') == 'conflicting' else _basis(act.get("amount_basis")))
        if key in by_key and by_key[key] != evidence:
            uncertain = True
        by_key[key] = evidence
    if uncertain:
        warnings.append("Акты без даты, суммы или с конфликтующими значениями требуют сверки; выполнение не посчитано.")
        return amount, None, amount_basis, "unspecified"
    act_bases = {basis for _, basis in by_key.values() if basis != "unspecified"}
    if len(act_bases) > 1 or 'conflicting' in act_bases:
        warnings.append("В актах смешаны суммы с НДС и без НДС; они не сложены в единое выполнение.")
        return amount, None, amount_basis, "unspecified"
    completed_basis = next(iter(act_bases)) if act_bases else "unspecified"
    return amount, sum(value for value, _ in by_key.values()), amount_basis, completed_basis


def _summary_observation(items: list[dict], cut: str) -> dict:
    """One qualified financial reading of the uploaded closing summary.

    This is a source observation, not natural readiness or an execution date.
    A printed final section total can establish zero without inventing act rows.
    """
    rows = [row for row in items if row.get('kind') == 'summary']
    result = {'state': 'unknown', 'ratio': None, 'planned': None, 'completed': None,
        'basis': 'closing_summary_contract', 'basis_label': 'суммы КС-2 по сводной',
        'origin': 'closing_summary_statement', 'scope_fingerprint': None,
        'basis_signature': None, 'requires_reconciliation': False,
        'why': 'В сводной не подтверждены сопоставимые план и итог КС-2.'}
    if not rows:
        return result
    if any(_date(act.get('date')) and _date(act.get('date')) > cut
           for row in rows for act in row.get('acts') or []):
        return dict(result, why='Итог сводной содержит акты позже выбранного среза; общий итог не использован.')
    if any(_date(version.get('date')) and _date(version.get('date')) > cut
           for row in rows for version in row.get('reported_amount_versions') or []):
        return dict(result, why='Итог цены сводной включает допсоглашение позже среза; процент требует сверки.')
    totals = [row.get('reported_total') for row in rows]
    if any(not isinstance(total, dict) for total in totals):
        return result
    basis = lambda value: value if value in {'with_vat', 'without_vat', 'unspecified'} else 'conflicting'
    values = {(_number(total.get('planned')), _number(total.get('completed')),
               basis(total.get('planned_amount_basis')), basis(total.get('completed_amount_basis')))
              for total in totals}
    if len(values) != 1:
        return dict(result, why='Сводные дают разные общие итоги договора; процент не выбран.')
    planned, completed, first_basis, second_basis = next(iter(values))
    if planned is None or planned <= 0:
        return dict(result, completed=completed, planned=planned,
                    why='В сводной не подтверждена положительная полная сумма договора; денежный процент не определён.')
    if completed is None:
        return dict(result, planned=planned, why='В сводной не подтверждён общий итог КС-2.')
    if ('conflicting' in {first_basis, second_basis}
            or first_basis != 'unspecified' and second_basis != 'unspecified' and first_basis != second_basis):
        return dict(result, why='План и итог КС-2 сводной имеют разные основания НДС; процент не рассчитан.')
    acts = {}
    for row in rows:
        source_acts = set()
        for act in row.get('acts') or []:
            key = _norm(act.get('number')), _date(act.get('date'))
            if key in source_acts:
                return dict(result, why='В одном разделе сводной повторяется номер и дата акта; итог требует сверки.')
            source_acts.add(key)
            if key in acts and acts[key] != _number(act.get('amount')):
                return dict(result, why='В сводной конфликтуют суммы одного акта; итог требует сверки.')
            acts[key] = _number(act.get('amount'))
    identity = _source_identity(rows[0])
    if not identity:
        return dict(result, why='У денежного итога сводной не подтверждена договорная идентичность.')
    digest = lambda value: hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()
    return dict(result, state='known', ratio=completed/planned, planned=planned, completed=completed,
        scope_fingerprint=digest(['closing_summary_contract', identity]),
        basis_signature=digest(['closing_summary_contract', planned, first_basis, second_basis]),
        requires_reconciliation=completed < 0 or completed > planned,
        source=_source(totals[0].get('source')),
        why='Денежное закрытие по итогам КС-2 из сводной; не физическая готовность и не объёмы КС-6а.')


def _physical(item: dict, ledger: dict, cut: str, *, _duplicates=None) -> dict:
    import developaid_monitor_ledgers as ledgers
    result = {k: item.get(k) for k in
              ("position", "name", "scope", "unit", "plan_quantity", "planned_amount",
               "section_path", "context_headings", "parent_row", "is_group", "planned_work_amount",
               "planned_material_amount", "planned_cost_split", "planned_work_amount_basis", "planned_cost_method",
               "completed_amount_derivation", "duplicate_of", "duplicate_proof", "duplicate_note",
               "duplicate_source_fingerprint")}
    if _duplicates is None:
        _duplicates = ledgers.verified_duplicate_sources(ledger.get('items') or []) if item.get('is_duplicate') else {}
    result['is_duplicate'] = ledgers._duplicate_key(dict(item, period_year=ledger.get('period_year'))) in _duplicates
    result["source"] = _source(item.get("source") or ledger.get("source"), "Накопительная ведомость работ")
    result["period_year"] = ledger.get("period_year")
    result["warnings"] = _warnings(item.get("warnings"))
    result["snapshot_date"] = _date(ledger.get("source_date"))
    periods = list(item.get("periods") or [])
    period_year = ledger.get("period_year")
    future_year = type(period_year) is int and period_year > int(cut[:4])
    included = [p for p in periods if not future_year and _date(p.get("date_end"))
                and _date(p["date_end"]) <= cut
                and (not _date(p.get("date_start"))
                     or _date(p["date_start"]) <= _date(p["date_end"]))]
    # A period ending after cut is never returned as a fact for the cut.
    result["periods"] = included
    result["quantity_date"] = max((_date(p["date_end"]) for p in included), default=None)
    result["quantity_cut"] = cut
    has_future_values = future_year or any(_date(p.get("date_end")) and _date(p["date_end"]) > cut
                            and any((_number(p.get(key)) or 0) != 0
                                    for key in ("quantity", "material_quantity", "amount"))
                            for p in periods)

    def asof(field: str, annual_field: str) -> tuple[float | None, str]:
        if future_year:
            return None, "Год ведомости позже выбранного среза; итог не использован как текущее выполнение."
        annual = _number(item.get(annual_field))
        if annual is None:
            return None, "Накопительный итог не подтверждён числом."
        if not any(_date(p.get("date_end")) for p in periods):
            return None, "Накопительный итог без дат выполнения; доступен только справочно."
        values = [(p, _number(p.get(field))) for p in periods]
        if any(value not in (None, 0) and not _date(p.get("date_end")) for p, value in values):
            return None, "Есть выполнение без даты периода; итог на дату среза не определён."
        if any(value not in (None, 0) and _date(p.get("date_start"))
               and _date(p.get("date_end")) and _date(p["date_start"]) > _date(p["date_end"])
               for p, value in values):
            return None, "Начало периода позже его окончания; итог на дату среза не определён."
        if any(value not in (None, 0) and _date(p.get("date_end")) > cut
               and (not _date(p.get("date_start")) or _date(p["date_start"]) <= cut)
               for p, value in values if _date(p.get("date_end"))):
            return None, "Период выполнения пересекает дату среза; делить его объём по дням нельзя."
        total = sum(value for _, value in values if value is not None)
        if abs(total-annual) > max(1e-6, abs(annual)*1e-7):
            return None, "Накопительный итог не сходится с объёмами периодов; требуется сверка."
        fact = sum(_number(p.get(field)) or 0 for p in included)
        return fact, "По датированным периодам, завершённым не позднее даты среза."

    fact, basis = asof("quantity", "completed_quantity")
    material, _ = asof("material_quantity", "material_quantity")
    amount, _ = asof("amount", "completed_amount")
    result["completed_amount"] = amount
    result["material_quantity"] = material
    result["quantity_basis"] = basis
    result["dated_completed_quantity"] = sum(_number(p.get("quantity")) or 0 for p in included) if included else None
    # Undated source totals remain explicitly separate reference values. An
    # annual total known to contain future periods is not exposed in this cut.
    for field in ("completed_quantity", "material_quantity", "completed_amount"):
        result["reported_"+field] = (_number(item.get(field)) if fact is None
                                     and not has_future_values else None)
    reported = result["reported_completed_quantity"]
    reported_plan = _number(result["plan_quantity"])
    result["reported_completion_ratio"] = (reported / reported_plan if reported is not None
                                           and reported_plan is not None and reported_plan > 0 else None)
    result["reported_quantity_basis"] = ("Итог ведомости, дата выполнения не подтверждена; не факт на дату среза."
        if not any(_date(p.get("date_end")) for p in periods) else
        "Справочный итог ведомости; как факт на дату среза не подтверждён.")
    result["future_periods_excluded"] = has_future_values
    if fact is None:
        result["warnings"].append(basis)
    if has_future_values:
        result["warnings"].append("Выполнение периодов позже даты среза исключено.")
    plan = _number(result["plan_quantity"])
    result["plan_quantity"], result["completed_quantity"] = plan, fact
    result["completion_ratio"] = fact / plan if plan is not None and plan > 0 and fact is not None else None
    if plan is None or plan <= 0:
        result["warnings"].append("Нет положительного полного объёма этой позиции; процент не определён.")
    if fact is not None and fact < 0:
        result["warnings"].append("Отрицательное выполнение требует проверки.")
    if result["completion_ratio"] is not None and result["completion_ratio"] > 1.000001:
        result["warnings"].append("Выполнение превышает объём позиции; требуется сверка.")
    return ledgers.stamp_duplicate_view(result)


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


def _identity(item: dict) -> tuple | None:
    base, date = _reference_key(item), _date(item.get("contract_date"))
    return (*base, date) if all(base) and date else None


def _source_date_key(item: dict) -> str:
    """Keep an unparsed source date as evidence, never invent a calendar year."""
    supplied = item.get("source_date_key")
    if isinstance(supplied, str) and re.fullmatch(r'(?:raw-date|unverified-source):[0-9a-f]{64}', supplied):
        return supplied
    dates = sorted({_norm(entry.get("raw")) for entry in
                    (item.get("contract_date_evidence") or item.get("date_evidence") or [])
                    if isinstance(entry, dict) and _norm(entry.get("raw"))})
    source = item.get("source") or {}
    value = dates if dates else [item.get("file_sha256"), source.get("filename"), source.get("sheet")]
    digest = hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    return ('raw-date:' if dates else 'unverified-source:') + digest


def _source_identity(item: dict) -> tuple | None:
    """Source work identity; strict _identity still owns RSS/payment joins."""
    exact = _identity(item)
    if exact is not None:
        return exact
    base = _reference_key(item)
    return (*base, _source_date_key(item)) if all(base) else None


def _reference_differences(identity: tuple, entry: dict) -> list[str]:
    """Which identity attributes of a reference row (РСС, сводная) differ.

    An attribute the reference does not state at all is unknown, not a
    mismatch, only for the customer of the project's own RSS register, whose
    sheet may not name the customer. Every other attribute must be equal."""
    customer, contractor, number, date = identity
    other = _reference_key(entry)
    other_date = _date(entry.get("contract_date"))
    out = []
    if other[1] != contractor:
        out.append("подрядчик")
    if other[2] != number:
        out.append("номер договора")
    if not other_date:
        out.append("дата договора не указана")
    elif other_date != date:
        out.append("дата договора")
    if entry.get("customer_conflict"):
        out.append("в шапке РСС названы разные заказчики")
    elif other[0] and other[0] != customer:
        out.append("заказчик")
    elif not other[0] and entry.get("kind") != "rss":
        out.append("заказчик не указан")
    return out


def _physical_key(item: dict) -> tuple:
    return tuple(_norm(item.get(key)) for key in ("position", "name", "scope", "unit"))


def _cumulative_money(physical: list[dict], warnings: list[str],
                      parts: dict | None = None, dated: list | None = None) -> tuple[float | None, str]:
    """Sum dated, nonduplicated work-period evidence, never RSS closing or payments.

    ``parts`` receives works (СМР) and materials money of the same periods when
    every period carries both labelled halves; otherwise they stay unknown.
    ``dated`` receives (start, end, total, works or None) of the same periods for
    the deadline pace; no second reading."""
    if parts is not None:
        parts.update(works=None, materials=None, split=False)
    if not physical:
        return None, "unspecified"
    periods, ranges, bases = {}, {}, set()
    uncertain = False
    import developaid_monitor_ledgers as ledgers
    for item in ledgers.aggregation_members(physical):
        work = _physical_key(item)
        if item.get("completed_amount") is None:
            uncertain = True
        for period in item.get("periods") or []:
            # An empty cell group is not an execution record. Only omit it
            # after _physical has reconciled this item's monetary total;
            # never turn a missing price for a stated quantity into zero.
            if (item.get("completed_amount") is not None
                    and all(period.get(field) is None
                            for field in ("amount", "quantity", "material_quantity"))):
                continue
            first, last = _date(period.get("date_start")), _date(period.get("date_end"))
            amount = _number(period.get("amount"))
            if not first or not last or amount is None or first > last:
                uncertain = True
                continue
            key = (*work, first, last)
            evidence = (amount, _number(period.get("quantity")), _number(period.get("material_quantity")),
                        _number(period.get("work_amount")) if period.get("amount_split") else None,
                        _number(period.get("material_amount")) if period.get("amount_split") else None)
            if key in periods and periods[key] != evidence:
                uncertain = True
            periods[key] = evidence
            for previous_first, previous_last in ranges.setdefault(work, set()):
                if (first, last) != (previous_first, previous_last) and first <= previous_last and previous_first <= last:
                    uncertain = True
            ranges[work].add((first, last))
            if period.get("amount_basis") == "conflicting":
                uncertain = True
            basis = _basis(period.get("amount_basis"))
            if basis != "unspecified":
                bases.add(basis)
    if len(bases) > 1:
        uncertain = True
        warnings.append("В загруженных накопительных различаются базы НДС выполнения; суммы не сложены.")
    if uncertain or not periods:
        warnings.append("Сумма выполнения по загруженным накопительным на срез не подтверждена: проверьте даты, пересечения периодов, сохранённые суммы и повторяющиеся позиции.")
        return None, "unspecified"
    split = all(v[3] is not None and v[4] is not None for v in periods.values())
    if parts is not None and split:
        parts.update(works=sum(v[3] for v in periods.values()),
                     materials=sum(v[4] for v in periods.values()), split=True)
    if dated is not None:
        dated.extend((dt.date.fromisoformat(key[-2]), dt.date.fromisoformat(key[-1]), value[0],
                      value[3] if split else None)
                     for key, value in periods.items())
    return sum(value[0] for value in periods.values()), next(iter(bases)) if bases else "unspecified"


def build(project: str, cut: str = "", *, include_history: bool = True) -> dict:
    """The universe is the contracts explicitly present in uploaded documents."""
    cut = _cut(cut)
    if not str(project or "").strip():
        raise ContractProblem("Выберите проект.")
    snapshot = _archive(project, cut)
    archive_day = (snapshot or {}).get("taken_at")
    warnings = []
    if snapshot and (not _date(archive_day) or _date(archive_day) > cut):
        warnings.append("Дата накопительного архива не подтверждена или позже среза; архив не включён в этот срез.")
        snapshot, archive_day = None, None
    if snapshot:
        import developaid_monitor_ledgers as ledgers
        try:
            snapshot = ledgers.effective_snapshot(project, cut, snapshot=snapshot)
        except ledgers.LedgerProblem as exc:
            raise ContractProblem(str(exc)) from None
    primary, unresolved = [], []
    for original in (snapshot or {}).get("ledgers") or []:
        ledger = dict(original, kind="ledger", source_date=archive_day)
        missing = [label for field, label in (("customer", "заказчик"), ("contractor", "контрагент"),
                   ("contract", "номер договора"), ("contract_date", "действительная дата договора"))
                   if not (_date(ledger.get(field)) if field == "contract_date" else str(ledger.get(field) or "").strip())]
        if not missing and _date(ledger["contract_date"]) > cut:
            missing.append("дата договора не позже среза")
        if missing:
            unresolved.append({"source": _source(ledger.get("source"), "Накопительная ведомость работ"),
                "contractor": ledger.get("contractor") or "", "contract": ledger.get("contract") or "",
                "contract_date": ledger.get("contract_date"),
                "date_evidence": _date_evidence(snapshot, ledger),
                "identity_warnings": ledger.get("identity_warnings") or [],
                "party_evidence": ledger.get("party_evidence") or {},
                "date_confirmation": ledger.get("date_confirmation"),
                "snapshot_id": (snapshot or {}).get("snapshot_id"), "file_sha256": ledger.get("file_sha256"),
                "reason": "В шапке не подтверждены: " + ", ".join(missing) + ". Источник не потерян и не объединён по догадке."})
            if missing == ["действительная дата договора"]:
                # Known contractor + number are enough to display the source
                # and its quantities. Date qualification stays explicit and
                # cannot enrich RSS, payments or dated legal assertions.
                ledger["contract_date_unverified"] = True
                unresolved[-1]["included_in_register"] = True
                primary.append(ledger)
            continue
        primary.append(ledger)
    summary_sources = [dict(item, kind='summary', source_date=archive_day)
                       for item in (snapshot or {}).get('summary_contracts') or []]
    for summary in summary_sources:
        if summary.get('document_form') != 'closing_summary':
            continue  # Unqualified saved/RSS projections do not expand the universe.
        missing = [label for field, label in (('customer', 'заказчик'), ('contractor', 'подрядчик'),
                   ('contract', 'номер договора')) if not str(summary.get(field) or '').strip()]
        if missing:
            unresolved.append({'source': _source(summary.get('source'), 'Сводная по КС-2'),
                'contractor': summary.get('contractor') or '', 'contract': summary.get('contract') or '',
                'source_kind': 'closing_summary', 'reason': 'В сводной не подтверждены: ' + ', '.join(missing) + '.'})
            continue
        identity = _identity(summary)
        if identity and any(_identity(ledger) and not _reference_differences(_identity(ledger), summary)
                            for ledger in primary):
            continue  # Enrich the existing cumulative id, never create a copy.
        if _date(summary.get('contract_date')) and _date(summary['contract_date']) > cut:
            continue
        if not _date(summary.get('contract_date')):
            unresolved.append({'source': _source(summary.get('source'), 'Сводная по КС-2'),
                'contractor': summary.get('contractor') or '', 'contract': summary.get('contract') or '',
                'source_kind': 'closing_summary', 'included_in_register': True,
                'reason': 'В сводной не подтверждена дата договора; денежный источник сохранён отдельно.'})
        primary.append(summary)
    rss, rss_day = [], None
    if primary:
        rss, rss_day, rss_warnings = _read_rss(project, cut)
        warnings.extend(rss_warnings)
    extras = [*rss, *summary_sources]
    terms, rows = (_read_terms(project) if primary else {}), []
    paid_rows = None
    if primary:
        paid_rows, payment_warnings = contract_risk.payments(
            monitor._latest(project, "estimate", ".xlsx", cut), dt.date.fromisoformat(cut))
        warnings.extend(payment_warnings)
    groups = _groups(primary, project)
    payment_identities: dict[tuple, int] = {}
    for _, ledger_items in groups:
        key = contract_risk.payment_identity(ledger_items[0], reference_key=_reference_key)
        payment_identities[key] = payment_identities.get(key, 0) + 1
    claims: dict[int, int] = {}
    for _, ledger_items in groups:
        identity = _identity(ledger_items[0])
        for entry in extras:
            if identity and not _reference_differences(identity, entry):
                claims[id(entry)] = claims.get(id(entry), 0) + 1
    ambiguous = sum(1 for count in claims.values() if count > 1)
    if ambiguous:
        warnings.append(f"{ambiguous} строк РСС или сводной подходят сразу к нескольким договорам из накопительных "
                        "по подрядчику, номеру и дате; они не присоединены ни к одному.")
    for identifier, ledger_items in groups:
        first = ledger_items[0]
        identity = _identity(first)
        matched = [entry for entry in extras if entry not in ledger_items and identity and not _reference_differences(identity, entry)
                   and claims.get(id(entry), 0) == 1]
        items = ledger_items + matched
        rss_candidates = [entry for entry in extras if entry.get("kind") == "rss" and identity
                          and entry not in matched
                          and (_reference_key(entry)[1] == identity[1] or _reference_key(entry)[2] == identity[2])]
        rss_items = [x for x in items if x.get("kind") == "rss"]
        summary_items = [x for x in items if x.get("kind") == "summary"]
        row_warnings = _warnings([v for x in items for v in [*(x.get("warnings") or []), *(x.get("identity_warnings") or [])]])
        rss_amount, rss_completed, rss_amount_basis, rss_completed_basis = _rss_money(items, row_warnings)
        summary_amount, summary_completed, summary_amount_basis, summary_completed_basis = _summary_money(items, cut, row_warnings)
        amount, amount_basis = (summary_amount, summary_amount_basis) if summary_items else (rss_amount, rss_amount_basis)
        amount_source = ("Сводная: полная сумма договора" if summary_amount is not None else
                         "РСС: полная сумма договора" if rss_amount is not None else "Полная сумма договора не подтверждена")
        if summary_amount is not None and rss_amount is not None and abs(summary_amount-rss_amount) > .01:
            amount = None
            row_warnings.append("РСС и сводная дают разные полные суммы договора; действующая цена не выбрана автоматически.")
        physical_sources = []
        for ledger in ledger_items:
            if ledger.get('kind') != 'ledger':
                continue
            import developaid_monitor_ledgers as ledgers
            duplicates = ledgers.verified_duplicate_sources(ledger.get('items') or [])
            physical_sources.append((ledger, [_physical(item, ledger, cut, _duplicates=duplicates)
                                              for item in ledger.get('items') or []]))
        physical = [item for _, views in physical_sources for item in views]
        money_parts: dict = {}
        dated_money: list = []
        completed, completed_basis = _cumulative_money(physical, row_warnings, money_parts, dated_money)
        if amount is None:
            row_warnings.append("Нет подтверждённой полной суммы договора. Итог года или отдельной ведомости не использован как цена всего договора.")
        comparable = (amount_basis != "conflicting" and completed_basis != "conflicting"
                      and not (amount_basis != "unspecified" and completed_basis != "unspecified"
                               and amount_basis != completed_basis))
        if not comparable:
            row_warnings.append("Полная сумма договора и выполнение по накопительным имеют разные базы НДС; процент и остаток не рассчитаны.")
        ratio = completed / amount if comparable and amount is not None and amount > 0 and completed is not None else None
        if ratio is not None and (ratio < 0 or ratio > 1.000001):
            row_warnings.append("Выполнение по загруженным накопительным выходит за пределы полной суммы договора; требуется сверка.")
        deadlines = {_date(x.get("deadline")) for x in items if _date(x.get("deadline"))}
        deadline = next(iter(deadlines)) if len(deadlines) == 1 else None
        deadline_source = {"label": "Срок из источника"} if deadline else None
        if len(deadlines) > 1:
            row_warnings.append("В источниках указаны разные сроки договора; срок не выбран автоматически.")
        manual = terms.get(identifier)
        manual_reference = None
        if isinstance(manual, dict) and _date(manual.get("deadline")):
            updated = str(manual.get("updated_at") or "")
            updated_day = _date(updated[:10])
            manual_reference = {"deadline": _date(manual["deadline"]), "note": str(manual.get("note") or ""),
                                "updated_at": manual.get("updated_at"), "label": "Текущий ручной срок",
                                "applicable_to_cut": bool(updated_day and updated_day <= cut)}
            if updated_day and updated_day <= cut:
                deadline = manual_reference["deadline"]
                deadline_source = {"label": "Указан вручную", "note": manual_reference["note"],
                                   "updated_at": manual.get("updated_at")}
            else:
                row_warnings.append("Ручной срок введён позже даты среза или дата ввода неизвестна; он показан только как текущая справка.")
        financial = []
        if rss_items:
            financial.append({"label": "РСС — справочная сверка", "amount": rss_amount,
                "completed": rss_completed, "completed_label": ("Столбец L РСС: «" +
                    str((rss_items[0].get("source") or {}).get("completed_header") or "заголовок не подтверждён") +
                    "»; показатель источника, не выполнение по накопительным"),
                "source": _source(rss_items[0].get("source")), "source_date": rss_day,
                "amount_basis": rss_amount_basis, "completed_basis": rss_completed_basis})
        if summary_items:
            financial.append({"label": "Сводная — справочная сверка", "amount": summary_amount,
                "completed": summary_completed, "completed_label": "Сумма актов сводной; не подмена выполнения по накопительным",
                "source": _source(summary_items[0].get("source")), "source_date": archive_day,
                "amount_basis": summary_amount_basis, "completed_basis": summary_completed_basis})
        references = []
        for ledger, views in physical_sources:
            source_items = ledgers.aggregation_members(ledger.get('items') or [])
            values = [_number(item.get("completed_amount")) for item in source_items]
            planned_values = [_number(item.get("planned_amount")) for item in source_items]
            future_excluded = any(item.get("future_periods_excluded") for item in views)
            reported_completed = (sum(values) if not future_excluded and values
                                  and all(v is not None for v in values) else None)
            reported_planned = (sum(planned_values) if planned_values
                                and all(v is not None for v in planned_values) else None)
            planned_bases = {item.get("planned_amount_basis") for item in source_items} - {None, "", "unspecified"}
            completed_bases = ({item.get("completed_amount_basis") for item in source_items}
                               | {p.get("amount_basis") for item in source_items for p in item.get("periods") or []}) - {None, "", "unspecified"}
            statement_comparable = (_basis_metadata_current(snapshot)
                                    and "conflicting" not in planned_bases | completed_bases
                                    and len(planned_bases) <= 1 and len(completed_bases) <= 1
                                    and not (planned_bases and completed_bases and planned_bases != completed_bases))
            source_split = bool(source_items) and all(item.get("amount_split")
                and _number(item.get("completed_work_amount")) is not None
                and _number(item.get("completed_material_amount")) is not None for item in source_items)
            financial_complete = bool(source_items) and all(
                _number(item.get(field)) is not None for item in source_items
                for field in ('planned_amount', 'completed_amount')) and not ledger.get('unread_rows_count')
            natural_complete = bool(source_items) and all(item.get('unit') and all(
                _number(item.get(field)) is not None for field in ('plan_quantity', 'completed_quantity'))
                for item in source_items)
            planned_split = bool(source_items) and all(item.get('planned_cost_split') is True and all(
                _number(item.get(field)) is not None for field in ('planned_work_amount', 'planned_material_amount'))
                and _number(item.get('planned_amount')) is not None
                and abs(_number(item.get('planned_work_amount'))+_number(item.get('planned_material_amount'))
                        -_number(item.get('planned_amount'))) <= max(.01, abs(_number(item.get('planned_amount')))*1e-7)
                for item in source_items)
            planned_works = sum(_number(item.get('planned_work_amount')) for item in source_items) if planned_split else None
            planned_materials = sum(_number(item.get('planned_material_amount')) for item in source_items) if planned_split else None
            completed_works = (sum(_number(item.get('completed_work_amount')) for item in source_items)
                               if source_split and reported_completed is not None else None)
            completed_materials = (sum(_number(item.get('completed_material_amount')) for item in source_items)
                                   if source_split and reported_completed is not None else None)
            part_bases = {item.get('planned_work_amount_basis') for item in source_items} - {None, '', 'unspecified'}
            parts_comparable = (planned_split and source_split and financial_complete and _basis_metadata_current(snapshot)
                and 'conflicting' not in part_bases | completed_bases and len(part_bases) <= 1
                and len(completed_bases) <= 1 and not (part_bases and completed_bases and part_bases != completed_bases)
                and all(_number(item.get(field)) >= 0 for item in source_items
                        for field in ('planned_work_amount', 'planned_material_amount')))
            references.append({"source": _source(ledger.get("source"), "Накопительная ведомость"),
                "period_year": ledger.get("period_year"), "source_date": archive_day,
                "completed": reported_completed,
                "planned": reported_planned,
                "completion_ratio": (reported_completed / reported_planned
                                     if reported_completed is not None
                                     and reported_planned is not None and reported_planned > 0
                                     and statement_comparable else None),
                "monetary_comparable": statement_comparable,
                'financial_complete': financial_complete, 'natural_complete': natural_complete,
                "source_complete": bool(ledger.get("source_complete")) and all(
                    _number(item.get(field)) is not None for item in source_items
                    for field in ("plan_quantity", "planned_amount", "completed_quantity", "completed_amount")),
                "unread_rows_count": ledger.get("unread_rows_count", 0),
                "incomplete_rows_count": ledger.get("incomplete_rows_count", 0),
                "planned_amount_basis": ("conflicting" if len(planned_bases) > 1 else
                                         next(iter(planned_bases)) if planned_bases else "unspecified"),
                "completed_amount_basis": ("conflicting" if len(completed_bases) > 1 else
                                           next(iter(completed_bases)) if completed_bases else "unspecified"),
                "amount_scope": "statement",
                "stated_contract_amount": _number(ledger.get("contract_amount")),
                "works_materials_split": source_split,
                'planned_cost_split': planned_split,
                'planned_works': planned_works, 'planned_materials': planned_materials,
                'completed_works': completed_works, 'completed_materials': completed_materials,
                'parts_monetary_comparable': parts_comparable,
                'works_completion_ratio': (completed_works/planned_works if parts_comparable
                    and planned_works is not None and planned_works > 0 and completed_works is not None else None),
                'materials_completion_ratio': (completed_materials/planned_materials if parts_comparable
                    and planned_materials is not None and planned_materials > 0 and completed_materials is not None else None),
                "period_dates_known": bool(ledger.get("period_dates_known")),
                "future_periods_excluded": future_excluded,
                "label": "Сумма сохранённых итогов позиций этой ведомости; справочно, период закрытия не установлен"})
        summary_only = not any(ledger.get('kind') == 'ledger' for ledger in ledger_items)
        row = {"id": identifier, "contractor": str(first.get("contractor") or ""),
               'source_kind': 'closing_summary' if summary_only else 'cumulative',
               "customer": str(first.get("customer") or ""), "contract": str(first.get("contract") or ""),
               "contract_date": _date(first.get("contract_date")),
               "source_date_key": _source_date_key(first),
               "contract_identity_kind": ('closing_summary_date_unverified' if not _date(first.get('contract_date')) else 'closing_summary')
                   if summary_only else "source_header_date_unverified" if not _date(first.get("contract_date")) else "header",
               "identity_source": first.get("identity_source") or {},
               "date_confirmation": first.get("date_confirmation"),
               "date_confirmations": [x["date_confirmation"] for x in ledger_items if x.get("date_confirmation")],
               "date_evidence": [e for x in ledger_items for e in _date_evidence(snapshot, x)],
               "subject": str(next((x.get("subject") for x in items if x.get("subject")), "")),
               "amount": amount, "amount_source_label": amount_source,
               "completed": completed, "completion_ratio": ratio,
               # Works (СМР) and materials supply are separate facts; delivery is
               # not construction. Unknown when the books do not label both halves.
               "completed_works": money_parts.get("works"),
               "completed_materials": money_parts.get("materials"),
               "works_materials_split": bool(money_parts.get("split")),
               "works_materials_note": ("" if money_parts.get("split") or completed is None else
                   "В накопительных этого договора суммы работ (СМР) и материалов не разделены; "
                   "показано общее выполнение."),
               "amount_basis": amount_basis, "completed_basis": completed_basis,
               "monetary_comparable": comparable,
               "remaining": amount-completed if comparable and amount is not None and completed is not None else None,
               "deadline": deadline, "deadline_source": deadline_source,
               "manual_deadline_reference": manual_reference, "deadline_passed": bool(deadline and deadline < cut),
               "source": _source(first.get("source"), 'Договор из сводной КС-2' if summary_only else "Договор из шапки накопительной"),
               "source_date": archive_day, "warnings": _warnings(row_warnings),
               "requires_reconciliation": bool(row_warnings), "physical_items": physical,
               "sources": [_source(x.get("source")) for x in ledger_items],
               "financial_sources": financial,
               "rss_match": _rss_match(identity, rss_items, rss_candidates, rss_day),
               "scope": sorted({str(item.get("scope") or "") for item in physical if item.get("scope")}),
               "performance_basis": ('Денежное закрытие по КС-2 из сводной; не физическая готовность и не объёмы КС-6а'
                   if summary_only else "Денежное выполнение только по загруженным накопительным и завершённым датированным периодам; не оплата и не физическая готовность"),
               "performance_source_count": len(physical_sources), "reported_performance_sources": references}
        if summary_only:
            row['summary_progress'] = _summary_observation(summary_items, cut)
        else:
            from developaid_monitor_statement_union import statement_union
            row["statement_progress"] = statement_union(row)
        row["risk"] = contract_risk.forecast(
            amount=amount, completed=completed, comparable=comparable, periods=dated_money,
            cut=dt.date.fromisoformat(cut), deadline=dt.date.fromisoformat(deadline) if deadline else None,
            works=row["completed_works"] if row["works_materials_split"] else None,
            materials=row["completed_materials"] if row["works_materials_split"] else None)
        row["advance"] = contract_risk.advance(
            row, paid_rows, reference_key=_reference_key,
            identity_counts=payment_identities, completed_basis=completed_basis)
        rows.append(row)
    rows.sort(key=lambda r: (_norm(r["contractor"]), _norm(r["customer"]), _norm(r["contract"]), r["id"]))
    note = ("Договоры из загруженных КС-6а и подписанных разделов сводной КС-2 показаны с источниками показателей. "
            "Общий реестр РСС не расширяет этот список; разные реквизиты не объединяются автоматически.")
    result = {"cut": cut, "source_date": archive_day, "rows": rows,
            "source_coverage": {"files": (snapshot or {}).get("files") or [],
                "cumulative_sheets": len((snapshot or {}).get("ledgers") or []),
                "source_complete": bool(snapshot) and all(ledger.get("source_complete") is True
                                       for ledger in (snapshot or {}).get("ledgers") or []),
                "incomplete_rows": sum(ledger.get("incomplete_rows_count") or 0
                                       for ledger in (snapshot or {}).get("ledgers") or [])},
            "unresolved_sources": unresolved,
            "counts": {"contracts_from_cumulative": sum(row.get('source_kind') == 'cumulative' for row in rows), "cumulative_sheets": len((snapshot or {}).get("ledgers") or []),
                       "unresolved_headers": len(unresolved)},
            "scope_note": note, "empty_reason": ("Загрузите архив накопительных: без него списка договоров нет." if not snapshot else
                                                   "В загруженных документах пока нет распознанных договоров." if not rows else ""),
            "snapshots": {"rss": rss_day, "cumulative": archive_day, "cumulative_id": (snapshot or {}).get("snapshot_id")},
            "warnings": _warnings(warnings + _warnings((snapshot or {}).get("warnings"))),
            "performance_basis": "Выполнение по загруженным накопительным; реестр РСС и оплата не подменяют выполнение КС.",
            "risk_summary": contract_risk.summary(rows),
            "risk_basis": ("Прогноз окончания — по денежному темпу накопительных за последние 90 дней; "
                           "это показатель выполнения, а не физическая готовность. Оплаты — «Реестр платежей» РСС "
                           "по точному подрядчику, номеру и дате договора.")}
    if any(item.get('document_form') == 'closing_summary' for item in summary_sources):
        result['counts']['contracts_from_documents'] = len(rows)
        result['counts']['contracts_from_closing_summary_only'] = sum(row['source_kind'] == 'closing_summary' for row in rows)
        result['source_coverage']['closing_summary_sections'] = len(summary_sources)
    if include_history:
        import developaid_monitor_contract_history as progress_history
        return progress_history.enrich(project, cut, result,
            build_register=lambda previous_cut: build(project, previous_cut, include_history=False))
    return result


def _date_evidence(snapshot: dict, ledger: dict) -> list[dict]:
    """Header date cells with the exact binding the page sends back to clarify."""
    if ledger.get('kind') == 'summary':
        return [dict(evidence) for evidence in ledger.get('contract_date_evidence') or []]
    import developaid_monitor_header_confirmations as confirmations
    return [dict(evidence, binding=confirmations.binding(snapshot, ledger, evidence))
            for evidence in ledger.get("contract_date_evidence") or []]


def _rss_match(identity: tuple | None, matched: list[dict], candidates: list[dict],
               rss_day: str | None) -> dict:
    """Why RSS did or did not complete this contract, attribute by attribute."""
    if rss_day is None:
        return {"status": "no_rss", "text": "РСС на дату среза не загружен.", "candidates": []}
    if matched:
        return {"status": "matched", "text": "Строка РСС совпала по подрядчику, номеру и дате договора.",
                "candidates": []}
    rows = [{"source": _source(entry.get("source")), "contractor": str(entry.get("contractor") or ""),
             "contract": str(entry.get("contract") or ""), "contract_date": _date(entry.get("contract_date")),
             "differences": _reference_differences(identity, entry) if identity else []}
            for entry in candidates[:3]]
    if not rows:
        return {"status": "not_found", "candidates": [],
                "text": "В РСС нет строки с тем же подрядчиком или номером договора."}
    return {"status": "differs", "candidates": rows,
            "text": "В РСС есть похожие строки, но не совпало: " + "; ".join(
                f"{row['contract'] or 'без номера'} — {', '.join(row['differences']) or 'подходит к нескольким договорам'}"
                for row in rows) + "."}


def confirm_header_date(project: str, cut: str, snapshot_id: str, **fields) -> dict:
    """The HTTP caller must authenticate before entering this operation."""
    import developaid_monitor_header_confirmations as confirmations
    snapshot = _archive(project, _cut(cut))
    if not snapshot or snapshot.get("snapshot_id") != snapshot_id:
        raise ContractProblem("Выбранный архив накопительных не найден; уточнение даты не перенесено на другой снимок.")
    try:
        return confirmations.confirm(project, snapshot, **fields)
    except confirmations.ConfirmationProblem as exc:
        raise ContractProblem(str(exc)) from None


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

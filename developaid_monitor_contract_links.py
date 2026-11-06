"""Evidence links between contracts, cumulative ledgers and site reports.

This module does not accept works, infer quantities from prose, or change money.
A suggested contractor match remains a suggestion until a human confirms it.
Both Monitor and management reports use this resolver.
"""
from __future__ import annotations

import contextlib
import copy
import datetime
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import developaid_monitor as monitor
import developaid_monitor_daily as daily

_MAX_TEXT = 20000
_ID = re.compile(r"^[0-9a-f]{64}$")
_LEGAL_FORMS = {"ооо", "ао", "пао", "оао", "зао", "ип"}
_STATUS = {
    "confirmed": "Договор определён",
    "proposed": "Связь с договором нужно подтвердить",
    "ambiguous": "Подходит несколько договоров — требуется выбор",
    "unmatched": "Договор не уточнён",
}


class LinkProblem(ValueError):
    """A safe, user-facing validation problem, with no source paths."""


def _day(value: Any, *, optional: bool = False) -> str:
    if not value and optional:
        return ""
    if not value:
        return datetime.date.today().isoformat()
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.date().isoformat() if isinstance(value, datetime.datetime) else value.isoformat()
    try:
        text = str(value)
        date = datetime.date.fromisoformat(text)
        if date.isoformat() != text:
            raise ValueError
        return text
    except (TypeError, ValueError):
        raise LinkProblem("Укажите дату в виде ГГГГ-ММ-ДД.") from None


def _text(value: Any) -> str:
    return " ".join(str(value or "").replace("ё", "е").casefold().split())


def _party(value: Any) -> str:
    # Legal forms and punctuation may differ. Substrings/acronyms are never an
    # exact identity: e.g. Альфа and Альфа Строй remain different parties.
    words = re.findall(r"[0-9a-zа-я]+", _text(value))
    if words and words[0] in _LEGAL_FORMS:
        words.pop(0)
    return " ".join(words)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _project_key(project: str) -> str:
    return monitor._resolved_slug(project)


def _scope(value: Any) -> set[str]:
    return {m.casefold() for m in re.findall(
        r"\bкорпус\s*№?\s*([0-9]{1,3}[а-яa-z]?)\b", str(value or "")[:_MAX_TEXT], re.I)}


def _contract_scopes(row: dict) -> set[str]:
    scopes = _scope(row.get("subject"))
    for scope in row.get("scope") or []:
        scopes.update(_scope(scope))
    for item in row.get("physical_items") or []:
        scopes.update(_scope(item.get("scope")))
        scopes.update(_scope(item.get("name")))
    return scopes


def _compatible(evidence: dict, row: dict) -> bool:
    actual, expected = _scope(evidence.get("scope")), _contract_scopes(row)
    return not actual or not expected or bool(actual & expected)


def _number(value: Any) -> str:
    text = _text(value).replace("–", "-").replace("—", "-")
    text = re.sub(r"^договор\s*", "", text).lstrip("№# ")
    return text.split(" от ", 1)[0].strip()


def _explicit_number(text: str, row: dict) -> bool:
    number = _number(row.get("contract"))
    if not number:
        return False
    # An apartment/floor number does not identify a contract. Require the word
    # договор/дог. immediately before the escaped number, with a token boundary.
    pattern = (r"\b(?:договор(?:у|а|ом)?|дог\.)\s*(?:№|n)?\s*"
               + re.escape(number) + r"(?![\w/-])")
    return bool(re.search(pattern, _text(text).replace("–", "-").replace("—", "-")))


def _signature(evidence: dict) -> str:
    return _digest([_party(evidence.get("contractor")), _text(evidence.get("text")),
                    _text(evidence.get("scope"))])


def _evidence(project: str, register: dict, cut: str, start: str = "") -> list[dict]:
    names = [str(row.get("contractor") or "") for row in register.get("rows") or []]
    out: dict[str, dict] = {}
    for report in sorted(daily._load_reports(project), key=lambda r: str(r.get("date") or "")):
        try:
            day = _day(report.get("date"))
        except LinkProblem:
            continue
        if not report.get("date") or day > cut or start and day < start:
            continue
        parsed = report.get("parsed") or {}
        known = names + [str(c.get("name") or "") for c in parsed.get("contractors") or []]
        raw = parsed.get("works") or []
        attributed = daily.attribute_works(raw, known)
        for index, item in enumerate(attributed):
            line = str(item.get("line") or "").strip()[:_MAX_TEXT]
            if not line:
                continue
            name = str(item.get("contractor") or "").strip()
            inline = daily._split_inline(line)
            exact_party = bool(name)
            if item.get("named_inline"):
                # The ordinary daily UI allows fuzzy aliases. Such attribution
                # must not silently approve a legal contract identity.
                exact_party = len(inline) == 2 and _party(inline[0]) == _party(name)
                line = inline[-1].strip()
            elif index < len(raw):
                exact_party = exact_party and _party(raw[index].get("contractor")) == _party(name)
            line = " ".join(line.split()).strip(" ;.")
            if not line:
                continue
            scopes = _scope(line)
            scope = ", ".join(f"Корпус {n}" for n in sorted(scopes))
            evidence = {"date": day, "contractor": name, "scope": scope, "text": line,
                        "source": {"kind": "daily_report", "date": day, "line_index": index + 1},
                        "party_exact": exact_party}
            evidence["signature"] = _signature(evidence)
            evidence["id"] = _digest([_project_key(project), day, evidence["signature"]])
            # Repeated identical lines within one daily report are one piece of
            # evidence, never extra work/quantity or additional acceptance.
            out.setdefault(evidence["id"], evidence)
    return list(out.values())


def _path(project: str) -> Path:
    return monitor._project_dir(project) / "contract_links.json"


@contextlib.contextmanager
def _locked(project: str):
    folder = monitor._project_dir(project)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        import fcntl
    except ImportError:
        raise LinkProblem("Сохранение связей недоступно в этой среде.") from None
    descriptor = os.open(folder / ".contract_links.lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def _read(project: str) -> dict:
    try:
        value = json.loads(_path(project).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "links": {}}
    except (ValueError, OSError):
        raise LinkProblem("Сохранённые связи договоров не удалось прочитать.") from None
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("links"), dict):
        raise LinkProblem("Формат сохранённых связей договоров не распознан.")
    for evidence_id, item in value["links"].items():
        if not isinstance(evidence_id, str) or not _ID.fullmatch(evidence_id) or not isinstance(item, dict):
            raise LinkProblem("Формат сохранённых связей договоров не распознан.")
        if not _ID.fullmatch(str(item.get("signature") or "")) or not isinstance(item.get("confirmed"), bool):
            raise LinkProblem("Происхождение сохранённой связи договора не распознано.")
        if item.get("contract_id") and not _ID.fullmatch(str(item["contract_id"])):
            raise LinkProblem("Сохранённый номер договора не распознан.")
        for field in ("candidate_contract_ids", "blocked_contract_ids"):
            ids = item.get(field, [])
            if not isinstance(ids, list) or any(not isinstance(i, str) or not _ID.fullmatch(i) for i in ids):
                raise LinkProblem("Сохранённые номера договоров не распознаны.")
    return value


def _write(project: str, data: dict) -> None:
    path = _path(project)
    descriptor, temporary = tempfile.mkstemp(prefix=".contract_links-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def enrich(project: str, register: dict, cut: str, start: str = "") -> dict:
    """Return a copy of a register with traceable, non-financial daily evidence."""
    cut, start = _day(cut), _day(start, optional=True)
    if start and start > cut:
        raise LinkProblem("Начало периода позже его окончания.")
    result = copy.deepcopy(register)
    rows = result.get("rows") or []
    # An identity collision is not a reason to pick a row by list position.
    ids: dict[str, list[dict]] = {}
    for row in rows:
        ids.setdefault(str(row.get("id") or ""), []).append(row)
    unique = {key: values[0] for key, values in ids.items() if key and len(values) == 1}
    evidence = _evidence(project, result, cut, start)
    saved = _read(project).get("links") or {}
    for item in evidence:
        candidates = [row for row in rows if row.get("id") in unique
                      and _party(item["contractor"])
                      and _party(item["contractor"]) == _party(row.get("contractor"))
                      and _compatible(item, row)]
        direct = saved.get(item["id"])
        applicable = [record for record in saved.values()
                      if record["signature"] == item["signature"]
                      and str(record.get("source_date") or "9999") <= item["date"]]
        manual = direct or max(applicable, key=lambda r: (r.get("source_date") or "", r.get("confirmed_at") or ""), default={})
        blocked = {str(manual.get("contract_id") or "")} if manual.get("confirmed") is False else set()
        explicit = [row for row in candidates if item["party_exact"]
                    and str(row["id"]) not in blocked and _explicit_number(item["text"], row)]
        # Bind to the exact work signature and the current project's registry.
        # Stale/deleted contracts and a changed contract scope do not revive links.
        manual_row = unique.get(str(manual.get("contract_id") or ""))
        candidate_ids = sorted({str(row["id"]) for row in candidates})
        same_source = manual.get("evidence_id") == item["id"]
        # An identical line can recur under the same known contract choices.
        # A newly introduced competing contract makes future copies ambiguous;
        # a prior confirmation is not a perpetual contractor-wide permission.
        repeat_with_same_choices = (item["date"] >= str(manual.get("source_date") or "9999")
                                    and manual.get("candidate_contract_ids") == candidate_ids)
        if (manual.get("confirmed") is True and manual_row is not None and _compatible(item, manual_row)
                and (same_source or repeat_with_same_choices)):
            chosen, basis = manual_row, "manual"
        elif len(explicit) == 1:
            chosen, basis = explicit[0], "explicit_number"
        else:
            chosen, basis = None, "candidate" if candidates else "none"
        item["contract_id"] = str(chosen["id"]) if chosen else ""
        item["candidate_contract_ids"] = candidate_ids
        if chosen and item["contract_id"] not in item["candidate_contract_ids"]:
            item["candidate_contract_ids"].append(item["contract_id"])
        item["link_basis"] = basis
        item["match_status"] = ("confirmed" if chosen else "ambiguous" if len(candidates) > 1
                                else "proposed" if candidates else "unmatched")
        item["status"] = _STATUS[item["match_status"]]
        item.pop("signature", None)
        item.pop("party_exact", None)
    for row in rows:
        related = [item for item in evidence if str(row.get("id") or "") in item["candidate_contract_ids"]]
        dates = {"Срез договоров": str(row.get("source_date") or result.get("source_date") or "")}
        for label, field in (("Срез РСС", "rss"), ("Архив накопительных", "cumulative")):
            snapshot_date = (result.get("snapshots") or {}).get(field)
            if isinstance(snapshot_date, str) and snapshot_date:
                dates[label] = snapshot_date
        if related:
            dates["Последнее сообщение о работах"] = max(item["date"] for item in related)
        dates = {label: day for label, day in dates.items() if day}
        confirmed = [item for item in related if item["contract_id"] == row.get("id")]
        issues = []
        if not evidence:
            issues.append("В выбранном периоде нет строк работ из ежедневных отчётов. Это не подтверждает остановку работ.")
        elif not related:
            issues.append("Работы этого договора в ежедневных отчётах периода не определены. Акты могут относиться к другому периоду.")
        if any(item["match_status"] != "confirmed" for item in related):
            issues.append("Связь сообщений с договором требует подтверждения; совпадение подрядчика не подтверждает состав работ.")
        if related and not row.get("physical_items"):
            issues.append("Накопительная с объёмами к этому договору не привязана.")
        if str(row.get("id") or "") not in unique:
            issues.append("Идентификатор договора неоднозначен; автоматическая привязка отключена.")
        row["reconciliation"] = {
            "status": "Есть подтверждённые связи" if confirmed else "Требуется уточнение" if related else "Нет сопоставленных сообщений",
            "source_dates": dates, "daily_evidence": related, "issues": issues}
    result["unmatched_works"] = [item for item in evidence if item["match_status"] != "confirmed"]
    result["reconciliation_cut"] = cut
    result["reconciliation_start"] = start or None
    result["reconciliation_note"] = "Ежедневный отчёт — сообщение со стройки, а не акт приёмки или подтверждение объёма."
    return result


def set_link(project: str, contract_id: str, evidence_id: str, cut: str,
             confirmed: bool = True) -> dict:
    """Confirm/remove an exact-source work link; never accepts client work text."""
    if not isinstance(confirmed, bool) or not _ID.fullmatch(str(evidence_id)):
        raise LinkProblem("Неверное подтверждение или номер строки ежедневного отчёта.")
    import developaid_monitor_contracts as contracts
    register = contracts.build(project, _day(cut))
    rows = [row for row in register.get("rows") or [] if str(row.get("id")) == str(contract_id)]
    if len(rows) != 1 or not contract_id:
        raise LinkProblem("Договор не найден в выбранном проекте или его номер неоднозначен.")
    found = [item for item in _evidence(project, register, _day(cut)) if item["id"] == evidence_id]
    if len(found) != 1:
        raise LinkProblem("Строка ежедневного отчёта не найдена в выбранном проекте на эту дату.")
    evidence = found[0]
    if not _compatible(evidence, rows[0]):
        raise LinkProblem("Корпус в сообщении не соответствует корпусу работ договора. Проверьте исходные данные.")
    with _locked(project):
        value = _read(project)
        signature = evidence["signature"]
        candidates = sorted({str(row["id"]) for row in register.get("rows") or []
                             if _party(evidence["contractor"])
                             and _party(evidence["contractor"]) == _party(row.get("contractor"))
                             and _compatible(evidence, row)})
        # One record per exact source preserves previous decisions when an
        # identically worded task later moves to another contract. A negative
        # decision also suppresses number-based auto-linking until confirmed.
        value["links"][evidence_id] = {"contract_id": str(contract_id), "evidence_id": evidence_id,
                                       "signature": signature, "confirmed": confirmed,
                                       "confirmed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                       "source_date": evidence["date"], "basis": "manual",
                                       "candidate_contract_ids": candidates}
        _write(project, value)
    return {"contract_id": str(contract_id), "evidence_id": evidence_id, "confirmed": confirmed}


def enrich_report_works(project: str, groups: list[dict], start: Any, end: Any) -> list[dict]:
    """Link report lines using the same registry/resolver, without money totals.

    Existing reports without cumulative sources keep their historical shape.
    No second, competing interpretation of a contractor name is created here.
    """
    import developaid_monitor_ledgers as ledgers
    if ledgers.latest_snapshot(project, _day(end)) is None:
        return groups
    import developaid_monitor_contracts as contracts
    register = enrich(project, contracts.build(project, _day(end)), _day(end), _day(start))
    by_id = {str(row.get("id")): row for row in register.get("rows") or []}
    evidences: dict[str, dict] = {}
    for row in register.get("rows") or []:
        for item in (row.get("reconciliation") or {}).get("daily_evidence") or []:
            evidences[item["id"]] = item
    for item in register.get("unmatched_works") or []:
        evidences[item["id"]] = item
    out = copy.deepcopy(groups)
    for group in out:
        for entry in group.get("lines") or []:
            matches = [item for item in evidences.values()
                       if _party(item["contractor"]) == _party(group.get("contractor"))
                       and _text(item["text"]).strip(" ;.") == _text(entry.get("line")).strip(" ;.")
                       and item["date"] in entry.get("days", [])]
            links = {}
            for item in matches:
                if item["match_status"] == "confirmed" and item["contract_id"] in by_id:
                    row = by_id[item["contract_id"]]
                    links[row["id"]] = {"id": row["id"], "contract": str(row.get("contract") or ""),
                                        "label": f"Договор {row.get('contract') or 'без номера'}",
                                        "status": "confirmed", "source": item["link_basis"],
                                        "href": "/monitor#" + urlencode({"tab": "contracts", "project": project,
                                                                         "contract": row["id"]})}
            entry["contract_links"] = list(links.values())
            entry["contract_status"] = "Договор определён" if links else "Договор не уточнён"
    return out

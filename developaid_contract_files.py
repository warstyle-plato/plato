"""Contract PDFs uploaded into the contract card of «Договоры».

A file belongs to one contract of the register (its 64-hex id). The PDF is kept
next to its read result, so a newer reader reads it again instead of serving a
frozen answer. A document that names another contract is refused: a schedule
of a neighbouring contract must not become this one's plan. Each contract or
supplementary agreement is an edition; two files of one edition are both kept
and named, the choice is the owner's. Positions of each estimate are proposed
links to the schedule of the latest edition at or before it. Authenticate first.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

import developaid_contract_documents as documents
import developaid_contract_schedule_links as links
import developaid_monitor as monitor

MAX_BYTES = 20 * 1024 * 1024


class ContractFilesProblem(ValueError):
    """A controlled, safe message that may be returned to an authenticated user."""


def _directory(project: str, contract_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", str(contract_id or "")):
        raise ContractFilesProblem("Выберите договор из списка.")
    if not str(project or "").strip():
        raise ContractFilesProblem("Выберите проект.")
    return monitor._project_dir(project) / "contract_documents" / contract_id


def _write(path: Path, data: bytes) -> None:
    handle, temporary = tempfile.mkstemp(prefix=".part-", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _shown(iso: str | None) -> str:
    return ".".join(reversed(iso.split("-"))) if iso else "без даты"


def _same_contract(found: dict | None, row: dict) -> str:
    """Empty when the document names the card's contract; otherwise the reason."""
    from developaid_monitor_contracts import _contract_number
    if not found:
        return ""
    number = _contract_number(found.get("number"), reference=True)
    expected = _contract_number(row.get("contract"), reference=True)
    date, expected_date = found.get("date"), row.get("contract_date")
    if number == expected and (not expected_date or date == expected_date):
        return ""
    return (f"В документе договор № {found.get('number')} от {_shown(date)}, а в карточке — "
            f"договор № {row.get('contract') or '—'} от {_shown(expected_date)}. "
            "Загрузите документ этого договора.")


def _record(sha: str, filename: str, content: bytes, uploaded_at: str) -> dict:
    try:
        read = documents.read(content)
    except ValueError as exc:
        raise ContractFilesProblem(str(exc)) from None
    return {"sha256": sha, "filename": filename, "uploaded_at": uploaded_at,
            "reader": documents.READER_VERSION, **read}


def store(project: str, row: dict, filename: str, content: bytes) -> dict:
    """Read and keep one PDF of the contract `row`; the same file twice is one file."""
    folder = _directory(project, row.get("id"))
    if not content or len(content) > MAX_BYTES:
        raise ContractFilesProblem("Выберите непустой PDF размером не больше 20 МБ.")
    if not content.startswith(b"%PDF"):
        raise ContractFilesProblem("Файл не открылся как PDF.")
    sha = hashlib.sha256(content).hexdigest()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    existing = folder / f"{sha}.json"
    if existing.exists() and (folder / f"{sha}.pdf").exists():
        record = _current(folder, sha)
        return {**_summary(record), "already": True}
    record = _record(sha, Path(str(filename or "")).name[:240] or "документ.pdf", content,
                     dt.datetime.now(dt.timezone.utc).isoformat())
    reason = _same_contract(record.get("contract"), row)
    if reason:
        raise ContractFilesProblem(reason)
    _write(folder / f"{sha}.pdf", content)
    _write(existing, json.dumps(record, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    return {**_summary(record), "already": False}


def _current(folder: Path, sha: str) -> dict:
    """The stored read, read again from the PDF when the reader has changed since."""
    path = folder / f"{sha}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        raise ContractFilesProblem("Сохранённый документ договора не прочитан; проверьте хранилище проекта.") from None
    if record.get("reader") == documents.READER_VERSION:
        return record
    pdf = folder / f"{sha}.pdf"
    if not pdf.exists():
        record.setdefault("warnings", []).insert(
            0, "Файл документа не сохранился: показан прежний разбор, перечитать его нечем.")
        return record
    try:
        fresh = _record(sha, record.get("filename", ""), pdf.read_bytes(), record.get("uploaded_at", ""))
    except ContractFilesProblem as exc:
        fresh = {**record, "reader": documents.READER_VERSION, "estimates": [], "schedule": None,
                 "warnings": [str(exc)]}
    _write(path, json.dumps(fresh, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    return fresh


def _edition(record: dict) -> tuple:
    agreement = record.get("agreement")
    if not agreement:
        return (0, (record.get("contract") or {}).get("date") or "", 0)
    number = agreement.get("number") or ""
    return (1, agreement.get("date") or "", int(number) if number.isdigit() else 0)


def _title(record: dict) -> str:
    agreement, contract = record.get("agreement"), record.get("contract")
    if agreement:
        return f"Дополнительное соглашение № {agreement['number']} от {_shown(agreement.get('date'))}"
    if contract:
        return f"Договор № {contract['number']} от {_shown(contract.get('date'))}"
    return "Документ без номера договора и соглашения"


def _summary(record: dict) -> dict:
    schedule = record.get("schedule") or {}
    return {"sha256": record["sha256"], "filename": record.get("filename", ""), "title": _title(record),
            "estimates": len(record.get("estimates") or []), "schedule_lines": len(schedule.get("lines") or []),
            "corrections": len(schedule.get("corrections") or [])}


def listing(project: str, contract_id: str) -> dict:
    """Every stored document of the contract, contract first, agreements by date."""
    folder = _directory(project, contract_id)
    if not folder.is_dir():
        return {"contract_id": contract_id, "documents": []}
    records = [_current(folder, path.stem) for path in sorted(folder.glob("*.json"))
               if re.fullmatch(r"[0-9a-f]{64}", path.stem)]
    records.sort(key=lambda r: (_edition(r), r.get("uploaded_at", ""), r["sha256"]))
    for record in records:
        record["title"] = _title(record)
        notes = []
        if not record.get("contract"):
            notes.append("Номер договора в документе не прочитан: документ привязан к договору по выбору "
                         "в карточке.")
        twins = [r["filename"] for r in records if r is not record and _edition(r) == _edition(record)]
        if twins:
            notes.append(f"{record['title']} загружено ещё и файлом «{'», «'.join(twins)}». "
                         "Проверьте, какой из файлов действующий.")
        record["warnings"] = notes + list(record.get("warnings") or [])
    _propose_links(records)
    return {"contract_id": contract_id, "documents": records}


def _propose_links(records: list[dict]) -> None:
    """Each estimate against the schedule in force at its edition; proposed anew, never stored."""
    current = None
    for record in records:
        if ((record.get("schedule") or {}).get("lines")):
            current = record
        for estimate in record.get("estimates") or []:
            estimate["links"] = {
                **links.propose(estimate, current and current["schedule"], agreement=bool(record.get("agreement"))),
                "schedule": current["title"] if current else ""}

"""Contract PDFs uploaded into the contract card of «Договоры».

A file belongs to one contract of the register (its 64-hex id). The PDF is kept
next to its read result, so a newer reader reads it again instead of serving a
frozen answer. A document that names another contract is refused: a schedule
of a neighbouring contract must not become this one's plan. Each contract or
supplementary agreement is an edition; two files of one edition are both kept
and named, the choice is the owner's. Positions of each estimate are proposed
links to the schedule of the latest edition at or before it; the owner's
choices (`links.json`) are laid over the proposals. A removed file stays on
disk with the time of removal and can be returned. Authenticate first.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import logging
import os
import re
import tempfile
from pathlib import Path

import developaid_contract_act_dates as act_dates
import developaid_contract_documents as documents
import developaid_contract_control as control
import developaid_contract_fact as fact
import developaid_contract_link_choices as choices
import developaid_contract_plan as plan
import developaid_contract_schedule_links as links
import developaid_monitor as monitor

MAX_BYTES = 20 * 1024 * 1024
CHOICES = "links.json"


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


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


@contextlib.contextmanager
def _locked(folder: Path):
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        import fcntl
    except ImportError:
        raise ContractFilesProblem("Сохранение в карточке договора недоступно в этой среде.") from None
    descriptor = os.open(folder / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def _json(path: Path, value) -> None:
    _write(path, json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))


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
        raise ContractFilesProblem("Файл не открылся как PDF. Сохраните документ в PDF заново, например выгрузкой из системы электронного документооборота, и загрузите ещё раз.")
    sha = hashlib.sha256(content).hexdigest()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    existing = folder / f"{sha}.json"
    if existing.exists() and (folder / f"{sha}.pdf").exists():
        with _locked(folder):
            record = _current(folder, sha)
            restored = bool(record.pop("removed_at", None))
            if restored:
                _json(existing, record)
        return {**_summary(record), "already": True, "restored": restored}
    record = _record(sha, Path(str(filename or "")).name[:240] or "документ.pdf", content, _now())
    reason = _same_contract(record.get("contract"), row)
    if reason:
        raise ContractFilesProblem(reason)
    _write(folder / f"{sha}.pdf", content)
    _json(existing, record)
    return {**_summary(record), "already": False, "restored": False}


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
        if record.get("removed_at"):
            fresh["removed_at"] = record["removed_at"]
    except ContractFilesProblem as exc:
        fresh = {**record, "reader": documents.READER_VERSION, "estimates": [], "schedule": None,
                 "warnings": [str(exc)]}
    _json(path, fresh)
    return fresh


def _edition(record: dict) -> tuple:
    act = record.get("act")
    if act:
        # An act of acceptance is no edition of the plan: it follows the contract and its agreements.
        number = act.get("number") or ""
        return (2, act.get("date") or "", int(number) if number.isdigit() else 0)
    agreement = record.get("agreement")
    if not agreement:
        return (0, (record.get("contract") or {}).get("date") or "", 0)
    number = agreement.get("number") or ""
    return (1, agreement.get("date") or "", int(number) if number.isdigit() else 0)


def _title(record: dict) -> str:
    agreement, contract, act = record.get("agreement"), record.get("contract"), record.get("act")
    if act:
        return f"Акт КС-2 № {act.get('number') or 'без номера'} от {_shown(act.get('date'))}"
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


def _records(folder: Path) -> list[dict]:
    """Documents in the card, contract first, agreements by date; removed ones are not among them."""
    records = [_current(folder, path.stem) for path in sorted(folder.glob("*.json"))
               if re.fullmatch(r"[0-9a-f]{64}", path.stem)]
    records.sort(key=lambda r: (_edition(r), r.get("uploaded_at", ""), r["sha256"]))
    for record in records:
        record["title"] = _title(record)
    return records


def _in_force(records: list[dict]):
    """Each estimate with the latest schedule at or before its edition."""
    current = None
    for record in records:
        if (record.get("schedule") or {}).get("lines"):
            current = record
        for index, estimate in enumerate(record.get("estimates") or []):
            yield record, index, estimate, current


def _proposal(record: dict, estimate: dict, schedule: dict | None) -> dict:
    return links.propose(estimate, schedule and schedule["schedule"], agreement=bool(record.get("agreement")))


def _date(record: dict) -> str | None:
    return ((record.get("agreement") or record.get("contract")) or {}).get("date")


def _editions(records: list[dict], chosen: dict) -> list[dict]:
    """Documents that bring an estimate or a schedule, each with the latest of both at or before it."""
    editions, schedule, source = [], None, None
    for record in records:
        brings_schedule = bool((record.get("schedule") or {}).get("lines"))
        brings_estimate = any(e.get("scope") != "accepted" for e in record.get("estimates") or [])
        schedule = record if brings_schedule else schedule
        source = record if brings_estimate else source
        if source is None or not (brings_schedule or brings_estimate):
            continue
        estimates = []
        for estimate in source["estimates"]:
            if estimate["links"]["schedule_sha256"] != (schedule["sha256"] if schedule else ""):
                # A newer schedule without a new estimate: the links are carried onto it.
                estimate = {**estimate, "links": choices.apply(_proposal(source, estimate, schedule), chosen,
                                                               schedule and schedule["schedule"])}
            estimates.append(estimate)
        remaining = any(e.get("scope") == "remaining" for e in source["estimates"])
        editions.append({"sha256": record["sha256"], "title": record["title"], "date": _date(record),
                         "estimates": estimates, "estimate_title": source["title"],
                         "schedule": schedule and schedule["schedule"],
                         "schedule_title": schedule["title"] if schedule else "",
                         "start": _date(source) if remaining else None})
    return editions


def _choices(folder: Path) -> dict:
    try:
        stored = json.loads((folder / CHOICES).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (ValueError, OSError):
        raise ContractFilesProblem("Сохранённые связи с графиком не прочитаны; проверьте хранилище проекта.") from None
    return stored.get("choices") or {}


def listing(project: str, contract_id: str, cut: str = "", acts: dict | None = None) -> dict:
    """Every document in the card with its links, the accumulated plan and fact on `cut` and the removed files.

    `acts` are the KS-6a works of the contract on `cut` (`fact.acts`); None when the register has none.
    """
    folder = _directory(project, contract_id)
    cut = cut or dt.date.today().isoformat()
    if not folder.is_dir():
        acts = act_dates.resolve(acts, [])
        return _with_control({"contract_id": contract_id, "documents": [], "removed": [],
                              "plan": plan.build([], cut), "fact": _fact([], None, acts, cut)}, acts, cut)
    every = _records(folder)
    records = [r for r in every if not r.get("removed_at")]
    acts = act_dates.resolve(acts, records)
    for record in records:
        notes = []
        if not record.get("contract"):
            notes.append("Номер договора в документе не прочитан: документ привязан к договору по выбору "
                         "в карточке.")
        twins = [r["filename"] for r in records if r is not record and _edition(r) == _edition(record)]
        if twins:
            notes.append(f"{record['title']} загружен{'о' if record.get('agreement') else ''} ещё и файлом "
                         f"«{'», «'.join(twins)}». Проверьте, какой из файлов действующий.")
        record["warnings"] = notes + list(record.get("warnings") or [])
    chosen = _choices(folder)
    for record, _, estimate, schedule in _in_force(records):
        result = choices.apply(_proposal(record, estimate, schedule), chosen, schedule and schedule["schedule"])
        estimate["links"] = {**result, "schedule": schedule["title"] if schedule else "",
                             "schedule_sha256": schedule["sha256"] if schedule else ""}
    removed = [{"sha256": r["sha256"], "filename": r.get("filename", ""), "title": r["title"],
                "removed_at": r["removed_at"]} for r in every if r.get("removed_at")]
    editions = _editions(records, chosen)
    planned = plan.build(editions, cut)
    return _with_control({"contract_id": contract_id, "documents": records, "removed": removed, "plan": planned,
                          "fact": _fact(editions, planned["in_force"], acts, cut)}, acts, cut)


def _fact(editions, in_force, acts, cut):
    """The fact on `cut` with the dates the acts КС-2 gave to the KS-6a periods."""
    return {**fact.build(editions, in_force, acts, cut), "act_dates": (acts or {}).get("act_dates") or []}


def _with_control(listed, acts, cut):
    """The deviation, lag and forecast of the listed plan and fact (step 7)."""
    listed["control"] = control.build(listed["plan"], listed["fact"], (acts or {}).get("deadline"),
                                      (acts or {}).get("deadline_label") or "", cut)
    return listed


def register_control(project: str, register: dict, cut: str) -> dict:
    """Put the card's deviation, lag and forecast on every row of the register as `schedule_control`.

    The numbers are the card's own (`listing`), not a second calculation; a card that fails keeps
    the register and says why in its row.
    """
    for row in register.get("rows") or []:
        try:
            listed = listing(project, row["id"], cut, fact.acts(row))
        except ContractFilesProblem as exc:
            row["schedule_control"] = {"documents": None, "note": str(exc)}
            continue
        except Exception as exc:
            logging.getLogger("developaid.monitor").error("Contract card control unavailable (%s)", type(exc).__name__)
            row["schedule_control"] = {"documents": None, "note": "Отчёт по графику договора не построен: документы "
                                       "карточки не прочитаны. Откройте карточку договора и обновите её."}
            continue
        found = listed["control"]
        total, forecast = found["total"] or {}, found["forecast"] or {}
        row["schedule_control"] = {
            "documents": len(listed["documents"]),
            "note": found["note"] if listed["documents"] else "ГПР и расчёт договора в карточку не загружены.",
            **{k: total.get(k) for k in ("state", "lag_days", "ahead_days", "planned", "fact", "deviation", "percent")},
            **{k: forecast.get(k) for k in ("finish", "deadline", "from_register", "done", "threat", "days_over",
                                            "days_early", "passed")}}
    return register


def save_links(project: str, contract_id: str, sha256: str, estimate: int, picked: list[dict],
               clear: bool = False, cut: str = "", acts: dict | None = None) -> dict:
    """Confirm, choose or clear links of positions of one estimate; all positions or none are saved."""
    folder = _directory(project, contract_id)
    with _locked(folder):
        records = [r for r in _records(folder) if not r.get("removed_at")]
        found = next(((record, current, schedule) for record, index, current, schedule in _in_force(records)
                      if record["sha256"] == sha256 and index == estimate), None)
        if found is None:
            raise ContractFilesProblem("Расчёт не найден среди документов карточки: обновите карточку.")
        record, current, schedule = found
        positions = _proposal(record, current, schedule)["positions"]
        stored, now = _choices(folder), _now()
        for choice in picked:
            index = choice.get("index")
            if not isinstance(index, int) or not 0 <= index < len(positions):
                raise ContractFilesProblem("Позиция не найдена в расчёте: обновите карточку.")
            item = positions[index]
            if clear:
                stored.pop(item["key"], None)
                continue
            try:
                stored[item["key"]] = choices.decide(item, schedule and schedule["schedule"], choice.get("lines"),
                                                     choice.get("shares"), now)
            except choices.LinkChoiceProblem as exc:
                raise ContractFilesProblem(str(exc)) from None
        _json(folder / CHOICES, {"version": 1, "choices": stored})
    return listing(project, contract_id, cut, acts)


def remove(project: str, contract_id: str, sha256: str, *, restore: bool = False, cut: str = "",
           acts: dict | None = None) -> dict:
    """Take a file out of the card, or return it; the file itself is kept."""
    folder = _directory(project, contract_id)
    if not re.fullmatch(r"[0-9a-f]{64}", str(sha256 or "")) or not (folder / f"{sha256}.json").exists():
        raise ContractFilesProblem("Документ не найден в карточке: обновите карточку.")
    with _locked(folder):
        record = _current(folder, sha256)
        if restore:
            record.pop("removed_at", None)
        else:
            record["removed_at"] = _now()
        _json(folder / f"{sha256}.json", record)
    return listing(project, contract_id, cut, acts)

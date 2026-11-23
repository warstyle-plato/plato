"""Детерминированный контроль ответов продаж. Все данные живут на ядре.

Ответ/ожидание события не является банковским фактом. Вызывающий держит
current owner grant, затем origin_lock; функции берут project lock последним.
Telegram send intent необратим: неоднозначную отправку не повторяем.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import tempfile
import uuid

from . import sales_dialogue, sales_questions, sales_store

MOSCOW = dt.timezone(dt.timedelta(hours=3))
_POINT = re.compile(r"(?m)^\s*(\d+)[.)](?!\d)[ \t]*")
_DATE = re.compile(r"(?<!\w)(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?(?!\w|\.\d)")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _number(value):
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def _money(value, signed=False):
    return (f"{value:+,.2f}" if signed else f"{value:,.2f}").replace(",", " ").replace(".", ",") + " ₽"


def _label(question):
    subject = question.get("subject") or {}
    return ("Договор на " + str(subject["unit"]) if subject.get("unit") else
            "Договор " + str(subject["contract"]) if subject.get("contract") else "Вопрос по помещению")


def _event_id(scope, question_key):
    return f"{scope['chat_id']}:{question_key}"


def _calendar_token(text, start, end):
    return not (re.match(r"\s*(?:млн\b|тыс\b|руб\w*|₽|%|м[²2](?!\w)|кв\.?\s*м\b|га\b|кг\b|шт\b)", text[end:], re.I)
                or re.search(r"(?:№|номер|идентификатор|id|дду|договор)\s*[-:]?\s*$", text[:start], re.I))


def _day(value):
    try:
        return dt.date.fromisoformat(value) if isinstance(value, str) and len(value) == 10 else None
    except ValueError:
        return None


def _now(value=None):
    return (value or dt.datetime.now(dt.timezone.utc)).astimezone(MOSCOW)


def _path(where, project):
    return Path(where) / "cabinet" / "followups" / (sales_store.slug(project) + ".json")


def load(where, project):
    path = _path(where, project)
    if not path.exists():
        return {"project": project, "events": {}, "deliveries": {}, "attestations": {}, "seen": [], "ingestions": {}}
    try:
        value = json.loads(path.read_text())
        if value["project"] != project or any(not isinstance(value[k], dict)
                for k in ("events", "deliveries", "attestations")) or not isinstance(value["seen"], list):
            raise ValueError("shape")
        for group in ("events", "deliveries"):
            for item in value[group].values():
                if not isinstance(item, dict) or not isinstance(item.get("scope"), dict) or not isinstance(item.get("state"), str):
                    raise ValueError("entry")
                scope = item["scope"]
                if (not isinstance(scope.get("chat_id"), int) or scope["chat_id"] >= 0
                        or any(not isinstance(scope.get(k), str) or not scope[k]
                               for k in ("monitor_project", "sales_project", "grant_sha256", "link_sha256"))):
                    raise ValueError("scope")
        if any(not isinstance(item, dict) for item in value["attestations"].values()):
            raise ValueError("attestation")
        value.setdefault("ingestions", {})
        if not isinstance(value["ingestions"], dict) or any(not isinstance(item, str) for item in value["seen"]):
            raise ValueError("ingestion shape")
        return value
    except Exception as exc:
        raise RuntimeError("Не читается журнал отложенного контроля продаж.") from exc


def _save(where, project, data):
    path = _path(where, project)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".followup-")
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(data, out, ensure_ascii=False, allow_nan=False)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def source(where, project):
    kept = sales_store.load(where, project)
    contracts = ((kept.get("sources") or {}).get("contracting") or {}).get("data")
    if kept.get("broken") or not isinstance(contracts, dict):
        return None, ""
    if not isinstance(contracts.get("rows", []), list) or any(not isinstance(row, dict) for row in contracts.get("rows", [])):
        return None, ""
    try:
        return contracts, digest(contracts)
    except (ValueError, TypeError):
        return None, ""


def identity(row):
    from . import chessboard
    text = lambda v: " ".join(str(v or "").casefold().split())
    unit = str(row.get("unit") or "")
    hit = chessboard._UNIT.search(unit)
    return {"contract": text(row.get("contract")), "signed": str(row.get("signed") or ""),
            "product": text(row.get("product")), "building": chessboard.building(unit),
            "unit": str(int(hit[1])) if hit else text(unit)}


def _row(contracts, target):
    if not isinstance(target, dict) or not target.get("contract") or not _day(target.get("signed")) or not target.get("product"):
        return None
    rows = [r for r in (contracts or {}).get("rows") or [] if identity(r) == target]
    if not rows:
        return None
    try:
        return rows[0] if len({digest(r) for r in rows}) == 1 else None
    except (ValueError, TypeError):
        return None


def native_attestation(contracts, sha, target):
    """Uploader-declared business date plus lossless recognized row presence."""
    row = _row(contracts, target)
    if (row is not None and row.get("escrow_observed") is True
            and (contracts or {}).get("as_of_provenance") == "uploader_declared"
            and _day((contracts or {}).get("as_of"))):
        return {"source_sha256": sha, "target": target, "as_of": contracts["as_of"],
                "observed": True, "complete_scope": True, "provenance": "uploader_declared"}
    return {}


def resolve_question(question, contracts):
    """Restore only identity of a legacy question; never reconstruct its past balance."""
    if question.get("subject") or question.get("kind") != "money":
        return question
    candidates = [r for r in (contracts or {}).get("rows") or []
                  if sales_questions.money_key(r) == question.get("key")]
    try:
        if candidates and len({digest(r) for r in candidates}) == 1:
            row = candidates[0]
            if _row(contracts, identity(row)) is not None:
                return dict(question, subject={k:row.get(k) for k in ("contract", "signed", "product", "unit")},
                            expected_event=question.get("expected_event") or "payment",
                            subject_provenance="current_source_exact_question_key")
    except (ValueError, TypeError):
        pass
    return question


def extract(text, telegram_date, expected_event=""):
    """Один пункт ответа; даты только от настоящего Telegram timestamp."""
    kind = ("resigning" if re.search("переподпис", text, re.I) else
            "registration" if re.search("регистр", text, re.I) else
            "payment" if re.search(r"оплат|плат[её]ж|деньг|поступ", text, re.I) else "explanation")
    if kind == "explanation" and expected_event in ("payment", "registration", "resigning"):
        kind = expected_event
    out = {"quote": text, "event_kind": kind, "event_date": None, "due_at": None,
           "date_basis": "", "reason": "Уточните срок ожидаемого события."}
    claimed = (re.search(r"\b(?:оплатили|оплачено|зарегистрировали|зарегистрировано|поступили)\b", text, re.I)
               and not re.search(r"\bне\s+(?:оплатили|оплачено|зарегистрировали|зарегистрировано|поступили)\b", text, re.I))
    try:
        anchor = dt.datetime.fromtimestamp(int(telegram_date), MOSCOW).date()
        if int(telegram_date) <= 0:
            return out
    except (TypeError, ValueError, OverflowError, OSError):
        return out
    if claimed:
        out.update(claim="unverified", event_mode="reported_completion", event_date=anchor.isoformat(),
                   due_at=dt.datetime.fromtimestamp(int(telegram_date), MOSCOW).isoformat(),
                   date_basis="Telegram message timestamp; completion claim is unverified", reason="")
        return out
    dates = []
    try:
        for hit in _DATE.finditer(text):
            if not _calendar_token(text, hit.start(), hit.end()):
                return out
            dates.append((dt.date(int(hit[3]) if hit[3] else anchor.year, int(hit[2]), int(hit[1])), hit[0]))
        for hit in re.finditer(r"(?<!\w)\d{4}-\d{2}-\d{2}(?!\w)", text):
            if not _calendar_token(text, hit.start(), hit.end()):
                return out
            dates.append((dt.date.fromisoformat(hit[0]), hit[0]))
        for word, offset in (("послезавтра", 2), ("завтра", 1)):
            if re.search(r"(?<!\w)" + word + r"(?!\w)", text, re.I):
                dates.append((anchor + dt.timedelta(days=offset), word))
    except ValueError:
        return out
    if (len(dates) != 1 or dates[0][0] < anchor or kind == "explanation"
            or re.search(r"\bесли\b|после\s+(?:регистрации|переподписания|оплаты)", text, re.I)):
        return out
    day, quote = dates[0]
    out.update(event_date=day.isoformat(), date_basis=quote,
               due_at=dt.datetime.combine(day + dt.timedelta(days=1), dt.time(9), MOSCOW).isoformat(),
               reason="")
    return out


def _parts(text, count):
    hits = list(_POINT.finditer(text))
    if not hits:
        return {1: text} if count == 1 else {}
    parts = {}
    prefix = text[:hits[0].start()].strip()
    if prefix and not re.fullmatch(r"(?:добрый\s+(?:вечер|день)|доброе\s+утро|здравствуйте)[!,\.\s]*(?:платон(?:\s+сергеевич)?)?[!,\.\s]*", prefix, re.I):
        return {}
    for i, hit in enumerate(hits):
        n = int(hit[1])
        if not 1 <= n <= count or n in parts:
            return {}
        parts[n] = text[hit.end():hits[i + 1].start() if i + 1 < len(hits) else len(text)].strip()
    return parts


def looks_like_answer(text):
    return bool(_POINT.search(text) and re.search(r"ожида|переподпис|регистр|оплат|плат[её]ж", text, re.I))


def _explicit(text, subject):
    target = identity(subject)
    if target["unit"].isdigit() and re.search(r"кв(?:артира)?\.?\s*№?\s*0*" +
                                            re.escape(target["unit"]) + r"(?!\d)", text, re.I):
        return True
    contract = target["contract"].split(" от ")[0].removeprefix("дду ").strip()
    return bool(contract and len(contract) >= 4 and contract in " ".join(text.casefold().split()))


def _enqueue(where, project, data, scope, key, text, question=None, trusted_markup=False):
    if key in data["deliveries"]:
        old = data["deliveries"][key]
        if old["state"] != "cancelled" or old.get("cancel_reason") != "source_changed_before_send":
            return
    batch_id = ""
    if question:
        item = dict(question, text=text)
        text = sales_questions.message([item])
        batch_id = digest([scope, key, text])
        question = item
    elif not trusted_markup:
        text = html.escape(text)
    data["deliveries"][key] = {"id": key, "scope": scope, "text": text, "state": "pending",
                                "batch_id": batch_id, "question": question,
                                "event_key": _event_id(scope, question["key"]) if question else None}


def ingest(where, project, scope, *, message_id, reply_to_id, quoted, text, author_id,
           author, telegram_date, candidate=False):
    """Only core-verified Reply may attach events. Ordinary candidates never do."""
    if (message_id <= 0 or author_id <= 0 or telegram_date <= 0 or not text.strip()
            or not candidate and (reply_to_id <= 0 or not sales_dialogue.is_question(quoted))):
        return {"events": 0, "candidate": False}
    with sales_questions.lock(where, project):
        data = load(where, project)
        seen = f"{scope['chat_id']}:{message_id}"
        if seen in data["seen"]:
            return {"events": 0, "candidate": False}
        batches = sales_dialogue.load(where, project)["batches"]
        contracts, _ = source(where, project)
        matching = []
        for bid, batch in batches.items():
            if batch["chat_id"] != scope["chat_id"]:
                continue
            if candidate:
                parts = _parts(text, len(batch["questions"]))
                if (batch.get("message_id") and parts and all(
                        batch["questions"][n-1].get("kind") == "money"
                        and (data["events"].get(_event_id(scope, batch["questions"][n-1]["key"])) or {}).get("state") not in ("resolved", "cancelled", "answered")
                        and _explicit(part, resolve_question(batch["questions"][n-1], contracts).get("subject") or {})
                        for n, part in parts.items())):
                    matching.append((bid, batch))
            elif (batch.get("message_id") == reply_to_id or
                  not batch.get("message_id") and batch["text"] == quoted):
                if batch["text"] == quoted:
                    matching.append((bid, batch))
        if len(matching) != 1:
            return {"events": 0, "candidate": False}
        bid, batch = matching[0]
        data["seen"].append(seen)
        if candidate:
            message = int(batch["message_id"])
            chat = str(scope["chat_id"])
            context = (f'<a href="https://t.me/c/{chat[4:]}/{message}">исходное сообщение Платона</a>'
                       if chat.startswith("-100") else f"сообщение Платона № {message} от {batch.get('asked_at', '')}")
            # One invitation per original batch, not per repeated ordinary message.
            _enqueue(where, project, data, scope, f"candidate:{bid}",
                     f"Пожалуйста, ответьте через Reply на {context}, чтобы я связал пояснения с вопросами. "
                     "Это сообщение пока не связано с вопросами и сроки контроля не сохранены.", trusted_markup=True)
            _save(where, project, data)
            return {"events": 0, "candidate": True}
        parts = _parts(text, len(batch["questions"]))
        data["ingestions"][seen] = {"scope": scope, "batch_id": bid, "text": text, "quoted": quoted,
            "message_id": message_id, "reply_to_id": reply_to_id, "author_id": author_id,
            "author": author, "telegram_date": telegram_date, "provenance": "verified_telegram_reply"}
        invitation = data["deliveries"].get(f"candidate:{bid}")
        if invitation and invitation["state"] in ("pending", "claimed"):
            invitation["state"] = "cancelled"
        if not parts:
            _enqueue(where, project, data, scope, f"mapping:{seen}",
                     "Пожалуйста, укажите номера пунктов исходного сообщения, к которым относятся пояснения и сроки.")
        count = 0
        for n, part in parts.items():
            question = resolve_question(batch["questions"][n - 1], contracts)
            subject = question.get("subject") or {}
            baseline = _number((question.get("baseline") or {}).get("escrow_paid"))
            if question.get("baseline") and baseline is None:
                question = dict(question, baseline=dict(question["baseline"], escrow_paid=None))
            event_key = _event_id(scope, question["key"])
            previous = data["events"].get(event_key) or {}
            if previous.get("state") == "resolved" and re.fullmatch(r"(?:спасибо|благодарю|понятно|хорошо)[!.\s]*", part, re.I):
                continue
            revision = int(previous.get("revision") or 0) + 1
            for delivery in data["deliveries"].values():
                if delivery.get("event_key") == event_key and delivery["state"] in ("pending", "claimed"):
                    delivery["state"] = "cancelled"
            expected = previous.get("event_kind") or question.get("expected_event", "")
            event = {**extract(part, telegram_date, expected), "key": event_key, "question_key": question["key"], "revision": revision,
                     "scope": scope, "question": question, "batch_id": bid,
                     "target": identity(subject) if subject else None, "baseline_paid": baseline,
                     "baseline_source_sha256": (question.get("baseline") or {}).get("source_sha256", ""),
                     "baseline_quality": "reported_unverified",
                     "baseline_evidence": {"source_sha256": (question.get("baseline") or {}).get("source_sha256", ""),
                         "target": identity(subject) if subject else None,
                         "as_of": (question.get("baseline") or {}).get("as_of"),
                         "observed": (question.get("baseline") or {}).get("observed") is True
                             and (question.get("baseline") or {}).get("as_of_provenance") == "uploader_declared",
                         "complete_scope": True, "provenance": "original_uploader_declared_snapshot"},
                     "provenance": {"message_id": message_id, "reply_to_id": reply_to_id,
                                    "author": author, "author_id": author_id,
                                    "telegram_date": telegram_date, "timezone": "Europe/Moscow"},
                     "state": "scheduled", "eval_basis": "", "history": previous.get("history", [])}
            if previous:
                event["history"] = event["history"] + [{k:v for k,v in previous.items() if k != "history"}]
            timeline = bool(event["event_date"] or event["event_kind"] in ("payment", "registration", "resigning"))
            if question.get("kind") != "money" and not timeline:
                event["state"] = "answered"
            elif not event["due_at"] or not subject:
                event["state"] = "waiting_identity" if not subject else "waiting_deadline"
                label = {"payment": "оплата", "registration": "регистрация", "resigning": "переподписание ДДУ"}.get(event["event_kind"], "указанное событие")
                reason = ("Уточните точный договор, его дату и помещение: в сохранённом вопросе нет однозначной связи с выгрузкой."
                          if not subject else f"К какой дате ожидается {label}? Укажите дату с годом.")
                delivery_key = f"deadline:{event_key}:{revision}"
                _enqueue(where, project, data, scope, delivery_key, f"{_label(question)} (пункт {n}): {reason}", question)
                data["deliveries"][delivery_key]["event_revision"] = revision
            data["events"][event_key] = event
            count += 1
        _save(where, project, data)
        return {"events": count, "candidate": False}


def attest(where, project, request, now=None):
    with sales_questions.lock(where, project):
        data = load(where, project)
        contracts, sha = source(where, project)
        day = _day(request.get("as_of"))
        target = request.get("target")
        if (not sha or sha != request.get("source_sha256") or not day or day > _now(now).date()
                or not isinstance(target, dict) or _row(contracts, target) is None
                or request.get("observed") is not True or request.get("complete_scope") is not True):
            raise ValueError("Нужны точный текущий источник, дата и явное подтверждение наблюдаемого полного поля эскроу выбранного договора.")
        record = {"source_sha256": sha, "target": target, "as_of": day.isoformat(),
                  "observed": True, "complete_scope": True, "provenance": "owner-attested"}
        data["attestations"][digest([sha, target])] = record
        _save(where, project, data)
        return record


def evaluate(event, contracts, sha, attestation, now=None, baseline_attestation=None):
    day = _day((attestation or {}).get("as_of"))
    due = dt.datetime.fromisoformat(event["due_at"]).date()
    today = _now(now).date()
    row = _row(contracts, event.get("target")) if event.get("target") else None
    baseline = _number(event.get("baseline_paid"))
    paid, amount = _number((row or {}).get("escrow_paid")), _number((row or {}).get("amount"))
    if (not sha or not day or not attestation.get("observed") or not attestation.get("complete_scope")
            or attestation.get("source_sha256") != sha or attestation.get("target") != event.get("target")
            or not due <= day <= today or (today-day).days > sales_questions.FRESH_DAYS
            or row is None or paid is None or amount is None or amount <= 0):
        return {"state": "unknown", "reason": "Нет актуальной датированной полной выгрузки с однозначным договором и наблюдаемой суммой эскроу; проверка не выполнена."}
    initial = baseline_attestation or {}
    initial_day = _day(initial.get("as_of"))
    known = (baseline is not None and initial.get("observed") is True and initial.get("complete_scope") is True
             and initial.get("source_sha256") == event.get("baseline_source_sha256")
             and initial.get("target") == event.get("target") and initial_day and initial_day <= day)
    delta = paid - baseline if known else None
    state = ("full" if paid >= amount else
             "partial_current" if not known and paid > 0 else "zero_current" if not known else
             "unchanged" if delta == 0 else "decreased" if delta < 0 else "partial")
    return {"state": state, "as_of": day.isoformat(), "paid": paid, "amount": amount,
            "baseline_paid": baseline, "delta": delta,
            "baseline_quality": "observed" if known else "reported_unverified",
            "registration_state": str(_day(row.get("registered_at")) or "В источнике нет даты регистрации.")}


def scopes(where):
    result, errors = [], []
    for path in (Path(where) / "cabinet" / "followups").glob("*.json"):
        try:
            header = json.loads(path.read_text())
            if _path(where, header["project"]) != path:
                raise ValueError("journal path mismatch")
            raw = load(where, header["project"])
            result.extend((raw["project"], item["scope"]) for group in ("events", "deliveries")
                          for item in raw[group].values())
        except Exception:
            errors.append({"scope_id": digest(path.name), "error": "Не читается журнал контроля продаж; этот журнал закрыт для отправки."})
    return list({digest([project, scope]): (project, scope) for project, scope in result}.values()), errors


def poll(where, project, scope, now=None):
    moment = _now(now)
    with sales_questions.lock(where, project):
        data = load(where, project)
        contracts, sha = source(where, project)
        for event in data["events"].values():
            if event["scope"] != scope:
                if event["scope"]["chat_id"] == scope["chat_id"]:
                    event["state"] = "cancelled"
                continue
            if event["state"] not in ("scheduled", "waiting_data") or moment < dt.datetime.fromisoformat(event["due_at"]):
                continue
            attestation = data["attestations"].get(digest([sha, event.get("target")]),
                                                 native_attestation(contracts, sha, event.get("target")))
            initial = data["attestations"].get(digest([event.get("baseline_source_sha256"), event.get("target")]), event.get("baseline_evidence", {}))
            basis = digest([sha, attestation, initial, moment.date().isoformat()])
            if event["eval_basis"] == basis:
                continue
            event["eval_basis"] = basis
            result = evaluate(event, contracts, sha, attestation, moment, initial)
            event["evaluation"] = result
            key = f"{event['key']}:{event['revision']}"
            if result["state"] == "unknown":
                event["state"] = "waiting_data"
                text = result["reason"]
                delivery_key = "unknown:" + key
            else:
                event["state"] = ("resolved" if result["state"] == "full" else
                                  "awaiting_remainder_date" if result["state"] in ("partial", "partial_current") else "awaiting_reply")
                event["check_state"] = "completed"
                for delivery in data["deliveries"].values():
                    if delivery.get("event_key") == event["key"] and delivery["state"] in ("pending", "claimed"):
                        delivery["state"] = "cancelled"
                paid, delta = result["paid"], result["delta"]
                text = f"По выгрузке на {result['as_of']} на эскроу {_money(paid)} из {_money(result['amount'])}. "
                text += (f"Изменение к исходной сумме {_money(result['baseline_paid'])} — {_money(delta, True)}. "
                         if delta is not None else "Исходная сумма вопроса не подтверждена банковским срезом; прирост не рассчитан. ")
                if event.get("event_mode") == "reported_completion" and result["state"] != "full":
                    text += "Вы сообщили о выполненном событии. Уточните, пожалуйста, какая сумма и на какую дату отражена в подтверждающем источнике. "
                else:
                    text += {"full": "Сумма договора покрыта.", "partial": "Поступление частичное; полная сумма договора пока не покрыта. Уточните, пожалуйста, срок оплаты остатка.",
                         "partial_current": "Учтена часть суммы договора. Уточните, пожалуйста, срок оплаты остатка.",
                         "zero_current": "В этой выгрузке учтено 0 ₽. Уточните, пожалуйста, следующий срок оплаты.",
                         "unchanged": "Сумма не изменилась. Уточните, пожалуйста, следующий срок оплаты.",
                         "decreased": "Сумма уменьшилась. Уточните, пожалуйста, причину изменения и следующий срок."}[result["state"]]
                if event["event_kind"] == "registration":
                    text += ((f" В ответе сообщили о регистрации; {result['registration_state']} "
                              "Сообщение о регистрации не подтверждает факт оплаты.")
                             if event.get("event_mode") == "reported_completion" else
                             (f" Регистрацию ожидали {event['event_date']}; {result['registration_state']} "
                              "Ожидание регистрации не является обещанной датой оплаты."))
                delivery_key = "result:" + key
            _enqueue(where, project, data, scope, delivery_key, f"{_label(event['question'])}: {text}",
                     None if result["state"] == "full" else event["question"])
            data["deliveries"][delivery_key]["event_key"] = event["key"]
            data["deliveries"][delivery_key]["event_revision"] = event["revision"]
            data["deliveries"][delivery_key]["evaluation_basis"] = basis
        out = []
        for item in data["deliveries"].values():
            if item["scope"] != scope:
                if item["scope"]["chat_id"] == scope["chat_id"] and item["state"] in ("pending", "claimed"):
                    item["state"] = "cancelled"
                continue
            if item["state"] == "claimed" and moment.timestamp() >= item["lease_until"]:
                item["state"] = "pending"
            if item["state"] == "attempted" and moment.timestamp() >= item["attempted_at"] + 90:
                item.update(state="delivery_unknown", error="Подтверждение отправки не получено; повтор отключён.")
            if item["state"] != "pending":
                continue
            item.update(state="claimed", claim_id=uuid.uuid4().hex, lease_until=moment.timestamp()+90)
            out.append({k:item[k] for k in ("id", "claim_id", "scope")})
        _save(where, project, data)
        return out


def stop(where, project, chat_id, reason="Отменено владельцем."):
    with sales_questions.lock(where, project):
        data = load(where, project)
        for group in ("events", "deliveries"):
            for item in data[group].values():
                if item["scope"]["chat_id"] == chat_id and item["state"] not in ("sent", "attempted"):
                    item.update(state="cancelled", cancel_reason=reason)
        _save(where, project, data)


def begin(where, project, scope, delivery_id, claim_id, now=None):
    with sales_questions.lock(where, project), sales_store._project_lock(where, project):
        data = load(where, project)
        item = data["deliveries"].get(delivery_id)
        if (not item or item["scope"] != scope or item["state"] != "claimed"
                or item.get("claim_id") != claim_id or _now(now).timestamp() >= item["lease_until"]):
            return {"authorized": False}
        event = data["events"].get(item.get("event_key"))
        if item.get("event_key") and (not event or event.get("revision") != item.get("event_revision")
                                      or event["state"] == "cancelled"):
            item.update(state="cancelled", cancel_reason="answer_revision_changed")
            _save(where, project, data)
            return {"authorized": False}
        if item.get("evaluation_basis"):
            contracts, sha = source(where, project)
            attestation = data["attestations"].get(digest([sha, event.get("target")]), native_attestation(contracts, sha, event.get("target")))
            initial = data["attestations"].get(digest([event.get("baseline_source_sha256"), event.get("target")]), event.get("baseline_evidence", {}))
            basis = digest([sha, attestation, initial, _now(now).date().isoformat()])
            if basis != item["evaluation_basis"]:
                item.update(state="cancelled", cancel_reason="source_changed_before_send")
                event.update(state="scheduled", eval_basis="")
                _save(where, project, data)
                return {"authorized": False}
        if item["batch_id"]:
            sales_dialogue.prepare(where, project, scope["chat_id"], [item["question"]],
                                   _now(now).date().isoformat(), batch_id=item["batch_id"])
        item.update(state="attempted", attempt_id=uuid.uuid4().hex, attempted_at=_now(now).timestamp())
        _save(where, project, data)
        return {"authorized": True, "attempt_id": item["attempt_id"], "text": item["text"],
                "chat_id": scope["chat_id"]}


def receipt(where, project, scope, delivery_id, attempt_id, message_id, error=""):
    with sales_questions.lock(where, project):
        data = load(where, project)
        item = data["deliveries"].get(delivery_id)
        if not item or item["scope"] != scope or item.get("attempt_id") != attempt_id:
            return False
        if item["state"] == "sent":
            return item.get("message_id") == message_id
        if item["state"] not in ("attempted", "delivery_unknown"):
            return False
        item.update(state="sent" if message_id > 0 and not error else "delivery_unknown",
                    message_id=message_id, error=error[:200])
        if item["state"] == "sent" and item["batch_id"]:
            sales_dialogue.delivered(where, project, scope["chat_id"], item["batch_id"], message_id)
        _save(where, project, data)
        return True

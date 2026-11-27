"""Synthetic acknowledgements; no live chats, messages or bank observations."""
import copy
import datetime as dt

import pytest

from market_search import sales_dialogue as dialogue, sales_followups as follow, sales_questions as questions, sales_store as store
from test_sales_followups import STAMP, answer, native, setup


@pytest.mark.parametrize("text,expected,kind,day", [
    ("зарегистрировано, ожидаем оплату 03.12.26", "payment", "payment", "2026-12-03"),
    ("0010зарегистрировано ожидаем\n03.12.26", "payment", "payment", "2026-12-03"),
    ("0010зарегистрировано ожидаем03.12.26", "payment", "payment", "2026-12-03"),
    ("не зарегистрировано, ожидаем 03.12.26", "payment", "registration", "2026-12-03"),
    ("зарегистрировано", "payment", "registration", "2026-11-23"),
    ("не зарегистрировано ещё", "payment", "registration", None),
    ("ожидаем оплату 03.12.2026", "payment", "payment", "2026-12-03"),
    ("ожидаем оплату 03.12.25", "payment", "payment", None),
    ("ожидаем оплату 31.11.26", "payment", "payment", None),
    ("ожидаем оплату 03.12.20266", "payment", "payment", None),
    ("ожидаем оплату 01.03.12.26", "payment", "payment", None),
    ("оплата по договору №03.12.26", "payment", "payment", None),
    ("оплата по ID A03.12.26", "payment", "payment", None),
    ("ожидаем оплату 03.12.26 млн ₽", "payment", "payment", None),
    ("если зарегистрируют, ожидаем оплату 03.12.26", "payment", "payment", None),
    ("зарегистрировано, ожидаем оплату 03.12.26 или 04.12.26", "payment", "payment", None),
])
def test_short_year_and_registration_are_not_a_payment_fact(text, expected, kind, day):
    result = follow.extract(text, STAMP, expected)
    assert result["event_kind"] == kind and result["event_date"] == day
    assert result["quote"] == text
    if kind == "payment":
        assert "event_mode" not in result and "claim" not in result
    if kind == "payment" and text.startswith(("зарегистрировано", "0010")):
        assert result["registration_claim"] == "unverified"
    if day == "2026-12-03":
        assert result["due_at"] == "2026-12-04T09:00:00+03:00"


def test_compact_numbered_point_does_not_put_its_date_into_previous_answer(tmp_path):
    scope, _, _, batch = setup(tmp_path)
    text = ("Добрый вечер\n1. 0009 мм зарегистрировано, ожидаем оплату 03.12.26\n"
            "2. Мм009-1 не зарегистрировано ещё\n3.0010зарегистрировано ожидаем\n03.12.26")
    parts = follow._parts(text, 3)
    assert set(parts) == {1, 2, 3}
    assert "03.12.26" not in parts[2] and parts[3].startswith("0010зарегистрировано")
    assert answer(tmp_path, scope, batch, text=text)["events"] == 3
    events = list(follow.load(tmp_path, "Продажи")["events"].values())
    assert [event["event_kind"] for event in events] == ["payment", "registration", "payment"]
    assert [event["event_date"] for event in events] == ["2026-12-03", None, "2026-12-03"]
    assert events[1]["state"] == "waiting_deadline"
    assert all("claim" not in event for event in events)
    # A calendar date or decimal by itself cannot become a compact point.
    assert follow._parts("1. ожидаем оплату\n03.12.26", 3) == {1: "ожидаем оплату\n03.12.26"}
    assert follow._parts("1. ожидаем оплату\n3.0010 млн ₽", 3) == {1: "ожидаем оплату\n3.0010 млн ₽"}
    for calendar_text in ("03.12зарегистрировано", "3.12зарегистрировано"):
        assert follow._parts(calendar_text, 3) == {}


def saved_reply(where, scope, batch, *, message=101, text="Спасибо за вопрос", author=4242, stamp=STAMP):
    return dialogue.reply(where, "Продажи", chat_id=scope["chat_id"], message_id=message,
        reply_to_id=100, quoted=batch["text"], text=text, author="Менеджер",
        author_id=author, telegram_date=stamp)


def acknowledge(where, scope, **changes):
    values = dict(message_id=101, reply_to_id=100, text="Спасибо за вопрос", author_id=4242,
                  telegram_date=STAMP)
    values.update(changes)
    return follow.acknowledge(where, "Продажи", scope, **values)


def test_acknowledgement_requires_exact_durable_reply_and_is_once_per_message(tmp_path):
    scope, _, _, batch = setup(tmp_path)
    assert not acknowledge(tmp_path, scope)
    assert saved_reply(tmp_path, scope, batch)
    for changed in (dict(text="Другой ответ"), dict(author_id=999), dict(telegram_date=STAMP + 1),
                    dict(reply_to_id=200), dict(message_id=102)):
        assert not acknowledge(tmp_path, scope, **changed)
    assert not acknowledge(tmp_path, dict(scope, sales_project="Other"))
    assert not acknowledge(tmp_path, dict(scope, chat_id=scope["chat_id"] - 1))
    assert acknowledge(tmp_path, scope)
    data = follow.load(tmp_path, "Продажи")
    assert not data["events"] and not data["ingestions"]
    assert len(data["deliveries"]) == 1
    item = next(iter(data["deliveries"].values()))
    assert item["text"] == "Спасибо, ответ принят."
    assert item["question"] is None and not item["batch_id"] and item["event_key"] is None
    assert not acknowledge(tmp_path, scope)
    claim, = follow.poll(tmp_path, "Продажи", scope, dt.datetime.fromtimestamp(STAMP, follow.MOSCOW))
    sent = follow.begin(tmp_path, "Продажи", scope, claim["id"], claim["claim_id"],
                        dt.datetime.fromtimestamp(STAMP, follow.MOSCOW))
    assert sent["authorized"]
    assert not acknowledge(tmp_path, scope)
    assert follow.receipt(tmp_path, "Продажи", scope, claim["id"], sent["attempt_id"], 200)
    assert not acknowledge(tmp_path, scope) and len(follow.load(tmp_path, "Продажи")["deliveries"]) == 1


def test_acknowledgement_does_not_reopen_after_scope_change_or_legacy_reply(tmp_path):
    scope, _, _, batch = setup(tmp_path)
    saved_reply(tmp_path, scope, batch)
    assert acknowledge(tmp_path, scope)
    current = dict(scope, grant_sha256="new-grant")
    assert follow.poll(tmp_path, "Продажи", current) == []
    assert not acknowledge(tmp_path, current)
    assert not follow.begin(tmp_path, "Продажи", current, "answer:any", "missing")["authorized"]
    assert not follow.load(tmp_path, "Продажи")["events"]
    legacy = dialogue.load(tmp_path, "Продажи")
    next(iter(legacy["batches"].values()))["legacy"] = True
    dialogue._save(tmp_path, "Продажи", legacy)
    assert saved_reply(tmp_path, scope, batch, message=102)
    assert not acknowledge(tmp_path, scope, message_id=102)


def dropped_batch(where, scope, *, apartment=107, tower="Башня Тест", mid=300):
    item = {"key": f"dropped:{tower}:{apartment}:2026-11-25", "kind": "dropped",
            "text": f"Квартира №{apartment}: договор подписан или бронь снята?"}
    bid = dialogue.prepare(where, "Продажи", scope["chat_id"], [item], "2026-11-25")
    dialogue.delivered(where, "Продажи", scope["chat_id"], bid, mid)
    return dialogue.load(where, "Продажи")["batches"][bid]


def test_plain_dropped_answer_gets_truthful_invitation_without_attaching(tmp_path):
    scope, _, _, _ = setup(tmp_path)
    batch = dropped_batch(tmp_path, scope)
    text = "Добрый вечер!\nкв 107 расторгли бронь, т.к. выбрали готовое жильё"
    assert follow.looks_like_answer(text)
    before = copy.deepcopy(dialogue.load(tmp_path, "Продажи"))
    assert answer(tmp_path, scope, batch, text=text, mid=400, candidate=True)["candidate"]
    data = follow.load(tmp_path, "Продажи")
    assert not data["events"] and not data["ingestions"]
    notice, = data["deliveries"].values()
    assert "Спасибо за пояснение" in notice["text"]
    assert "не связано" in notice["text"] and "Reply" in notice["text"] and "принят" not in notice["text"]
    assert dialogue.load(tmp_path, "Продажи") == before
    assert not answer(tmp_path, scope, batch, text=text.replace("107", "108"), mid=401, candidate=True)["candidate"]
    dropped_batch(tmp_path, scope, tower="Другая башня", mid=301)
    assert not answer(tmp_path, scope, batch, text=text, mid=402, candidate=True)["candidate"]


def test_contract_identity_explanation_never_selects_one_payment_target(tmp_path):
    scope, _, _, _ = setup(tmp_path)
    item = {"key": "identity:legal-rows", "kind": "contract_identity",
            "text": "Уточните связь двух записей одного помещения.",
            "subject": {"contract": "synthetic-wrong-target", "signed": "2026-11-16"},
            "baseline": {"escrow_paid": 123}, "expected_event": "payment"}
    bid = dialogue.prepare(tmp_path, "Продажи", scope["chat_id"], [item], "2026-11-23")
    dialogue.delivered(tmp_path, "Продажи", scope["chat_id"], bid, 500)
    batch = dialogue.load(tmp_path, "Продажи")["batches"][bid]
    old = follow.load(tmp_path, "Продажи")
    old["events"][follow._event_id(scope, item["key"])] = {
        "scope": scope, "state": "scheduled", "event_kind": "payment", "revision": 1,
        "target": {"contract": "wrong old row"}, "baseline_paid": 123,
        "baseline_source_sha256": "wrong-source", "claim": "unverified", "history": []}
    follow._save(tmp_path, "Продажи", old)
    assert follow.ingest(tmp_path, "Продажи", scope, message_id=501, reply_to_id=500,
        quoted=batch["text"], text="Оплату ожидаем 03.12.26", author_id=4242, author="Менеджер",
        telegram_date=STAMP)["events"] == 1
    event, = follow.load(tmp_path, "Продажи")["events"].values()
    assert event["state"] == "answered" and event["event_kind"] == "explanation"
    assert event["target"] is None and event["due_at"] is None and event["event_date"] is None
    assert event["baseline_paid"] is None and "claim" not in event
    assert event["baseline_source_sha256"] == "" and event["baseline_evidence"]["target"] is None
    assert not any(key in event["question"] for key in ("subject", "baseline", "expected_event"))
    assert not follow.load(tmp_path, "Продажи")["deliveries"]


def native_message(scope, batch, text="1. ожидаем оплату 03.12.26"):
    return {"chat": {"id": scope["chat_id"], "type": "supergroup"}, "from": {"id": 4242},
            "message_id": 101, "date": STAMP, "text": text,
            "reply_to_message": {"message_id": 100, "text": batch["text"],
                                 "from": {"id": 123, "is_bot": True}}}


def test_native_ack_is_outbox_only_and_replayed_webhook_does_not_repeat(native, monkeypatch):
    main, core, where, scope, sent = native
    batch = next(iter(dialogue.load(where, "Продажи")["batches"].values()))
    msg = native_message(scope, batch)
    core._telegram_group_message(msg["chat"], msg)
    assert not sent
    assert len(next(iter(dialogue.load(where, "Продажи")["batches"].values()))["replies"]) == 1
    monkeypatch.setattr(follow, "_now", lambda value=None: dt.datetime.fromtimestamp(STAMP, follow.MOSCOW))
    assert main._deliver_sales_followups()["items"]
    assert len(sent) == 1 and sent[0][1] == "Спасибо, ответ принят."
    core._telegram_group_message(msg["chat"], msg)
    main._deliver_sales_followups()
    assert len(sent) == 1


def test_native_failed_raw_save_never_queues_thanks(native, monkeypatch):
    _, core, where, scope, sent = native
    batch = next(iter(dialogue.load(where, "Продажи")["batches"].values()))
    monkeypatch.setattr(dialogue, "reply", lambda *a, **kw: (_ for _ in ()).throw(OSError("synthetic disk full")))
    msg = native_message(scope, batch)
    core._telegram_group_message(msg["chat"], msg)
    assert not any(k.startswith("answer:") for k in follow.load(where, "Продажи")["deliveries"])
    assert not next(iter(dialogue.load(where, "Продажи")["batches"].values()))["replies"]
    assert not sent


def legacy_parking_batch(where, scope):
    rows = [dict(contract=f"ДДУ №{number}М{suffix}/ГР", signed="2026-11-16", product="Машиноместо",
                 unit="", amount=1000, area=1, escrow_paid=0, escrow_observed=True)
            for number, suffix in (("0009", ""), ("0009", "-1"), ("0010", ""))]
    store.save(where, "Продажи", {"contracting": {"rows": rows}}, "synthetic-parking.xlsx")
    # This reproduces a previously delivered message, before uncertainty
    # clarifications were introduced. Its three original legal rows stay separate.
    items = [{"key": questions.money_key(row), "kind": "money", "expected_event": "payment",
              "subject": {k:row[k] for k in ("contract", "signed", "product", "unit")},
              "baseline": {"escrow_paid": 0}, "text": f"{row['contract']}: когда ждать оплату?"}
             for row in rows]
    bid = dialogue.prepare(where, "Продажи", scope["chat_id"], items, "2026-11-23")
    dialogue.delivered(where, "Продажи", scope["chat_id"], bid, 600)
    return dialogue.load(where, "Продажи")["batches"][bid]


PARKING_REPLY = ("Добрый вечер\n1. 0009 мм зарегистрировано, ожидаем оплату 03.12.26\n"
                 "2. Мм009-1 не зарегистрировано ещё\n3.0010зарегистрировано ожидаем\n03.12.26")


def test_short_parking_references_only_invite_reply_and_preserve_three_legal_rows(tmp_path):
    scope, _, _, _ = setup(tmp_path)
    batch = legacy_parking_batch(tmp_path, scope)
    before = copy.deepcopy(store.load(tmp_path, "Продажи"))
    assert answer(tmp_path, scope, batch, text=PARKING_REPLY, mid=700, candidate=True)["candidate"]
    data = follow.load(tmp_path, "Продажи")
    assert not data["events"] and not data["ingestions"]
    notice, = data["deliveries"].values()
    assert "Спасибо за пояснение" in notice["text"] and "не связано" in notice["text"]
    assert "Reply" in notice["text"] and "принят" not in notice["text"]
    assert len(batch["questions"]) == 3 and len(store.load(tmp_path, "Продажи")["sources"]["contracting"]["data"]["rows"]) == 3
    assert store.load(tmp_path, "Продажи") == before
    assert not dialogue.load(tmp_path, "Продажи")["batches"][notice["id"].removeprefix("candidate:")]["replies"]
    assert answer(tmp_path, scope, batch, text=PARKING_REPLY, mid=701, candidate=True)["candidate"]
    assert len(follow.load(tmp_path, "Продажи")["deliveries"]) == 1


def test_short_parking_suffix_is_exact_and_namespace_conflict_remains_ambiguous(tmp_path):
    scope, _, _, _ = setup(tmp_path)
    batch = legacy_parking_batch(tmp_path, scope)
    one, version, ten = batch["questions"]
    assert follow._explicit_question("ММ009-1 не зарегистрировано", version, batch["questions"])
    assert follow._explicit_question("0009-1 мм зарегистрировано", version, batch["questions"])
    assert not follow._explicit_question("ММ009-1 не зарегистрировано", one, batch["questions"])
    assert not follow._explicit_question("ММ009 зарегистрировано", version, batch["questions"])
    assert follow._explicit_question("0010зарегистрировано", ten, batch["questions"])
    for invalid in ("ММ009-2", "ММ009-1-2", "ММ009 -1", "0009 мм -1", "0009 мм.1",
                    "ММ009–1", "0009 мм –1", "0009–1 мм", "ММ009—1", "0009 мм −1",
                    "A0009 мм", "ММ03.12.26", "03.12.26"):
        assert not follow._explicit_question(invalid, one, batch["questions"])
    other = dict(one, subject=dict(one["subject"], contract="ДДУ №0009М/ТЕСТ"))
    assert not follow._explicit_question("ММ009 зарегистрировано", one, [one, other])
    assert not answer(tmp_path, scope, batch,
        text=PARKING_REPLY.replace("0009 мм", "0009-1 мм"), mid=702, candidate=True)["candidate"]


def test_native_plain_parking_answer_gets_one_guarded_truthful_hint(native, monkeypatch):
    main, core, where, scope, sent = native
    legacy_parking_batch(where, scope)
    before = copy.deepcopy(store.load(where, "Продажи"))
    msg = {"chat": {"id": scope["chat_id"], "type": "supergroup"}, "from": {"id": 4242},
           "message_id": 700, "date": STAMP, "text": PARKING_REPLY}
    core._telegram_group_message(msg["chat"], msg)
    assert not sent and not follow.load(where, "Продажи")["events"]
    monkeypatch.setattr(follow, "_now", lambda value=None: dt.datetime.fromtimestamp(STAMP, follow.MOSCOW))
    main._deliver_sales_followups()
    assert len(sent) == 1 and "Спасибо за пояснение" in sent[0][1]
    assert "не связано" in sent[0][1] and "принят" not in sent[0][1]
    core._telegram_group_message(msg["chat"], dict(msg, message_id=701))
    main._deliver_sales_followups()
    assert len(sent) == 1 and store.load(where, "Продажи") == before


def test_native_ack_queue_failure_does_not_claim_that_saved_raw_reply_was_lost(native, monkeypatch):
    _, core, where, scope, sent = native
    batch = next(iter(dialogue.load(where, "Продажи")["batches"].values()))
    monkeypatch.setattr(follow, "acknowledge", lambda *a, **kw: (_ for _ in ()).throw(OSError("synthetic outbox full")))
    result = core.internal_monitor_sales_chat(core.SalesChatRequest(
        chat_id=scope["chat_id"], action="reply", message_id=101, reply_to_id=100,
        reply_text=batch["text"], reply_from_id=123, reply_is_bot=True, text="1. ожидаем оплату 03.12.26",
        author_id=4242, author="Менеджер", telegram_date=STAMP,
        sign=core._web_login_sign("monitor-sales", scope["chat_id"])))
    assert result["reply_saved"] is True and "synthetic outbox full" in result["followup_error"]
    assert len(next(iter(dialogue.load(where, "Продажи")["batches"].values()))["replies"]) == 1
    assert not any(key.startswith("answer:") for key in follow.load(where, "Продажи")["deliveries"])
    assert not sent

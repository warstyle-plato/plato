"""Ответы Telegram на вопросы продаж: синтетика, без сетевых сообщений."""
import datetime
import html
import time

import pytest

from market_search import sales_dialogue, sales_questions, sales_store
from test_the_bot_reads_the_sales_chat import _Bot, core
from test_platon_asks_the_sales_chat import ROWS, _report, LOT


def _setup(monkeypatch, tmp_path, count=1):
    import developaid_management_report as report
    import developaid_monitor as monitor

    bot = _Bot(monkeypatch, tmp_path)
    monkeypatch.setattr(core, "_telegram_token", lambda: "123:test-token")
    def send(chat_id, text, **kw):
        bot.said.append((int(chat_id), text))
        return {"message_id": 100}
    monkeypatch.setattr(core, "_telegram_send_message", send)
    today = datetime.date.today()
    rows = [dict(row, signed=(today - datetime.timedelta(days=21)).isoformat())
            for row in ROWS[:count]]
    where = sales_store.default_dir()
    sales_store.save(where, "Тест", {"contracting": {"rows": rows}}, "synthetic.xlsx")
    monitor._project_dir("Тест")
    report.link_sales("Тест", "Тест", "тест")
    bot.authorize("Тест")
    bot.said.clear()
    return bot, where, rows


def _question(bot):
    bot.send(_report(datetime.date.today().strftime("%d.%m.%Y"), []), date=int(time.time()))
    return html.unescape(next(t for c, t in bot.said if c == bot.chat["id"]))


def _reply(bot, quoted, text="По кв.41 ожидаем оплату до 09.11.2026.", **changes):
    msg = {"chat": bot.chat, "from": {"id": 4242, "first_name": "Менеджер"},
           "message_id": 101, "date": int(time.time()), "text": text,
           "reply_to_message": {"message_id": 100, "text": quoted,
                                "from": {"id": 123, "is_bot": True}}}
    msg.update(changes)
    core._telegram_handle_message(msg)


def test_reply_is_durable_linked_and_not_a_new_report_or_payment(monkeypatch, tmp_path):
    bot, where, rows = _setup(monkeypatch, tmp_path, 2)
    quoted = _question(bot)
    batch = next(iter(sales_dialogue.load(where, "Тест")["batches"].values()))
    assert batch["message_id"] == 100
    assert len(batch["questions"]) == 2
    before = sales_store.load(where, "Тест")["sources"]
    _reply(bot, quoted)
    _reply(bot, quoted)  # Повтор доставки Telegram.
    data = sales_dialogue.load(where, "Тест")  # Читает диск, а не память воркера.
    batch = next(iter(data["batches"].values()))
    assert len(batch["replies"]) == 1
    reply = batch["replies"][0]
    assert reply["author_id"] == 4242 and reply["author"] == "Менеджер"
    assert reply["telegram_date"] > 0 and "09.11.2026" in reply["text"]
    assert all("closed" not in q and "answered" not in q for q in batch["questions"])
    assert sales_store.load(where, "Тест")["sources"] == before
    assert "ответ Платону сохранён" in bot.outcome
    # Замена источника и отсутствие старого asked не стирают память журнала.
    sales_questions._asked_path(where, "Тест").unlink()
    sales_store.save(where, "Тест", {"contracting": {"rows": rows}}, "new.xlsx")
    bot.send(_report(datetime.date.today().strftime("%d.%m.%Y"), [LOT]), date=int(time.time()))
    assert len([t for c, t in bot.said if c == bot.chat["id"]]) == 1


def test_reply_to_an_old_question_is_kept_without_inventing_keys(monkeypatch, tmp_path):
    bot, where, _ = _setup(monkeypatch, tmp_path)
    original = sales_questions.GREETING + ". Договор на корп 1 кв.41: когда ждать оплату?"
    sales_questions.remember(where, "Тест", [{"key": "money:old:2026-10-01"}], "2026-11-01")
    _reply(bot, original)
    assert sales_dialogue.load(where, "Тест")["batches"] == {}
    batch = next(iter(sales_dialogue.load(where / "unattributed", str(bot.chat["id"]))["batches"].values()))
    assert batch["legacy"] and batch["text"] == original
    assert batch["questions"] == [] and len(batch["replies"]) == 1
    assert sales_questions.load_asked(where, "Тест") == {"money:old:2026-10-01": "2026-11-01"}
    assert bot.said == []
    assert "без привязки к проекту" in bot.outcome


@pytest.mark.parametrize("sender,quote", [({"id": 124, "is_bot": True}, None),
                                         ({"id": 123, "is_bot": False}, None),
                                         ({"id": 123, "is_bot": True}, "Постороннее сообщение")])
def test_other_bots_people_and_unrelated_messages_are_ignored(monkeypatch, tmp_path, sender, quote):
    bot, where, _ = _setup(monkeypatch, tmp_path)
    quoted = _question(bot)
    _reply(bot, quoted, reply_to_message={"message_id": 100, "text": quote or quoted,
                                         "from": sender})
    batch = next(iter(sales_dialogue.load(where, "Тест")["batches"].values()))
    assert batch["replies"] == []


def test_lost_delivery_ack_falls_back_to_exact_quoted_text(monkeypatch, tmp_path):
    bot, where, _ = _setup(monkeypatch, tmp_path)
    # Telegram отправил, но возвращённый ID/подтверждение не дошло.
    def send(chat_id, text, **kw):
        bot.said.append((int(chat_id), text))
        return None
    monkeypatch.setattr(core, "_telegram_send_message", send)
    quoted = _question(bot)
    _reply(bot, quoted)
    batches = sales_dialogue.load(where, "Тест")["batches"]
    assert len(batches) == 1
    assert next(iter(batches.values()))["message_id"] == 100
    assert len(next(iter(batches.values()))["replies"]) == 1


def test_remote_bot_passes_reply_and_delivery_metadata(monkeypatch, tmp_path):
    bot, where, _ = _setup(monkeypatch, tmp_path)
    calls = []
    def post(url, payload, timeout):
        calls.append(dict(payload))
        return core.internal_monitor_sales_chat(core.SalesChatRequest(**payload))
    monkeypatch.setattr(core, "_core_api_url", lambda path: "https://synthetic.invalid" + path)
    monkeypatch.setattr(core, "_core_post", post)
    quoted = _question(bot)
    _reply(bot, quoted)
    assert [p["action"] for p in calls] == ["report", "send", "delivered", "reply"]
    assert calls[2]["message_id"] == 100 and calls[2]["batch_id"]
    assert calls[3]["reply_to_id"] == 100 and calls[3]["author_id"] == 4242
    assert len(next(iter(sales_dialogue.load(where, "Тест")["batches"].values()))["replies"]) == 1


def test_core_rejects_wrong_signature_and_wrong_bot(monkeypatch, tmp_path):
    bot, where, _ = _setup(monkeypatch, tmp_path)
    quoted = _question(bot)
    args = dict(chat_id=bot.chat["id"], action="reply", message_id=101, reply_to_id=100,
                reply_text=quoted, reply_from_id=124, reply_is_bot=True, text="ответ")
    with pytest.raises(core.HTTPException) as exc:
        core.internal_monitor_sales_chat(core.SalesChatRequest(**args, sign="wrong"))
    assert exc.value.status_code == 403
    result = core.internal_monitor_sales_chat(core.SalesChatRequest(
        **args, sign=core._web_login_sign("monitor-sales", bot.chat["id"])))
    assert result["reply_saved"] is False
    assert next(iter(sales_dialogue.load(where, "Тест")["batches"].values()))["replies"] == []


def test_broken_journal_stops_questions_instead_of_repeating(monkeypatch, tmp_path):
    bot, where, _ = _setup(monkeypatch, tmp_path)
    place = sales_dialogue._path(where, "Тест")
    place.parent.mkdir(parents=True)
    place.write_text("{broken", encoding="utf-8")
    bot.send(_report(datetime.date.today().strftime("%d.%m.%Y"), []), date=int(time.time()))
    assert bot.said == []
    assert "вопросы Платона не собраны" in bot.outcome


def test_delivery_is_bound_to_chat_and_batch_and_reply_id(monkeypatch, tmp_path):
    bot, where, _ = _setup(monkeypatch, tmp_path)
    quoted = _question(bot)
    batch_id = next(iter(sales_dialogue.load(where, "Тест")["batches"]))
    assert not sales_dialogue.delivered(where, "Тест", -1234, batch_id, 200)
    assert not sales_dialogue.delivered(where, "Тест", bot.chat["id"], batch_id, 200)
    _reply(bot, quoted, reply_to_message={"message_id": 100, "text": quoted + "подмена",
                                         "from": {"id": 123, "is_bot": True}})
    assert next(iter(sales_dialogue.load(where, "Тест")["batches"].values()))["replies"] == []


def test_reply_scope_requires_original_project_and_survives_reauthorization(monkeypatch, tmp_path):
    import developaid_management_report as report
    import developaid_monitor as monitor

    bot, where, _ = _setup(monkeypatch, tmp_path)
    quoted = _question(bot)
    monitor._project_dir("Другой")
    sales_store.save(where, "Другие продажи", {"contracting": {"rows": []}}, "other.xlsx")
    report.link_sales("Другой", "Другие продажи", "тест")
    # Owner-authorized change of scope still cannot write the old project's journal.
    bot.authorize("Другой")
    _reply(bot, quoted)
    original = next(iter(sales_dialogue.load(where, "Тест")["batches"].values()))
    assert original["replies"] == []
    assert sales_dialogue.load(where, "Другие продажи")["batches"] == {}
    # Restore the same explicit owner scope: the original durable question is retained.
    bot.authorize("Тест")
    _reply(bot, quoted, message_id=102)
    assert len(next(iter(sales_dialogue.load(where, "Тест")["batches"].values()))["replies"]) == 1


def test_pending_questions_in_other_projects_do_not_choose_a_project(monkeypatch, tmp_path):
    bot, where, _ = _setup(monkeypatch, tmp_path)
    items = [{"key": "money:example:2026-10-01", "kind": "money", "text": "Когда ждать оплату?"}]
    for project in ("Один", "Два"):
        sales_dialogue.prepare(where, project, bot.chat["id"], items, "2026-11-05")
    quoted = html.unescape(sales_questions.message(items))
    _reply(bot, quoted)
    assert "без привязки к проекту" in bot.outcome
    for project in ("Один", "Два"):
        assert next(iter(sales_dialogue.load(where, project)["batches"].values()))["replies"] == []


def test_two_workers_do_not_ask_the_same_question_twice(monkeypatch, tmp_path):
    import multiprocessing

    bot, where, _ = _setup(monkeypatch, tmp_path)
    ctx = multiprocessing.get_context("fork")
    start, results = ctx.Event(), ctx.Queue()
    def worker(lots):
        start.wait(5)
        req = core.SalesChatRequest(
            chat_id=bot.chat["id"], sign=core._web_login_sign("monitor-sales", bot.chat["id"]),
            text=_report(datetime.date.today().strftime("%d.%m.%Y"), lots),
            taken_at=datetime.date.today().isoformat())
        results.put(bool(core.internal_monitor_sales_chat(req).get("ask")))
    workers = [ctx.Process(target=worker, args=(lots,)) for lots in ([], [LOT])]
    try:
        for p in workers:
            p.start()
        start.set()
        assert sum(results.get(timeout=10) for _ in workers) == 1
        for p in workers:
            p.join(5)
            assert p.exitcode == 0
    finally:
        for p in workers:
            if p.is_alive():
                p.terminate()
                p.join(5)
    assert len(sales_dialogue.load(where, "Тест")["batches"]) == 1

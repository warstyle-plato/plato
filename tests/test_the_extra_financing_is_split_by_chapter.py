"""«Нужно дофинансировать» раскладывается по главам и говорит, чего в нём нет.

Владелец (02.11.2026) о сумме дофинансирования: «А почему только? Это без
учёта 3 главы?» Итог стоял один, без разбивки, и не говорил, что участок
(глава 1) и проценты по кредиту в него не входят. Теперь водопад Монитора сам
раскладывает непокрытую потребность по главам (сумма и первый месяц
нехватки), а монитор и сводка читают эту разбивку, не пересчитывая.

Все числа — синтетика.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import developaid_monitor_dashboard as dashboard  # noqa: E402
import developaid_management_report as report  # noqa: E402

M = 1e6
CUT = datetime.date(2026, 10, 20)


def _articles() -> dict:
    # Глава 2: две статьи, нехватка с декабря (у одной) и с января (у другой).
    # Глава 3: одна статья, нехватка с февраля. Резерв 25 гасит часть декабря,
    # поэтому первый месяц НЕПОКРЫТОЙ потребности у главы 2 — не декабрь.
    return {
        "2.1": {"chapter": "2", "rss_limit": 100.0, "paid_at_baseline": 60.0,
                "monthly_need": {"2026-11-01": 30.0, "2026-12-01": 30.0}},
        "2.2": {"chapter": "2", "rss_limit": 50.0, "paid_at_baseline": 0.0,
                "monthly_need": {"2027-01-01": 80.0}},
        "3.1": {"chapter": "3", "rss_limit": 20.0, "paid_at_baseline": 0.0,
                "monthly_need": {"2026-11-01": 20.0, "2027-02-01": 15.0}},
    }


def test_the_chapters_add_up_to_the_total_with_their_own_month():
    got = dashboard._article_waterfall(_articles(), 25.0, CUT)
    split = {row["chapter"]: row for row in got["additional_financing_by_chapter"]}
    assert set(split) == {"2", "3"}
    assert sum(row["amount"] for row in split.values()) == pytest.approx(got["additional_financing"])
    # Глава 2: декабрь 20 нехватки гасит резерв, январь 30 — 5 из резерва, 25 непокрыто.
    assert split["2"]["amount"] == pytest.approx(25.0)
    assert split["2"]["from"] == "2027-01-01"
    assert split["3"]["amount"] == pytest.approx(15.0)
    assert split["3"]["from"] == "2027-02-01"
    assert split["2"]["label"] == "стройка" and split["3"]["label"] == "коммерция"
    note = got["additional_financing_note"]
    assert "участ" in note and "глава 1" in note and "проценты по кредиту" in note


def test_the_note_does_not_exclude_the_land_when_its_chapter_is_counted():
    articles = _articles()
    articles["1.1"] = {"chapter": "1", "rss_limit": 10.0, "paid_at_baseline": 0.0,
                       "monthly_need": {"2026-11-01": 12.0}}
    got = dashboard._article_waterfall(articles, 0.0, CUT)
    assert "участ" not in got["additional_financing_note"]
    assert "проценты по кредиту" in got["additional_financing_note"]
    assert sum(row["amount"] for row in got["additional_financing_by_chapter"]) \
        == pytest.approx(got["additional_financing"])


def test_the_monitor_funding_and_summary_read_the_waterfall_split(monkeypatch):
    from test_the_monitor_takes_the_finmodel_as_its_finance_book import (
        ESTIMATE, PAID, SECTIONS, _finmodel_funding)

    got = _finmodel_funding(monkeypatch, SECTIONS, ESTIMATE, PAID)
    split = got["additional_financing_by_chapter"]
    assert [row["chapter"] for row in split] == ["2", "3"]
    assert sum(row["amount"] for row in split) == pytest.approx(got["additional_financing"])
    assert {row["chapter"]: row["amount"] for row in split} == {
        ch: pytest.approx(got["need_by_chapter"][ch]["gap"]) for ch in ("2", "3")}
    lines = dashboard._summary({}, {**got, "additional_financing": 370 * M,
                                    "additional_financing_by_chapter": [
                                        {**row, "amount": row["amount"] * M} for row in split]},
                               {"known": False})
    hole = next(line for line in lines if line.startswith("Когда возникает дыра"))
    assert "по главе 2 (стройка) — 300,0 млн ₽" in hole
    assert "по главе 3 (коммерция) — 70,0 млн ₽" in hole
    assert "не входят покупка участка (глава 1 сметы) и проценты по кредиту" in hole


def _limit() -> dict:
    return {
        "known": True, "need_basis": "model", "bank_limit": 900 * M, "paid_actual": 600 * M,
        "paid_borrowed": 500 * M, "bank_remaining": 120 * M, "reserve": 0.0,
        "remaining_scope": {"chapters": "2–3", "limit": 700 * M, "paid": 580 * M,
                            "borrowed": 480 * M},
        "need_by_chapter": {"2": {"label": "стройка", "label_acc": "стройку", "need": 400 * M,
                                  "remaining": 100 * M, "gap": 300 * M, "gap_from": "2027-01-01"},
                            "3": {"label": "коммерция", "label_acc": "коммерцию", "need": 90 * M,
                                  "remaining": 20 * M, "gap": 70 * M, "gap_from": "2027-03-01"}},
        "additional_financing": 370 * M, "additional_financing_from": "2027-01-01",
        "additional_financing_by_chapter": [
            {"chapter": "2", "label": "стройка", "label_acc": "стройку",
             "amount": 300 * M, "from": "2027-01-01"},
            {"chapter": "3", "label": "коммерция", "label_acc": "коммерцию",
             "amount": 70 * M, "from": "2027-03-01"}],
        "additional_financing_note": dashboard._gap_scope_note([{"chapter": "2"}, {"chapter": "3"}]),
        "approved": 1_000 * M, "approved_remaining": 490 * M,
        "deficit_ladder": {"total": 370 * M}}


def test_the_report_says_the_chapters_and_what_is_left_out(monkeypatch):
    from test_management_report_funding import PROJECT, _project

    _project()
    monkeypatch.setattr(report, "_monitor_view",
                        lambda project, end: {"dashboard": {"funding": _limit()}})
    built = report.build(PROJECT, "week", "2026-10-18")
    text = {item["topic"]: item["text"] for item in built["findings"]}["Финансирование"]
    assert ("(на стройку по главе 2 — 300,0 млн ₽ с января 2027, на коммерцию по главе 3 — "
            "70,0 млн ₽ с марта 2027)") in text
    assert "не входят покупка участка (глава 1 сметы) и проценты по кредиту" in text
    tile = {item["label"]: item for item in report.tiles(built)}[
        "Потребность в допфинансировании банка"]
    assert "участок и проценты по кредиту сюда не входят" in tile["note"]
    page = report._funding_html(built)
    assert "не входят покупка участка (глава 1 сметы) и проценты по кредиту" in page
    assert "Не хватает на коммерцию" in page and "с марта 2027" in page
    words = report.render_text(built)
    assert "по главам: на стройку по главе 2 — 300,0 млн ₽ с января 2027" in words
    assert "не входят покупка участка (глава 1 сметы) и проценты по кредиту" in words


# Всё, что зовёт fundingStructure на странице Монитора.
PAGE_FUNCTIONS = ("money", "dt", "pct", "unspentTable", "gapByChapter", "limitReconciliation",
                  "fundingStructure")


def _function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    depth = 0
    for at in range(source.index("{", start), len(source)):
        depth += {"{": 1, "}": -1}.get(source[at], 0)
        if depth == 0:
            return source[start:at + 1]
    raise AssertionError(name)


def test_the_monitor_page_shows_the_chapters_and_the_note():
    """Настоящие функции страницы Монитора, а не копия логики."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    import developaid_monitor_page as page

    script = page.MONITOR_PAGE  # функции ищутся по имени, разбирать теги не нужно
    esc = re.search(r"const esc=.*?;\n", script).group(0)
    parts = [esc] + [_function(script, name) for name in
                     PAGE_FUNCTIONS]
    funding = {key: value for key, value in _limit().items() if key != "need_by_chapter"}
    funding["remaining_need"] = 490 * M
    code = "\n".join(parts) + (
        f"\nconst f={json.dumps(funding, ensure_ascii=False)};"
        "\nprocess.stdout.write(fundingStructure(f,true,1e9,6e8,490e6));")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(code)
    try:
        done = subprocess.run([node, fh.name], capture_output=True, text=True, timeout=60)
    finally:
        os.unlink(fh.name)
    assert done.returncode == 0, done.stderr
    html = done.stdout
    assert "глава 2 (стройка)" in html and "глава 3 (коммерция)" in html
    assert "первый месяц нехватки — 01.03.2027" in html
    assert "не входят покупка участка (глава 1 сметы) и проценты по кредиту" in html
    # Нет разбивки — нет и строки «из них»: подделка без глав не проходит.
    empty = subprocess.run([node, "-e", "\n".join(parts) + (
        f"\nconst f={json.dumps({**funding, 'additional_financing_by_chapter': []}, ensure_ascii=False)};"
        "\nprocess.stdout.write(fundingStructure(f,true,1e9,6e8,490e6));")],
        capture_output=True, text=True, timeout=60)
    assert empty.returncode == 0, empty.stderr
    assert "глава 2 (стройка)" not in empty.stdout


# --- Как сходится: лимит → оплачено → остаток → осталось достроить → не хватает.

def _surplus_articles() -> dict:
    # Глава 2 не хватает; у главы 3 лимита больше, чем осталось достроить.
    return {
        "2.1": {"chapter": "2", "rss_limit": 500.0, "paid_at_baseline": 400.0,
                "monthly_need": {"2026-11-01": 60.0, "2026-12-01": 90.0}},
        "3.1": {"chapter": "3", "rss_limit": 100.0, "paid_at_baseline": 40.0,
                "monthly_need": {"2026-11-01": 25.0}},
    }


def test_the_chain_adds_up_and_names_the_surplus_of_one_chapter():
    waterfall = dashboard._article_waterfall(_surplus_articles(), 0.0, CUT)
    rec = dashboard._limit_reconciliation(waterfall, 900.0, ["1", "2", "3"])
    assert rec["matches"]
    two, three = rec["chapters"]
    assert (two["limit"], two["paid"], two["remaining"], two["need"], two["gap"]) == \
        pytest.approx((500.0, 400.0, 100.0, 150.0, 50.0))
    assert (three["remaining"], three["need"], three["gap"], three["unused"]) == \
        pytest.approx((60.0, 25.0, 0.0, 35.0))
    total = rec["total"]
    # 175 − 160 = 15, но дофинансировать — 50: излишек главы 3 (35) не переносится.
    assert total["plain"] == pytest.approx(15.0)
    assert total["gap"] == pytest.approx(waterfall["additional_financing"]) == pytest.approx(50.0)
    assert total["plain"] + total["unused"] == pytest.approx(total["gap"])
    assert rec["outside_chapters"] == ["1"] and rec["outside_limit"] == pytest.approx(300.0)
    lines = dashboard.reconciliation_lines(rec, report._rub)
    assert lines[0] == ("Лимит банка по главам 1–3 — 900 ₽. Сверка дофинансирования считает "
                        "только главы 2–3 — 600 ₽. Остальные 300 ₽ приходятся на главы вне "
                        "этой сверки: глава 1 (участок). В дофинансирование они не входят.")
    assert "Глава 3 (коммерция): лимит 100 ₽, оплачено всего 40 ₽, остаток по смете 60 ₽; " \
           "осталось достроить 25 ₽; не хватает 0 ₽. Лимита останется 35 ₽" in lines[2]
    assert "излишек одной главы или статьи не покрывает нехватку другой" in lines[-1]
    assert "дофинансировать нужно 50 ₽, а не меньше" in lines[-1]


def test_the_chain_counts_the_reserve_and_the_overpaid_chapter():
    articles = _articles()
    articles["3.2"] = {"chapter": "3", "rss_limit": 10.0, "paid_at_baseline": 14.0,
                       "monthly_need": {"2026-12-01": 6.0}}
    waterfall = dashboard._article_waterfall(articles, 25.0, CUT)
    rec = dashboard._limit_reconciliation(waterfall, 0.0, [])
    assert rec["matches"]
    total = rec["total"]
    assert total["plain"] - total["reserve"] + total["unused"] == pytest.approx(total["gap"])
    assert total["gap"] == pytest.approx(waterfall["additional_financing"])
    three = rec["chapters"][1]
    assert three["overpaid"] == pytest.approx(4.0)
    assert three["remaining"] == pytest.approx(three["limit"] - three["paid"] + three["overpaid"])
    text = " ".join(dashboard.reconciliation_lines(rec, report._rub))
    assert "Оплачено больше сметы на 4 ₽" in text and "Резерв закрывает из этого" in text
    assert "Лимит банка по главам" not in text


def test_a_forged_gap_does_not_reconcile():
    waterfall = dashboard._article_waterfall(_surplus_articles(), 0.0, CUT)
    forged = {**waterfall, "articles": [{**row, "unfunded_take": row["unfunded_take"] + 5.0}
                                        for row in waterfall["articles"]]}
    assert not dashboard._limit_reconciliation(forged, 0.0, [])["matches"]


def test_the_monitor_reconciles_the_bank_limit_with_chapters_two_and_three(monkeypatch):
    from test_the_monitor_takes_the_finmodel_as_its_finance_book import (
        ESTIMATE, PAID, SECTIONS, _finmodel_funding)

    got = _finmodel_funding(monkeypatch, SECTIONS, ESTIMATE, PAID)
    rec = got["limit_reconciliation"]
    assert rec["matches"]
    assert rec["bank_limit"] == pytest.approx(got["bank_limit"])
    assert rec["total"]["limit"] == pytest.approx(got["remaining_scope"]["limit"])
    assert rec["total"]["paid"] == pytest.approx(got["remaining_scope"]["paid"])
    assert rec["total"]["remaining"] == pytest.approx(got["bank_remaining"])
    assert rec["total"]["need"] == pytest.approx(got["remaining_need"])
    assert rec["total"]["gap"] == pytest.approx(got["additional_financing"])
    assert rec["outside_chapters"] == ["1"]
    assert got["limit_reconciliation_lines"] == dashboard.reconciliation_lines(
        rec, dashboard._fmt_money)


def test_the_report_and_the_page_show_the_chain(monkeypatch):
    from test_management_report_funding import PROJECT, _project

    waterfall = dashboard._article_waterfall(_surplus_articles(), 0.0, CUT)
    rec = dashboard._limit_reconciliation(waterfall, 900.0, ["1", "2", "3"])
    limit = {**_limit(), "limit_reconciliation": rec,
             "limit_reconciliation_lines": dashboard.reconciliation_lines(rec, dashboard._fmt_money)}
    _project()
    monkeypatch.setattr(report, "_monitor_view",
                        lambda project, end: {"dashboard": {"funding": limit}})
    built = report.build(PROJECT, "week", "2026-10-18")
    for body in (report._funding_html(built), report.render_text(built)):
        assert "Как сходится дофинансирование" in body
        assert "не покрывает нехватку другой" in body
        assert "Лимит банка по главам 1–3" in body

    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    import developaid_monitor_page as page

    script = page.MONITOR_PAGE  # функции ищутся по имени, разбирать теги не нужно
    parts = [re.search(r"const esc=.*?;\n", script).group(0)] + [
        _function(script, name) for name in PAGE_FUNCTIONS]
    funding = {key: value for key, value in limit.items() if key != "need_by_chapter"}
    funding["remaining_need"] = 490 * M
    done = subprocess.run([node, "-e", "\n".join(parts) + (
        f"\nconst f={json.dumps(funding, ensure_ascii=False)};"
        "\nprocess.stdout.write(fundingStructure(f,true,1e9,6e8,490e6));")],
        capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert "Как сходится дофинансирование" in done.stdout
    assert "не покрывает нехватку другой" in done.stdout


# --- Плашки складываются: «лимит − выбрано» против «осталось по смете».

def _overpaid_rec():
    articles = _surplus_articles()
    articles["3.1"] = {**articles["3.1"], "paid_at_baseline": 120.0}  # перебор 20
    waterfall = dashboard._article_waterfall(articles, 0.0, CUT)
    return dashboard._limit_reconciliation(
        waterfall, 900.0, ["1", "2", "3"],
        smeta_by_chapter={"1": 300.0, "2": 500.0, "3": 100.0},
        paid_by_chapter={"1": {"total": 250.0, "borrowed": 200.0},
                         "2": {"total": 400.0, "borrowed": 300.0},
                         "3": {"total": 120.0, "borrowed": 90.0}},
        approved_by_chapter={"1": 300.0, "2": 520.0, "3": 110.0})


def test_limit_minus_drawn_meets_the_remaining_through_a_named_difference():
    rec = _overpaid_rec()
    tiles = rec["tiles"]
    assert tiles["matches"] and rec["matches"]
    assert tiles["can_draw"] == pytest.approx(900.0 - 590.0)
    # Остаток по смете — главы 2–3, глава с перебором стоит нулём.
    assert tiles["remaining"] == pytest.approx(100.0)
    assert tiles["difference"] == pytest.approx(210.0)
    # 210 = глава 1 (300 − 200) + свои деньги (100 + 30) − перебор главы 3 (20).
    assert tiles["not_in_remaining"] == [{"chapter": "1", "label": "участок", "amount": 100.0}]
    assert tiles["own_money"] == pytest.approx(130.0)
    assert tiles["overpaid"] == [{"chapter": "3", "label": "коммерция", "amount": 20.0}]
    lines = dashboard.reconciliation_lines(rec, report._rub)
    assert lines[0].startswith("Можно ещё выбрать у банка 310 ₽: это лимит 900 ₽ минус 590 ₽")
    assert lines[1] == (
        "Разница 210 ₽ складывается так: глава 1 (участок) — 100 ₽: её лимит минус "
        "выбранное по ней в остаток по смете не входит; собственные деньги, уже заплаченные "
        "по главам 2–3, — 130 ₽; по главе 3 (коммерция) оплачено больше сметы на 20 ₽ — в "
        "остатке такая глава стоит нулём, поэтому этот перебор разницу уменьшает.")
    by_chapter = {line.split(":")[0]: line for line in lines if line.startswith("Глава ")}
    assert by_chapter["Глава 1 (участок)"] == (
        "Глава 1 (участок): бюджет 300 ₽, лимит 300 ₽, оплачено всего 250 ₽, из них кредитом "
        "200 ₽, остаток по смете 50 ₽; в расчёт дофинансирования эта глава не входит.")
    assert "бюджет 110 ₽, лимит 100 ₽, оплачено всего 120 ₽, из них кредитом 90 ₽, остаток " \
           "по смете 0 ₽" in by_chapter["Глава 3 (коммерция)"]
    assert "Оплачено больше сметы на 20 ₽" in by_chapter["Глава 3 (коммерция)"]


def test_the_monitor_and_the_tiles_carry_the_bridge(monkeypatch):
    from test_the_monitor_takes_the_finmodel_as_its_finance_book import (
        ESTIMATE, PAID, SECTIONS, _finmodel_funding)
    from test_management_report_funding import PROJECT, _project

    got = _finmodel_funding(monkeypatch, SECTIONS, ESTIMATE, PAID)
    tiles = got["limit_reconciliation"]["tiles"]
    assert tiles["matches"]
    assert tiles["remaining"] == pytest.approx(got["bank_remaining"])
    assert tiles["borrowed"] == pytest.approx(got["paid_borrowed"])
    assert tiles["can_draw"] == pytest.approx(got["bank_limit"] - got["paid_borrowed"])

    _project()
    monkeypatch.setattr(report, "_monitor_view",
                        lambda project, end: {"dashboard": {"funding": {
                            **_limit(), "limit_reconciliation": _overpaid_rec()}}})
    built = report.build(PROJECT, "week", "2026-10-18")
    shown = {item["label"]: item for item in report.tiles(built)}
    can_draw = shown["Можно ещё выбрать у банка"]
    drawn = built["funding"]["draws"]["total"]
    assert can_draw["value"] == report._rub(_limit()["bank_limit"] - drawn)
    assert can_draw["note"].startswith("лимит минус выбранное кредитом")
    left = shown["Осталось по смете после всех оплат"]
    assert left["note"].startswith("смета минус всё оплаченное, кредитом и своими деньгами; "
                                   "по главе 3 оплачено больше сметы на 20 ₽")
    assert "Остаток лимита банка" not in shown

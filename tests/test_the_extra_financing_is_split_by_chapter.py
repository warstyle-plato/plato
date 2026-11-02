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

    script = max(re.findall(r"<script[^>]*>(.*?)</script>", page.MONITOR_PAGE, re.S), key=len)
    esc = re.search(r"const esc=.*?;\n", script).group(0)
    parts = [esc] + [_function(script, name) for name in
                     ("money", "dt", "pct", "unspentTable", "gapByChapter", "fundingStructure")]
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

"""Regression guard for the user-facing Project Monitor operating contract.

A project benchmark is fixed once. After that the recurring operating inputs
are only a fresh RSS 6.1.2 and a sales report. Raw PM and approved article
rebaselines are benchmark/schedule metadata; they are not weekly sources of
physical fact. Physical fact still comes only from RSS accepted-work acts.
"""

from pathlib import Path

import developaid_monitor as monitor
import developaid_monitor_page as page


def test_monitor_page_exposes_fixed_benchmark_then_rss_and_sales():
    html = page.MONITOR_PAGE
    assert "Benchmark проекта" in html
    assert "После benchmark регулярно нужны только новый РСС и отчёт продаж" in html
    assert 'id="gpr"' in html
    assert 'id="finance"' in html
    assert 'id="pm"' in html
    assert 'id="rss"' in html
    assert 'id="sales"' in html
    assert 'id="programmeFile"' not in html
    assert 'id="proposalFile"' not in html
    assert "Физический факт — только «Реестр выполненных работ»" in html


def test_monitor_build_does_not_replace_baseline_with_legacy_programmes():
    source = Path(monitor.__file__).read_text(encoding="utf-8")
    build = source.split("def build(", 1)[1].split("def gantt(", 1)[0]
    assert "apply_proposals" not in build
    assert "_stored_programme" not in build
    assert "_stored_proposals" not in build

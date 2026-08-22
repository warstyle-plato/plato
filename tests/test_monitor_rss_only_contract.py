"""Regression guard for the Project Monitor operating contract.

A project benchmark is fixed once. After that recurring inputs are a fresh RSS
6.1.2 and sales. RSS accepted-work acts are the operational progress proxy;
calendar variance is derived from actual КС % versus the approved linear plan,
not from the recent monetary act rate.
"""

from pathlib import Path

import developaid_monitor as monitor
import developaid_monitor_page as page


def test_monitor_page_exposes_fixed_benchmark_then_rss_and_sales():
    html = page.MONITOR_PAGE
    assert "Benchmark проекта" in html
    assert 'id="gpr"' in html
    assert 'id="finance"' in html
    assert 'id="pm"' in html
    assert 'id="rss"' in html
    assert 'id="sales"' in html
    assert 'id="programmeFile"' not in html
    assert 'id="proposalFile"' not in html
    assert "Состояние работ берётся из актов РСС" in html
    assert "Forecast строится из КС-процента" in html


def test_monitor_build_does_not_replace_baseline_with_legacy_programmes():
    source = Path(monitor.__file__).read_text(encoding="utf-8")
    build = source.split("def build(", 1)[1].split("def gantt(", 1)[0]
    assert "apply_proposals" not in build
    assert "_stored_programme" not in build
    assert "_stored_proposals" not in build

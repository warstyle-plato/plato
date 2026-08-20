"""Regression guard for the user-facing Project Monitor contract.

The browser page must ask for a baseline once and then for RSS 6.1.2 only.
Legacy endpoints may remain temporarily, but they must not be presented as
weekly inputs and the server build path must not call apply_proposals.
"""

from pathlib import Path

import developaid_monitor as monitor
import developaid_monitor_page as page


def test_monitor_page_exposes_only_baseline_and_weekly_rss_uploads():
    html = page.MONITOR_PAGE
    assert "Baseline проекта" in html
    assert "только РСС 6.1.2" in html
    assert 'id="baselineFile"' in html
    assert 'id="rssFile"' in html
    assert 'id="programmeFile"' not in html
    assert 'id="proposalFile"' not in html
    assert 'id="salesFile"' not in html
    assert 'id="gprFile"' not in html


def test_monitor_build_does_not_replace_baseline_with_proposals():
    source = Path(monitor.__file__).read_text(encoding="utf-8")
    build = source.split("def build(", 1)[1].split("def gantt(", 1)[0]
    assert "apply_proposals" not in build
    assert "_stored_programme" not in build
    assert "_stored_proposals" not in build
    assert "store_sales" not in build

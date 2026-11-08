"""The approved baseline remains immutable. Weekly GPR records describe work
progress; RSS accepted acts and payments remain separate monetary evidence.
"""

from pathlib import Path

import developaid_monitor as monitor
import developaid_monitor_page as page


def test_monitor_page_exposes_fixed_benchmark_then_rss_and_sales():
    html = page.MONITOR_PAGE
    assert "Утверждённый ГПР" in html
    assert 'id="gpr"' in html
    assert 'id="finance"' in html
    assert 'id="pm"' in html
    assert 'id="rss"' in html
    # Продажи живут в «Отчёте о продажах»: загрузка в мониторе убрана
    # (владелец, 20.10.2026), прежние данные читаются как раньше.
    assert 'id="sales"' not in html
    assert 'id="programmeFile"' not in html
    assert 'id="proposalFile"' not in html
    assert "Реестр выполненных работ" in html
    assert "Выполнение работ смотрите по ГПР" in html


def test_monitor_build_does_not_replace_baseline_with_legacy_programmes():
    source = Path(monitor.__file__).read_text(encoding="utf-8")
    build = source.split("def build(", 1)[1].split("def gantt(", 1)[0]
    assert "apply_proposals" not in build
    assert "_stored_programme" not in build
    assert "_stored_proposals" not in build

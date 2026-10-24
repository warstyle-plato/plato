"""Сводка называет, когда и какой сборкой она собрана.

Владелец (24.10.2026) прислал таблицу «Остаток лимита (лимит минус выбранное)
1,98» — подпись, которую убрал #872, хотя на проде уже стояла 0.27.61:
скриншот был со старой сводки, а различить старую и новую по самому документу
было нечем. Подвал страницы и PDF (оба — `render_html`) теперь говорит «Сформировано
… (МСК), сборка …».
"""
from __future__ import annotations

import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_management_report as report  # noqa: E402
from test_management_report_analytics import _full  # noqa: E402


def test_the_footer_names_the_time_and_the_build(monkeypatch):
    monkeypatch.setitem(sys.modules, "developaid_core", types.SimpleNamespace(VERSION="0.27.99"))
    built = _full()
    assert built["built"]["version"] == "0.27.99"
    page = report.render_html(built)
    footer = re.search(r"<p class='note built'>([^<]+)</p>", page)
    assert footer, "подвала со сборкой нет"
    assert re.fullmatch(r"Сформировано \d\d\.\d\d\.\d{4} в \d\d:\d\d \(МСК\), сборка 0\.27\.99\.",
                        footer.group(1)), footer.group(1)
    # Подвал — последняя строка документа, после всех разделов.
    assert page.rstrip().endswith(footer.group(0))


def test_without_a_known_build_the_time_still_shows(monkeypatch):
    monkeypatch.setitem(sys.modules, "developaid_core", types.SimpleNamespace(VERSION=""))
    monkeypatch.delitem(sys.modules, "main_legacy", raising=False)
    page = report.render_html(_full())
    assert re.search(r"Сформировано \d\d\.\d\d\.\d{4} в \d\d:\d\d \(МСК\)\.</p>", page)

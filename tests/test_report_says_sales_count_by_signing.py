"""Сводка говорит, что продажи считаются по дате подписания договора.

Владелец (24.10.2026, отчёт отдела продаж в чате): «Странно. Продажники считают
не так» — у сводки за октябрь 4 ДДУ на 178,0 млн ₽, у отдела продаж 6 на
291,5 млн ₽. Разница — два договора, подписанные 28 и 30 сентября и
зарегистрированные в октябре: отдел продаж считает по регистрации, сводка — по
подписанию, как план финмодели. Решение владельца: считать по подписанию и
говорить об этом рядом с числом.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_management_report as report  # noqa: E402
from test_management_report_analytics import _full  # noqa: E402


def test_the_sales_figures_name_their_date():
    built = _full()
    assert built["sales"]["state"] == "ok"
    found = {item["topic"]: item["text"] for item in built["findings"]}
    assert "(по дате подписания)" in found["Продажи"]
    built["sales"]["quarter"]["fm"] = {"amount": 500e6,
                                       "area": 1.0}
    tiles = {item["label"]: item for item in report.tiles(built)}
    assert "по дате подписания" in tiles["Продажи квартала к плану финмодели"]["note"]
    assert "по дате регистрации" in report.render_text(built)
    assert "по дате регистрации" in report.render_html(built)

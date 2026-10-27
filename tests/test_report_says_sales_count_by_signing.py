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
    # Плашка — число и одна строка (владелец, 27.10.2026: «Сложный язык,
    # непонятный»); про дату подписания — в «Главном» и в разделе «Продажи».
    assert tiles["Продажи квартала к плану финмодели"]["note"].startswith("продано на ")
    assert "по дате регистрации" in report.render_text(built)
    assert "по дате регистрации" in report.render_html(built)


def test_the_note_names_the_contracts_at_the_quarter_edge():
    """«Надо в отчёте это расхождение примечанием пометить» — с цифрами
    (владелец, 24.10.2026). Договоры, подписанные в последние две недели
    сентября, сводка в четвёртый квартал не берёт; отдел продаж берёт, если их
    зарегистрировали в октябре."""
    from test_management_report_model import M, _contract, _sales

    _sales([_contract("2026-09-10", "Квартира", 40.0, 30 * M),   # раньше двух недель
            _contract("2026-09-28", "Квартира", 50.0, 57.1 * M),
            _contract("2026-09-30", "Квартира", 50.0, 56.4 * M),
            _contract("2026-10-09", "Квартира", 60.0, 89.0 * M),
            _contract("2026-10-09", "Квартира", 60.0, 89.0 * M)])
    got = report.sales("ЖК Гродненская", "week", "2026-10-18")
    quarter = got["quarter"]
    assert quarter["fact"]["amount"] == 178 * M
    assert quarter["edge"] == {"contracts": 2, "amount": 113.5 * M,
                               "days": ["2026-09-28", "2026-09-30"]}
    note = report._signed_note(quarter)
    assert ("Сейчас это 2 договора на 113,5 млн ₽: они подписаны 28.09 и 30.09, в конце "
            "прошлого квартала, и сводка относит их туда. Если их зарегистрировали уже в этом "
            "квартале, у отдела продаж квартал — 291,5 млн ₽, а в сводке — 178,0 млн ₽.") in note
    built = _full()
    built["sales"]["quarter"] = dict(quarter, fm={"amount": 1_680 * M, "area": 1.0})
    tiles = {item["label"]: item for item in report.tiles(built)}
    # Плашка — без истории про регистрацию: число и одна строка (владелец,
    # 27.10.2026: «Сложный язык, непонятный»); пример с цифрами — в разделе.
    note = tiles["Продажи квартала к плану финмодели"]["note"]
    assert note.startswith("продано на 178,0 млн ₽ из 1,68 млрд ₽, а квартал прошёл на "), note
    assert "регистрац" not in note and ";" not in note
    assert "у отдела продаж квартал — 291,5 млн ₽, а в сводке — 178,0 млн ₽" in \
        report.render_text(built)
    assert "у отдела продаж квартал — 291,5 млн ₽, а в сводке — 178,0 млн ₽" in \
        report.render_html(built)


def test_without_edge_contracts_the_note_stays_general():
    quarter = {"key": "2026 Q4", "fact": {"amount": 1.0}, "edge": None}
    assert report._signed_note(quarter) == report.SIGNED_NOTE


def test_the_note_opens_with_the_reason():
    """«Расхождение по продажам из-за разных дат учёта» (владелец, 24.10.2026)."""
    assert report.SIGNED_NOTE.startswith("Расхождение с отделом продаж — из-за разных дат учёта.")
    built = _full()
    assert "из-за разных дат учёта" in report.render_text(built)
    assert "из-за разных дат учёта" in report.render_html(built)

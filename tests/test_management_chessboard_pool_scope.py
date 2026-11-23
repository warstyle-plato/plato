"""Наличие шахматки и сверка с отдельным планом — разные основания остатка."""
from __future__ import annotations

from html.parser import HTMLParser
import re

import developaid_management_report as report
from market_search import chessboard


def stock():
    snapshot = {"buildings": {"1": {"as_of": "2026-11-15", "lots": [
        {"key": f"1:apartment:{unit}", "building": "1", "unit": str(unit),
         "product": "apartment", "area": area, "status": status,
         "price_consistent": True, "price_per_sqm": 100_000, "amount": area * 100_000}
        for unit, area, status in [(1, 40, "available"), (2, 60, "not_listed")]
    ]}}}
    return chessboard.overlay(snapshot, None, "2026-11-20")


def test_valid_chessboard_inventory_stays_visible_while_missing_plan_source_is_explicit():
    board = stock()
    body = report._sales_depth_html({"state": "ok", "chessboard": board, "pool": {}}, "month")
    assert chessboard.render(board) in body
    assert "известный непроданный остаток — 2 квартир, 100,0 м²" in body
    assert "не выведены на витрину" in body
    assert ("Сверка остатка с квартирографией и планом не выполнена: в отчёте о продажах "
            "нет квартирографии или плана финмодели по объёмам.") in body
    assert "Остаток нераспроданного не посчитан" not in body


def test_positive_pool_heading_names_its_source_and_preserves_the_inventory_row():
    body = report._sales_depth_html({"state": "ok", "chessboard": stock(), "pool": {
        "products": [{"product": "Квартира", "sold_units": 1, "pool_units": 3,
                      "sold_area": 40, "pool_area": 140}]}}, "month")
    assert "<h3>Остаток по квартирографии или плану финмодели</h3>" in body
    assert "<h3>Остаток нераспроданного</h3>" not in body
    assert "Сверка остатка с квартирографией и планом не выполнена" not in body
    values = re.findall(r"<td[^>]*>(.*?)</td>", body)
    assert values == ["Квартира", "1", "3", "40 м²", "140 м²", "100 м²"]


def test_shared_overlay_separates_inventory_value_and_horizon_explanations():
    class Paragraphs(HTMLParser):
        def __init__(self):
            super().__init__()
            self.items = []
            self.inside = False

        def handle_starttag(self, tag, attrs):
            if tag == "p":
                self.items.append("")
                self.inside = True

        def handle_endtag(self, tag):
            if tag == "p":
                self.inside = False

        def handle_data(self, data):
            if self.inside:
                self.items[-1] += data

    paragraphs = Paragraphs()
    paragraphs.feed(chessboard.render(stock()))
    assert len(paragraphs.items) == 3
    assert "известный непроданный остаток — 2 квартир, 100,0 м²" in paragraphs.items[0]
    assert "не выведены на витрину" in paragraphs.items[0]
    assert "Стоимость этой части остатка" in paragraphs.items[1]
    assert "Цена за м² и полная стоимость согласованы для 2 из 2 квартир" in paragraphs.items[1]
    assert "Контрактация не загружена" in paragraphs.items[2]
    assert "Сроки выхода невыведенных квартир неизвестны" in paragraphs.items[2]

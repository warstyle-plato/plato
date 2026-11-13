"""Переданные акты видны отдельными строками, не только внутри чужой истории."""
from html.parser import HTMLParser
from types import SimpleNamespace

from starlette.requests import Request

import normatives_registry as registry


class CardTitles(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.titles = []

    def handle_starttag(self, tag, attrs):
        if tag == "h2":
            self.in_title = True

    def handle_data(self, data):
        if self.in_title:
            self.titles.append(data)

    def handle_endtag(self, tag):
        if tag == "h2":
            self.in_title = False


def test_each_uploaded_act_has_its_own_public_card(monkeypatch):
    monkeypatch.setattr(registry, "_load_state", lambda: {})
    request = Request({"type": "http", "query_string": b"", "headers": []})
    page = registry._page(request, SimpleNamespace(_is_admin_request=lambda *args: False))
    parser = CardTitles()
    parser.feed(page)
    items = registry._merged_registry()
    for number in ("1420-ПП", "1310-ПП", "1860-ПП"):
        assert sum(title.startswith(number + " —") for title in parser.titles) == 1
        card = next(x for x in items if x["short_name"].startswith(number + " —"))
        assert card["level"] == "mo"
        assert not registry.in_history(card)
        assert card["source_url"] in page
        assert not registry.verdict_problems(card)


def test_adding_a_source_does_not_claim_a_validated_current_calculation():
    rows = {x["id"]: x for x in registry._load_registry()}
    for key in ("mo-1860-investment-projects", "mo-1310-vri-ksu", "mo-1745-vri-kd"):
        card = rows[key]
        assert card["status"] == "not_confirmed"
        assert card["unconfirmed_reason"] and card["to_confirm"]
    investment = rows["mo-1860-investment-projects"]
    assert "294-ПП" in investment["latest_amendment"]
    assert "932-ПП" in investment["latest_amendment"]
    assert "консолидированным" in investment["latest_amendment"]
    assert rows["mo-1310-vri-ksu"]["effective_from"] == "2026-10-16"

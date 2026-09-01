"""Росэлторг сначала измеряется на ядре, затем разбирается."""

from __future__ import annotations

from pathlib import Path

from auction_search.adapters import roseltorg_probe


ROOT = Path(__file__).resolve().parent.parent


def test_the_probe_asks_the_exact_moscow_territory_page(monkeypatch) -> None:
    asked: list[tuple[str, float]] = []

    def fake(url: str, seconds: float = 45.0):
        asked.append((url, seconds))
        return {"ok": True, "data_calls": []}

    monkeypatch.setattr(roseltorg_probe, "probe_browser", fake)
    got = roseltorg_probe.probe(seconds=17)

    assert asked == [(roseltorg_probe.CATALOGUE_URL, 17.0)]
    assert roseltorg_probe.CATALOGUE_URL == (
        "https://www.roseltorg.ru/imuschestvo/prochee/razvitie-territorii"
        "?sale=5&okato[]=45000000000&status[]=5&status[]=0&status[]=1&page=1"
    )
    assert got["ok"] is True
    assert "разбора нет" in got["parsing"]


def test_the_route_has_no_arbitrary_url_and_no_parser() -> None:
    api = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")
    start = api.index('    @app.get("/auctions/roseltorg/probe")')
    end = api.index("\n    @app.get", start + 10)
    route = api[start:end]

    assert "url:" not in route
    assert "roseltorg_probe" in route
    for invented in ("lot_id", "start_price", "application_deadline", "AuctionLot"):
        assert invented not in route

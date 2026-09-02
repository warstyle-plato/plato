"""Росэлторг сначала измеряется на ядре, затем разбирается.

Проверки взяты из ветки `codex/roseltorg-probe` (коммит 79a466e) и сведены с
нашей пробой. Сам коммит не переносился: он заводит ВТОРУЮ пробу того же
раздела под тем же адресом маршрута, а правило у нас одно — читатель и проба
объявляются один раз. Наша проба спрашивает тот же адрес владельца, плюс
простой запрос и контрольный запрос по нынешнему пути разведки.

Запуск: python3 -m pytest tests/test_roseltorg_krt_probe.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.adapters import roseltorg_probe  # noqa: E402


def test_the_probe_asks_the_exact_moscow_territory_page(monkeypatch) -> None:
    asked: list[tuple[str, float]] = []

    def fake_browser(url: str, seconds: float = 45.0, **kwargs):
        asked.append((url, seconds))
        return {"ok": True, "data_calls": []}

    monkeypatch.setattr(roseltorg_probe, "probe_browser", fake_browser)
    monkeypatch.setattr(roseltorg_probe, "_fetch",
                        lambda url, context: {"http_status": 200, "bytes": 0})
    got = roseltorg_probe.probe(seconds=17)

    assert asked == [(roseltorg_probe.CATALOGUE_URL, 17.0)]
    assert roseltorg_probe.CATALOGUE_URL == (
        "https://www.roseltorg.ru/imuschestvo/prochee/razvitie-territorii"
        "?sale=5&okato[]=45000000000&status[]=5&status[]=0&status[]=1&page=1"
    )
    assert got["browser"]["ok"] is True
    assert "разбора нет" in got["parsing"]


def test_the_same_address_is_asked_by_urllib_only_percent_encoded() -> None:
    """Скобки кодируются для `urllib`, но адрес остаётся тем же.

    Похожий адрес — не тот же адрес: у ГИС Торгов параметр, при котором
    целевых записей стало МЕНЬШЕ, выглядел ровно как работающий.
    """
    encoded = roseltorg_probe._for_urllib(roseltorg_probe.CATALOGUE_URL)
    assert "okato%5B%5D=45000000000" in encoded
    assert "[" not in encoded and "]" not in encoded
    assert encoded.split("?")[0] == roseltorg_probe.CATALOGUE_URL.split("?")[0]


def test_the_route_has_no_arbitrary_url_and_no_parser() -> None:
    api = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")
    start = api.index('    @app.get("/auctions/roseltorg/probe")')
    end = api.index("\n    @app.get", start + 10)
    route = api[start:end]

    assert "url:" not in route
    assert "roseltorg_probe" in route
    for invented in ("lot_id", "start_price", "application_deadline", "AuctionLot"):
        assert invented not in route


def test_the_dom_is_asked_by_what_a_card_is_not_by_a_guessed_class() -> None:
    """Пустой `data_calls` при видимых карточках — не «карточек нет».

    Карточка опознаётся ближайшим предком ссылки на `/procedure/`. Придуманное
    имя класса — тот же разбор по догадке, только раньше.
    """
    js = roseltorg_probe._DOM_FACTS_JS
    assert 'a[href*="/procedure/"]' in js
    assert "first_card_outer_html" in js and "first_procedure_links" in js
    for invented in ("card-item", "lot-card", "procedure-card", "js-lot"):
        assert invented not in js


def test_there_is_only_one_roseltorg_probe() -> None:
    """Второй пробы того же раздела не заводим — она разошлась бы с первой."""
    probes = sorted(p.name for p in (ROOT / "auction_search" / "adapters").glob("*roseltorg*"))
    assert probes == ["roseltorg.py", "roseltorg_probe.py", "roseltorg_public.py"]

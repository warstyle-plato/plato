"""Раздел читается постранично, а не одной страницей.

«Там целый раздел же так и называется КРТ на сайте» (владелец, 02.09.2026, со
снимком экрана). Раздел оказался тот самый, который мы и читаем, — и на его
экране в нём 44 процедуры. А разведка спрашивала РОВНО ОДНУ страницу: у поиска
по тегам обход был, у раздела нет. Всё, что не уместилось на первой, до нас не
доезжало вовсе, и недостачу я объяснял порядком чтения карточек — то есть
чинил не ту болезнь.

Запуск: python3 -m pytest tests/test_the_section_is_read_page_by_page.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.adapters.roseltorg import RoseltorgAdapter  # noqa: E402

OWNER_URL = ("https://www.roseltorg.ru/imuschestvo/prochee/razvitie-territorii"
             "?sale=5&okato%5B%5D=45000000000&status%5B%5D=5")


def test_the_page_keeps_the_owner_filters() -> None:
    """Страница добавляется к адресу, а не собирается заново."""
    assert RoseltorgAdapter._paged(OWNER_URL, 1) == OWNER_URL, "первая страница — как есть"
    second = RoseltorgAdapter._paged(OWNER_URL, 2)
    assert "page=2" in second
    for kept in ("sale=5", "okato", "status"):
        assert kept in second, f"фильтр {kept} потерян при переходе на страницу"
    # Страница не накапливается: третья не тащит за собой вторую.
    third = RoseltorgAdapter._paged(second, 3)
    assert third.count("page=") == 1, third


def test_the_section_walks_more_than_one_page() -> None:
    source = (ROOT / "auction_search" / "adapters" / "roseltorg.py").read_text("utf-8")
    body = source[source.index("    def discover_moscow("):
                  source.index("    def discover_moscow_history(")]
    section = body[body.index("for label, section_url in self.SECTION_URLS:"):
                   body.index("for tag in self.DISCOVERY_TAGS:")]
    assert "SECTION_MAX_PAGES" in section, "у раздела нет обхода по страницам"
    assert "_paged(" in section, "страница не подставляется в адрес раздела"
    assert RoseltorgAdapter.SECTION_MAX_PAGES > 1


def test_an_empty_page_stops_the_walk() -> None:
    """Страница без новых ссылок кончает обход, а не жжёт срок до потолка."""
    source = (ROOT / "auction_search" / "adapters" / "roseltorg.py").read_text("utf-8")
    body = source[source.index("for label, section_url in self.SECTION_URLS:"):
                  source.index("for tag in self.DISCOVERY_TAGS:")]
    assert "if not found:" in body and "break" in body


def test_the_probe_measures_the_next_pages() -> None:
    """Спор решает измерение с ядра: страницы 2 и 3 стоят в пробе."""
    from auction_search.adapters import roseltorg_probe

    urls = [url for _label, url in roseltorg_probe.SECTIONS]
    assert any("page=2" in url for url in urls), "вторая страница не измеряется"
    assert any("page=3" in url for url in urls)


def test_the_probe_reports_what_the_discovery_actually_reads() -> None:
    """Оговорка обязана пережить смену источника — проверяется утверждением.

    Первая версия этой проверки запрещала СЛОВА («не спрашивает вовсе») и
    завалилась на честном упоминании прошлого текста в объяснении, почему он
    снят. Запрещают место, а не слово: проба обязана называть разделы, которые
    разведка читает сегодня, и глубину их обхода — тогда устаревшее
    утверждение расходится с данными, а не с поиском по строке.
    """
    from auction_search.adapters import roseltorg_probe

    today = {
        "url_shape": roseltorg_probe.RoseltorgAdapter.SEARCH_URL,
        "sections": [url for _label, url in RoseltorgAdapter.SECTION_URLS],
        "section_max_pages": RoseltorgAdapter.SECTION_MAX_PAGES,
    }
    assert today["sections"], "проба не называет читаемые разделы"
    assert today["section_max_pages"] > 1
    source = (ROOT / "auction_search" / "adapters" / "roseltorg_probe.py").read_text("utf-8")
    assert '"sections": [url for _label, url in RoseltorgAdapter.SECTION_URLS]' in source, (
        "отчёт пробы не берёт разделы у самой разведки — список разойдётся")

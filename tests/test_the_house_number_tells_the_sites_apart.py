"""Две площадки на одной улице — разные, и оператор одной не факт о другой.

«Ты перепутал две Фестивальные: Бореалис — это про 6а, 6б, а не про 53А»
(владелец, 02.09.2026). Якорь держал улицу, а не владение: обе площадки есть в
каталоге, обе на Фестивальной, и находка приезжала в обе карточки сразу.

Текст без номера конфликтом не считается: об одной территории часто пишут
просто «на Фестивальной», и требовать номер значило бы выбрасывать настоящие
находки.

Запуск: python3 -m pytest tests/test_the_house_number_tells_the_sites_apart.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import krt_open_sources as sources  # noqa: E402

NEIGHBOUR = "Фестивальная ул., вл. 6, 6а, 6б, 4а пересечение с ул. Лавочкина"
OURS = "Фестивальная ул., вл. 53А"
NEWS = SimpleNamespace(
    title="КРТ на Фестивальной", url="https://www.mos.ru/news/1", domain="mos.ru",
    snippet='Оператором КРТ на Фестивальной ул., вл. 6, 6а, 6б, 4а стало '
            'ООО «СЗ „Бореалис Девелопмент“».')


def test_the_numbers_are_read_from_both_sides() -> None:
    assert sources._house_numbers(OURS) == {"53а"}
    assert sources._house_numbers(NEIGHBOUR) == {"6", "6а", "6б", "4а"}
    # Номер, названный без сокращения, тоже читается — «дом 12», «№ 9».
    assert sources._house_numbers("Молдавская ул., дом 3") == {"3"}


def test_the_neighbours_operator_is_not_our_fact() -> None:
    ours = sources.read_findings([NEWS], OURS)
    assert ours["operator_named"] == [], "оператор соседней площадки стал нашим"
    assert ours["taken"] is False
    assert [d["anchored"] for d in ours["documents"]] == [False]


def test_the_owner_of_the_news_still_gets_it() -> None:
    theirs = sources.read_findings([NEWS], NEIGHBOUR)
    assert theirs["operator_named"], "находка потеряна у той площадки, о которой она"
    assert "Бореалис" in theirs["operator_named"][0]["name"]
    assert theirs["taken"] is True


def test_a_text_without_numbers_is_not_a_conflict() -> None:
    assert sources._house_conflict("На Фестивальной улице построят жильё.", {"53а"}) is False
    # И у площадки без номера конфликта не бывает вовсе.
    assert sources._house_conflict("вл. 6, 6а", set()) is False


def test_the_card_says_whose_term_the_kind_is() -> None:
    """«Нежилой застройки» — про то, что на территории сейчас, а не что построят."""
    page = (ROOT / "auction_search" / "ui.py").read_text(encoding="utf-8")
    assert "Вид КРТ по решению города" in page
    assert "а не тем, что на ней построят" in page

"""Имя из общих слов якорем не работает — и молчит, а не утверждает.

«Магистральные улицы тер. 4, 5, 6» — настоящее имя площадки в каталоге города.
Якорем из него выходило «магис» + «улицы», и под такой якорь подходит любая
проза о московских магистралях: в карточку приехала статья dp.ru про
Москва-Сити и «реновацию локации в 3 тыс. га» — как признак ГОРОДСКИХ НУЖД
этой площадки (экран владельца, 02.09.2026).

Хуже того, после чистки якорей не оставалось вовсе, а пустой набор означал
«подходит любое предложение». Отсутствие якоря — причина ничего не утверждать,
а не разрешение утверждать всё.

Запуск: python3 -m pytest tests/test_a_generic_name_is_not_an_anchor.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import krt_open_sources as sources  # noqa: E402

GENERIC = "Магистральные улицы тер. 4, 5, 6"
ALIEN = SimpleNamespace(
    title="Перестроить статус. Где искать площадки",
    url="https://www.dp.ru/a/2023/09/28/perestroit-status-gde-iskat",
    domain="dp.ru",
    snippet=('Стоит отметить, что формирование "Москва-Сити" оказалось стимулом '
             'для реновации гигантской локации площадью 3 тыс. га на территории '
             'четырёх административных округов столицы.'),
)


def test_a_generic_name_has_no_anchors() -> None:
    assert sources._anchor_words(GENERIC) == set()
    # У настоящего имени якорь остаётся — чистка не съедает нужное.
    assert sources._anchor_words("Светлый проезд, вл. 3") == {"светл"}
    assert sources._anchor_words("Молдавская ул., вл. 3-5") == {"молда"}


def test_no_anchor_means_nothing_is_attributed() -> None:
    """Пустой набор якорей — причина молчать, а не разрешение утверждать всё."""
    assert sources._mentions("любое предложение о городе", set()) is False


def test_an_alien_article_is_not_a_fact_about_this_site() -> None:
    found = sources.read_findings([ALIEN], GENERIC)
    assert found["city_needs"] == [], "чужая статья стала фактом об этой площадке"
    assert found["operator_named"] == [] and found["taken"] is False
    # Прочитанное показываем — молча выброшенный документ читается как его
    # отсутствие, — но помечаем непривязанным.
    assert [d["anchored"] for d in found["documents"]] == [False]


def test_the_real_article_about_this_site_still_counts() -> None:
    """Лечить ложную находку потерей настоящей нельзя.

    У имени из общих слов якорь — ФРАЗА: слова подряд и в том же порядке.
    «Магистральные улицы» в тексте — это про площадку; «магистралей» вразброс
    по статье о городе — нет.
    """
    real = SimpleNamespace(
        title="Магистральные улицы: комплексное развитие территории",
        url="https://www.mos.ru/news/item/1", domain="mos.ru",
        snippet='Оператором выступает компания «КРТ «Магистральные улицы» - группа ЕСН.')
    found = sources.read_findings([real], GENERIC)
    assert found["operator_named"], "настоящая публикация о площадке потеряна"
    assert found["taken"] is True
    assert found["anchors"] == ["магис улицы"], "якорь — фраза, а не отдельные слова"


def test_a_name_with_neither_words_nor_phrase_is_anchorless() -> None:
    """Одно общее слово фразой не станет: якоря нет, и это сказано вслух."""
    found = sources.read_findings([ALIEN], "Территория")
    assert found["anchorless"] is True
    assert found["anchors"] == []


def test_a_generic_name_is_asked_by_its_district() -> None:
    """По такой площадке пишут по району и по соседству, а не по имени."""
    asked = sources.queries(GENERIC, "САО", "Хорошёвский")
    assert asked and all("Хорошёвский" in q for q in asked), (
        "район — единственное, чем такая площадка названа однозначно")
    # Имя всё же спрашивается — но словами, как их пишут, а не основами:
    # «Магис Улицы» поиску не сказать.
    assert any("Магистральные улицы" in q for q in asked)
    assert not any("Магис " in q for q in asked)
    # Без района спрашивать нечем — и это отказ, а не запрос наугад.
    assert sources.queries(GENERIC, "", "") == []


def test_the_card_says_why_it_stays_silent() -> None:
    page = (ROOT / "auction_search" / "ui.py").read_text(encoding="utf-8")
    assert "d.anchorless" in page
    assert "состоит" in page and "общих слов" in page

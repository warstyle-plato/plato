"""Неразобранная карточка КРТ называется, а не пропадает с экрана.

Снимок прода (31.08.2026) показал, что у части карточек значения съезжают на
поле. У «2-й Звенигородской»: округ «Планируемый», статус «влд. 13» (хвост
адреса, он же в слаге `...-ul-vld-13`), общий объём 350 м² при жилье 27 580 —
одно число досталось трём разным показателям, а общий получил чужое.

Наружу это выглядит как отсутствие площадки: строка с «округом» «Планируемый»
не проходит ни один флажок округа, и с экрана она исчезает молча. Так пропали
две площадки из ручной таблицы владельца, и без сверки этого не было видно
вовсе — ни ошибки, ни счётчика.

Проверка не чинит съезд: причина в разметке карточки, и её надо смотреть.
Она не даёт выдать неразобранное за разобранное — разбор проверяется тем, что
известно о нём самом.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from market_search.krt_registry import (  # noqa: E402
    KrtTerritory,
    parse_catalogue,
    parse_problem,
)

_CARD = ('<a href="/projects/{slug}/">{name} Подробнее</a>'
         '<div>Округ: {okrug}</div><div>Район: {district}</div>'
         '<div>Статус: {status}</div><div>Площадь: 1,0</div>'
         '<div>Общий объем застройки: {total}</div>'
         '<div>Жилое назначение: {housing}</div>')

_GOOD = _CARD.format(slug="pudovkina-ul-vl-7", name="ул. Пудовкина, вл. 7А",
                     okrug="ЗАО", district="Раменки", status="В реализации",
                     total="25550", housing="25550")
# Ровно та строка, что нашлась в снимке прода.
_BROKEN = _CARD.format(slug="2-ya-zvenigorodskaya-ul-vld-13",
                       name="КРТ 2-я Звенигородская ул.", okrug="Планируемый",
                       district="ЦАО", status="влд. 13",
                       total="350", housing="27580")


def test_a_healthy_card_carries_no_complaint() -> None:
    rows, _ = parse_catalogue(_GOOD)
    assert len(rows) == 1
    assert rows[0].parse_problem == "", rows[0].parse_problem


def test_the_shifted_card_names_all_three_signs() -> None:
    """Съезд виден по трём независимым признакам — проверяются все три."""
    rows, _ = parse_catalogue(_BROKEN)
    assert len(rows) == 1
    problem = rows[0].parse_problem
    assert problem, "съехавшая карточка выдана за разобранную"
    assert "округ" in problem
    assert "статус" in problem
    assert "общий объём меньше жилого" in problem


def test_the_broken_card_is_not_dropped() -> None:
    """Молча выброшенная площадка читается как её отсутствие.

    Строка остаётся в каталоге со своим диагнозом: выбросить её — значит
    повторить ту же пропажу, только с нашей стороны.
    """
    rows, _ = parse_catalogue(_GOOD + _BROKEN)
    assert [row.slug for row in rows] == [
        "pudovkina-ul-vl-7", "2-ya-zvenigorodskaya-ul-vld-13"]
    assert rows[0].to_dict()["parse_problem"] == ""
    assert rows[1].to_dict()["parse_problem"]


def test_an_unknown_field_alone_is_not_a_verdict() -> None:
    """Пустое поле — «не знаем», а не «разбор сломан».

    У части карточек города общего объёма или статуса нет вовсе, и объявлять
    их неразобранными значило бы вычеркнуть исправные площадки.
    """
    bare = KrtTerritory(slug="s", name="n", url="u")
    assert parse_problem(bare) == ""
    assert parse_problem(KrtTerritory(slug="s", name="n", url="u", okrug="ТАО")) == ""
    assert parse_problem(
        KrtTerritory(slug="s", name="n", url="u", total_gfa_sqm=100.0)) == ""


def test_the_catalogue_route_counts_what_did_not_parse(monkeypatch) -> None:
    """Счёт неразобранного доезжает до страницы, а не остаётся в логе."""
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auction_search.api import install

    monkeypatch.setenv("MARKET_CABINET_KEY", "test-key")
    rows, _ = parse_catalogue(_GOOD + _BROKEN)
    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(
            catalogue=lambda **_: [row.to_dict() for row in rows],
            status=lambda: {"complete": True, "refreshing": False},
        ),
    )
    install(app)
    got = TestClient(app).get("/auctions/krt", headers={"X-Market-Key": "test-key"})
    assert got.status_code == 200, got.text
    payload = got.json()
    assert payload["count"] == 2
    assert payload["unparsed_count"] == 1
    assert payload["unparsed"][0]["slug"] == "2-ya-zvenigorodskaya-ul-vld-13"
    assert payload["unparsed"][0]["problem"]


def test_the_page_says_it_out_loud() -> None:
    """Счётчик в ответе, о котором никто не сказал, — это молчание."""
    import auction_search.ui as ui

    page = ui.auctions_page()
    assert "renderKrtUnparsedNote" in page
    assert "не разобрались" in page
    assert "d.unparsed" in page, "страница счёт с сервера не читает"

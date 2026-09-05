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


def test_the_okrug_is_recognised_whatever_the_case() -> None:
    """«ЗелАо» — это Зеленоградский округ, а не съехавшее поле.

    Регистр каталог держит как придётся, а набор сравнивался буква в букву:
    из восьми строк, объявленных неразобранными на снимке прода 05.09.2026,
    пять были разобраны верно и стояли с пометкой о съезде. Кричащая зря
    проверка хуже отсутствующей — её перестают читать, и настоящие три
    съехавшие карточки тонут среди ложных пяти.
    """
    for written in ("ЗелАо", "ЗелАО", "зелао", "ЦАО", "цао"):
        row = KrtTerritory(slug="s", name="n", url="u", okrug=written)
        assert parse_problem(row) == "", f"«{written}» объявлен не московским"
    # Набор при этом остаётся набором имён: чужой округ по-прежнему называется.
    assert "не из московских" in parse_problem(
        KrtTerritory(slug="s", name="n", url="u", okrug="Планируемый"))


def test_a_shifted_card_is_not_run_through_the_model() -> None:
    """Съехавшая карточка до модели не доходит, и отказ несёт диагноз.

    На «ул. Мусоргского» площадь участка вышла 26 500 «га» — метры, съехавшие
    на поле, — и модель посчитала на них LLCR 1,10x, маржу 8,7% и балл 55.
    Правдоподобный вердикт из чисел, стоящих не в своих колонках, страшнее
    отсутствующего: отличить его на экране не от чего.
    """
    from auction_search.krt_screening import build_krt_model_screening

    project = {"slug": "ul-musorgskogo", "name": "ул. Мусоргского",
               "housing_gfa_sqm": 26_500.0, "area_ha": 26_500.0,
               "parse_problem": "округ «ул. Декабристов» не из московских"}
    refused = build_krt_model_screening(project, {}, core=None)
    assert refused["available"] is False
    assert "со сдвигом" in refused["reason"]
    assert "ул. Декабристов" in refused["reason"], "отказ не назвал, чем именно"


def test_the_shift_travels_with_the_ranking_row() -> None:
    """Экран прячет числа съехавшей карточки — но только если знает о съезде.

    Поле читалось лишь из каталога: строка рейтинга приходила без него, и
    площадь, жильё и балл в ней выглядели измеренными. А починившаяся карточка
    обязана снять метку, поэтому поле обновляется и пустым.
    """
    from auction_search.krt_ranking import keep_computed, score_row

    shifted = {"slug": "ul-musorgskogo", "name": "ул. Мусоргского",
               "parse_problem": "статус «влд. 1» не опознан"}
    row = score_row(shifted, {"available": False, "reason": "не считали"})
    assert row["parse_problem"] == "статус «влд. 1» не опознан"

    healed = score_row({"slug": "ul-musorgskogo", "name": "ул. Мусоргского"},
                       {"available": False, "reason": "не считали"})
    kept = keep_computed({**row, "available": True, "margin_pct": 8.7}, healed)
    assert kept["parse_problem"] == "", "метка пережила починку карточки"
    assert kept["margin_pct"] == 8.7, "неудача пересчёта затёрла посчитанное"


def test_numbers_counted_on_shifted_fields_do_not_survive() -> None:
    """«Посчитанное не выбрасывают» — про счёт, а не про съехавший источник.

    Прежние числа посчитаны на полях этой же карточки: у «ул. Мусоргского»
    площадь участка стояла 26 500 «га». Оставить их значило бы хранить вердикт
    из чисел не в своих колонках — а он выглядит ровно как настоящий.
    """
    from auction_search.krt_ranking import keep_computed

    counted = {"slug": "ul-musorgskogo", "available": True, "margin_pct": 8.7,
               "project_llcr_x": 1.099, "parse_problem": ""}
    shifted = {"slug": "ul-musorgskogo", "available": False,
               "reason": "Карточка каталога разобрана со сдвигом (…) — считать нечем",
               "parse_problem": "статус «влд. 1» не опознан"}
    kept = keep_computed(counted, shifted)
    assert kept.get("margin_pct") is None, "вердикт из съехавших чисел остался"
    assert kept.get("project_llcr_x") is None
    assert kept["parse_problem"]

    # Обычная неудача пересчёта по-прежнему не затирает посчитанное.
    ordinary = {"slug": "ul-musorgskogo", "available": False,
                "reason": "Маркетинг пока не дал ценового ориентира", "parse_problem": ""}
    assert keep_computed(counted, ordinary)["margin_pct"] == 8.7


def test_the_table_does_not_show_economy_of_a_shifted_card() -> None:
    """Две правды в одной строке: колонки ТЭП «не разобрано», а рядом LLCR.

    Экран прятал числа каталога и рисовал модель, посчитанную на тех же
    съехавших числах, — то есть отвечал на один вопрос дважды и по-разному.
    """
    import auction_search.ui as ui

    page = ui.auctions_page()
    assert "function krtBrokenSlug(" in page
    assert "krtBrokenModelNote" in page
    body = page[page.index("function krtModelCell("):page.index("function krtRankCell(")]
    assert "krtBrokenSlug(slug)" in body, "колонка модели про съезд не знает"

    # Отчёт приходит ПОЗЖЕ отрисовки карточки и переписывал бы блок своими
    # числами: гейт обязан стоять и там, где его рисуют.
    loader = page[page.index("async function loadKrtReport("):page.index("function renderKrtReport(")]
    assert "krtBroken(x)" in loader, "готовый отчёт съехавшей карточки всё равно рисуется"

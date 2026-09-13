"""Воронка обращений помесячно, с подсвеченным окном последних месяцев.

«Можно эту информацию разложить по месяцам и отдельно подсветить последние 3
месяца» (владелец, 12.09.2026). Блок отвечал одним числом за всё время: канал,
который работал год назад и затих, от канала, который живёт сейчас, по такой
колонке не отличить.

Две вещи меряются здесь отдельно, потому что молча они читаются наоборот.
Месяц ставится по дате ОБРАЩЕНИЯ, а бронь приходит позже — у свежих месяцев
доля занижена по построению. И последний месяц выгрузки почти всегда неполон:
это меряется по дате последнего обращения в ней, а не предполагается.
"""
from __future__ import annotations

from pathlib import Path

from market_search import demand

CABINET = Path(__file__).resolve().parent.parent / "market_search" / "cabinet.py"


def _deals(rows: list[dict]) -> list[dict]:
    base = {"source": "Звонок", "manager": "Иванов", "booked": False, "month": "2026-08",
            "need_asked": False, "next_step": False, "not_a_lead": False}
    return [{**base, **row} for row in rows]


def _month(month: str, calls: int, booked: int = 0) -> list[dict]:
    return _deals([{"month": month, "booked": index < booked} for index in range(calls)])


def test_the_row_goes_by_the_month_of_the_enquiry() -> None:
    """Доля месяца — судьба его обращений, а не броней этого месяца."""
    got = demand.funnel(_month("2026-06", 10, 2) + _month("2026-07", 5, 0))
    assert [row["month"] for row in got["by_month"]] == ["2026-06", "2026-07"]
    june = got["by_month"][0]
    assert june["calls"] == 10 and june["target"] == 10 and june["booked"] == 2
    assert june["share"] == 0.2
    assert got["by_month"][1]["share"] == 0
    assert any("дате ОБРАЩЕНИЯ" in note and "занижена" in note for note in got["notes"])


def test_the_window_is_the_last_three_months_and_it_is_named() -> None:
    """Окно названо именем периода, а не краями: края читаются вычитанием."""
    deals = sum((_month(month, 4, 1) for month in
                 ("2026-04", "2026-05", "2026-06", "2026-07", "2026-08")), [])
    got = demand.funnel(deals)
    assert got["recent_months"] == 3
    assert got["recent"]["months"] == ["2026-06", "2026-07", "2026-08"]
    assert got["recent"]["label"] == "июнь, июль и август 2026"
    assert got["recent"]["calls"] == 12 and got["recent"]["booked"] == 3
    assert [row["recent"] for row in got["by_month"]] == [False, False, True, True, True]
    # Прежние месяцы — свой ответ: без них «17,4%» не с чем сравнить.
    assert got["before"]["label"] == "апрель и май 2026"
    assert got["before"]["calls"] == 8


def test_the_window_name_carries_the_year_where_it_changes() -> None:
    """«декабрь 2025, январь и февраль 2026» — год у того месяца, где он сменился."""
    deals = sum((_month(month, 3) for month in
                 ("2025-11", "2025-12", "2026-01", "2026-02")), [])
    got = demand.funnel(deals)
    assert got["recent"]["label"] == "декабрь 2025, январь и февраль 2026"


def test_a_short_history_is_the_whole_window_and_has_nothing_to_compare_with() -> None:
    """Двух месяцев на окно не хватает — «прежних месяцев» тогда нет вовсе."""
    got = demand.funnel(_month("2026-07", 3) + _month("2026-08", 3))
    assert got["recent"]["months"] == ["2026-07", "2026-08"]
    assert got["recent"]["label"] == "июль и август 2026"
    assert got["before"] is None


def test_the_partial_month_is_measured_not_guessed() -> None:
    """Выгрузка снята серединой месяца — и говорит это сама, своей датой."""
    deals = _month("2026-07", 4) + _month("2026-08", 4)
    got = demand.funnel(deals, {"last_created": "2026-08-21"})
    assert got["partial_month"] == "2026-08"
    assert any("Август 2026" in note and "21-го" in note and "31 день" in note
               for note in got["notes"])
    # Выгрузка снята последним днём — месяц полон, и объявлять его частью
    # нельзя: «неполный» тогда было бы нашей догадкой, а не измерением.
    whole = demand.funnel(deals, {"last_created": "2026-08-31"})
    assert whole["partial_month"] == ""
    assert not any("неполный месяц" in note for note in whole["notes"])
    # Даты выгрузки нет вовсе — это «не знаем», а не «месяц полон».
    silent = demand.funnel(deals)
    assert silent["partial_month"] == ""


def test_an_enquiry_without_a_date_is_counted_aloud() -> None:
    """Молча выброшенное обращение читается как «его не было»."""
    got = demand.funnel(_month("2026-08", 3) + _deals([{"month": ""}, {"month": ""}]))
    assert got["undated"] == 2
    assert got["quality"]["calls"] == 5, "в общих числах они стоят"
    assert sum(row["calls"] for row in got["by_month"]) == 3
    assert any("без даты создания" in note and "2" in note for note in got["notes"])


def test_a_source_carries_the_same_window_as_the_row() -> None:
    """«За 3 мес.» у источника — то же окно, что у помесячного ряда."""
    deals = sum((_month(month, 4, 1) for month in
                 ("2026-04", "2026-05", "2026-06", "2026-07", "2026-08")), [])
    deals += _deals([{"month": "2026-08", "source": "Агент", "booked": True}])
    got = demand.funnel(deals)
    call = next(row for row in got["by_source"] if row["name"] == "Звонок")
    assert call["deals"] == 20 and call["recent_deals"] == 12
    assert call["recent_booked"] == 3 and call["recent_share"] == 0.25
    agent = next(row for row in got["by_source"] if row["name"] == "Агент")
    assert agent["recent_deals"] == 1 and agent["recent_share"] == 1.0


def test_the_window_is_highlighted_on_the_live_chart(tmp_path) -> None:
    """Подсветка — это геометрия, и меряет её браузер.

    В исходнике полоса выглядит одинаково у верного кода и у сломанного: она
    рисуется по индексам, пришедшим с сервера. Поэтому здесь меряется, какие
    именно столбики она накрывает, — и что бледный столбик ровно один и стоит
    он на неполном месяце.

    Цвет окна и цвет неполного периода разные намеренно: бледный столбик уже
    значит «периода не хватает», и второй смысл на ту же краску вешать нельзя.
    """
    import sys

    import pytest

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from browser import chromium_or_skip

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    from market_search import cabinet

    deals = sum((_month(month, 8, 2) for month in
                 ("2026-04", "2026-05", "2026-06", "2026-07", "2026-08")), [])
    payload = {"demand": {"funnel": demand.funnel(deals, {"last_created": "2026-08-14"})},
               "total": {}, "dynamics": [], "sources": []}

    file = tmp_path / "cabinet.html"
    file.write_text(cabinet.cabinet_page("sales").replace("__DEVELOPAID_VERSION__", "t"),
                    encoding="utf-8")
    with sync_playwright() as play:
        browser = play.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page(viewport={"width": 1200, "height": 900})
            errors: list[str] = []
            tab.on("pageerror", lambda exc: errors.append(str(exc)))
            tab.route("**/*", lambda route: route.abort()
                      if route.request.url.startswith("http") else route.continue_())
            tab.goto(file.as_uri())
            tab.evaluate("(d)=>renderSales(d)", payload)
            got = tab.evaluate("""()=>{
              const box=document.querySelector('#sb-lead');
              if(!box) return {missing:'блока воронки нет'};
              const svg=[...box.querySelectorAll('svg')].find(
                s=>/по месяцу обращения/.test(s.textContent||''));
              if(!svg) return {missing:'графика по месяцам нет'};
              const rects=[...svg.querySelectorAll('rect')];
              const band=rects.find(r=>r.getAttribute('fill')==='#eef4fa');
              const bars=rects.filter(r=>r!==band).map(r=>({
                x:Number(r.getAttribute('x'))+Number(r.getAttribute('width'))/2,
                pale:r.getAttribute('fill')!=='#4E9BDE'}));
              const labels=[...svg.querySelectorAll('text')].map(t=>t.textContent);
              const inBand=band?bars.map(b=>b.x>=Number(band.getAttribute('x'))
                &&b.x<=Number(band.getAttribute('x'))+Number(band.getAttribute('width'))):[];
              // Таблица месяцев стоит ПОД своим графиком: в колоде чертится
              // та таблица, над которой график, а без неё числа живут только
              // на экране.
              const table=[...box.querySelectorAll('table')].find(
                t=>(t.querySelector('th')||{}).textContent==='Месяц');
              return {bars:bars.length, inBand, pale:bars.map(b=>b.pale), labels,
                      table:table?[...table.querySelectorAll('tr')].length:0,
                      tableAfterChart:!!(table&&svg.compareDocumentPosition(table)
                        &Node.DOCUMENT_POSITION_FOLLOWING)};
            }""")
        finally:
            browser.close()

    assert not got.get("missing"), got.get("missing")
    assert got["bars"] == 5, got
    assert got["inBand"] == [False, False, True, True, True], got["inBand"]
    assert got["pale"] == [False, False, False, False, True], got["pale"]
    assert any("последние 3 мес." in (line or "") for line in got["labels"]), got["labels"]
    assert got["table"] == 6, "в таблице шапка и пять месяцев"
    assert got["tableAfterChart"], "таблица месяцев стоит не под своим графиком"
    assert not errors, errors


def _window_deals() -> list[dict]:
    return sum((_month(month, 20, booked) for month, booked in
                (("2026-04", 1), ("2026-05", 1), ("2026-06", 3),
                 ("2026-07", 2), ("2026-08", 2))), [])


def test_the_window_reaches_the_conclusion_under_the_block() -> None:
    """«Как сейчас» — отдельный вопрос, и вывод обязан на него отвечать."""
    from market_search import contracting

    lead = demand.funnel(_window_deals(), {"last_created": "2026-08-14"})
    line = contracting.conclusions(
        {"demand": {"funnel": lead}, "total": {}, "dynamics": []})["funnel"]
    assert "июнь, июль и август 2026" in line
    assert "11,7%" in line and "5,0%" in line, line
    assert "занижена по построению" in line, line


def test_the_window_reaches_the_question(tmp_path) -> None:
    """Платон отвечает по тем числам, что на экране, — включая окно."""
    import importlib
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    question = importlib.import_module("test_the_question_fits_the_limit")

    # Свод берётся ЛЁГКИЙ: у «толстого» воронка в бюджет не влезает вовсе, и
    # проверка тогда меряла бы укладку, а не то, доезжает ли окно до вопроса.
    summary = question._fat_summary()
    for heavy in ("salesroom", "by_channel", "by_payment", "dynamics", "by_size",
                  "by_product", "pool", "by_quarter", "terminated"):
        summary.pop(heavy, None)
    summary["demand"] = {"funnel": demand.funnel(_window_deals(),
                                                 {"last_created": "2026-08-14"})}
    message = question._question(summary)
    assert "ВОРОНКА за июнь, июль и август 2026" in message, message[:400]
    # Свежесть месяца оговаривается в самом вопросе: без неё Платон прочитает
    # провал там, где бронь просто ещё не пришла.
    assert "занижена по построению" in message

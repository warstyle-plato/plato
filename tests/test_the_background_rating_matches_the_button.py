"""Балл каталога считает ОДНА политика: фон и кнопка не расходятся.

Симптом (владелец, 27.09.2026): «в каталоге КРТ вчера числовой рейтинг был
почти у всех, сейчас у единиц».

Замер прода того же утра (GET /auctions/krt/ranking, выпуск 0.24.31): строк
601, `investment_rating` есть у 365, а score/display_score не null — у 13. У 352
причина «Не хватает данных даже после подстановок: burden». При этом
`burden_complete=True` стоял ровно у ОДНОЙ строки.

Причина — два расчёта одного балла с разной политикой. Медианная подстановка
жила только в явном пересчёте (кнопка каталога), а фоновый слой
`_cached_investment_rating_fields` считал тот же балл без неё. Пока фон почти
ничего не пересчитывал, расхождение не было видно; #517 поднял
`BURDEN_PIPELINE_VERSION`, `_rating_needs_recount` пометил к пересчёту весь
каталог — и фон перезаписал вчерашние баллы отказом.

Второе следствие того же замера: медиана нагрузки считалась по n=1. Медиана по
одной точке — не подстановка, и выдавать её за ответ нельзя; но и обнулять ею
балл нельзя тоже, потому что отсутствие нагрузки у ВСЕГО каталога — наш
незакрытый конвейер, а не свойство площадки. Отсюда порог выборки и отложенная
составляющая с названной причиной.

Запуск: python3 -m pytest tests/test_the_background_rating_matches_the_button.py -q
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auction_search import api, krt_investment_score  # noqa: E402

# Наблюдения каталога в том виде, в каком их отдаёт `_rating_catalogue_medians`.
# Числа — с прода 27.09.2026: burden собран у одной строки, остальное — у многих.
MEDIANS_AFTER_517 = {
    "llcr": {"value": 1.14, "count": 362},
    "price": {"value": 431_000.0, "count": 358},
    "absorption": {"value": 1_240.0, "count": 244},
    "burden": {"value": 46.2, "count": 1},
}
MOSCOW = {"price": 452_000.0, "absorption": 1_310.0, "segment": "комфорт"}
ROW_WITHOUT_BURDEN = {
    "project_llcr_x": 1.19,
    "surrounding_price_rub_sqm": 486_000.0,
    "local_absorption_sqm_month": 1_180.0,
    "moscow_absorption_sqm_month": 1_310.0,
    "burden_reason": "Финансовая модель площадки не собрана",
}


def _rating(medians: dict, *, burden_pct: float | None) -> dict:
    """Балл по одной политике: так его считают и фон, и кнопка."""
    policy = krt_investment_score.rating_inputs(
        project={"slug": "krt-row"},
        row=ROW_WITHOUT_BURDEN,
        segment="комфорт",
        llcr=ROW_WITHOUT_BURDEN["project_llcr_x"],
        market_price=ROW_WITHOUT_BURDEN["surrounding_price_rub_sqm"],
        local_absorption=ROW_WITHOUT_BURDEN["local_absorption_sqm_month"],
        benchmark_absorption=ROW_WITHOUT_BURDEN["moscow_absorption_sqm_month"],
        burden_pct=burden_pct,
        burden_state={"available": burden_pct is not None,
                      "reason": "" if burden_pct is not None
                      else "Финансовая модель площадки не собрана"},
        catalogue_medians=medians,
        city_reference=MOSCOW,
    )
    return krt_investment_score.score(
        status_kind="planned",
        target_rub_sqm=krt_investment_score.DEFAULT_PRICE_TARGET_RUB_SQM,
        llcr=policy["llcr"],
        market_rub_sqm=policy["market_rub_sqm"],
        local_sqm_month=policy["local_sqm_month"],
        benchmark_sqm_month=policy["benchmark_sqm_month"],
        burden_pct=policy["burden_pct"],
        missing_reasons=policy["missing_reasons"],
        observed_components=policy["observed_components"],
        imputed_components=policy["imputed_components"],
        deferred_components=policy["deferred_components"],
    )


def test_a_row_without_burden_keeps_a_number_and_says_why() -> None:
    """Строка без нагрузки получает балл, а не прочерк, и оговорка названа."""
    got = _rating(MEDIANS_AFTER_517, burden_pct=None)

    assert got["display_score"] is not None, got["reason"]
    # Три составляющих из четырёх — это и есть coverage: подстановки не было.
    assert got["coverage_pct"] == 75
    assert [item["component"] for item in got["deferred"]] == ["burden"]
    said = got["deferred"][0]["reason"]
    assert "у строк: 1" in said and "не ответ" in said, said
    assert str(krt_investment_score.MIN_MEDIAN_SAMPLE) in said
    # Причина видна там, где её читает экран, а не только в поле.
    assert "burden" in got["reason"] and "отложена" in got["reason"]
    # Отказ площадки при этом не потерян: он остаётся причиной у составляющей.
    assert "Финансовая модель" in got["components"]["burden"]["missing_reason"]
    # Предохранитель: те же входы без отложенной составляющей дают ПРОЧЕРК —
    # ровно это фон и записал 352 строкам каталога.
    bare = krt_investment_score.score(
        status_kind="planned",
        target_rub_sqm=krt_investment_score.DEFAULT_PRICE_TARGET_RUB_SQM,
        llcr=ROW_WITHOUT_BURDEN["project_llcr_x"],
        market_rub_sqm=ROW_WITHOUT_BURDEN["surrounding_price_rub_sqm"],
        local_sqm_month=ROW_WITHOUT_BURDEN["local_absorption_sqm_month"],
        benchmark_sqm_month=ROW_WITHOUT_BURDEN["moscow_absorption_sqm_month"],
        burden_pct=None,
    )
    assert bare["display_score"] is None
    assert bare["reason"].startswith("Не хватает данных")


def test_the_median_of_one_point_is_not_passed_off_as_an_answer() -> None:
    """Медиана по n=1 не подставляется, а по достаточной выборке — подставляется."""
    scarce = _rating(MEDIANS_AFTER_517, burden_pct=None)
    assert scarce["imputed"] == [], scarce["imputed"]
    assert scarce["components"]["burden"]["value"] is None

    enough = dict(MEDIANS_AFTER_517, burden={"value": 46.2, "count": 12})
    filled = _rating(enough, burden_pct=None)
    assert [item["component"] for item in filled["imputed"]] == ["burden"]
    assert filled["deferred"] == []
    assert filled["components"]["burden"]["estimated"] is True
    # Подстановка — не факт: coverage остаётся долей измеренного.
    assert filled["coverage_pct"] == 75
    # И это РАЗНЫЕ баллы: иначе порог выборки ничего не менял бы.
    assert filled["display_score"] != scarce["display_score"]


def test_a_measured_burden_still_beats_every_substitution() -> None:
    """Предохранитель: посчитанная нагрузка идёт в балл как факт, coverage 100%."""
    got = _rating(MEDIANS_AFTER_517, burden_pct=46.2)
    assert got["coverage_pct"] == 100
    assert got["imputed"] == [] and got["deferred"] == []
    assert got["components"]["burden"]["estimated"] is False


def test_two_missing_components_still_refuse_a_number() -> None:
    """Отложить можно одну составляющую: индекс по двум из четырёх — другая мера."""
    bare = {key: {"value": None, "count": 0} for key in
            ("llcr", "price", "absorption", "burden")}
    policy = krt_investment_score.rating_inputs(
        project={}, row={}, segment="",
        llcr=1.19, market_price=486_000.0,
        local_absorption=None, benchmark_absorption=None, burden_pct=None,
        catalogue_medians=bare, city_reference={"price": None, "absorption": None},
    )
    got = krt_investment_score.score(
        status_kind="planned", target_rub_sqm=600_000.0,
        llcr=policy["llcr"], market_rub_sqm=policy["market_rub_sqm"],
        local_sqm_month=policy["local_sqm_month"],
        benchmark_sqm_month=policy["benchmark_sqm_month"],
        burden_pct=policy["burden_pct"],
        missing_reasons=policy["missing_reasons"],
        observed_components=policy["observed_components"],
        imputed_components=policy["imputed_components"],
        deferred_components=policy["deferred_components"],
    )
    assert got["display_score"] is None
    assert set(got["missing"]) == {"absorption", "burden"}
    assert got["reason"].startswith("Не хватает данных")


def _score_call(source: str, start: str) -> str:
    """Вызов score() целиком — от имени до закрывающей скобки того же отступа."""
    block = source[source.index(start):]
    call = block[block.index("krt_investment_score.score("):]
    end = re.search(r"\n        \)\n", call)
    assert end is not None, "вызов score() не найден целиком"
    return call[:end.end()]


def test_both_recounts_feed_the_score_from_the_same_policy() -> None:
    """Фоновый пересчёт и пересчёт по кнопке зовут одну политику одинаково.

    Это и есть дефект #517 в одной проверке: у фонового слоя своей политики
    больше нет, и все входы балла он берёт из того же `policy`, что кнопка.
    """
    source = inspect.getsource(api.install)
    assert source.count("policy = _rating_score_inputs(") == 2

    explicit = _score_call(source, "async def auction_krt_investment_score")
    background = _score_call(source, "def _cached_investment_rating_fields")
    for line in ('llcr=policy["llcr"]',
                 'market_rub_sqm=policy["market_rub_sqm"]',
                 'local_sqm_month=policy["local_sqm_month"]',
                 'benchmark_sqm_month=policy["benchmark_sqm_month"]',
                 'burden_pct=policy["burden_pct"]',
                 'missing_reasons=policy["missing_reasons"]',
                 'observed_components=policy["observed_components"]',
                 'imputed_components=policy["imputed_components"]',
                 'deferred_components=policy["deferred_components"]'):
        assert line in explicit, line
        assert line in background, line
    # Снимок балла для строки тоже один: разный набор полей у кнопки и у фона
    # однажды дал бы карточке и таблице два разных ответа об одном балле.
    assert source.count("stored_rating = _stored_rating(rating)") == 2
    assert "def _stored_rating(" in source
    # Прежняя подстановка в маршруте не осталась второй копией.
    assert not re.search(r"\n\s+catalogue_medians = _rating_catalogue_medians\(\)\n",
                         source)

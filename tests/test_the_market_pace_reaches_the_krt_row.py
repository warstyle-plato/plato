"""Темп окружения доезжает до строки рейтинга, а «нет данных» не ноль.

Владелец (20.09.2026): «в разделе КРТ фильтр окружения не работает — у
проектов отсутствуют рыночные цены и данные о продажах окружения», и в журнале
Render стоит «Источник рыночных данных выключен: не заданы PULSE_LOGIN и
PULSE_PASSWORD».

Замер прода того же часа развёл две вещи. Источник РАБОТАЕТ: по Варшавскому ш.,
вл. 37 `krt:<slug>` разрешился в «г Москва, Варшавское шоссе, д 37»
(55.688649 / 37.623411), Pulse нашёл 64 проекта, в расчёт взято 24, цена
окружения 640 176 ₽/м², темп 16,6 ДДУ/мес. Строка Render — с хоста БОТА, у
которого доступа к Pulse нет по построению (это отдельное решение и отдельный
сторож, `test_the_krt_run_needs_the_market_source.py`).

А не работало другое: темп до СТРОКИ рейтинга не доезжал вовсе. Посчитанное на
сервере, но не доехавшее до строки, неотличимо от непосчитанного — экран
читает строку, а не скрининг.

Цена окружения при этом остаётся своим полем и своим фильтром: «почём здесь
продают» и «сколько продают в месяц» — разные вопросы, и два числа под одним
именем читались бы как одно.

Запуск: python3 -m pytest tests/test_the_market_pace_reaches_the_krt_row.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auction_search import krt_ranking  # noqa: E402
from auction_search import krt_screening  # noqa: E402

SITE = {"slug": "varshavskoe", "name": "Варшавское шоссе, вл. 37",
        "okrug": "ЮАО", "area_ha": 14.62, "housing_gfa_sqm": 229_490}

# Числа — с живого отчёта прода по этой площадке (20.09.2026).
SCREENING = {
    "available": True,
    "traffic_light": {"tone": "warn", "label": "Проходит", "score": 55},
    "market": {"start_price_rub_sqm": 640_176,
               "market_price_rub_sqm": 640_176,
               "entry_price_rub_sqm": 479_592,
               "recommended_segment": "бизнес"},
    "absorption": {"available": True, "market_units_per_month": 16.6,
                   "sellout_months_per_phase": 50},
    "krt": {"project_llcr_x": 1.177, "margin_pct": 14.2},
    "phasing": {"count": 4, "saleable_sqm": 150_000},
}


def test_the_row_carries_both_the_price_and_the_pace():
    row = krt_ranking.score_row(dict(SITE), dict(SCREENING))
    assert row["surrounding_price_rub_sqm"] == 640_176, row
    assert row["surrounding_sales_units_per_month"] == 16.6, row
    # Предохранитель: это РАЗНЫЕ величины, и совпади они — проверка не значит
    # ничего. «Почём продают» и «сколько продают» меряются разным.
    assert row["surrounding_price_rub_sqm"] != row["surrounding_sales_units_per_month"]


def test_no_data_is_not_zero():
    """Темп не определён — это None, а не ноль: ноль читается как «не продают»."""
    silent = {**SCREENING, "absorption": {"available": False}}
    assert krt_ranking.score_row(dict(SITE), silent)["surrounding_sales_units_per_month"] is None

    # А вот честный ноль источника остаётся нулём: источник вправе сказать, что
    # сделок в округе не было, и это ответ, а не молчание.
    zero = {**SCREENING, "absorption": {"available": True, "market_units_per_month": 0.0}}
    assert krt_ranking.score_row(dict(SITE), zero)["surrounding_sales_units_per_month"] == 0.0


def test_a_row_without_a_model_says_nothing_about_the_market():
    """Модель не посчиталась — поля нет вовсе, а не ноль в нём."""
    refused = {"available": False, "reason": "Маркетинг пока не дал ценового ориентира"}
    row = krt_ranking.score_row(dict(SITE), refused)
    assert row["available"] is False
    assert row.get("surrounding_sales_units_per_month") is None, row
    assert row.get("surrounding_price_rub_sqm") is None, row


def test_the_pace_travels_to_the_screen_and_the_export():
    """Поле доезжает до выгрузки и до груза страницы — иначе его нет на экране."""
    from auction_search import api, ui

    source = Path(api.__file__).read_text(encoding="utf-8")
    assert '("surrounding_sales_units_per_month", "Продажи окружения, ДДУ/мес.", 27)' in source, \
        "колонки выгрузки не знают о темпе"
    assert '"surrounding_sales_units_per_month",' in source, \
        "темп не назван числовым — в Excel он поедет текстом"

    page = ui.auctions_page(None)
    assert "surrounding_sales_units_per_month:rank.surrounding_sales_units_per_month" in page, \
        "страница не кладёт темп в груз выгрузки"


def test_the_rules_version_rises_with_the_answer():
    """Строка без темпа — ответ прежних правил, и перечитать её должен кто-то.

    Правило то же, что у версии читателя выписок: поднятая версия ОТВЕТА без
    поднятой версии правил означает, что починка до уже посчитанных строк не
    доедет — их никто не закажет заново.
    """
    fresh = krt_ranking.score_row(dict(SITE), dict(SCREENING))
    assert fresh["rules_version"] == krt_screening.SCREENING_RULES_VERSION
    assert krt_ranking.model_is_current(fresh) is True

    # Строка, посчитанная прежними правилами, нынешней методикой не считается —
    # значит попадёт в план пересчёта.
    stale = {**fresh, "rules_version": krt_screening.SCREENING_RULES_VERSION - 1}
    assert krt_ranking.model_is_current(stale) is False
    assert krt_ranking.model_needs_recount(stale) is True


# Состав строки и версия правил сверяются ПАРОЙ, целиком. Поодиночке ни одно из
# двух чисел ошибки не ловит: поле, добавленное без подъёма версии, доедет
# только до новых строк, а уже посчитанные останутся неполными навсегда — их
# никто не закажет заново. Ровно это и случилось 20.09.2026 с ценой окружения:
# поле завели, строки не перечитали, и колонка стояла пустой у 585 из 585.
#
# Равенство здесь и есть утверждение: правка ЛЮБОЙ половины обязана уронить
# проверку, чтобы вторая была решена, а не забыта. Добавили поле — поднимите
# версию; поле переименовали или убрали — тем более.
#
# 4 — 23.09.2026: точный потолок входа больше не публикуется при неполной
# нагрузке КРТ. Вместо него строка хранит верхнюю границу в млн ₽ и ₽/м²,
# поэтому состав вырос на два поля и версия правил поднята вместе с ним.
ROW_KEYS_AT_RULES_VERSION = (4, (
    "area_ha", "at_asking_price", "available", "card_facts", "computed_at",
    "district", "engine_version", "entry_capacity_mln", "entry_capacity_reason",
    "entry_capacity_rub_per_sqm", "entry_capacity_upper_bound_mln",
    "entry_capacity_upper_bound_rub_per_sqm", "housing_gfa_sqm", "margin_pct",
    "model_fingerprint", "name", "net_profit_mln", "okrug", "parse_problem",
    "phase_count", "press_facts", "project_llcr_x", "renovation", "requirements",
    "rules_version", "saleable_sqm", "segment", "slug", "start_price_rub_sqm",
    "status", "surrounding_price_rub_sqm", "surrounding_sales_units_per_month",
    "traffic_light", "weakest_phase_llcr_x",
))


def test_a_new_field_comes_with_a_new_rules_version():
    row = krt_ranking.score_row(dict(SITE), dict(SCREENING))
    got = (krt_screening.SCREENING_RULES_VERSION, tuple(sorted(row)))
    assert got == ROW_KEYS_AT_RULES_VERSION, (
        "состав строки и версия правил разошлись: поле, добавленное без подъёма "
        "версии, до уже посчитанных строк не доедет — их никто не перечитает. "
        f"сейчас {got[0]} и {len(got[1])} полей")

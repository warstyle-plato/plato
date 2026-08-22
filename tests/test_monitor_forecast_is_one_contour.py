"""Текущий прогноз РНВ считается один раз, а не в каждом экране по-своему.

Верхняя карточка состояния, «Платон · управленческий прогноз», сценарий
«Текущий темп» и база сравнения для задержки и ускорения отвечают на один
вопрос: когда объект будет введён при нынешнем темпе. На Гродненской верхняя и
нижняя даты расходились, и причина была не в подписи и не в округлении, а в
двух независимых реализациях одной формулы:

* при принятом объёме 100% pace-версия отвечала «готово на дату среза», а копия
  в сценарном движке — «прогноза нет»;
* pace сеял опоздания против планового финиша и отдельно добавлял утверждённый
  rebaseline, а сценарии подмешивали `forecast_finish` строки и сравнивали с
  финишем PM-задачи — то есть считали одну задержку дважды.

Здесь закреплено, что реализация одна и что три величины не путаются.

Запуск: python3 -m pytest tests/test_monitor_forecast_is_one_contour.py -q
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import developaid_monitor_forecast as forecast  # noqa: E402
import developaid_monitor_pace as pace  # noqa: E402
import developaid_monitor_scenarios as scenarios  # noqa: E402


def test_the_formula_is_declared_once():
    """Копия формулы в двух модулях — это два ответа на один вопрос."""
    assert pace._pace_finish is forecast.pace_finish
    assert scenarios._pace_finish is forecast.pace_finish
    assert scenarios._network_rnv is forecast.network_rnv
    # И сама формула живёт в общем модуле, а не переписана заново.
    source = Path("developaid_monitor_scenarios.py").read_text(encoding="utf-8")
    assert "def _pace_finish(" not in source, "вторая реализация вернулась"
    source = Path("developaid_monitor_pace.py").read_text(encoding="utf-8")
    assert "def _pace_finish(" not in source, "вторая реализация вернулась"


def test_a_finished_task_answers_the_same_to_both():
    """Та самая разница: 100% принятого объёма.

    Одна реализация отвечала «готово на дату среза», другая — «прогноза нет».
    Завершённая задача двигала сеть по-разному, и РНВ расходился.
    """
    cut = datetime.date(2026, 8, 22)
    row = {"plan_start": "2026-01-01", "plan_finish": "2026-06-01",
           "rss_accepted_ratio": 1.0}
    predicted, method = forecast.pace_finish(row, cut)
    assert predicted == cut and method == "accepted_complete"


def test_the_mixed_rss_article_never_becomes_a_date():
    """РСС 2.1 — стоимостная улика, а не календарный прогноз WBS.

    Исключение обязано действовать одинаково в обоих контурах, иначе один
    экран увидит многолетний «Подготовительный период», а другой нет.
    """
    cut = datetime.date(2026, 8, 22)
    row = {"code": "2.1", "plan_start": "2024-01-01", "plan_finish": "2024-06-01",
           "rss_accepted_ratio": 0.8, "rss_act_cost_rate_3m": 0.02}
    predicted, method = forecast.pace_finish(row, cut)
    assert predicted is None and method == "mixed_lifecycle_rss"
    built = forecast.current_seeds([{**row, "id": "2.1"}], cut)
    assert "2.1" not in built["seeds"], "смешанная статья создала pace seed"
    assert built["excluded_rss_codes"] == ["2.1"]


def test_an_approved_plan_is_not_reseeded_as_current_pace():
    """Голый `forecast_finish` — уже учтённый в PM план, а не новая задержка.

    Сценарный движок пересевал им сеть, верхняя карточка — нет: одна задержка
    считалась дважды, и нижняя дата уезжала.
    """
    cut = datetime.date(2026, 1, 15)
    plain = {"id": "1", "plan_start": "2026-01-01", "plan_finish": "2026-03-01",
             "forecast_finish": "2026-04-15"}
    assert forecast.current_seeds([plain], cut)["seeds"] == {}
    approved = {**plain, "forecast_source": "approved_rebaseline"}
    assert forecast.current_seeds([approved], cut)["seeds"] == {
        "1": datetime.date(2026, 4, 15)}


def test_the_late_task_seeds_the_network():
    """Опоздание против плана — это и есть seed текущего темпа."""
    cut = datetime.date(2026, 1, 1)
    row = {"id": "1", "plan_start": "2025-01-01", "plan_finish": "2025-06-01",
           "rss_accepted_ratio": 0.5, "rss_act_cost_rate_3m": 0.1}
    built = forecast.current_seeds([row], cut)
    assert built["seeds"]["1"] == datetime.date(2026, 6, 2)
    assert built["methods"]["1"] == "rolling_3m_acts"


def test_the_context_says_which_cut_and_snapshot_were_used():
    """Два экрана по разным срезам дают разные даты честно — и это надо видеть."""
    cut = datetime.date(2026, 8, 22)
    result = forecast.current_forecast({"schedule": {"rows": []}}, {"known": False},
                                       cut, rss_snapshot="rss-2026-08-22.xlsx")
    context = result["context"]
    assert context["cut"] == "2026-08-22"
    assert context["rss_snapshot"] == "rss-2026-08-22.xlsx"
    assert context["forecast_method"] == "current_pace_network"
    assert context["excluded_rss_codes"] == ["2.1"]
    assert context["pace_seed_count"] == 0

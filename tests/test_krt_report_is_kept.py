"""Посчитанное не выбрасывают: отчёт площадки лежит рядом с баллом.

Еженедельный прогон собирал по каждой площадке всё — маркетинг, соседей,
модель, очереди, потолок цены входа, — записывал в рейтинг одно число и
выбрасывал остальное. Человек открывал карточку и ждал те же минуты второй раз
на уже сделанной работе (владелец, 23.08.2026: «движок же уже прогнал»).

Здесь же проверяется вторая половина: вводные, которыми посчитан отчёт, едут
вместе с ним. Иначе «передать в DevelopAid» пришлось бы собирать модель заново,
и два сборщика на одну площадку однажды разошлись бы — карточка и калькулятор
показывали бы разное, оба достоверно.

Запуск: python3 -m pytest tests/test_krt_report_is_kept.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auction_search import krt_ranking  # noqa: E402
from auction_search.api import _plato_krt_prompt  # noqa: E402


PROJECT = {"slug": "nagatino", "name": "КРТ Нагатино", "okrug": "ЮАО",
           "district": "Нагатино-Садовники", "status": "Планируемый",
           "area_ha": 12.0, "housing_gfa_sqm": 215720.6}


def _screening() -> dict:
    return {
        "available": True,
        "traffic_light": {"tone": "ok", "label": "Операционный сценарий проходит"},
        "metrics": {"project_llcr_x": 1.31, "weakest_phase_llcr_x": 1.19,
                    "margin_pct": 14.8, "net_profit_mln": 17_084.9,
                    "revenue_mln": 203_114.2, "capex_mln": 158_134.4,
                    "peak_bridge_mln": 35_048.3, "peak_pf_mln": 103_994.1},
        "phasing": {"count": 3, "saleable_sqm": 140_218.4},
        "market": {"recommended_segment": "комфорт", "start_price_rub_sqm": 442_050,
                   "market_price_rub_sqm": 455_000, "price_basis": "медиана соседей"},
        "entry_capacity": {"available": True, "amount_mln": 4_180.0},
        "exclusions": ["Цена приобретения / входа принята равной нулю."],
        "model_inputs": {"inputs": {"apartment_price_th": 442.05},
                         "tep": {"apartments": {"gns": 215720.6}},
                         "phasing": {"enabled": True, "phase_count": 3}},
        "market_report": {"peers": [{"name": "Сосед", "distance_km": 1.2}],
                          "verdict": {"units_per_month": 21}},
    }


@pytest.fixture
def ranking(tmp_path) -> krt_ranking.KrtRanking:
    return krt_ranking.KrtRanking(tmp_path)


def test_a_run_keeps_the_whole_report_not_only_the_score(ranking) -> None:
    ranking.start([PROJECT], lambda project: _screening())
    ranking._thread.join(timeout=30)

    stored = ranking.report("nagatino")
    assert stored, "отчёт площадки должен пережить прогон"
    assert stored["project"]["name"] == "КРТ Нагатино"
    assert stored["screening"]["metrics"]["project_llcr_x"] == 1.31
    assert stored["market"]["peers"][0]["name"] == "Сосед", "маркетинг тоже сохраняется"


def test_the_inputs_travel_with_the_report(ranking) -> None:
    """Передавать в калькулятор надо посчитанное, а не собранное заново."""
    ranking.start([PROJECT], lambda project: _screening())
    ranking._thread.join(timeout=30)

    model = ranking.report("nagatino")["screening"]["model_inputs"]
    assert model["inputs"]["apartment_price_th"] == 442.05
    assert model["phasing"]["phase_count"] == 3


def test_a_failure_is_stored_too(ranking) -> None:
    """«Не посчитали и вот почему» — тоже ответ, и карточка обязана его знать."""
    ranking.start([PROJECT], lambda project: {"available": False, "reason": "Нет жилого объёма"})
    ranking._thread.join(timeout=30)

    stored = ranking.report("nagatino")
    assert stored["screening"]["reason"] == "Нет жилого объёма"


def test_asking_platon_does_not_restamp_the_calculation(ranking) -> None:
    """Дописать рекомендацию — не значит пересчитать: свежесть врать не должна."""
    ranking.save_report("nagatino", {"screening": _screening()}, computed_at=1_000_000)
    stored = ranking.report("nagatino")
    ranking.save_report("nagatino", {**{k: v for k, v in stored.items()
                                        if k not in {"schema_version", "slug", "computed_at"}},
                                     "plato": {"text": "смотреть дальше"}},
                        computed_at=stored["computed_at"])
    again = ranking.report("nagatino")
    assert again["computed_at"] == 1_000_000
    assert again["plato"]["text"] == "смотреть дальше"


def test_a_foreign_slug_cannot_escape_the_reports_directory(ranking) -> None:
    """Слаг приходит из адреса — значит проверяется, а не подставляется."""
    path = ranking.report_path("../../etc/passwd")
    assert path.parent == ranking.reports_dir
    with pytest.raises(ValueError):
        ranking.report_path("   ")


def test_the_question_to_platon_carries_both_sides(ranking) -> None:
    """Рекомендация, разведённая по двум ответам, не сходится сама с собой."""
    prompt = _plato_krt_prompt({"project": PROJECT, "screening": _screening(),
                                "market": _screening()["market_report"]})
    assert "МАРКЕТИНГ" in prompt and "МОДЕЛЬ DEVELOPAID" in prompt
    assert "комфорт" in prompt
    assert "1,31x" in prompt, "LLCR подаётся готовым числом, модель его не считает"
    assert "НЕ УЧТЕНО: Цена приобретения" in prompt
    assert "Не выдумывай чисел" in prompt


# --- новое в каталоге -----------------------------------------------------------

def test_the_first_ever_snapshot_marks_nobody_as_new(ranking) -> None:
    """Мы только начали смотреть: сто двадцать «новинок» разом — это не новость."""
    seen = ranking.mark_seen(["a", "b", "c"])
    assert set(seen) == {"a", "b", "c"}
    assert all(value == 0 for value in seen.values())
    assert not any(ranking.is_new(value) for value in seen.values())


def test_a_site_absent_from_the_previous_snapshot_is_new(ranking) -> None:
    import time as _time
    ranking.mark_seen(["a", "b"])
    later = _time.time() + 7 * 86400
    seen = ranking.mark_seen(["a", "b", "c"], now=later)
    assert seen["a"] == 0 and seen["b"] == 0
    assert ranking.is_new(seen["c"], now=later)
    assert not ranking.is_new(seen["a"], now=later)


def test_the_mark_expires(ranking) -> None:
    import time as _time
    ranking.mark_seen(["a"])
    later = _time.time() + 7 * 86400
    seen = ranking.mark_seen(["a", "c"], now=later)
    assert not ranking.is_new(seen["c"], now=later + 400 * 86400)


def test_a_site_that_left_and_came_back_is_news_again(ranking) -> None:
    import time as _time
    ranking.mark_seen(["a", "c"])
    gone = ranking.mark_seen(["a"], now=_time.time() + 7 * 86400)
    assert "c" not in gone, "исчезнувшая площадка забывается"
    back = _time.time() + 14 * 86400
    seen = ranking.mark_seen(["a", "c"], now=back)
    assert ranking.is_new(seen["c"], now=back)

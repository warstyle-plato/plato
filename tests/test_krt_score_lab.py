from __future__ import annotations

from auction_search.krt_score_lab import krt_score_lab_page


def test_lab_never_scores_running_krt() -> None:
    page = krt_score_lab_page()
    assert "status_kind!=='running'" in page
    assert "Площадки со статусом «В реализации» исключаются до расчёта" in page


def test_lab_reuses_current_catalogue_and_ranking() -> None:
    page = krt_score_lab_page()
    assert "fetch('/auctions/krt-lab/data?ts='" in page
    assert "/ranking/refresh" not in page
    assert "?refresh=true" not in page


def test_lab_exposes_score_components_and_coverage() -> None:
    page = krt_score_lab_page()
    for label in ("Экономика", "Рынок", "Нагрузка КРТ", "Доступность входа", "Покрытие"):
        assert label in page
    assert "entry_capacity_rub_per_sqm" in page
    assert "project_llcr_x" in page
    assert "demolition_area_sqm" in page
    assert "renovation" in page

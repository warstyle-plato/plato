from __future__ import annotations

import tep_progress_ui


def _page() -> str:
    stages = "\n".join(tep_progress_ui._REPLACEMENTS)
    return (
        "<style>" + tep_progress_ui._CSS_ANCHOR + "</style>\n"
        + tep_progress_ui._JS_ANCHOR + "\n"
        + stages
    )


def test_long_tep_run_gets_visible_real_stage_progress():
    page = tep_progress_ui._patch_page(_page())

    assert "tep-progress-card" in page
    assert "role=\"progressbar\"" in page
    assert "TEP_PROGRESS_LABELS" in page
    assert "Территория и ЕГРН" in page
    assert "Расчёт ГлавАПУ" in page
    assert "Чтение ТЭП" in page
    assert "Подготовка результата" in page
    assert "от 30 секунд до 2 минут" in page

    # Процент берётся из тех же четырёх реальных шагов, которые уже были в
    # pipeline, а не из искусственного таймера.
    for step in range(1, 5):
        assert f"setTepProgress(status,{step},4" in page
    assert "status.textContent='2 из 4" not in page


def test_progress_patch_is_idempotent():
    once = tep_progress_ui._patch_page(_page())
    assert tep_progress_ui._patch_page(once) == once

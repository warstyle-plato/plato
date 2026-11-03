"""Прочитанное о КРТ живёт на сервере и общее для всех.

«Можно прочитанные данные о КРТ хранить где-то для всех и обновлять по
требованию? сейчас всё слетает» (владелец, 02.09.2026). Публикации, прочитанные
кнопкой на карточке, лежали в памяти вкладки: перезагрузка — и находки нет ни у
кого. Поиск при этом платный, и потерянная находка — это второй счёт за тот же
ответ.

Кладём туда же, куда кладёт прогон, — в строку рейтинга: она на диске, общая, и
переживает перезагрузку и выкатку. Перечитать можно по требованию, кнопкой.

Запуск: python3 -m pytest tests/test_what_was_read_survives_a_reload.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.krt_ranking import KrtRanking  # noqa: E402


def test_the_finding_is_kept_next_to_the_score(tmp_path) -> None:
    ranking = KrtRanking(tmp_path)
    ranking.upsert_row({"slug": "site", "name": "Площадка", "score": 87,
                        "available": True, "entry_capacity_rub_per_sqm": 42000})
    ranking.remember("site", {"press_facts": {"available": True, "taken": True}})
    row = ranking.stored_row("site")
    assert row["press_facts"]["taken"] is True
    # Балл не тронут: находка дописывается полем, а не встаёт на место счёта.
    assert row["score"] == 87 and row["entry_capacity_rub_per_sqm"] == 42000


def test_a_site_without_a_row_yet_still_keeps_its_finding(tmp_path) -> None:
    ranking = KrtRanking(tmp_path)
    ranking.remember("fresh", {"press_facts": {"available": True}})
    assert ranking.stored_row("fresh")["press_facts"]["available"] is True


def test_nothing_to_remember_writes_nothing(tmp_path) -> None:
    ranking = KrtRanking(tmp_path)
    ranking.remember("", {"press_facts": {}})
    ranking.remember("site", {})
    assert ranking.rows() == []


def test_the_route_stores_and_the_page_shows_it_first() -> None:
    api = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")
    assert "krt_ranking.remember" in api, "находка кнопки нигде не сохраняется"
    page = (ROOT / "auction_search" / "ui.py").read_text(encoding="utf-8")
    assert "press_facts||null" in page, "страница не показывает сохранённое"
    assert "loadKrtPress(x,true)" in page, "перечитать по требованию нечем"
    assert "krtPressAgain" in page

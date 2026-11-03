"""Посчитанное по площадке КРТ не пропадает под чужой записью.

Правило «посчитанное не выбрасывают» было записано построчно — неудача не
встаёт на место счёта (`keep_computed`). Мимо него шли три пути, и все три
молчали:

* прогон держал снимок каталога в памяти и переписывал файл ЦЕЛИКОМ, поэтому
  пересчёт одной площадки из карточки стирался следующей же его записью;
* «идёт прогон» жило в памяти воркера, а воркеров два — кнопка, попавшая во
  второй, поднимала второй прогон, и два снимка затирали друг друга;
* смена версии схемы обнуляла рейтинг первой же записью, и на экране это
  выглядело как «модель здесь никогда не считали».
"""

import threading
import time

from auction_search.krt_ranking import KrtRanking
from market_search.http import load_json


def _row(slug: str, per_sqm: int, at: int) -> dict:
    return {"slug": slug, "name": slug, "available": True,
            "entry_capacity_rub_per_sqm": per_sqm, "computed_at": at}


def _rows_by_slug(ranking: KrtRanking) -> dict[str, dict]:
    return {str(row.get("slug")): row for row in ranking.rows()}


def test_a_card_recount_survives_the_run_that_is_going_on(tmp_path):
    ranking = KrtRanking(tmp_path)
    ranking._persist({"alpha": _row("alpha", 100, 1000)})

    # Так начинается прогон: он берёт снимок и дальше живёт им.
    snapshot = {str(row.get("slug")): row for row in ranking.rows()}

    # Пока прогон идёт, человек пересчитал соседнюю площадку из карточки.
    ranking.upsert_row(_row("beta", 200, 2000))

    # Следующая запись прогона обязана её сохранить.
    snapshot["alpha"] = _row("alpha", 111, 3000)
    ranking._persist(snapshot)

    rows = _rows_by_slug(ranking)
    assert set(rows) == {"alpha", "beta"}, "пересчёт из карточки затёрт прогоном"
    assert rows["beta"]["entry_capacity_rub_per_sqm"] == 200
    assert rows["alpha"]["entry_capacity_rub_per_sqm"] == 111


def test_a_later_count_wins_and_a_failure_still_does_not(tmp_path):
    ranking = KrtRanking(tmp_path)
    ranking._persist({"alpha": _row("alpha", 100, 3000)})

    # Запись старше той, что уже лежит, не отменяет более поздний счёт.
    ranking._persist({"alpha": _row("alpha", 999, 1000)})
    assert _rows_by_slug(ranking)["alpha"]["entry_capacity_rub_per_sqm"] == 100

    # А неудача не встаёт на место счёта ни при каком порядке.
    ranking._persist({"alpha": {"slug": "alpha", "available": False,
                                "reason": "Модель не собрана",
                                "computed_at": 9000}})
    kept = _rows_by_slug(ranking)["alpha"]
    assert kept["available"] and kept["entry_capacity_rub_per_sqm"] == 100
    assert kept["recompute_reason"] == "Модель не собрана"


def test_the_second_worker_does_not_start_a_second_run(tmp_path):
    """Воркеров два, память раздельная, а файл рейтинга общий."""
    first, second = KrtRanking(tmp_path), KrtRanking(tmp_path)
    hold, seen = threading.Event(), threading.Event()

    def screen(project):
        seen.set()
        hold.wait(5)
        return {"available": False, "reason": "не считаем"}

    assert first.start([{"slug": "alpha", "name": "alpha"}], screen) is True
    assert seen.wait(5)
    try:
        assert second.start([{"slug": "beta", "name": "beta"}], screen) is False
        # И второй воркер обязан сказать, что прогон идёт, а не молчать.
        progress = second.progress()
        assert progress["running"] is False
        assert progress["running_elsewhere"] is True
    finally:
        hold.set()
    for _ in range(50):
        if not first.progress()["running"]:
            break
        time.sleep(0.1)
    assert first.progress()["running"] is False
    # Замок отпущен — следующий прогон запускается.
    assert second.claimed() is False


def test_a_foreign_schema_is_put_aside_and_not_erased(tmp_path):
    ranking = KrtRanking(tmp_path)
    from market_search.http import save_json
    save_json(ranking.path, {"schema_version": 99, "updated_at": 1,
                             "rows": [_row("alpha", 100, 1000)]})
    assert ranking.rows() == []

    ranking._persist({"beta": _row("beta", 200, 2000)})
    assert _rows_by_slug(ranking).keys() == {"beta"}

    archived = load_json(ranking.path.parent / "ranking.v99.json")
    assert archived and archived["rows"][0]["slug"] == "alpha", \
        "посчитанное на прежней схеме стёрто без следа"


def test_a_dead_run_does_not_keep_the_button_shut(tmp_path, monkeypatch):
    """Замок брошенного прогона протухает, и отказ не превращается в неправду.

    Прогон подтверждает себя сам — трогает замок после каждой площадки.
    Перезапуск контейнера посреди прогона иначе запирал бы кнопку до конца
    срока, а на экране стояло бы «прогон уже идёт».
    """
    from auction_search import krt_ranking as module

    ranking = KrtRanking(tmp_path)
    assert ranking.claim() is True
    assert ranking.claimed() is True

    monkeypatch.setattr(module, "LOCK_TTL_SECONDS", -1)
    assert ranking.claimed() is False, "брошенный замок считается занятым"
    assert KrtRanking(tmp_path).start([], lambda project: {}) is True

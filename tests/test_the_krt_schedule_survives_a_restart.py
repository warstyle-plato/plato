"""Плановый пересчёт КРТ переживает перезапуск и называет, почему не прошёл.

Владелец, 31.10.2026: «Почему КРТ не пересчитываются по расписанию».

Полный проход по каталогу идёт часами, а выкатка перезапускает процесс
несколько раз в день. Прежде прогон жил в памяти воркера: после каждого
перезапуска начинался с первой площадки и до последней не доходил, а прогон,
оборванный исключением, в `finally` всё равно отмечался полным — и неделю
недосчитанный каталог выдавался за посчитанный. Снаружи это было не видно:
дата «оценка от …» менялась от любой открытой карточки.

Запуск: python3 -m pytest tests/test_the_krt_schedule_survives_a_restart.py -q
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from auction_search import krt_ranking  # noqa: E402

PROJECT = {"okrug": "ЮАО", "district": "Нагатино-Садовники",
           "status": "Планируемый", "area_ha": 12.0}


class ProcessKilled(BaseException):
    """Выкатка: процесс уходит посреди площадки, ни одна ветка `except` не ловит."""


def _screening() -> dict:
    return {
        "available": True,
        "traffic_light": {"tone": "ok", "label": "Проходит"},
        "metrics": {"project_llcr_x": 1.3, "margin_pct": 14.0},
        "phasing": {"count": 1, "saleable_sqm": 10_000},
        "entry_capacity": {"available": True, "amount_mln": 100},
    }


def _projects(*slugs: str) -> list[dict]:
    return [{**PROJECT, "slug": s, "name": s} for s in slugs]


def _wait(ranking: krt_ranking.KrtRanking) -> None:
    for _ in range(300):
        if not ranking.progress()["running"]:
            return
        time.sleep(0.01)
    raise AssertionError("прогон не закончился")


def test_a_run_cut_by_a_restart_is_not_counted_and_resumes(tmp_path, monkeypatch):
    # Тред, убитый «выкаткой», печатает трассировку — это и есть сценарий.
    monkeypatch.setattr("threading.excepthook", lambda args: None)
    first = krt_ranking.KrtRanking(tmp_path)
    assert first.due() is True

    def killed_on_b(project: dict) -> dict:
        if project["slug"] == "b":
            raise ProcessKilled()
        return _screening()

    assert first.claim() is True
    assert first.start(_projects("a", "b", "c"), killed_on_b,
                       scheduled=True, claimed=True) is True
    _wait(first)
    # Дошёл до «a» и умер — полным такой прогон не считается.
    assert first.due() is True, "оборванный прогон отмечен как полный"
    status = first.schedule_status()
    assert status["due"] is True and status["done"] == 1 and status["total"] == 3
    assert status["last_completed_at"] is None

    # Новый процесс продолжает с места: «a» второй раз не считается.
    seen: list[str] = []

    def screen(project: dict) -> dict:
        seen.append(project["slug"])
        return _screening()

    second = krt_ranking.KrtRanking(tmp_path)
    second.release()   # замок умершего воркера протух
    assert second.claim() is True
    assert second.start(_projects("a", "b", "c"), screen,
                        scheduled=True, claimed=True) is True
    _wait(second)
    assert seen == ["b", "c"], f"после перезапуска счёт начат заново: {seen}"
    assert second.due() is False, "дошедший до конца прогон отмечается полным"
    status = second.schedule_status()
    assert status["due"] is False
    assert status["last_completed_at"] and status["next_at"] > time.time()


def test_a_broken_run_names_its_reason_and_is_not_counted(tmp_path, monkeypatch):
    ranking = krt_ranking.KrtRanking(tmp_path)
    calls = {"n": 0}
    real = ranking._persist

    def failing_persist(rows, *, catalogue_run=False):
        calls["n"] += 1
        if rows:
            raise OSError("диск переполнен")
        return real(rows, catalogue_run=catalogue_run)

    monkeypatch.setattr(ranking, "_persist", failing_persist)
    assert ranking.start(_projects("a", "b"), lambda p: _screening(), scheduled=True) is True
    _wait(ranking)
    assert ranking.due() is True
    status = ranking.schedule_status()
    assert "диск переполнен" in status["stop_reason"]
    assert status["interrupted"] is False


def test_an_interrupted_run_is_called_so(tmp_path):
    ranking = krt_ranking.KrtRanking(tmp_path)
    ranking._schedule_begin(_projects("a", "b"))
    ranking._schedule_mark("a", False)
    status = ranking.schedule_status()
    assert status["interrupted"] is True and status["running"] is False
    assert status["done"] == 1 and status["total"] == 2


def test_a_host_that_cannot_run_says_why(tmp_path):
    ranking = krt_ranking.KrtRanking(tmp_path)
    status = ranking.schedule_status("не заданы PULSE_LOGIN и PULSE_PASSWORD")
    assert status["due"] is True
    assert status["blocked"] == "не заданы PULSE_LOGIN и PULSE_PASSWORD"
    assert status["due_since"] == int(ranking.last_scheduled_moment())


def _page_text(schedule: dict) -> str:
    import page_blocks  # noqa: PLC0415
    from auction_search import ui  # noqa: PLC0415

    page = ui.auctions_page(None)
    tail = f"console.log(JSON.stringify(krtScheduleText({json.dumps(schedule)})));"
    out = page_blocks.run_json("", tail, page=page)
    return out


@pytest.mark.parametrize("schedule, expected", [
    ({"due": False, "last_completed_at": 1793000000, "next_at": 1793600000},
     ["Последний полный пересчёт по расписанию", "Следующий"]),
    ({"due": True, "due_since": 1793000000, "next_at": 1793600000,
      "blocked": "Источник рыночных данных выключен"},
     ["не идёт", "Источник рыночных данных выключен", "ещё не было"]),
    ({"due": True, "due_since": 1793000000, "next_at": 1793600000,
      "interrupted": True, "done": 120, "total": 538, "restarts": 3},
     ["прервал перезапуск сервера", "Посчитано 120 из 538", "с того же места"]),
    ({"due": True, "due_since": 1793000000, "next_at": 1793600000,
      "stop_reason": "Прогон остановился с ошибкой: диск", "done": 5, "total": 9},
     ["остановился", "Причина: Прогон остановился с ошибкой: диск"]),
])
def test_the_page_says_when_and_why(schedule, expected):
    text = _page_text(schedule)
    for piece in expected:
        assert piece in text, (piece, text)


def test_the_rating_and_the_watch_carry_the_schedule():
    source = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")
    route = source[source.index('async def auction_krt_ranking('):]
    route = route[:route.index("\n    @app.")]
    assert '"schedule": await run_in_threadpool(' in route
    watch = source[source.index('async def auction_krt_watch('):]
    watch = watch[:watch.index("\n    @app.")]
    assert '"ranking_schedule"' in watch
    # Причину для страницы и для потока даёт одна функция.
    loop = source[source.index("def _weekly_ranking("):]
    loop = loop[:loop.index("\n    # main.py loads")]
    assert "_weekly_blocked()" in loop

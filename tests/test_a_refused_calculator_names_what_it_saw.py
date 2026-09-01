"""Отказ ГлавАПУ называет то, что увидел, а не то, чего не дождался.

Живой ответ ядра (01.09.2026): `state` «готов», а `last_error` — «калькулятор
не отдал таблицу за 90 с (строк 79)». Читается это как «таблицы нет», а на деле
таблица ПРИШЛА и в ней семьдесят девять строк: не сошлись коды, по которым
считается готовность. Какие коды пришли, знала только чужая страница — и в
сообщении их не было.

Три состояния выглядели одинаково и означают разное: таблицы нет вовсе; таблица
есть и пуста; таблица полна, но столбец с кодом сменился — тогда готовность не
наступит НИКОГДА, сколько ни ждать, и ждать девяносто секунд бессмысленно.

Правило прежнее: селектор на чужой странице живёт парой с диагностикой, и в
ошибку кладётся сама страница, а не её отсутствие.

Запуск: python3 -m pytest tests/test_a_refused_calculator_names_what_it_saw.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def _rows(count: int, coded: bool) -> list[dict[str, str]]:
    return [{"code": str(60 + i) if coded else "", "name": f"строка {i}",
             "unit": "м²", "value": "1"} for i in range(count)]


def test_a_missing_table_says_which_tables_are_there():
    message = core._glavapu_not_ready_message(
        [], [], {"calc_table": False,
                 "tables": [{"label": "", "rows": 3}, {"label": "other", "rows": 9}]})
    assert "calc table" in message and "нет" in message
    assert "other:9" in message, "не сказано, какие таблицы на странице есть"


def test_an_empty_table_is_not_a_missing_one():
    message = core._glavapu_not_ready_message([], [], {"calc_table": True})
    assert "пуста" in message


def test_a_full_table_without_codes_names_the_changed_column():
    """Самый частый случай — и раньше он выглядел как «таблицы нет»."""
    snapshot = {"calc_table": True, "widths": [5],
                "sample": [["Население", "чел.", "1 200", "—", ""]]}
    message = core._glavapu_not_ready_message(_rows(79, coded=False), [], snapshot)
    assert "79 строк" in message
    assert "столбец сменился" in message, "не названа причина, по которой ждать бесполезно"
    assert "Население" in message, "первой строки в отказе нет — смотреть нечего"


def test_a_table_with_other_codes_lists_them():
    seen = ["1", "2", "3", "61", "62"]
    message = core._glavapu_not_ready_message(_rows(79, coded=True), seen, {"calc_table": True})
    assert "нет кодов 60, 54" in message, "не сказано, каких кодов не хватило"
    assert "61" in message and "прочитаны" in message, "прочитанные коды не названы"


def test_the_refusal_carries_the_snapshot():
    error = core.GlavapuTableNotReady("что-то не так", {"url": "https://genplan.tech/calc/"})
    assert isinstance(error, TimeoutError), "отказ перестал быть таймаутом — его ловят как таймаут"
    assert error.snapshot["url"].endswith("/calc/")
    assert core.GlavapuTableNotReady("без снимка").snapshot == {}


def test_the_probe_goes_through_the_same_path_as_the_calculation():
    """Второго пути наружу не заводим: он однажды ответит иначе, чем расчёт."""
    source = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    body = source[source.index("def glavapu_probe("):]
    body = body[:body.index("\n@app.get(\"/glavapu/health\")")]
    assert "_glavapu_headless_rows(" in body, "проба ходит своим путём мимо расчёта"
    assert "sync_playwright" not in body and "browser_launch" not in body, \
        "у пробы завёлся свой браузер"
    assert "exc.snapshot" in body, "снимок страницы до человека не доезжает"
    assert "/glavapu/probe" in source


def test_the_probe_refuses_without_a_cadastral_number():
    from fastapi import HTTPException

    try:
        core.glavapu_probe(cad="  ")
    except HTTPException as exc:
        assert exc.status_code == 400 and "кадастровый" in exc.detail
    else:  # pragma: no cover - проба без номера гоняла бы браузер впустую
        raise AssertionError("проба без номера должна отказывать, а не считать")


def test_the_snapshot_asks_for_what_is_needed_to_decide():
    js = core._GLAVAPU_SNAPSHOT_JS
    for field in ("aria-label", "calc_table", "row_count", "sample", "buttons", "location.href"):
        assert field in js, f"снимок не показывает {field}"


def test_a_ready_browser_is_not_a_working_calculator():
    """«Готов» — про Chromium, а не про расчёт.

    На живом ответе ядра стояло «готов» при пустом `last_ok` и четырёх откатах
    на формулы: браузер поднимался исправно, расчёт не удавался ни разу, и
    состояние это скрывало. Тот же случай, что «пустой результат проверки — не
    чисто»: готовность запустить и удача — разные ответы.
    """
    broken = core._glavapu_state_with_history(
        {"state": "готов", "where": "ядро", "last_ok": "", "runs": 1, "fallbacks": 4})
    assert broken["state"] != "готов", "неработающая связка отвечает «готов»"
    assert "не удавался" in broken["state"]
    assert "probe" in broken["hint"], "не сказано, чем посмотреть причину"

    fresh = core._glavapu_state_with_history(
        {"state": "готов", "where": "ядро", "last_ok": "", "runs": 0, "fallbacks": 0})
    assert "ещё не было" in fresh["state"], "«не пробовали» подано как «не работает»"

    working = core._glavapu_state_with_history(
        {"state": "готов", "where": "ядро", "last_ok": "2026-09-01T10:00:00",
         "runs": 3, "fallbacks": 1})
    assert working["state"] == "готов", "удавшийся расчёт перестал считаться удачей"


def test_a_tripped_breaker_keeps_its_own_state():
    """Предохранитель — своё состояние, и переписывать его историей нельзя."""
    tripped = core._glavapu_state_with_history(
        {"state": "предохранитель", "blocked_for": 200, "last_ok": "", "runs": 0})
    assert tripped["state"] == "предохранитель"

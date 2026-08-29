"""Красный хвост объясняет, чем он вызван.

«В каждой статье монитора, где есть красный хвост, должно быть пояснение, почему
произойдёт такое смещение вправо… непонятно, когда нет никаких данных, почему
именно они смещены» (владелец, 27 и 29.08.2026).

Второе важнее первого: работа без единого акта КС всё равно уезжает вправо —
она унаследовала сдвиг по сети от предшественников. На экране это выглядело как
сдвиг ниоткуда.

Причина не считается заново: сдвиг уже разложен на свой и унаследованный, запас
посчитан, метод прогноза известен. Разбор выбирает из этих чисел и называет
причину — второй расчёт того же сдвига разошёлся бы с первым молча.

Запуск: python3 -m pytest tests/test_the_red_tail_says_why.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import developaid_monitor_reason as reason  # noqa: E402

PAGE = (ROOT / "developaid_monitor_page.py").read_text(encoding="utf-8")


def node(**kwargs):
    base = {"delta_days": 30, "pace_forecast_method": "rolling_3m_acts",
            "dependencies": {"own_delay_days": 30, "inherited_delay_days": 0,
                             "current_float_days": 4, "impact_rnv_days": 0,
                             "predecessors": []}}
    deps = kwargs.pop("dependencies", None)
    if deps:
        base["dependencies"].update(deps)
    base.update(kwargs)
    return base


def test_a_work_without_a_single_fact_still_says_where_the_shift_came_from() -> None:
    """Тот самый случай: данных нет, а работа смещена."""
    got = reason.delay_reason(node(
        pace_forecast_method="no_pace",
        dependencies={"own_delay_days": 0, "inherited_delay_days": 30,
                      "current_float_days": -5, "impact_rnv_days": 30,
                      "predecessors": [{"id": "12", "name": "Монтаж каркаса"},
                                       {"id": "13", "name": "Фасад"}]}))
    assert got["kind"] == "inherited"
    assert "унаследован" in got["text"]
    assert "Монтаж каркаса" in got["text"] and "Фасад" in got["text"]
    assert "запаса не осталось" in got["text"]
    assert "критическом пути" in got["text"], "сдвиг ввода — часть ответа"


def test_its_own_shift_names_what_the_forecast_stands_on() -> None:
    got = reason.delay_reason(node())
    assert got["kind"] == "own"
    assert "по темпу актов КС за последние три месяца" in got["text"]
    assert "свободный запас 4 дн" in got["text"]


def test_both_halves_are_named_separately() -> None:
    got = reason.delay_reason(node(
        delta_days=40,
        dependencies={"own_delay_days": 15, "inherited_delay_days": 25,
                      "predecessors": [{"name": "Свайное поле"}]}))
    assert got["kind"] == "both"
    assert "свой сдвиг 15 дн" in got["text"] and "25 дн" in got["text"]


def test_an_inherited_shift_without_a_named_predecessor_says_so() -> None:
    """Связь есть в расчёте и потеряна в показе — это находка, а не мелочь."""
    got = reason.delay_reason(node(
        dependencies={"own_delay_days": 0, "inherited_delay_days": 12,
                      "predecessors": []}))
    assert "в сети не указано" in got["text"]


def test_a_work_on_time_gets_no_explanation() -> None:
    """Объяснение сдвига там, где сдвига нет, — выдуманный сдвиг."""
    assert reason.delay_reason(node(delta_days=0)) is None
    assert reason.delay_reason(node(delta_days=-3)) is None
    assert reason.delay_reason({"delta_days": None}) is None


def test_no_network_is_not_a_reason() -> None:
    """«Сети нет» — отсутствие ответа, и выдавать его за причину нельзя."""
    got = reason.delay_reason({"delta_days": 10, "dependencies": {}})
    assert "сеть зависимостей не загружена" in got["text"]


def test_every_late_node_of_the_view_is_annotated() -> None:
    view = {"schedule": {
        "management": [{"name": "Корпус 1", "delta_days": 20,
                        "dependencies": {"own_delay_days": 20},
                        "children": [{"name": "Работа", "delta_days": 20,
                                      "dependencies": {"own_delay_days": 0,
                                                       "inherited_delay_days": 20}}]}],
        "rows": [{"id": "1", "delta_days": 5, "dependencies": {"own_delay_days": 5}}],
    }}
    reason.annotate(view)
    root = view["schedule"]["management"][0]
    assert root["delay_reason"]["kind"] == "own"
    assert root["children"][0]["delay_reason"]["kind"] == "inherited"
    assert view["schedule"]["rows"][0]["delay_reason"]["delay_days"] == 5


def test_the_reason_is_attached_where_the_screen_draws_the_shift() -> None:
    """Пояснение стоит рядом с хвостом, а не за отдельным запросом."""
    pace = (ROOT / "developaid_monitor_pace.py").read_text(encoding="utf-8")
    assert "reason.annotate(view)" in pace
    assert 'id="detailWhy"' in PAGE
    assert "Почему сдвиг +" in PAGE
    # И на самой полосе: наведение отвечает без открытия карточки.
    assert "n.delay_reason?' · '+n.delay_reason.text:''" in PAGE
    assert "от предшественников" in PAGE


def test_the_model_is_not_asked_what_the_network_already_answers() -> None:
    """«По мнению ИИ» рядом с однозначным ответом — второй ответ на один вопрос."""
    body = (ROOT / "developaid_monitor_reason.py").read_text(encoding="utf-8")
    for name in ("plato", "openai", "agent_chat", "prompt"):
        assert name not in body.lower()

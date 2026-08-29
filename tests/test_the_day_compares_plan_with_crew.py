"""Работы дня: кто должен был работать и кто вышел.

«Кто должен был работать судя по договорам и типу работ (это РСС) и кто реально
работал и в каком количестве» (владелец, 29.08.2026).

План собирается из двух источников, которые уже есть: ГПР даёт работы дня, РСС —
подрядчика за статьёй (реестры выполненных работ и платежей несут пару «код ССР
→ контрагент»). Своего справочника договоров не заводим: он стал бы вторым
мнением о том, кто за статью отвечает.

Обе стороны разрыва видны. Подрядчик, которого нет в плане, не выбрасывается:
молча потерянный читается как «его не было» — та же ошибка, что «пустой ответ
НСПД принят за отсутствие ограничений».

Запуск: python3 -m pytest tests/test_the_day_compares_plan_with_crew.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import developaid_monitor_crew as crew  # noqa: E402

PAGE = (ROOT / "developaid_monitor_page.py").read_text(encoding="utf-8")

ROWS = [
    {"code": "2.1.1", "name": "Монолит корпус 1",
     "plan_start": "2026-08-01", "plan_finish": "2026-09-30"},
    {"code": "2.1.5", "name": "Фасад корпус 1",
     "plan_start": "2026-09-01", "plan_finish": "2026-12-01"},
]
REGISTER = {"rows": [
    {"estimate_code": "2.1.1", "contractor": "НУР ООО"},
    {"estimate_code": "2.1.5", "contractor": "ООО «Альтитьюд»"},
]}


def day(report=None, when="2026-08-15", rows=None, by_code=None):
    return crew.crew_day(ROWS if rows is None else rows,
                         crew.contractors_by_code(REGISTER) if by_code is None else by_code,
                         report, when)


def report(contractors, works=()):
    return {"parsed": {"contractors": list(contractors), "works": list(works)}}


def test_the_plan_of_the_day_comes_from_the_schedule_and_the_registers() -> None:
    got = day(report([{"name": "Нур", "itr": 3, "workers": 54}]))
    assert [item["code"] for item in got["planned"]] == ["2.1.1"], \
        "фасад в этот день ещё не начат"
    assert got["expected"] == ["НУР ООО"]


def test_the_name_in_the_report_is_matched_to_the_name_in_the_register() -> None:
    """«Нур» в отчёте и «НУР ООО» в реестре — один подрядчик."""
    got = day(report([{"name": "Нур", "itr": 3, "workers": 54}],
                     [{"contractor": "Нур", "line": "бетонирование 3 этаж"}]))
    assert len(got["matched"]) == 1
    assert got["matched"][0]["workers"] == 54
    assert got["matched"][0]["lines"] == ["бетонирование 3 этаж"]
    assert got["missing"] == [] and got["extra"] == []
    assert got["people"] == {"itr": 3, "workers": 54, "contractors": 1}


def test_who_did_not_come_is_named_with_his_articles() -> None:
    got = day(report([{"name": "Базис", "itr": 1, "workers": 8}]))
    assert [item["name"] for item in got["missing"]] == ["НУР ООО"]
    assert got["missing"][0]["codes"] == ["2.1.1"]
    # И тот, кого в плане нет, тоже назван: молча потерянный читается как
    # «его не было».
    assert [item["name"] for item in got["extra"]] == ["Базис"]
    assert got["extra"][0]["workers"] == 8


def test_a_short_name_does_not_match_by_letters() -> None:
    """«Нур» внутри «Стройэнергонур» — совпадение по букве, а не по лицу."""
    assert crew.same_party("НУР ООО", "Нур")
    assert crew.same_party("СК Термоформ ООО", "Термоформ")
    assert not crew.same_party("ООО", "ООО Базис"), "форма собственности не имя"
    assert not crew.same_party("Ай", "Айсберг"), "два знака не имя"


def test_the_form_of_ownership_is_not_the_name() -> None:
    assert crew.name_key("ООО «НУР»") == crew.name_key("нур ооо")
    assert crew.name_key("СЗ Гродненская 18") == crew.name_key("Гродненская 18")


def test_each_missing_source_says_which_one() -> None:
    """Пустая сверка и несобранная выглядят одинаково, а значат разное."""
    assert any("ГПР" in note for note in day(report([]), rows=[])["notes"])
    assert any("код статьи" in note for note in day(report([]), by_code={})["notes"])
    assert any("отчёта за этот день нет" in note for note in day(None)["notes"])
    quiet = day(report([]))
    assert any("нет численности" in note for note in quiet["notes"])


def test_names_that_never_match_are_called_out() -> None:
    got = day(report([{"name": "Подрядчик без имени в реестре", "itr": 1, "workers": 5}]))
    assert any("ни одно имя" in note for note in got["notes"]) or got["missing"]


def test_a_bar_of_the_day_opens_its_history() -> None:
    assert 'class="daybar" data-day=' in PAGE
    assert "showCrew(b.dataset.day)" in PAGE
    body = PAGE[PAGE.index("async function showCrew("):]
    body = body[: body.index("\n}\n")]
    assert "'/monitor/crew?'" in body
    for column in ("Вышли по плану", "Должны были, но не вышли", "Вышли вне плана"):
        assert column in body
    # Экран не считает: план приходит с сервера собранным.
    assert "plan_start" not in body and "estimate_code" not in body


def test_the_route_is_registered() -> None:
    import main_legacy

    assert "/monitor/crew" in {getattr(route, "path", "") for route in main_legacy.app.routes}

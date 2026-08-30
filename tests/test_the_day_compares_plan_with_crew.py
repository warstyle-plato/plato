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


SUBS = {crew.name_key("СП Менеджмент ООО"): ["НУР ООО", "СТАЛКО ИПЛ ООО", "КЛОДО ООО"]}


def test_the_crew_of_the_planned_contractor_is_not_off_plan() -> None:
    """«Они точно все вне плана? Странно» (владелец, 30.08.2026).

    Не все. В реестрах РСС у статьи стоит ГЕНПОДРЯДЧИК — с ним договор, — а на
    площадку выходят его субподрядчики, и в реестрах РСС их нет вовсе. Пока
    связь «кто чей» не читалась, сверка выдавала «никто из плановых не отмечен»
    и всю бригаду записывала «вне плана»: девять подрядчиков из девяти.

    Связь берётся из реестра гарантийных удержаний — его ведёт генподрядчик, и
    в нём его договоры. Своего справочника договоров не заводим.
    """
    got = crew.crew_day(
        [{"code": "2.2.2.1", "name": "Монолит",
          "plan_start": "2026-08-01", "plan_finish": "2026-12-01"}],
        crew.contractors_by_code({"rows": [
            {"estimate_code": "2.2.2.1", "contractor": "ООО СП Менеджмент"}]}),
        report([{"name": "НУР", "itr": 11, "workers": 54},
                {"name": "Сталко", "itr": 2, "workers": 31}]),
        "2026-08-29", SUBS)
    assert [item["name"] for item in got["matched"]] == ["НУР", "Сталко"]
    assert all(item["via"] == "ООО СП Менеджмент" for item in got["matched"])
    assert got["missing"] == [] and got["extra"] == []


def test_a_party_named_in_the_works_without_a_headcount_is_not_absent() -> None:
    """«Моэк (теплосети) — монтаж ограждения» в отчёте есть, а сколько человек —
    нет. Это «работы отмечены, людей не назвали», а не «не вышли»."""
    got = crew.crew_day(
        [{"code": "2.4.3", "name": "Теплосети",
          "plan_start": "2026-08-01", "plan_finish": "2026-12-01"}],
        crew.contractors_by_code({"rows": [
            {"estimate_code": "2.4.3", "contractor": "ПАО МОЭК"}]}),
        report([{"name": "НУР", "itr": 11, "workers": 54}],
               [{"contractor": "НУР", "line": "Моэк ( теплосети)- монтаж ограждения"}]),
        "2026-08-29", SUBS)
    named = next(item for item in got["matched"] if item["name"] == "ПАО МОЭК")
    assert named["headcount_unknown"] is True
    assert named["workers"] == 0 and named["lines"]
    assert got["missing"] == []


def test_a_short_name_is_not_hunted_inside_the_works_text() -> None:
    """«СП» нашлось бы в любом «спуске» и превратило сверку в шум."""
    assert crew._named_in("ПАО МОЭК", "Моэк ( теплосети)- монтаж") is True
    assert crew._named_in("СП", "спуск в подвал") is False


def test_nothing_matched_says_why_it_could_not() -> None:
    got = crew.crew_day(
        [{"code": "2.2.2.1", "name": "Монолит",
          "plan_start": "2026-08-01", "plan_finish": "2026-12-01"}],
        crew.contractors_by_code({"rows": [
            {"estimate_code": "2.2.2.1", "contractor": "ООО СП Менеджмент"}]}),
        report([{"name": "НУР", "itr": 11, "workers": 54}]),
        "2026-08-29", None)
    assert not got["matched"] and got["extra"]
    assert any("генподрядчик" in note for note in got["notes"])


def test_the_route_passes_the_relation() -> None:
    body = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    route = body[body.index("def monitor_crew("):]
    route = route[: route.index("\n@app.")]
    assert "crew.subcontractors(" in route and "latest_retention(project)" in route
    assert "субподрядчик" in PAGE, "на экране видно, чьей бригадой вышли"


def test_the_line_belongs_to_the_party_named_in_it() -> None:
    """«Что такое Клодо кладка и потом другие подрядчики? Бред какой-то»
    (владелец, 30.08.2026).

    Разбор вёл строки за последним заголовком-подрядчиком, а в отчёте имя
    следующего стоит В САМОЙ строке: «Клодо( кладка): Сталко — сборка лесов»
    читалось как работа Клодо. Так под одним именем оказались работы шести
    подрядчиков.
    """
    import developaid_monitor_daily as daily

    text = "\n".join([
        "1. НУР ООО Итр- 11 чел. Рабочие - 54 чел.",
        "2. Клодо ( кладка) Итр 2 чел. рабочих 10",
        "3. Сталко Итр 2 рабочих 31",
        "По работам:",
        "Клодо( кладка):",
        "Устройство стен из пеноблока",
        "Корпус 3 - 6,7,8,9",
        "Сталко -сборка лесов и монтаж люлек на Корпусе 1и2.",
        "Бетонирование ПП - 68,5 м3 24 эт.(1,2зах)",
    ])
    works = {item["line"]: item["contractor"]
             for item in daily.parse_daily_report(text)["works"]}
    assert works["Сталко -сборка лесов и монтаж люлек на Корпусе 1и2."] == "Сталко", \
        "имя в строке сильнее заголовка"
    assert works["Устройство стен из пеноблока"] == "Клодо( кладка)", \
        "заголовок работает там, где имени в строке нет"
    # И приставка без имени подрядчика заголовок не перебивает: иначе
    # «Бетонирование ПП» стало бы подрядчиком.
    assert works["Бетонирование ПП - 68,5 м3 24 эт.(1,2зах)"] == "Клодо( кладка)"
    assert works["Корпус 3 - 6,7,8,9"] == "Клодо( кладка)"


def test_a_name_known_only_to_the_registers_still_claims_its_line() -> None:
    """МОЭК людей в этот день не выводил, поэтому в численности отчёта его нет —
    а работа его названа, и строка обязана достаться ему."""
    import developaid_monitor_daily as daily

    works = daily.parse_daily_report(
        "По работам:\nКлодо( кладка):\nМоэк ( теплосети)- монтаж ограждения")["works"]
    assert works[0]["contractor"] == "Клодо( кладка)", "своими силами разбор его не знает"
    fixed = daily.attribute_works(works, ["ПАО МОЭК"])
    assert fixed[0]["contractor"] == "ПАО МОЭК" and fixed[0]["named_inline"] is True


def test_the_summary_route_hands_over_the_known_names() -> None:
    body = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    assert "known=_monitor_known_parties(project)" in body
    helper = body[body.index("def _monitor_known_parties("):]
    helper = helper[: helper.index("\n@app.")]
    assert "read_completed_works" in helper and "latest_retention" in helper

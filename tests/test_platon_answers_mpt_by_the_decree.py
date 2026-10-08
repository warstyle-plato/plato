"""Платон отвечает о льготе МПТ по 1874-ПП, а не «в выжимках нет».

Вопрос владельца 06.10.2026: офисы строятся взамен 177 000 м² существующих,
новых — 167 000 м². Будет ли льгота, и правда ли она только по вновь
создаваемым рабочим местам? Платон ответил «методики нет в выжимках» и велел
держать льготу нулевой: ни калькулятора МПТ, ни текста 1874-ПП у него не было.

Здесь проверяется то, во что ходит сам Платон: его инструмент, его поиск по
записям и формула калькулятора, у которой существующая площадь теперь есть.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main as wrapper  # noqa: E402
import mpt_calculator as mpt  # noqa: E402
import project_knowledge as knowledge  # noqa: E402

core = wrapper.core
TODAY = date(2026, 10, 6)


def _office(area: float, existing: float, mode: str) -> mpt.MptResult:
    return mpt.calculate_mpt_benefit(mpt.MptInput(
        category="office", district="Нагатино-Садовники", ttk_position="outside",
        area_sqm=area, existing_area_sqm=existing, mode=mode,  # type: ignore[arg-type]
        kzatr_quarter="2026-Q4",
    ), today=TODAY)


def test_reconstruction_to_a_smaller_area_gives_no_benefit() -> None:
    """п. 1.14.1: при реконструкции Sмпт — прирост; 167 000 после 177 000 — его нет."""
    got = _office(167_000, 177_000, "reconstruction")
    assert got.area_increment_sqm == -10_000
    assert got.eligible_area_sqm == 0
    assert got.benefit_rub == 0
    assert any("прирост" in b.lower() and "1.14.1" in b for b in got.blockers)


def test_reconstruction_counts_only_the_increment() -> None:
    got = _office(190_000, 177_000, "reconstruction")
    assert got.eligible_area_sqm == 13_000
    assert got.benefit_rub == pytest.approx(1000 * 13_000 * mpt.KZATR_DEFAULT * 0.7)


def test_without_existing_area_reconstruction_keeps_the_old_meaning() -> None:
    """Сохранённый расчёт без новой графы: площадь — уже прирост, как раньше."""
    got = _office(13_000, 0, "reconstruction")
    assert got.eligible_area_sqm == 13_000
    assert not got.blockers


def test_new_construction_does_not_net_demolished_area_but_says_so() -> None:
    """Снос и новое строительство — строительство (ГрК РФ, ст. 1, п. 13).

    Вычти калькулятор сносимые площади молча, льгота стала бы нулём без
    основания в формуле; промолчи он о них — владелец не узнал бы о ветке
    «реконструкция», которую выбирает город.
    """
    got = _office(167_000, 177_000, "new")
    assert got.eligible_area_sqm == 167_000
    assert got.benefit_rub == pytest.approx(1000 * 167_000 * mpt.KZATR_DEFAULT * 0.7)
    note = " ".join(got.warnings)
    assert "ст. 1, п. 13" in note
    assert "-10 000" in note and "льготы не будет" in note


def test_platon_answers_the_owners_question_through_his_own_tool() -> None:
    answer = core._execute_agent_tool("calculate_mpt_benefit", {
        "category": "office", "district": "Нагатино-Садовники",
        "ttk_position": "outside", "mode": "new", "area_sqm": 167_000,
        "existing_area_sqm": 177_000, "cadastral_number": None,
        "sqm_per_workplace": 10,
    }, None, {})
    assert answer["available"] is True
    assert answer["result"]["eligible_area_sqm"] == 167_000
    assert answer["result"]["benefit_rub"] > 0
    # Ветка «реконструкция» стоит рядом: выбирает между ними город.
    assert answer["if_reconstruction"]["benefit_rub"] == 0
    # Рабочие места — справка по плотности пользователя, не норма акта.
    places = answer["workplaces_estimate"]
    assert (places["existing"], places["planned"], places["delta"]) == (17_700, 16_700, -1_000)
    assert "не устанавливает" in places["basis"]
    # Ответ опирается на акт и называет прочитанную редакцию.
    assert "вновь создаваемым" in answer["workplaces_rule"]
    assert "п. 1.14.1" in answer["existing_area_rule"]
    assert "2072-ПП" in answer["edition_read"]
    assert "выжимк" not in str(answer)


def test_no_workplace_estimate_without_a_density_from_the_user() -> None:
    answer = mpt.agent_answer(
        category="office", district="Нагатино-Садовники", ttk_position="outside",
        mode="new", area_sqm=167_000, existing_area_sqm=177_000, today=TODAY)
    assert "workplaces_estimate" not in answer


def test_the_tool_is_offered_and_the_prompt_sends_mpt_questions_to_it() -> None:
    names = {tool.get("name") for tool in core._AGENT_TOOLS}
    assert "calculate_mpt_benefit" in names
    assert "→ calculate_mpt_benefit" in core._AGENT_INSTRUCTIONS


@pytest.mark.parametrize("question, heading", [
    ("Будет ли льгота МПТ, если строим офисы взамен существующих сносимых",
     "существующие и сносимые площади"),
    ("Льгота МПТ только по вновь создаваемым рабочим местам", "рабочие места"),
])
def test_the_decree_excerpt_answers_the_owners_words(question: str, heading: str) -> None:
    found = knowledge.search(question, source="normative")
    titles = [entry["title"] for entry in found["entries"]]
    assert any("moscow_mpt_1874pp" in t and heading in t for t in titles[:2]), titles


def test_the_page_sends_the_existing_area_to_the_calculator() -> None:
    import main_registry
    client = TestClient(main_registry.app, raise_server_exceptions=False)
    response = client.post("/api/mpt/calculate", json={
        "category": "office", "district": "Нагатино-Садовники",
        "ttk_position": "outside", "mode": "reconstruction",
        "area_sqm": 167_000, "existing_area_sqm": 177_000,
    })
    assert response.status_code == 200, response.text
    assert response.json()["benefit_rub"] == 0
    assert response.json()["area_increment_sqm"] == -10_000
    from mpt_extension import _MPT_FRAGMENT
    assert 'id="mpt-existing"' in _MPT_FRAGMENT
    assert "existing_area_sqm:" in _MPT_FRAGMENT


def test_the_page_and_the_api_take_kterm_again() -> None:
    """Ксрок есть в п. 1.14.1 (ред. 24.04.2026); прежде API отказывал полю."""
    import main_registry
    client = TestClient(main_registry.app, raise_server_exceptions=False)
    base = {"category": "office", "district": "Нагатино-Садовники",
            "ttk_position": "outside", "area_sqm": 10_000}
    plain = client.post("/api/mpt/calculate", json=base).json()
    early = client.post("/api/mpt/calculate", json={**base, "kterm": 1.1})
    assert early.status_code == 200, early.text
    assert early.json()["benefit_rub"] == pytest.approx(plain["benefit_rub"] * 1.1)
    from mpt_extension import _MPT_FRAGMENT
    assert 'id="mpt-kterm"' in _MPT_FRAGMENT


def test_the_workplaces_answer_rests_on_the_text_not_on_silence() -> None:
    assert "не встречается ни разу" in mpt.WORKPLACES_RULE
    assert "1.3.15" in mpt.EXISTING_AREA_RULE
    assert "24.04.2026" in mpt.EDITION_READ

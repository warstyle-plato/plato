"""Воронка обращений: верх, которого в своде не было вовсе.

Свод продаж начинался с подписанного договора, то есть с конца. Обращения
объясняют остальное: девять из десяти — звонки с конверсией в бронь около трёх
процентов, тогда как агентские каналы дают тридцать шесть.

«Эти данные надо дать Платону к выводам» (владелец, 26.08.2026) — поэтому
воронка идёт и в вывод под блоком, и в вопрос Платону.
"""
from __future__ import annotations

from pathlib import Path

from market_search import contracting, demand

CABINET = Path(__file__).resolve().parent.parent / "market_search" / "cabinet.py"


def _deals(rows: list[dict]) -> list[dict]:
    base = {"source": "Звонок", "manager": "Иванов", "booked": False,
            "need_asked": False, "next_step": False, "not_a_lead": False,
            "area_min": None, "budget_max": None, "wants": []}
    return [{**base, **row} for row in rows]


def test_a_non_lead_call_is_out_of_the_denominator() -> None:
    """Реклама и предложения услуг — не обращение, и доля по ним врёт."""
    got = demand.funnel(_deals([
        {"not_a_lead": True}, {"booked": True}, {},
    ]))
    assert got["quality"]["calls"] == 3
    assert got["quality"]["not_a_lead"] == 1
    assert got["quality"]["target"] == 2
    assert got["quality"]["booked_target"] == 0.5


def test_the_card_is_measured_not_the_call() -> None:
    """Комментарий — пересказ BitrixGPT, и это сказано вслух."""
    got = demand.funnel([])
    assert any("пересказ BitrixGPT" in note for note in got["notes"])
    assert any("перезвонить не с чем" in note for note in got["notes"])


def test_what_the_funnel_cannot_do_is_said() -> None:
    """Связи с договором нет, денег у обращения нет — обещать их нельзя."""
    got = demand.funnel([])
    assert any("ни номера договора" in note for note in got["notes"])
    assert any("сколько выручки" in note for note in got["notes"])
    assert any("ещё рано" in note for note in got["notes"])


def test_the_share_travels_with_its_count() -> None:
    """На пяти бронях доля не значит ничего, и число обращений рядом."""
    got = demand.funnel(_deals([{"source": "Сайт"}, {"source": "Сайт", "booked": True}]))
    row = next(x for x in got["by_source"] if x["name"] == "Сайт")
    assert row["deals"] == 2 and row["booked"] == 1 and row["share"] == 0.5


def test_the_conclusion_calls_the_gap_a_neighbourhood_not_a_cause() -> None:
    """Менеджер мог расспрашивать тех, кто и так был готов."""
    deals = _deals(
        [{"need_asked": True, "booked": True}] * 3
        + [{"need_asked": True}] * 7
        + [{}] * 40)
    summary = {"demand": {"funnel": demand.funnel(deals)}, "total": {}, "dynamics": []}
    line = contracting.conclusions(summary)["funnel"]
    assert "не доказанная причина" in line
    assert "не осталось ни потребности" in line


def test_the_funnel_goes_into_the_question() -> None:
    page = CABINET.read_text()
    body = page[page.index("function salesDigest("):page.index("async function askPlatoSales(")]
    assert "ВОРОНКА:" in body and "ИСТОЧНИК ${x.name}" in body
    assert "МЕНЕДЖЕР ${x.name}" in body


def test_a_block_without_a_conclusion_says_what_is_missing() -> None:
    """Пустое место под блоком и отсутствующий вывод выглядят одинаково."""
    page = CABINET.read_text()
    assert "const NOTE_NEEDS=" in page
    body = page[page.index("function salesNote("):page.index("\n}", page.index("function salesNote("))]
    assert "Вывод не сложился" in body
    for key in ("pool", "bands", "demand", "funnel", "escrow", "fm", "bank"):
        assert f"{key}:" in page[page.index("const NOTE_NEEDS="):page.index("function salesNote(")], key

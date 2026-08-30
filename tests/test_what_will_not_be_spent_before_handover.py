"""Что не будет израсходовано до ввода — и о чём можно просить банк.

«Потребность в отдельных статьях уже не будет израсходована, если заключён
договор по этой статье и он в рамках лимита, но с учётом ГУ этот лимит никогда
не будет использован полностью до РнВ, а значит можно попросить банк
перераспределить остаток в другую главу» (владелец, 30.08.2026).

Сшивка здесь непрямая, и проверяется именно она. Номером договора ГУ со статьёй
не свяжешь: в РСС стоит договор с генподрядчиком, а реестр ГУ ведёт он сам, и
в нём его договоры с субподрядчиками — этих номеров в РСС нет вовсе («в РСС
нет, ты прав; там генподрядчик СП Менеджмент, но его ГУ примерно равны ГУ по
его договорам с субчиками»). Значит связь идёт через лицо, и полученное число —
оценка, а не выписка.
"""
from __future__ import annotations

from pathlib import Path

import developaid_monitor_unspent as unspent_mod

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "developaid_monitor_page.py").read_text(encoding="utf-8")

ESTIMATE = {"rows": [
    {"code": "2", "article": "Глава 2", "estimate": 100.0, "contracted": 90.0},
    {"code": "2.1", "article": "Сети", "estimate": 60.0, "contracted": 50.0},
    {"code": "2.2", "article": "Снос", "estimate": 40.0, "contracted": 40.0},
    {"code": "3.1", "article": "СМР", "estimate": 900.0, "contracted": 900.0},
]}
CONTRACTS = {"rows": [
    {"contractor": "СП Менеджмент ООО", "estimate_code": "3.1", "amount": 900.0},
    {"contractor": "Мостеплосеть", "estimate_code": "2.1", "amount": 50.0},
]}


def _register(rows):
    return {"rows": rows}


def test_the_free_part_is_the_limit_minus_what_is_contracted() -> None:
    """Свободное считается точно и без всяких сшивок — прямо из РСС."""
    got = unspent_mod.unspent(ESTIMATE, horizon="2027-06-30")
    by_code = {item["code"]: item for item in got["articles"]}
    assert by_code["2.1"]["free"] == 10.0
    assert "2.2" not in by_code, "статья выбрана договорами целиком — показывать нечего"
    assert got["free_total"] == 10.0


def test_a_chapter_is_not_counted_together_with_its_own_articles() -> None:
    """Строки РСС идут деревом: сумма по всем кодам считает главу дважды."""
    got = unspent_mod.unspent(ESTIMATE, horizon="2027-06-30")
    assert "2" not in {item["code"] for item in got["articles"]}
    # Глава 2 сама по себе дала бы ещё 10 сверх статьи 2.1 — тех же денег.
    assert got["free_total"] == 10.0


def test_the_retention_of_a_general_contractor_lands_on_his_article() -> None:
    """Сшивка по лицу, а не по номеру договора: СПМ и есть СП Менеджмент."""
    register = _register([
        {"customer": "СПМ", "counterparty": "Нур", "left": 40.0, "due": "2031-01-01"},
        {"customer": "СПМ", "counterparty": "Сталко", "left": 30.0, "due": "2031-01-01"},
    ])
    got = unspent_mod.unspent(ESTIMATE, contracts=CONTRACTS, retention=register,
                              horizon="2027-06-30")
    by_code = {item["code"]: item for item in got["articles"]}
    assert by_code["3.1"]["retention_deferred"] == 70.0
    assert got["retention_deferred_total"] == 70.0
    # И это названо оценкой: выписки из договора с генподрядчиком у нас нет.
    assert got["retention_is_estimate"] is True


def test_a_party_standing_on_several_articles_is_not_split_by_shares() -> None:
    """Разложить ГУ долями значит выдать выдуманное число за посчитанное."""
    contracts = {"rows": CONTRACTS["rows"] + [
        {"contractor": "СП Менеджмент ООО", "estimate_code": "2.1", "amount": 10.0}]}
    register = _register([
        {"customer": "СП Менеджмент", "counterparty": "Нур", "left": 40.0,
         "due": "2031-01-01"}])
    got = unspent_mod.unspent(ESTIMATE, contracts=contracts, retention=register,
                              horizon="2027-06-30")
    assert got["retention_deferred_total"] == 0.0
    unsplit = got["retention"]["unsplit"]
    assert len(unsplit) == 1 and unsplit[0]["left"] == 40.0
    assert sorted(unsplit[0]["codes"]) == ["2.1", "3.1"]


def test_a_party_missing_from_the_estimate_is_named_not_dropped() -> None:
    """Молча потерянная строка читается как её отсутствие."""
    register = _register([
        {"customer": "Чужой подрядчик", "counterparty": "Кто-то", "left": 5.0,
         "due": "2031-01-01"}])
    got = unspent_mod.unspent(ESTIMATE, contracts=CONTRACTS, retention=register,
                              horizon="2027-06-30")
    assert got["retention"]["unmatched_total"] == 5.0
    assert got["retention"]["unmatched"][0]["name"] == "Чужой подрядчик"


def test_retention_without_a_due_date_is_not_called_deferred() -> None:
    """«Срок не назван» — не «после ввода»: в перераспределение не идёт."""
    register = _register([
        {"customer": "СПМ", "counterparty": "Клодо", "left": 2.0, "due": ""},
        {"customer": "СПМ", "counterparty": "Нур", "left": 8.0, "due": "2026-01-01"},
    ])
    got = unspent_mod.unspent(ESTIMATE, contracts=CONTRACTS, retention=register,
                              horizon="2027-06-30")
    assert got["retention"]["undated"] == 2.0
    # Выплаченное до горизонта — тоже не отложенное: оно уйдёт в стройке.
    assert got["retention"]["paid_before_horizon"] == 8.0
    assert got["retention_deferred_total"] == 0.0


def test_without_a_horizon_nothing_is_deferred_and_the_reason_is_named() -> None:
    register = _register([
        {"customer": "СПМ", "counterparty": "Нур", "left": 40.0, "due": "2031-01-01"}])
    got = unspent_mod.unspent(ESTIMATE, contracts=CONTRACTS, retention=register)
    assert got["retention_deferred_total"] == 0.0
    assert "горизонт" in got["retention"]["reason"]


def test_the_module_does_not_recount_limits_or_deficit() -> None:
    """Лимиты, потребность и дефицит считает дашборд — второго счёта нет."""
    source = (ROOT / "developaid_monitor_unspent.py").read_text(encoding="utf-8")
    for word in ("remaining_need", "additional_financing", "reserve"):
        assert word not in source, f"модуль трогает {word} — это счёт дашборда"


def test_the_screen_folds_the_detail_and_shows_the_answer() -> None:
    """Наверху ответ, остальное под раскрытием.

    «Повторно и суматошно слишком много индикаторов, плашек стало» (владелец,
    30.08.2026): четыре блока и тринадцать строк, часть чисел дважды под
    разными именами.
    """
    body = PAGE[PAGE.index("function fundingStructure("):]
    body = body[: body.index("\n return html;")]
    top = body[: body.index("<details")]
    assert "Надо достроить по утверждённой модели" in top
    assert "Есть: остаток лимитов + резерв" in top
    assert "row('ДЕФИЦИТ'" in top
    # Наверху только ответ: контуры, справочные строки и ГУ уехали внутрь.
    for hidden in ("Общая сметная стоимость глав 2–3", "Резерв 2.8/2.9",
                   "Гарантийные удержания", "Средства на завершение"):
        assert hidden not in top, f"«{hidden}» осталась в верхнем блоке"
        assert hidden in body, f"«{hidden}» пропала совсем, а не свернулась"
    assert body.count("<details") >= 1
    assert "unspentTable(f.unspent)" in body


def test_the_battery_block_no_longer_repeats_the_structure() -> None:
    """Резерв, дефицит и остаток лимита стояли и в батареях, и в структуре."""
    block = PAGE[PAGE.index("$('fundingCompare').innerHTML="):]
    block = block[: block.index("\n")]
    for gone in ("Остаток лимита банка на срез", "Резерв 2.8/2.9",
                 "Исчерпание резерва по программе РСС", "Дефицит по РСС"):
        assert gone not in block, f"«{gone}» повторяется рядом со структурой"


def test_the_table_shows_where_to_ask_and_says_it_is_an_estimate() -> None:
    body = PAGE[PAGE.index("function unspentTable("):]
    body = body[: body.index("\n return html;\n}")]
    assert "Не будет выбрано" in body
    assert "оценка" in body, "разложенные по статьям ГУ выданы за измеренные"
    assert "Куда просить" in body, "вторая половина ответа — статьи с нехваткой"
    assert "долями не делим" in body
    # Экран не считает: числа приходят готовыми.
    for arithmetic in ("*", "/"):
        assert f"a.limit{arithmetic}" not in body

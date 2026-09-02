"""Что не будет израсходовано до ввода — и о чём можно просить банк.

«Потребность в отдельных статьях уже не будет израсходована, если заключён
договор по этой статье и он в рамках лимита, но с учётом ГУ этот лимит никогда
не будет использован полностью до РнВ, а значит можно попросить банк
перераспределить остаток в другую главу» (владелец, 30.08.2026).

Источник перераспределения — не всякий свободный лимит. «Перераспределение
лимитов внутри банковской РСС можно рассматривать только там, где работы
завершены или завершатся судя по актированию, договор заключён и очевидно
нового скорее всего не будет» (владелец, 01.09.2026). Первая версия называла
«не будет выбрано» всё свободное подряд, и первыми стояли резервы 2.8/2.9
(«Резервы разве не будут выбраны???»).

Сшивка ГУ здесь непрямая, и проверяется именно она. Номером договора ГУ со статьёй
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
    {"code": "2", "article": "Глава 2", "estimate": 1100.0, "contracted": 1040.0, "completed": 990.0},
    # Договор есть, акты закрыли 96% — новых трат не будет: источник.
    {"code": "2.1", "article": "Сети", "estimate": 60.0, "contracted": 50.0, "completed": 48.0},
    # Выбрано договорами целиком — свободного нет.
    {"code": "2.2", "article": "Снос", "estimate": 40.0, "contracted": 40.0, "completed": 40.0},
    # Договора нет вовсе: свободный лимит есть, но он ещё будет законтрактован.
    {"code": "2.3", "article": "Благоустройство", "estimate": 50.0, "contracted": 0.0, "completed": 0.0},
    # Договор в работе — акты закрыли 30%: не источник, пока идёт.
    {"code": "2.4", "article": "Отделка", "estimate": 50.0, "contracted": 40.0, "completed": 12.0},
    # Резерв — не статья: договоров у него нет по построению.
    {"code": "2.8", "article": "Резерв на непредвиденные", "estimate": 100.0, "contracted": 0.0, "completed": 0.0},
    {"code": "3.1", "article": "СМР генподряд", "estimate": 900.0, "contracted": 900.0, "completed": 900.0},
    # Глава 3, договор есть, свободно 5 — источник наравне с главой 2.
    {"code": "3.2", "article": "Прочие", "estimate": 25.0, "contracted": 20.0, "completed": 19.0},
]}
CONTRACTS = {"rows": [
    {"contractor": "СП Менеджмент ООО", "estimate_code": "2.4", "amount": 40.0},
    {"contractor": "Мостеплосеть", "estimate_code": "2.1", "amount": 50.0},
    {"contractor": "Юрбюро", "estimate_code": "3.2", "amount": 20.0},
]}


def _register(rows):
    return {"rows": rows}


def _codes(items):
    return {item["code"]: item for item in items}


def test_a_closed_contract_with_free_limit_is_a_source() -> None:
    """Свободное считается точно и без всяких сшивок — прямо из РСС."""
    got = unspent_mod.unspent(ESTIMATE, horizon="2027-06-30")
    src = _codes(got["sources"])
    assert src["2.1"]["free"] == 10.0
    assert "принято по актам 96%" in src["2.1"]["basis"]
    assert "2.2" not in src, "статья выбрана договорами целиком — показывать нечего"


def test_the_reserve_is_not_an_article_and_not_a_source() -> None:
    """«Резервы разве не будут выбраны???» — резерв гасит нехватку других."""
    got = unspent_mod.unspent(ESTIMATE, horizon="2027-06-30")
    codes = set(_codes(got["sources"])) | set(_codes(got["excluded"]))
    assert "2.8" not in codes


def test_an_article_without_a_contract_is_named_but_not_a_source() -> None:
    """Договора нет — новые договоры ещё придут; лимит не источник, но виден."""
    got = unspent_mod.unspent(ESTIMATE, horizon="2027-06-30")
    assert "2.3" not in _codes(got["sources"])
    skipped = _codes(got["excluded"])["2.3"]
    assert skipped["free"] == 50.0
    assert "договора нет" in skipped["reason"]
    assert got["excluded_free_total"] >= 50.0


def test_a_contract_in_progress_is_not_a_source_until_the_acts_close_it() -> None:
    got = unspent_mod.unspent(ESTIMATE, horizon="2027-06-30")
    assert "2.4" not in _codes(got["sources"])
    assert "в работе: принято по актам 30%" in _codes(got["excluded"])["2.4"]["reason"]


def test_a_programme_that_plans_more_than_the_contracts_leave_means_new_spending() -> None:
    """Третья часть признака — «нового не будет» — проверяется программой РСС.

    Реклама с договорами, принятыми на 91%, по актам выглядит закрытой, а
    тратится до конца продаж: программа после среза планирует больше, чем
    осталось выплатить по договорам, — значит новые договоры придут.
    """
    # 2.1: заключено 50, оплачено 0 → остаток по договорам 50; программа 80 > 50.
    got = unspent_mod.unspent(ESTIMATE, horizon="2027-06-30", programme_left={"2.1": 80.0})
    assert "2.1" not in _codes(got["sources"])
    reason = _codes(got["excluded"])["2.1"]["reason"]
    assert "новые траты ожидаются" in reason and "больше остатка по договорам" in reason
    # Программа в пределах остатка договоров — источник, и это сказано в основании.
    again = unspent_mod.unspent(ESTIMATE, horizon="2027-06-30", programme_left={"2.1": 40.0})
    assert "новых трат нет" in _codes(again["sources"])["2.1"]["basis"]
    # Программа не прочитана — судим по актам, и это тоже сказано.
    blind = unspent_mod.unspent(ESTIMATE, horizon="2027-06-30")
    assert "не прочитана" in _codes(blind["sources"])["2.1"]["basis"]
    # Тихая программа при незакрытом договоре источником не делает: договор
    # ещё в работе, и свободный лимит его ждёт.
    quiet = unspent_mod.unspent(ESTIMATE, horizon="2027-06-30", programme_left={"2.4": 0.0})
    assert "2.4" not in _codes(quiet["sources"])


def test_chapter_three_is_a_source_like_chapter_two() -> None:
    """Лимиты считаются по главам 2–3, как и остаток банка, — иначе главы
    расходятся на экране (владелец, 01.09.2026: «Это точно 2 глава?»)."""
    got = unspent_mod.unspent(ESTIMATE, horizon="2027-06-30")
    assert _codes(got["sources"])["3.2"]["free"] == 5.0


def test_a_chapter_is_not_counted_together_with_its_own_articles() -> None:
    """Строки РСС идут деревом: сумма по всем кодам считает главу дважды."""
    got = unspent_mod.unspent(ESTIMATE, horizon="2027-06-30")
    codes = set(_codes(got["sources"])) | set(_codes(got["excluded"]))
    assert "2" not in codes and "3" not in codes
    assert got["free_total"] == 15.0  # 2.1 → 10, 3.2 → 5


def test_the_retention_of_a_general_contractor_lands_on_his_article() -> None:
    """Сшивка по лицу, а не по номеру договора: СПМ и есть СП Менеджмент.

    Договор СПМ ещё в работе — свободный лимит источником не идёт, а удержанное
    по актам до ввода не выплатится в любом случае: источником идёт оно одно.
    """
    register = _register([
        {"customer": "СПМ", "counterparty": "Нур", "left": 4.0, "due": "2031-01-01"},
        {"customer": "СПМ", "counterparty": "Сталко", "left": 3.0, "due": "2031-01-01"},
    ])
    got = unspent_mod.unspent(ESTIMATE, contracts=CONTRACTS, retention=register,
                              horizon="2027-06-30")
    item = _codes(got["sources"])["2.4"]
    assert item["retention_deferred"] == 7.0
    assert item["free"] == 0.0 and item["free_in_work"] == 10.0
    assert item["unspent"] == 7.0
    assert got["retention_deferred_total"] == 7.0
    # И это названо оценкой: выписки из договора с генподрядчиком у нас нет.
    assert got["retention_is_estimate"] is True


def test_retention_belongs_to_chapter_two_only() -> None:
    """«ГУ имеют отношение только к главе 2» (владелец, 01.09.2026)."""
    register = _register([
        {"customer": "Юрбюро", "counterparty": "Кто-то", "left": 3.0, "due": "2031-01-01"}])
    got = unspent_mod.unspent(ESTIMATE, contracts=CONTRACTS, retention=register,
                              horizon="2027-06-30")
    assert _codes(got["sources"])["3.2"]["retention_deferred"] == 0.0
    # Подрядчик главы 3 для ГУ — чужой, и это сказано, а не проглочено.
    assert got["retention"]["unmatched_total"] == 3.0


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
    assert sorted(unsplit[0]["codes"]) == ["2.1", "2.4"]


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


def test_the_shortage_side_repeats_the_waterfall_and_sums_to_the_structural_deficit() -> None:
    """«Куда просить» обязано коррелировать со структурным дефицитом выше
    (владелец, 01.09.2026) — это те же строки водопада, и итог тот же."""
    needy = [
        {"code": "2.4", "name": "Отделка", "need_total": 90.0, "opening_limit": 38.0,
         "own_take": 38.0, "reserve_take": 20.0, "unfunded_take": 32.0,
         "first_reserve_month": "2026-10-01"},
        {"code": "2.5", "name": "Фасады", "need_total": 30.0, "opening_limit": 10.0,
         "own_take": 10.0, "reserve_take": 12.0, "unfunded_take": 8.0,
         "first_reserve_month": "2026-11-01"},
    ]
    got = unspent_mod.unspent(ESTIMATE, horizon="2027-06-30", needy=needy)
    assert [row["code"] for row in got["needy"]] == ["2.4", "2.5"]
    assert got["needy"][0] == {"code": "2.4", "name": "Отделка", "need": 90.0,
                               "own_limit": 38.0, "from_reserve": 20.0,
                               "shortage": 32.0, "from": "2026-10-01"}
    assert got["shortage_total"] == 40.0
    # Источников 15 на нехватку 40 — не хватает, и это сказано, а не выведено.
    assert got["covers"] is False


def test_chapter_three_limit_is_not_a_source_for_chapter_two() -> None:
    """«3 глава не доступна для 2 главы увы» (владелец, 02.09.2026).

    Источники главы 3 (3.2 — 5) рядом с нехваткой главы 2 обещали бы
    перераспределение, которого банк не даст: ответ считается по главам.
    """
    needy = [{"code": "2.4", "name": "Отделка", "need_total": 90.0, "opening_limit": 38.0,
              "own_take": 38.0, "reserve_take": 20.0, "unfunded_take": 4.0,
              "first_reserve_month": "2026-10-01"}]
    got = unspent_mod.unspent(ESTIMATE, horizon="2027-06-30", needy=needy)
    by = {b["chapter"]: b for b in got["by_chapter"]}
    # Глава 2: нехватка 4, источник 2.1 → 10 — хватает внутри главы.
    assert by["2"]["shortage"] == 4.0 and by["2"]["sources"] == 10.0 and by["2"]["covers"] is True
    # Глава 3: источники есть, нехватки нет — вердикта нет, а не «хватает».
    assert by["3"]["sources"] == 5.0 and by["3"]["covers"] is None
    # Нехватка главы 2 больше её источников — главой 3 не закрывается, хотя
    # общая сумма источников (15) больше нехватки (12).
    needy[0]["unfunded_take"] = 12.0
    again = unspent_mod.unspent(ESTIMATE, horizon="2027-06-30", needy=needy)
    assert again["total"] == 15.0 and again["shortage_total"] == 12.0
    assert again["covers"] is False
    assert {b["chapter"]: b["covers"] for b in again["by_chapter"]}["2"] is False
    for item in again["sources"]:
        assert item["chapter"] == item["code"].split(".")[0]
    assert got["criterion"].startswith("договор заключён, по актам принято")


def test_the_module_does_not_recount_limits_or_deficit() -> None:
    """Лимиты, потребность и дефицит считает дашборд — второго счёта нет."""
    source = (ROOT / "developaid_monitor_unspent.py").read_text(encoding="utf-8")
    for word in ("remaining_need", "additional_financing", "_waterfall", "monthly_need"):
        assert word not in source, f"модуль трогает {word} — это счёт дашборда"
    # Нехватка берётся из строк водопада как есть, а не пересчитывается.
    assert 'float(row.get("unfunded_take")' in source


def test_the_screen_opens_the_detail_and_shows_the_answer() -> None:
    """Наверху ответ; подробности — раскрыты, а не спрятаны мелким шрифтом.

    «Два важных раздела мелким шрифтом свёрнуты» (владелец, 01.09.2026).
    """
    body = PAGE[PAGE.index("function fundingStructure("):]
    body = body[: body.index("\n return html;")]
    top = body[: body.index("<details")]
    assert "Надо достроить по утверждённой модели" in top
    assert "Есть: остаток лимитов + резерв" in top
    assert "row('ДЕФИЦИТ'" in top
    for hidden in ("Общая сметная стоимость глав 2–3", "Резерв 2.8/2.9",
                   "Гарантийные удержания", "Средства на завершение"):
        assert hidden not in top, f"«{hidden}» осталась в верхнем блоке"
        assert hidden in body, f"«{hidden}» пропала совсем, а не свернулась"
    assert '<details class="fundmore" open>' in body, "подробности снова свёрнуты"
    assert "unspentTable(f.unspent,structural)" in body
    table = PAGE[PAGE.index("function unspentTable("):]
    table = table[: table.index("\n return html;\n}")]
    assert '<details class="fundmore" open>' in table
    css = PAGE[PAGE.index(".fundmore>summary{"):]
    css = css[: css.index("}")]
    assert "font-size:10px" not in css, "заголовок раскрытия снова мелкий"


def test_the_battery_block_no_longer_repeats_the_structure() -> None:
    """Резерв, дефицит и остаток лимита стояли и в батареях, и в структуре."""
    block = PAGE[PAGE.index("$('fundingCompare').innerHTML="):]
    block = block[: block.index("\n")]
    for gone in ("Остаток лимита банка на срез", "Резерв 2.8/2.9",
                 "Исчерпание резерва по программе РСС", "Дефицит по РСС"):
        assert gone not in block, f"«{gone}» повторяется рядом со структурой"


def test_the_table_shows_both_halves_and_says_what_is_an_estimate() -> None:
    """Кому не хватает — таблицей с итогом, равным структурному дефициту;
    откуда просить — таблицей с признаком и основанием у каждой строки."""
    body = PAGE[PAGE.index("function unspentTable("):]
    body = body[: body.index("\n return html;\n}")]
    assert "Кому не хватает своего лимита" in body
    assert "Откуда просить" in body
    assert "Не покрыто" in body and "структурный дефицит" in body
    assert "u.shortage_total" in body and "u.criterion" in body
    assert "a.basis" in body, "основание источника не показано"
    assert "оценка" in body, "разложенные по статьям ГУ выданы за измеренные"
    assert "долями не делим" in body
    assert "Резерв 2.8/2.9 источником не считается" in body
    # Перераспределение — внутри главы: источники сгруппированы по главам, и
    # вердикт у каждой главы свой.
    assert "u.by_chapter" in body and "лимит главы 3 для главы 2 недоступен" in body
    assert "между главами лимит не переносится" in body
    assert "Лимит других глав сюда не переносится" in body
    # Снятые статьи названы с причиной, а не выброшены.
    assert "a.reason" in body and "источником не считаем" in body
    # Расхождение с дефицитом выше — ошибка счёта, и так и сказано.
    assert "не сходится со структурным дефицитом" in body
    # Экран не считает: числа приходят готовыми.
    for arithmetic in ("*", "/"):
        assert f"a.limit{arithmetic}" not in body
        assert f"n.need{arithmetic}" not in body


def test_the_battery_measures_against_the_model_not_the_bank_column() -> None:
    """Картинке верят быстрее, чем строке, — и она обязана мерить то же.

    Заряд считался от `remaining_need`, то есть от банковской колонки
    «Средства на завершение»: на Кутузов Сити 1,46 из 1,66 — 88% и
    «хватает до конца» при дефиците 2,2 млрд ₽. Три строки структуры
    говорили одно, батарея под ними — обратное. «Может, батареи нагляднее
    как раз?» (владелец, 30.08.2026) — нагляднее, поэтому и врали громче.
    """
    block = PAGE[PAGE.index("$('fundingCompare').innerHTML=(needAll==null"):]
    block = block[: block.index("\n}")]
    assert "надо по модели" in block
    assert "remaining_need" not in block, "заряд снова меряет банковской колонкой"
    assert "Остаток потребности по утверждённому бюджету" not in block
    assert "сказать нечем" in block
    setup = PAGE[PAGE.index("const fuel=(Number(f.bank_remaining)"):]
    setup = setup[: setup.index("\n")]
    assert "needAll=hasBook?Math.max(0,Number(remainingBudget)||0):null" in setup

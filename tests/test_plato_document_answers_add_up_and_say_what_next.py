"""Ответы по документу складываются, суммы читаются в своих единицах, а в конце
человек видит, что изменилось в модели и что делать дальше.

Владелец 22.10.2026 (прод, панель Платона, «2026-10 Светлый 4 - проект ЖК.pdf»):
«ответил на вопросы по разбору Платона тизера, а что дальше то?». На экране:
«Платёж 2,55 млрд руб. за SPV… — В цену сделки — 2,55 → в модели: Цена
сделки», три обязательства «в социальную нагрузку» (165, 500, 100) и больше
ничего. Что было не так:

* «2,55» вписано в поле с подписью «млн ₽» под вопросом про «2,55 млрд» — в
  модель легло 2,55 млн ₽ вместо 2 550, а «49% оплачено, остаток 51% в феврале
  2028» в график платежей покупки не попало вовсе;
* три обязательства писали одно поле по очереди — осталось последнее, 100;
* итог не говорил ни чисел, ни пересчёта, ни следующего шага.

Следом (тот же тизер): льгота МПТ 2,57 млрд не легла никуда — поля для неё у
разбора не было; «жилой комплекс – 82 840 м2» легло в квартиры, и коммерция
встала сверху; офисы записались в выключенный объект и в расчёт не попали.

Запуск: python3 -m pytest tests/test_plato_document_answers_add_up_and_say_what_next.py -q
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import document_intake  # noqa: E402
import main as wrapper  # noqa: E402

core = wrapper.core
PORT = 18291

SPV = ("Платёж 2,55 млрд руб. за SPV с городом (49% оплачено, остаток 51% в феврале "
       "2028) — отнести в цену сделки или в социальную нагрузку?")
TWO_WAYS = ["В цену сделки (purchase_price_mln)",
            "В социальную нагрузку (social_compensation_mln)"]
OBLIGATIONS = [
    "Обязательство построить постройку коммунально-складской базы ГБУ «Жилищник» "
    "1 500 м² и перебазирование — куда отнести?",
    "Финансирование строительства дороги от ул. Константина Царева до Светлого "
    "проезда по инфраструктурному договору — куда отнести?",
    "Благоустройство территории между МЦК и МЦД «Стрешнево» — куда отнести?",
]
EXTRACTION = {
    "fields": [
        {"key": "apartments_gns_sqm", "value": "82 840", "unit": "м2",
         "quote": "жилой комплекс – 82 840 м2"},
        {"key": "offices_gba_sqm", "value": "26 300", "unit": "м2",
         "quote": "бизнес-центр – 26 300 м2"},
        {"key": "vri_relief_mln", "value": "2,57", "unit": "млрд руб.",
         "quote": "Льгота МПТ – 2,57 млрд руб. – покрытие ВРИ на 65%"},
    ],
    "questions": [{"key": "", "question": SPV, "options": TWO_WAYS}]
    + [{"key": "", "question": q, "options": TWO_WAYS} for q in OBLIGATIONS],
    "notes": [],
}


def _card(question: str) -> dict:
    return document_intake.question_card({"key": "", "question": question,
                                          "options": TWO_WAYS})


# --- единицы и график -------------------------------------------------------

def test_the_obligation_takes_the_sum_from_its_question_in_millions() -> None:
    card = _card(SPV)
    option = card["options"][0]
    assert option["target"] == "purchase_price_mln"
    assert option["value"] == 2550.0, "2,55 млрд — это 2 550 млн ₽"


def test_a_bare_typed_number_equal_to_the_question_is_read_in_its_unit() -> None:
    got = document_intake.answer_card(_card(SPV), {"project_start": "2027-01-01"}, {},
                                      choice=0, typed="2,55", ledger={})
    price = got["applied"][0]
    assert price["now"] == 2550.0, price
    assert "2,55 млрд" in price["read_as"]


def test_the_paid_and_remaining_shares_become_the_purchase_schedule() -> None:
    got = document_intake.answer_card(_card(SPV), {"project_start": "2027-01-01"}, {},
                                      choice=0, ledger={})
    assert got["inputs"]["purchase_schedule"] == "1249.5@0; 1300.5@13"
    items, is_percent, warnings = core.parse_month_schedule(got["inputs"]["purchase_schedule"])
    assert items == [(1249.5, 0), (1300.5, 13)] and not is_percent and not warnings


# --- сложение и «прибавить или заменить» ------------------------------------

def _parse(monkeypatch) -> dict:
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    monkeypatch.setattr(core, "usage_track", lambda *_a, **_k: None)
    monkeypatch.setattr(document_intake, "extract_text",
                        lambda _data, name: {"text": "Тизер. Светлый 4.", "pages": 5,
                                             "filename": name})
    monkeypatch.setattr(core, "plato_answer",
                        lambda *_a: {"answer": json.dumps(EXTRACTION, ensure_ascii=False)})
    return core.agent_document(core.AgentDocumentRequest(
        filename="Светлый 4.pdf", content_b64=base64.b64encode(b"%PDF stub").decode()), None)


def _answer(queue: dict, index: int, inputs: dict, **kw) -> dict:
    return core.agent_document_answer(core.AgentDocumentAnswerRequest(
        intake_id=queue["id"], index=index, inputs=inputs, tep={}, **kw))


def test_three_obligations_into_social_load_add_up(monkeypatch) -> None:
    queue = _parse(monkeypatch)["queue"]
    inputs = {"project_start": "2027-01-01", "social_compensation_mln": 0}
    inputs = _answer(queue, 0, inputs, choice=0)["inputs"]
    for index, typed in ((1, "165"), (2, "500"), (3, "100")):
        got = _answer(queue, index, inputs, choice=1, value=typed)
        inputs = got["inputs"]
    assert inputs["social_compensation_mln"] == 765.0, "последний ответ затёр прежние"
    row = got["applied"][0]
    assert [part["value"] for part in row["parts"]] == [165.0, 500.0, 100.0]
    assert inputs["purchase_price_mln"] == 2550.0
    changes = got["queue"]["answers"][-1]["changes"]
    assert changes and changes[0]["was"] == 665.0 and changes[0]["now"] == 765.0


def test_a_field_with_its_own_number_asks_add_or_replace(monkeypatch) -> None:
    queue = _parse(monkeypatch)["queue"]
    _answer(queue, 0, {}, action="skip")
    inputs = {"social_compensation_mln": 1200,
              "_field_origin": {"inputs.social_compensation_mln":
                                {"source": "manual", "text": "вписано вручную"}}}
    asked = _answer(queue, 1, inputs, choice=1, value="165")
    assert asked["confirm"]["current"] == 1200 and asked["confirm"]["origin"] == "вписано вручную"
    assert not asked["applied"] and asked["queue"]["index"] == 1, "вопрос закрылся без решения"

    added = _answer(queue, 1, inputs, choice=1, value="165", mode="add")
    assert added["inputs"]["social_compensation_mln"] == 1365.0
    more = _answer(queue, 2, added["inputs"], choice=1, value="500")
    assert more["inputs"]["social_compensation_mln"] == 1865.0, "второе слагаемое спросило снова"


def test_replace_drops_the_old_number() -> None:
    card = _card(OBLIGATIONS[0])
    got = document_intake.answer_card(card, {"social_compensation_mln": 1200}, {},
                                      choice=1, typed="165", ledger={}, mode="replace")
    assert got["inputs"]["social_compensation_mln"] == 165.0


# --- льгота, дом целиком, офисы ---------------------------------------------

def test_the_mpt_relief_is_read_but_not_ticked() -> None:
    got = document_intake.parse_intake(json.dumps(EXTRACTION, ensure_ascii=False))
    relief = next(f for f in got["fields"] if f["key"] == "vri_relief_mln")
    assert relief["checked"] is False and "1874-ПП" in relief["hint"]
    applied = document_intake.apply_intake(got, {"vri_relief_mode": "none"}, {},
                                           accept=["vri_relief_mln"])
    assert applied["inputs"]["vri_relief_mln"] == 2570.0
    assert applied["inputs"]["vri_relief_mode"] == "amount"


def test_the_whole_house_is_split_not_put_into_apartments() -> None:
    got = document_intake.parse_intake(json.dumps(EXTRACTION, ensure_ascii=False))
    keys = [f["key"] for f in got["fields"]]
    assert "residential_spp_sqm" in keys and "apartments_gns_sqm" not in keys
    tep = {"apartments": {"gns": 1}, "ground_commercial": {"gns": 9664}}
    applied = document_intake.apply_intake(got, {}, tep, accept=["residential_spp_sqm"],
                                           spp_split=core.MKD_SPP_SPLIT)
    house = applied["tep"]["apartments"]["gns"] + applied["tep"]["ground_commercial"]["gns"]
    assert round(house, 1) == 82840.0, "квартиры с коммерцией больше дома из документа"
    assert applied["tep"]["apartments"]["gns"] == 77869.6


def test_offices_from_the_document_switch_the_object_on() -> None:
    got = document_intake.apply_intake(
        EXTRACTION, {"offices_enabled": False, "offices_saleable_sqm": 6000}, {},
        accept=["offices_gba_sqm"])
    assert got["inputs"]["offices_gba_sqm"] == 26300.0
    assert got["inputs"]["offices_enabled"] is True, "площадь легла в выключенный объект"
    assert got["inputs"]["offices_saleable_sqm"] == 0


# --- страница: итог после последнего вопроса --------------------------------

def test_on_the_page_the_summary_says_what_changed_and_what_next(monkeypatch) -> None:
    browser.chromium_or_skip()
    from playwright.sync_api import sync_playwright

    _parse(monkeypatch)  # заглушки модели и доступа
    with sync_playwright() as pw:
        chrome = pw.chromium.launch(executable_path=str(browser.chromium_or_skip()))
        page = chrome.new_page(viewport={"width": 390, "height": 844})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        with browser.serve(wrapper.app, PORT) as root:
            page.goto(root + "/", wait_until="domcontentloaded")
            browser.wait_for_result(page)
            price_before = page.evaluate("() => inputs.purchase_price_mln")
            page.evaluate("() => toggleAgent(true)")
            page.set_input_files("#aiFile", files=[{"name": "Светлый 4.pdf",
                                                    "mimeType": "application/pdf",
                                                    "buffer": b"%PDF-1.4 stub"}])
            page.wait_for_function("() => !aiBusy && aiIntake !== null", timeout=15_000)
            table = page.evaluate(
                "() => [...document.querySelectorAll('.ai-intake-pick')].map("
                "el => [el.dataset.key, el.checked, el.closest('tr').innerText])")

            def last_card():
                return page.locator(".ai-question").last

            last_card().get_by_role("button", name=TWO_WAYS[0]).click()
            for n, typed in ((2, "165"), (3, "500"), (4, "100")):
                page.wait_for_function(
                    f"() => !aiBusy && document.querySelectorAll('.ai-question').length==={n}",
                    timeout=15_000)
                last_card().locator(".ai-question-value").fill(typed)
                last_card().get_by_role("button", name=TWO_WAYS[1]).click()
            page.wait_for_selector(".ai-intake-summary", timeout=15_000)
            page.wait_for_function(
                "() => /Модель пересчитана|не пересчиталась/.test("
                "document.querySelector('.ai-intake-summary').innerText)", timeout=60_000)
            summary = page.evaluate(
                "() => document.querySelector('.ai-intake-summary').innerText"
            ).replace("\u00a0", " ")
            buttons = page.evaluate(
                "() => [...document.querySelectorAll('.ai-intake-summary button')]"
                ".map(b => b.innerText)")
            model = page.evaluate(
                "() => [inputs.purchase_price_mln, inputs.social_compensation_mln,"
                " inputs.purchase_schedule]")

            page.locator(".ai-intake-summary").get_by_role(
                "button", name="Применить к расчёту").click()
            page.wait_for_function(
                "() => document.querySelectorAll('.ai-intake-recalc').length === 2"
                " && /Модель пересчитана|не пересчиталась/.test("
                "[...document.querySelectorAll('.ai-intake-recalc')].pop().innerText)",
                timeout=60_000)
            table_applied = page.evaluate(
                "() => [inputs.offices_enabled, inputs.offices_gba_sqm,"
                " tep.apartments.gns + tep.ground_commercial.gns,"
                " inputs.vri_relief_mode, [...document.querySelectorAll('.ai-intake-recalc')]"
                ".pop().innerText]")

            page.locator(".ai-intake-summary").get_by_role(
                "button", name="Отменить изменения документа").click()
            page.wait_for_function("() => /отменены/.test(aiMessages.innerText)",
                                   timeout=30_000)
            undone = page.evaluate(
                "() => [inputs.purchase_price_mln, inputs.social_compensation_mln]")
        chrome.close()

    assert not errors, errors
    relief = next(row for row in table if row[0] == "vri_relief_mln")
    assert relief[1] is False, "льгота из документа отмечена сама"
    assert "Льгота по плате за смену ВРИ" in relief[2], "в таблице ключ вместо подписи"
    assert next(row for row in table if row[0] == "offices_gba_sqm")[1] is True

    assert model[0] == 2550.0 and model[1] == 765.0, model
    assert model[2] == "1249.5@0; 1300.5@13", model
    assert "Что изменилось в модели" in summary
    assert "2 550" in summary, "цены сделки в итоге нет в миллионах"
    assert "765" in summary and "165 + 500 + 100" in summary, summary
    assert "Модель пересчитана" in summary, summary
    assert "до документа" in summary.lower() and "LLCR" in summary
    assert "Ещё не применено из таблицы разбора" in summary
    pending = summary.split("Ещё не применено из таблицы разбора")[1].split("\n")[0]
    assert "Льгота" not in pending, "неотмеченная льгота попала под «Применить к расчёту»"
    assert "Не отмечено в таблице разбора" in summary and "1874-ПП" in summary
    assert {"Применить к расчёту", "Открыть результат", "Проверить вводные",
            "Отменить изменения документа"} <= set(buttons), buttons
    assert undone == [price_before, 0], undone
    offices_on, offices, house, relief_mode, recalc = table_applied
    assert offices_on is True and offices == 26300.0, table_applied
    assert round(house, 1) == 82840.0, "квартиры с коммерцией не равны дому из документа"
    assert relief_mode != "amount", "неотмеченная льгота легла в модель"
    assert "Модель пересчитана" in recalc, recalc

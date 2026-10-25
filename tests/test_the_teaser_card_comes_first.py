"""Тизер: сначала карточка, потом вопросы, расчёт — только кнопкой.

Владелец 25.10.2026: бот на сайте и в Telegram разбирал тизер так, что всё шло
сразу — таблица разбора и первый вопрос приходили вместе, каждый ответ тут же
писался в модель и пересчитывал её, а числа таблицы без отдельной кнопки до
движка не доходили вовсе («Светлый 4»: дом 82 840 м² и офисы 26 300 м²
остались за бортом, расчёт шёл по умолчанию 130 717 м² квартир). Непонятно
было, что ушло в движок.

Теперь путь в три шага, одинаковый на сайте и в боте (`teaser_card.py`):
1. карточка — найдено (со страницей), уйдёт в расчёт (поле и значение с
   происхождением), не хватает (что возьмётся по умолчанию или по норме);
   вопросов нет, модель не меняется;
2. вопросы — только о недостающем, по одному; ответ меняет карточку;
3. «Всё верно, считать» — и движок получает ровно строки карточки.

Запуск: python3 -m pytest tests/test_the_teaser_card_comes_first.py -q
"""

from __future__ import annotations

import base64
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from browser import chromium_or_skip, wait_for_result  # noqa: E402

import document_intake  # noqa: E402
import main as wrapper  # noqa: E402
import teaser_card  # noqa: E402

core = wrapper.core
PORT = 18293
NUMBER = "77:08:0010008:1049"
TEXT = ("[стр. 1]\nСветлый 4. Инвестиционный тизер\n\n"
        "[стр. 2]\nТЭП: жилой комплекс – 82 840 м2\nофисы – 26 300 м2\n\n"
        f"[стр. 3]\nЛьгота МПТ – 2,57 млрд руб.\nКН {NUMBER}")
EXTRACTION = {
    "fields": [
        {"key": "cadastral_numbers", "value": [NUMBER], "unit": "список", "quote": f"КН {NUMBER}"},
        {"key": "residential_spp_sqm", "value": "82 840", "unit": "м2",
         "quote": "жилой комплекс – 82 840 м2"},
        {"key": "offices_gba_sqm", "value": "26 300", "unit": "м2", "quote": "офисы – 26 300 м2"},
        {"key": "vri_relief_mln", "value": "2,57", "unit": "млрд руб.",
         "quote": "Льгота МПТ – 2,57 млрд руб."},
    ],
    "questions": [
        {"key": "", "question": "Платёж 2,55 млрд руб. за SPV — куда отнести?",
         "options": ["В цену сделки — платится на входе", "В соцнагрузку — идёт своей датой"]},
        # Тизер номер участка назвал — вопрос о нём снимается.
        {"key": "cadastral_numbers", "question": "Какой кадастровый номер участка?", "options": []},
        {"key": "resettlement_cost_mln", "question": "Требуется ли расселение?",
         "options": ["Расселение не требуется — 0", "Требуется"]},
    ],
    "notes": [],
}


def _stub(monkeypatch) -> None:
    monkeypatch.setattr(core, "_require_web_access", lambda *_a, **_k: None)
    monkeypatch.setattr(core, "usage_track", lambda *_a, **_k: None)
    monkeypatch.setattr(document_intake, "extract_text",
                        lambda _data, name: {"text": TEXT, "pages": 3, "filename": name})
    monkeypatch.setattr(core, "plato_answer",
                        lambda *_a: {"answer": json.dumps(EXTRACTION, ensure_ascii=False)})


def _parse(monkeypatch) -> dict:
    _stub(monkeypatch)
    return core.agent_document(core.AgentDocumentRequest(
        filename="svetly4.pdf", content_b64=base64.b64encode(b"%PDF").decode(),
        inputs=dict(core.DEFAULT_INPUTS), tep=core.TEP_DEFAULT), None)


def _answer(card: dict, **kw) -> dict:
    return core.agent_document_answer(core.AgentDocumentAnswerRequest(
        intake_id=card["id"], inputs=dict(core.DEFAULT_INPUTS), tep=core.TEP_DEFAULT, **kw))


# --- карточка: один сборщик, страница у каждого числа -------------------------

def test_the_page_is_read_from_the_text_not_guessed() -> None:
    assert teaser_card.quote_page(TEXT, "офисы – 26 300 м2") == 2
    assert teaser_card.quote_page(TEXT, f"КН {NUMBER}") == 3
    # Цитаты нет в тексте — страницы нет, а не первая попавшаяся.
    assert teaser_card.quote_page(TEXT, "торговый центр 5 000 м2") is None
    row = teaser_card.locate_pages([{"key": "x", "quote": "нет такого", "page": 7}], TEXT)[0]
    assert row["page"] == 7 and row["page_checked"] is False
    assert "по словам разбора" in teaser_card.page_text(row)


def test_the_first_step_is_a_card_without_questions_and_without_changes(monkeypatch) -> None:
    got = _parse(monkeypatch)
    card = got["card"]
    assert "queue" not in got, "первый шаг не должен открывать вопрос"
    found = {row["key"]: row for row in card["found"]}
    assert found["offices_gba_sqm"]["page_text"] == "стр. 2"
    assert found["cadastral_numbers"]["page_text"] == "стр. 3"
    assert "Спрошу" in found["vri_relief_mln"]["status"]
    engine = {row["path"]: row for row in card["to_engine"]}
    split = core.MKD_SPP_SPLIT["apartments"]
    assert engine["tep.apartments.gns"]["value"] == round(82_840 * split, 2)
    assert engine["inputs.offices_gba_sqm"]["value"] == 26_300
    assert engine["inputs.offices_enabled"]["value"] is True
    assert "стр. 2" in engine["inputs.offices_gba_sqm"]["origin"]
    # Льгота — заявление продавца: в расчёт только ответом.
    assert "inputs.vri_relief_mln" not in engine
    missing = {row["key"]: row for row in card["missing"]}
    assert missing["purchase_price_mln"]["origin"] == "По умолчанию модели DevelopAid."
    assert missing["resettlement_cost_mln"]["how"] == "ask"
    assert missing["retail_gba_sqm"]["how"] == "absent"
    assert missing["project_class"]["how"] == "ask"
    q = card["questions"]
    # Вопрос о номере участка снят: на него ответил тизер.
    assert q["total"] == 4 and q["index"] == 0
    assert "Какой кадастровый номер участка?" in card["answered_by_document"]


def test_answers_change_the_card_not_the_model(monkeypatch) -> None:
    card = _parse(monkeypatch)["card"]
    first = _answer(card, index=0, choice=0)
    assert first["applied"][0]["key"] == "purchase_price_mln"
    assert "inputs" not in first, "ответ не должен отдавать вводные для записи в модель"
    _answer(card, index=1, choice=0)
    _answer(card, index=2, choice=1)  # взять льготу тизера
    last = _answer(card, index=3, choice=1)  # класс «Бизнес»
    final = last["card"]
    assert final["ready"] is True
    engine = {row["path"]: row["value"] for row in final["to_engine"]}
    assert engine["inputs.purchase_price_mln"] == 2550.0
    assert engine["inputs.resettlement_cost_mln"] == 0.0
    assert engine["inputs.vri_relief_mln"] == 2570.0
    assert engine["inputs.vri_relief_mode"] == "amount"
    assert engine["inputs.project_class"] == "business"
    assert engine["inputs.apartment_price_th"] == core.PROJECT_CLASS_PRESETS["business"]["apartment_price_th"]


def test_the_class_shows_this_projects_numbers_and_keeps_typed_ones(monkeypatch) -> None:
    """Класс ставит то, что поставит страница в ЭТОМ проекте (регион, личные
    настройки), а вписанное руками не трогает — и карточка так и говорит."""
    card = _parse(monkeypatch)["card"]
    inputs = {**core.DEFAULT_INPUTS, "_class_manual": ["parking_price_th"], "parking_price_th": 3200}
    profile = {"business": {"apartment_price_th": 480}}
    for index in range(3):
        core.agent_document_answer(core.AgentDocumentAnswerRequest(
            intake_id=card["id"], index=index, action="skip", inputs=inputs, tep=core.TEP_DEFAULT))
    got = core.agent_document_answer(core.AgentDocumentAnswerRequest(
        intake_id=card["id"], index=3, choice=1, inputs=inputs, tep=core.TEP_DEFAULT,
        class_profile=profile))["card"]
    engine = {row["path"]: row["value"] for row in got["to_engine"]}
    assert engine["inputs.apartment_price_th"] == 480, "карточка показала базу, а не цену проекта"
    assert "inputs.parking_price_th" not in engine, "класс затёр вписанное руками"
    kept = next(row for row in got["missing"] if row["key"] == "parking_price_th")
    assert kept["value"] == 3200 and "Вписано вручную" in kept["origin"]


def test_a_repeated_click_does_not_answer_the_next_question(monkeypatch) -> None:
    card = _parse(monkeypatch)["card"]
    _answer(card, index=0, choice=0)
    again = _answer(card, index=0, choice=1)
    assert again["stale"] is True and again["card"]["questions"]["index"] == 1


def test_the_bot_overrides_are_exactly_the_card_rows(monkeypatch) -> None:
    card = _parse(monkeypatch)["card"]
    overrides = teaser_card.calc_overrides(card)
    assert overrides["offices_gba_sqm"] == 26_300
    assert overrides["_tep"]["apartments"]["gns"] == round(82_840 * core.MKD_SPP_SPLIT["apartments"], 2)
    assert set(overrides["_field_origin"]) == {row["path"] for row in card["to_engine"]
                                              if not row["path"].startswith("land.")}
    # Чего нет в карточке «уйдёт в расчёт», того нет и в расчёте бота.
    assert "purchase_price_mln" not in overrides


def test_the_parcel_rows_have_no_number_before_the_calculation(monkeypatch) -> None:
    _stub(monkeypatch)
    got = core.agent_document(core.AgentDocumentRequest(
        filename="svetly4.pdf", content_b64=base64.b64encode(b"%PDF").decode()), None)
    queue = json.loads(core._intake_queue_path(got["card"]["id"]).read_text(encoding="utf-8"))
    card = core.teaser_card_view(queue, dict(core.DEFAULT_INPUTS), core.TEP_DEFAULT, by_parcel=True)
    missing = {row["key"]: row for row in card["missing"]}
    # Отсутствие данных — не ноль: город посчитает при расчёте.
    assert missing["school_places"]["value"] is None
    assert "ГлавАПУ" in missing["school_places"]["origin"]


# --- страница: что видит человек и что получает движок -------------------------

def test_on_the_page_card_then_questions_then_the_button(monkeypatch) -> None:
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright
    import uvicorn

    _stub(monkeypatch)
    server = uvicorn.Server(uvicorn.Config(wrapper.app, host="127.0.0.1", port=PORT,
                                           log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    calcs: list[dict] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chrome))
            page = browser.new_page(viewport={"width": 390, "height": 844})
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.on("request", lambda r: calcs.append(json.loads(r.post_data or "{}"))
                    if r.method == "POST" and r.url.endswith("/calculate") else None)
            page.goto(f"http://127.0.0.1:{PORT}/", wait_until="networkidle")
            wait_for_result(page)
            calcs_before = len(calcs)
            page.evaluate("() => toggleAgent(true)")
            page.set_input_files("#aiFile", files=[{"name": "svetly4.pdf",
                                                    "mimeType": "application/pdf",
                                                    "buffer": b"%PDF-1.4 stub"}])
            page.wait_for_function("() => !aiBusy && aiCard !== null", timeout=15_000)
            # Снимок после загрузки: окно перед запросом переписывает поля во
            # вводные (`syncInputsForAgent`), и это не запись из тизера.
            before = page.evaluate("() => JSON.stringify([inputs, tep])")
            card_text = page.locator(".ai-card").last.inner_text()
            questions_on_first_step = page.locator(".ai-question").count()

            page.locator(".ai-card").last.get_by_role("button", name="Перейти к вопросам").click()
            for name in ("В цену сделки — платится на входе", "Расселение не требуется — 0",
                         "Взять сумму тизера — 2,57 млрд руб.", "Бизнес"):
                page.locator(".ai-question").last.get_by_role("button", name=name).click()
                page.wait_for_function("() => !aiBusy", timeout=10_000)
                page.wait_for_timeout(100)
            unchanged = page.evaluate("() => JSON.stringify([inputs, tep])") == before
            calcs_during = len(calcs) - calcs_before
            final_text = page.locator(".ai-card").last.inner_text()
            shown = page.evaluate("() => aiCard.to_engine.filter(r => !r.derived).map(r => [r.path, r.value])")

            page.locator(".ai-card").last.get_by_role("button", name="Всё верно, считать").click()
            page.wait_for_function(
                "() => !aiBusy && /Модель пересчитана|не пересчиталась/.test("
                "([...document.querySelectorAll('.ai-card .ai-intake-recalc')].pop()?.textContent||''))",
                timeout=30_000)
            recalc = page.locator(".ai-card").last.locator(".ai-intake-recalc").inner_text()
            mismatch = page.locator(".ai-card").last.inner_text()
            origin = page.evaluate("() => (inputs._field_origin||{})['inputs.offices_gba_sqm']")
            cad = page.evaluate("() => document.getElementById('cadastralNumbers').value")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert not errors, errors
    assert questions_on_first_step == 0, "на первом шаге уже задан вопрос"
    for line in ("Что найдено в тизере", "стр. 2", "Что уйдёт в расчёт", "Чего нет в тизере",
                 "По умолчанию модели DevelopAid", "Модель пока не менялась"):
        assert line in card_text, line
    assert unchanged, "ответы на вопросы записались в модель до кнопки «Всё верно, считать»"
    assert calcs_during == 0, "модель пересчитывалась во время вопросов"
    assert "Всё верно, считать" in final_text and "2 550" in final_text
    assert "Модель пересчитана" in recalc, recalc
    assert "Не совпало с карточкой" not in mismatch, mismatch
    # Движок получил ровно строки карточки.
    sent = calcs[-1]
    for path, value in shown:
        parts = path.split(".")
        if parts[0] == "inputs":
            got = sent["inputs"].get(parts[1])
        elif parts[0] == "tep":
            got = sent["tep"][parts[1]][parts[2]]
        else:
            continue
        assert got == value or (isinstance(value, (int, float)) and abs(float(got) - value) < 1e-6), \
            (path, value, got)
    # Продаваемую площадь офисов карточка обещала пересчитать — пересчитана.
    assert float(sent["inputs"]["offices_saleable_sqm"]) > 0
    assert origin and origin["source"] == "document" and "стр. 2" in origin["text"], origin
    assert cad == NUMBER


def test_the_mini_app_counts_exactly_the_bot_card(monkeypatch) -> None:
    """Кнопка бота «Всё верно, считать» без участка: мини-приложение считает
    с умолчаний движка и строк карточки — ни больше, ни меньше."""
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright
    import browser as stand

    card = _parse(monkeypatch)["card"]
    card = {**card, "to_engine": [row for row in card["to_engine"]
                                  if not row["path"].startswith("land.")]}
    monkeypatch.setattr(core, "_telegram_token", lambda: "123:test")
    url = core._telegram_intake_calc_markup(1, {**card, "cadastral_numbers": []}
                                            )["inline_keyboard"][0][0]["web_app"]["url"]
    fragment = url.split("#", 1)[1]
    calcs: list[dict] = []
    with sync_playwright() as pw:
        chromium = pw.chromium.launch(executable_path=str(chrome))
        page = chromium.new_page(viewport={"width": 390, "height": 844})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("request", lambda r: calcs.append(json.loads(r.post_data or "{}"))
                if r.method == "POST" and r.url.endswith("/calculate") else None)
        with stand.serve(wrapper.app, PORT + 1) as root:
            page.goto(f"{root}/?telegram=1#{fragment}", wait_until="domcontentloaded")
            page.wait_for_function(
                "() => /по карточке тизера готов/.test("
                "document.getElementById('glavapuStatus')?.textContent||'')", timeout=60_000)
            origin = page.evaluate("() => (inputs._field_origin||{})['tep.apartments.gns']")
        chromium.close()
    assert not errors, errors
    sent = calcs[-1]
    for row in card["to_engine"]:
        if row["derived"]:
            continue
        parts = row["path"].split(".")
        got = sent["inputs"][parts[1]] if parts[0] == "inputs" else sent["tep"][parts[1]][parts[2]]
        assert got == row["value"] or abs(float(got) - float(row["value"])) < 1e-6, (row["path"], got)
    # Чего в карточке нет — умолчание движка, а не остаток прежнего проекта.
    assert sent["inputs"]["purchase_price_mln"] == core.DEFAULT_INPUTS["purchase_price_mln"]
    assert origin and "стр. 2" in origin["text"], origin


EKATERINBURG = "66:41:0000000:1"
EKB_PARCEL = {
    "found": True, "cadastral_number": EKATERINBURG, "kind": "land",
    "kind_label": "Земельный участок", "address": "Свердловская область, г. Екатеринбург",
    "area_sqm": 12000.0, "area_ha": 1.2, "category": "Земли населённых пунктов",
    "permitted_use": "Многоэтажная жилая застройка", "cadastral_value_rub": 150_000_000.0,
    "cadastral_value_mln": 150.0, "region": "Свердловская область", "center": None,
    "contour_merc": [], "source": "НСПД / ЕГРН",
}


def _mini_app_by_parcel(monkeypatch, numbers: list[str], region: str, port: int, routes) -> dict:
    """Кнопка бота «Всё верно, считать» с участком не из Москвы: что увидел
    человек и что ушло в расчёт."""
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright
    import browser as stand

    card = _parse(monkeypatch)["card"]
    card = {**card, "cadastral_numbers": numbers,
            "to_engine": [row for row in card["to_engine"] if not row["path"].startswith("land.")]}
    monkeypatch.setattr(core, "_telegram_token", lambda: "123:test")
    url = core._telegram_intake_calc_markup(1, card, region)["inline_keyboard"][0][0]["web_app"]["url"]
    calcs: list[dict] = []
    with sync_playwright() as pw:
        chromium = pw.chromium.launch(executable_path=str(chrome))
        page = chromium.new_page(viewport={"width": 390, "height": 844})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("request", lambda r: calcs.append(json.loads(r.post_data or "{}"))
                if r.method == "POST" and r.url.endswith("/calculate") else None)
        for pattern, handler in routes:
            page.route(pattern, handler)
        with stand.serve(wrapper.app, port) as root:
            page.goto(f"{root}/?telegram=1#{url.split('#', 1)[1]}", wait_until="domcontentloaded")
            page.wait_for_function(
                "() => /по карточке тизера готов|не посчитан/.test("
                "(document.getElementById('glavapuStatus')?.textContent||'')"
                "+(document.body.innerText||''))", timeout=90_000)
            seen = page.evaluate("() => document.body.innerText")
            state = page.evaluate("() => ({region: inputs.vri_region, area: Number(inputs.site_area_ha),"
                                  " fee: Number(inputs.land_rights_cost_mln||0)})")
        chromium.close()
    assert not errors, errors
    assert "не посчитан" not in seen, seen[:500]
    sent = calcs[-1]
    for row in card["to_engine"]:
        if row["derived"]:
            continue
        parts = row["path"].split(".")
        got = sent["inputs"][parts[1]] if parts[0] == "inputs" else sent["tep"][parts[1]][parts[2]]
        assert got == row["value"] or abs(float(got) - float(row["value"])) < 1e-6, (row["path"], got)
    return {"seen": seen, "state": state, "sent": sent}


def test_the_mini_app_counts_another_region_with_the_card(monkeypatch) -> None:
    """Другой регион: госреестр, плата за смену ВРИ — ноль, остальное — наши
    умолчания, и поверх — строки карточки; человеку сказано, что норм региона
    у нас нет."""
    def fulfil(body):
        return lambda route: route.fulfill(status=200, content_type="application/json",
                                           body=json.dumps(body, ensure_ascii=False))
    got = _mini_app_by_parcel(monkeypatch, [EKATERINBURG], "other", PORT + 2, [
        ("**/land/lookup", fulfil({"query": EKATERINBURG, "results": [EKB_PARCEL],
                                   "found_count": 1, "warnings": []})),
        ("**/land/screening", fulfil({})),
    ])
    assert got["state"]["region"] == "other" and got["state"]["area"] == 1.2, got["state"]
    assert got["state"]["fee"] == 0
    assert "Норм этого региона у нас нет" in got["seen"]


def test_the_mini_app_counts_the_moscow_region_with_the_card(monkeypatch) -> None:
    """Московская область: нормы области, как «Получить ТЭП» на сайте, и
    поверх — строки карточки. Сведений ЕГРН в песочнице нет — расчёт области
    идёт по площади участка вместо номера (настоящий `/mo/calculate`)."""
    def by_area(route):
        body = json.loads(route.request.post_data or "{}")
        body.update(query="", site_area_ha=6.6667)
        route.continue_(post_data=json.dumps(body))
    got = _mini_app_by_parcel(monkeypatch, ["50:20:0010101:1"], "mo", PORT + 3,
                              [("**/mo/calculate", by_area)])
    assert got["state"]["region"] == "mo", got["state"]
    assert abs(got["state"]["area"] - 6.6667) < 1e-3, got["state"]
    assert "нормам Московской области" in got["seen"]

"""Площадка КРТ не перемеряется одним участком, а плата за ВРИ не прячется.

«Почему не могу нажать кнопку ВРИ? Передавал из Торгов КРТ. В итоге сбой
какой-то» (владелец, 22.10.2026, прод 0.26.88). Площадка КРТ на Светлом пр.
приехала из «Торгов» территорией около 5 га и ТЭП города на десятки тысяч
метров. Перечень проекта решения назвал два участка на 512 м², а разбор
кадастрового номера одного участка (66 м²) записал свою площадь в площадь
территории: подпись при этом продолжала говорить «из площадки КРТ», ТЭП
77 870 м² квартир стоял на 66 м², и никто об этом не сказал. Плата за смену
ВРИ у площадки КРТ не считается вовсе, и галочка «Требуется изменение ВРИ»
молча откатывалась обратно.

Проверяется:
- маршрут передачи называет, какую часть территории покрывают участки
  перечня (`krt_territory_coverage`), а вопрос моста — говорит это словами;
- разбор номеров не перемеряет территорию, приехавшую с источником;
- ТЭП, несовместимый с площадью, даёт предупреждение у поля площади с
  кнопкой вернуть площадь территории;
- клик по галочке ВРИ без платы объясняет, что делать, и ведёт к полю;
- подпись шага ВРИ в слое IA не говорит «можно пропустить» площадке КРТ.

Запуск: python3 -m pytest tests/test_a_krt_site_is_not_remeasured_by_one_parcel.py -q
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

from browser import chromium_or_skip

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as wrapper  # noqa: E402
from auction_search import bridge  # noqa: E402
from auction_search.developaid_mapper import krt_territory_coverage  # noqa: E402

core = wrapper.core
PORT = 18311
CADS = ["77:09:0004001:47", "77:09:0004001:5779"]
ONE = "77:09:0004001:5578"
TERRITORY_HA = 5.2


# --- маршрут передачи --------------------------------------------------------

def test_the_handoff_says_how_much_of_the_territory_the_parcels_cover() -> None:
    parcels = [{"cadastral_number": CADS[0], "area_sqm": 460},
               {"cadastral_number": CADS[1], "area_sqm": 52}]
    got = krt_territory_coverage(parcels, TERRITORY_HA)
    assert got["land_area_ha"] == 0.0512
    assert got["territory_area_ha"] == TERRITORY_HA
    assert got["covers_territory"] is False
    assert 0 < got["share"] < 0.02
    # Перечень, покрывающий территорию, так и называется.
    full = krt_territory_coverage([{"area_sqm": 51000}], TERRITORY_HA)
    assert full["covers_territory"] is True
    # Площадь без числа ЕГРН — не ноль, а «не измерено».
    blank = krt_territory_coverage([{"area_sqm": None}], TERRITORY_HA)
    assert blank["unmeasured"] == 1 and blank["share"] is None
    assert blank["covers_territory"] is False


def test_the_handoff_route_returns_the_coverage() -> None:
    import inspect
    from auction_search import api

    source = inspect.getsource(api)
    route = source[source.index('@app.get("/auctions/krt/{slug}/handoff")'):]
    route = route[:route.index("def _plato_access")]
    assert "krt_territory_coverage(" in route
    assert '"site_area_ha"' in route


# --- живая страница ------------------------------------------------------------

def _pending() -> dict:
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update({"site_area_ha": TERRITORY_HA, "site_density_sqm_per_ha": 20051.4,
                   "purchase_price_mln": 0.0, "land_rights_cost_mln": 0.0,
                   "vri_required": False, "vri_relief_mode": "amount", "vri_relief_mln": 2570.0})
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    tep["apartments"]["gns"] = 77870.0
    return {"krt_model": {"inputs": inputs, "tep": tep, "phasing": None},
            "krt_name": "Светлый проезд", "krt_slug": "svetly",
            "krt_cadastres": CADS,
            "krt_cadastre_note": {"land": 2, "listed": 3, "buildings": 1, "missing": 0,
                                  "source": "appendix", "problem": "",
                                  "land_area_ha": 0.0512, "territory_area_ha": TERRITORY_HA,
                                  "share": 0.0098, "unmeasured": 0, "covers_territory": False}}


ANALYSIS = {"requested": [ONE], "recognized": [ONE], "cadastral_numbers": [ONE],
            "parcels": [{"cadastral_number": ONE, "area_ha": 0.0066}],
            "territory": {"area_ha": 0.0066, "district": "Сокол", "inside_moscow": True}}

STATE = """() => ({
  area: inputs.site_area_ha,
  label: siteAreaSourceLabel(),
  warn: (document.getElementById('siteAreaWarning')||{}).textContent||'',
  warn_shown: (document.getElementById('siteAreaWarning')||{}).style.display,
  restore: !!document.getElementById('siteAreaRestore'),
})"""


def test_in_a_real_browser_the_krt_territory_survives_one_parcel() -> None:
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright
    import uvicorn

    bridge.install_page_bridge(core)
    server = uvicorn.Server(uvicorn.Config(wrapper.app, host="127.0.0.1", port=PORT, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started

    fake_land = json.dumps({"parcels": [], "verdict": {"status": "OK"}, "results": [], "found_count": 0})
    dialogs: list[str] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chrome))
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))

            def on_dialog(dialog):
                dialogs.append(dialog.message)
                dialog.accept()
            page.on("dialog", on_dialog)
            page.route("**/land/**", lambda route: route.fulfill(
                status=200, content_type="application/json", body=fake_land))
            page.route("**/cadastral/analyze", lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps(ANALYSIS)))
            # Калькулятор ГлавАПУ здесь не нужен: проверяется то, что
            # происходит ДО него, — запись площади по разбору номеров.
            page.route("**/calc/**", lambda route: route.abort())
            page.goto(f"http://127.0.0.1:{PORT}/", wait_until="networkidle")
            page.evaluate("(p) => sessionStorage.setItem('developaid.auction.pending.v1', JSON.stringify(p))",
                          _pending())
            page.goto(f"http://127.0.0.1:{PORT}/?krt_import=1", wait_until="networkidle")
            time.sleep(1.5)
            arrived = page.evaluate(STATE)
            territory = page.evaluate("() => (inputs._manual_tep_import||{}).territory||null")

            # Человек вписал один номер и попросил ТЭП: разбор отвечает 66 м².
            page.evaluate(f"() => {{ document.getElementById('cadastralNumbers').value='{ONE}';"
                          " obtainCadastralTep().catch(()=>null); }")
            # Площадь пишется сразу после разбора, до калькулятора: ждём шага
            # «2 из 4», а не паузу — иначе замер успевает раньше записи.
            page.wait_for_function(
                "() => /2 из 4/.test((document.getElementById('cadastralStatus')||{}).textContent||'')",
                timeout=15000)
            after_analysis = page.evaluate(STATE)

            # Сохранённый проект владельца: площадь уже перемерена 66 м².
            page.evaluate("() => { inputs.site_area_ha=0.0066; renderSitePanel(); }")
            broken = page.evaluate(STATE)
            page.evaluate("() => document.getElementById('siteAreaRestore').click()")
            time.sleep(0.5)
            restored = page.evaluate(STATE)

            # Галочка ВРИ без платы: клик не откатывается молча.
            page.evaluate("() => { inputs.land_rights_cost_mln=0; renderInputs(); }")
            before_click = page.evaluate(
                "() => (document.getElementById('vriRequiredNote')||{}).textContent||''")
            page.evaluate("() => document.getElementById('f_vri_required').click()")
            time.sleep(0.3)
            vri = page.evaluate("""() => ({
              checked: document.getElementById('f_vri_required').checked,
              note: (document.getElementById('vriRequiredNote')||{}).textContent||'',
              go: (document.getElementById('vriFeeGo')||{}).style.display,
            })""")
            page.evaluate("() => document.getElementById('vriFeeGo').click()")
            focused = page.evaluate("() => (document.activeElement||{}).id")
            # Вписали плату — подсказка уходит, галочка встаёт сама.
            page.evaluate("""() => { const f=document.getElementById('f_land_rights_cost_mln');
              f.value='150'; f.dispatchEvent(new Event('change')); }""")
            time.sleep(0.3)
            paid = page.evaluate("""() => ({
              checked: document.getElementById('f_vri_required').checked,
              go: (document.getElementById('vriFeeGo')||{}).style.display,
            })""")
            # Подпись шага ВРИ в слое IA при нулевой плате у площадки КРТ.
            page.evaluate("""() => { const f=document.getElementById('f_land_rights_cost_mln');
              f.value='0'; f.dispatchEvent(new Event('change')); }""")
            # Слой IA на корне ставит сборка прода (`ia_preview.install`); здесь
            # он подключается тем же файлом, что отдаёт `/ia/assets/overlay.js`.
            page.add_script_tag(path=str(ROOT / "ia_preview" / "assets" / "overlay.js"))
            time.sleep(0.5)
            page.evaluate("() => { const b=document.querySelector('.tabs [data-tab=\"vri\"]'); if(b) b.click(); }")
            time.sleep(0.3)
            hint = page.evaluate("() => (document.getElementById('iaStepHint')||{}).textContent||null")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert not errors, errors
    # Вопрос моста называет покрытие словами.
    question = next(m for m in dialogs if "Светлый проезд" in m)
    assert "0,0512 га из 5,2 га территории КРТ" in question, question
    assert territory and territory["cadastral_numbers"] == CADS and territory["covers_territory"] is False
    assert arrived["area"] == TERRITORY_HA and arrived["label"].startswith("из площадки КРТ"), arrived
    assert arrived["warn_shown"] == "none", arrived

    # Разбор одного номера территорию КРТ не перемерил.
    assert after_analysis["area"] == TERRITORY_HA, after_analysis
    assert after_analysis["label"].startswith("из площадки КРТ"), after_analysis

    # 66 м² под 77 870 м² — предупреждение с местом и кнопкой.
    assert broken["warn_shown"] == "", broken
    assert "Площадь участка не сходится с ТЭП" in broken["warn"], broken
    assert "шаге «ТЭП»" in broken["warn"], broken
    assert not broken["label"].startswith("из площадки КРТ"), "площадь 66 м² подписана как площадь КРТ"
    assert broken["restore"] and "5,2 га" in broken["warn"], broken
    assert restored["area"] == TERRITORY_HA and restored["warn_shown"] == "none", restored

    assert "Галочка ставится сама" not in before_click
    assert vri["checked"] is False
    assert "Галочка ставится сама, когда задана сумма платы" in vri["note"], vri
    assert "Для площадки КРТ" in vri["note"] and "0,0512 га из 5,2 га" in vri["note"], vri
    assert "льгота 2 570 млн ₽ без платы ни на что не действует" in vri["note"].replace(" ", " "), vri
    assert vri["go"] == "", vri
    assert focused == "f_land_rights_cost_mln", focused
    assert paid["checked"] is True and paid["go"] == "none", paid

    # Слой IA стоит на корне: подпись шага обязана найтись.
    assert hint is not None, "подпись шага IA не найдена"
    assert "можно пропустить" not in hint, hint
    assert "Плата за смену ВРИ не посчитана" in hint, hint

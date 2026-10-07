"""Сверка нашего сценария со штатным калькулятором ГлавАПУ (КРТ Нагатино).

Раньше от калькулятора приходила только выгрузка с ЕГО умолчаниями (94/6,
нежильё целиком в 4.1, плотность из таблицы), и сверить свой сценарий было не
с чем. Теперь калькулятору выставляются наши параметры — доля жилья и
встроенной коммерции, СПП, площадь, нежильё по ВРИ, соцобъекты, вид права, —
и его ответ стоит рядом с нашим по видам. ГлавАПУ — проверка
(`validation_only`), а не замена наших чисел.

Три слоя проверок:

* чистые функции `glavapu_scenario` на пресете Нагатино (без браузера);
* маршрут `/glavapu/scenario`: задание в фоне, ответ сразу, кэш по параметрам,
  отказ с местом;
* сквозной прогон драйвера на коде калькулятора из `genplan_assets` (локальная
  копия, анализ территории подставлен). Он проверяет ПОЛЯ и отказы драйвера,
  а не числа: копия от 28.09.2026 считает машино-места иначе, чем живой
  калькулятор 06.10.2026 (постоянные 1 469 против 2 902 на умолчаниях
  Нагатино при том же населении 7 618).

Запуск: python3 -m pytest tests/test_glavapu_scenario_check.py -q
"""

from __future__ import annotations

import copy
import functools
import http.server
import json
import os
import socketserver
import sys
import threading
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for _key in ("AUCTION_KRT_WEEKLY", "AUCTION_KRT_WATCH", "DEVELOPAID_WORKBOOK_CACHE",
             "NORMATIVES_WATCH", "NAGATINO_EGRN_READ"):
    os.environ.setdefault(_key, "0")

import glavapu_scenario as gs  # noqa: E402
import project_preset  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
# Выгрузка кнопкой «Excel» калькулятора из `genplan_assets` после того, как
# драйвер выставил сценарий Нагатино (14,62 га, аренда). Ставки квартала —
# умолчания самого калькулятора: анализ территории подставлен
# (`glavapu_analysis_stub_nagatino.json`), до glavapu-api.ru песочница не
# достаёт. Числа годятся для проверки разбора, а не как ответ города.
XLSX = FIXTURES / "glavapu_scenario_nagatino_vendored.xlsx"
NUMBERS = ["77:05:0004001:1"]


def _nagatino() -> tuple[dict, dict]:
    preview = project_preset.build_preview(
        json.loads((ROOT / "presets" / "КРТ_Нагатино.json").read_text(encoding="utf-8")))
    inputs = dict(preview["inputs"], site_area_ha=14.62, land_right="lease")
    inputs["_cadastral_analysis"] = {"recognized": NUMBERS}
    return inputs, preview["tep"]


# ------------------------------------------------------------- сценарий --

def test_the_nagatino_scenario_is_built_from_our_tep() -> None:
    inputs, tep = _nagatino()
    scenario = gs.build_scenario(inputs, tep, numbers=NUMBERS)
    params = scenario["params"]
    assert scenario["role"] == "validation_only"
    assert params["area_ha"] == 14.62 and params["land_right"] == "аренда"
    # 215 720,6 м² квартир + 13 769,4 м² встроенной коммерции: 94/6.
    assert params["spp_residential_ths"] == pytest.approx(229.49)
    assert params["vpp_pct"] == pytest.approx(6.0, abs=0.001)
    assert [(i["code"], i["spp_ths"]) for i in params["nonres"]] == [
        ("4_1", pytest.approx(92.845)), ("4_2", pytest.approx(92.845))]
    assert {(i["key"], i["places"]) for i in params["social"]} == {
        ("kindergarten", 350), ("school", 1000)}
    # Происхождение каждого параметра записано.
    for key in ("area_ha", "spp_residential", "vpp_pct", "spp_nonres", "land_right"):
        assert scenario["origin"][key]
    assert not scenario["not_sent"] and not scenario["problems"]


def test_a_product_without_a_vri_is_not_sent_under_a_foreign_one() -> None:
    """Контрпример: нежильё без строки в карте не уходит молча в 4.1."""
    inputs, tep = _nagatino()
    tep = copy.deepcopy(tep)
    tep["other_mandatory"] = {"label": "Прочие обязательные объекты", "gns": 5000.0}
    scenario = gs.build_scenario(inputs, tep, numbers=NUMBERS)
    assert scenario["params"]["spp_nonres_ths"] == pytest.approx(185.69)
    [item] = scenario["not_sent"]
    assert item["param"] == "nonres.other_mandatory"
    assert "NONRES_VRI" in item["reason"] and "5 000" in item["reason"]


def test_a_social_object_without_places_is_named() -> None:
    inputs, tep = _nagatino()
    tep = copy.deepcopy(tep)
    tep["clinic"] = {"label": "Поликлиника", "gns": 3000.0, "units": 0}
    scenario = gs.build_scenario(inputs, tep, numbers=NUMBERS)
    assert any(i["param"] == "social.clinic" and "нет числа мест" in i["reason"]
               for i in scenario["not_sent"])


def test_no_area_is_a_problem_not_a_zero_area_run() -> None:
    inputs, tep = _nagatino()
    inputs = dict(inputs, site_area_ha=0)
    scenario = gs.build_scenario(inputs, tep, numbers=NUMBERS)
    assert scenario["problems"] and "площади" in scenario["problems"][0]


def test_the_cache_key_follows_parameters_not_labels() -> None:
    inputs, tep = _nagatino()
    one = gs.build_scenario(inputs, tep, numbers=NUMBERS)
    relabeled = copy.deepcopy(one)
    relabeled["origin"]["area_ha"] = "другая подпись"
    assert gs.scenario_key(one) == gs.scenario_key(relabeled)
    moved = gs.build_scenario(dict(inputs, site_area_ha=15.0), tep, numbers=NUMBERS)
    assert gs.scenario_key(moved) != gs.scenario_key(one)
    other = gs.build_scenario(inputs, tep, numbers=["77:05:0004001:2"])
    assert gs.scenario_key(other) != gs.scenario_key(one)


# --------------------------------------------------------- выгрузка ГлавАПУ --

def test_mpt_and_parking_are_read_by_vri_from_the_calculator_book() -> None:
    data = XLSX.read_bytes()
    mpt = gs.mpt_by_vri(data)
    assert {i["vri"]: i["jobs"] for i in mpt["items"]}["Объекты торговли (4.2)"] == 1856
    assert mpt["total"] == 5007
    parking = gs.parking_by_vri(data)
    assert parking["totals"] == {"total": 1390, "attached": 461, "permanent": 820,
                                 "guest": 82, "short_stop": 27}


def test_parking_columns_are_found_by_header_not_position(tmp_path) -> None:
    """Контрпример: столбцы переставлены — виды мест не перепутаны."""
    import openpyxl
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Машино-места"
    sheet.append(["№", "Наименования", "Единицы измерения", "Гостевые", "Постоянные",
                  "Всего", "Кратковременные", "Приобъектные"])
    sheet.append([1, "Многоквартирный дом", "машино-места", 82, 820, 909, 7, 0])
    path = tmp_path / "book.xlsx"
    book.save(path)
    totals = gs.parking_by_vri(path.read_bytes())["totals"]
    assert totals["permanent"] == 820 and totals["guest"] == 82 and totals["short_stop"] == 7


def test_a_missing_sheet_is_none_not_zero(tmp_path) -> None:
    import openpyxl
    book = openpyxl.Workbook()
    book.active.title = "ТЭП"
    path = tmp_path / "book.xlsx"
    book.save(path)
    assert gs.mpt_by_vri(path.read_bytes()) is None
    side = gs.glavapu_side({}, {}, path.read_bytes())
    assert side["mpt"][0] is None


# ------------------------------------------------------------------ сверка --

def test_compare_names_the_reason_and_keeps_both_origins() -> None:
    ours = {"parking": {"permanent": (1619, "наша норма")}, "mpt": (None, "")}
    theirs = {"parking": {"permanent": (820.0, "строка 42.1")}, "mpt": (5007.0, "лист «МПТ»")}
    result = gs.compare(ours, theirs, {"parking.permanent": "наша норма от 140 218 м²",
                                       "mpt": "нет своей нормы"})
    rows = {r["kind"]: r for r in result["rows"]}
    permanent = rows["parking.permanent"]
    assert permanent["status"] == "diff" and permanent["delta"] == -799
    assert permanent["ours_origin"] == "наша норма" and permanent["glavapu_origin"] == "строка 42.1"
    assert "140 218" in permanent["reason"]
    # Своей величины нет — это не ноль и не совпадение.
    assert rows["mpt"]["status"] == "ours_missing" and rows["mpt"]["ours"] is None


def test_a_refused_parameter_marks_dependent_rows_not_applied() -> None:
    ours = {"spp": {"nonres": (185.69, "ТЭП")}, "density": (29.0, "ТЭП")}
    theirs = {"spp": {"nonres": (10.0, "строка 8.1")}, "density": (29.0, "строка 2")}
    applied = {"refused": [{"param": "nonres.4_2", "place": "раздел «Детализировать СПП»",
                            "reason": "нет пункта"}]}
    rows = {r["kind"]: r for r in gs.compare(ours, theirs, {}, applied)["rows"]}
    assert rows["spp.nonres"]["status"] == "not_applied"
    assert "nonres.4_2" in rows["spp.nonres"]["reason"]
    assert rows["density"]["status"] == "match"


# ------------------------------------------------------------------ маршрут --

@pytest.fixture()
def core(monkeypatch, tmp_path):
    import main as wrapper
    core = wrapper.core
    monkeypatch.setenv("DEVELOPAID_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    monkeypatch.setattr(core, "_glavapu_headless_available", lambda: True)
    return core


def _request(core, **extra):
    inputs, tep = _nagatino()
    return core.GlavapuScenarioRequest(inputs=inputs, tep=tep, **extra)


def _wait_done(core, req, seconds=10.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        answer = core.glavapu_scenario_check(req.model_copy(update={"poll": True}))
        if answer["state"] not in ("queued", "running"):
            return answer
        time.sleep(0.05)
    raise AssertionError("задание не кончилось")


def _fake_run(calls, release=None):
    def run(numbers, area_ha, params=None):
        calls.append((list(numbers), area_ha, params))
        if release is not None:
            assert release.wait(10)
        return {"rows": [], "scenario_report": {"applied": [], "refused": []},
                "scenario_rows": {"1": area_ha}, "scenario_xlsx": XLSX.read_bytes(),
                "timings": {"scenario": 1}}
    return run


def test_the_request_answers_at_once_and_the_browser_works_in_background(core, monkeypatch):
    calls: list = []
    release = threading.Event()
    monkeypatch.setattr(core, "_glavapu_headless_run", _fake_run(calls, release))
    started = time.monotonic()
    answer = core.glavapu_scenario_check(_request(core))
    assert time.monotonic() - started < 2.0, "окно ждало браузер"
    assert answer["state"] in ("queued", "running") and answer["key"]
    release.set()
    done = _wait_done(core, _request(core))
    assert done["state"] == "done" and done["role"] == "validation_only"
    rows = {r["kind"]: r for r in done["comparison"]["rows"]}
    # ГлавАПУ — рядом, а наша величина — своя, со своим происхождением.
    assert rows["parking.permanent"]["glavapu"] == 820
    assert rows["parking.permanent"]["ours"] is not None
    assert "tep_derived_norms" in rows["parking.permanent"]["ours_origin"]
    assert rows["spp.residential_living"]["glavapu_origin"] == "строка 7.1"
    # Виды машино-мест — те же четыре, что у разбора гаража (945-ПП п. 6.1.2).
    assert {k for k in rows if k.startswith("parking.")} == {
        "parking.permanent", "parking.guest", "parking.attached", "parking.short_stop"}
    assert rows["parking.short_stop"]["status"] == "ours_missing"
    assert "кратковременной" in rows["parking.short_stop"]["reason"]
    assert calls[0][0] == NUMBERS and calls[0][2]["spp_residential_ths"] == pytest.approx(229.49)


def test_the_same_parameters_run_the_browser_once(core, monkeypatch):
    calls: list = []
    monkeypatch.setattr(core, "_glavapu_headless_run", _fake_run(calls))
    core.glavapu_scenario_check(_request(core))
    _wait_done(core, _request(core))
    again = core.glavapu_scenario_check(_request(core))
    assert again["state"] == "done" and len(calls) == 1
    # Другие параметры — другой прогон.
    inputs, tep = _nagatino()
    changed = core.GlavapuScenarioRequest(inputs=dict(inputs, site_area_ha=15.0), tep=tep)
    core.glavapu_scenario_check(changed)
    _wait_done(core, changed)
    assert len(calls) == 2


def test_an_unavailable_calculator_is_named_with_its_place(core, monkeypatch):
    monkeypatch.setattr(core, "_glavapu_headless_available", lambda: False)
    answer = core.glavapu_scenario_check(_request(core))
    assert answer["state"] == "unavailable"
    assert answer["error"].startswith("штатный калькулятор:") and answer["where"]


def test_a_browser_failure_reaches_the_window_with_its_place(core, monkeypatch):
    def broken(numbers, area_ha, params=None):
        raise RuntimeError("поток браузера остановлен")
    monkeypatch.setattr(core, "_glavapu_headless_run", broken)
    core.glavapu_scenario_check(_request(core))
    answer = _wait_done(core, _request(core))
    assert answer["state"] == "error" and "RuntimeError" in answer["error"]
    # Место — файл и строка, где оборвалось (здесь — подделка браузера).
    assert "test_glavapu_scenario_check.py:" in answer["where"]


def test_no_parcel_is_refused_before_the_browser(core, monkeypatch):
    calls: list = []
    monkeypatch.setattr(core, "_glavapu_headless_run", _fake_run(calls))
    inputs, tep = _nagatino()
    inputs.pop("_cadastral_analysis")
    answer = core.glavapu_scenario_check(core.GlavapuScenarioRequest(inputs=inputs, tep=tep))
    assert answer["state"] == "refused" and "кадастровых" in answer["error"]
    assert not calls


def test_render_forwards_to_the_core(core, monkeypatch):
    seen = {}
    monkeypatch.setattr(core, "_core_api_url", lambda path: "http://core" + path)

    def post(url, payload, timeout):
        seen.update(url=url, payload=payload)
        return {"state": "queued", "key": "k"}
    monkeypatch.setattr(core, "_core_post", post)
    answer = core.glavapu_scenario_check(_request(core))
    assert seen["url"] == "http://core/glavapu/scenario" and answer["route"] == "ядро"
    assert seen["payload"]["tep"]["apartments"]["gns"] == pytest.approx(215720.6)


# ------------------------------------------- драйвер на коде калькулятора --

def _chromium():
    pytest.importorskip("playwright.sync_api")
    import browser_launch
    from playwright.sync_api import sync_playwright
    manager = sync_playwright().start()
    try:
        browser = browser_launch.launch(manager)
    except Exception as exc:  # noqa: BLE001
        manager.stop()
        pytest.skip(f"Chromium не поднялся: {exc}")
    return manager, browser


class _Calc(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D401 — тишина в выводе тестов
        pass

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path in ("/calc", "/calc/"):
            body = ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
                    '<link rel="stylesheet" href="/calc/assets/index-B8zlAO9I.css"></head>'
                    '<body><div id="root"></div><script type="module" '
                    'src="/calc/assets/index-B0jIwkVO.js"></script></body></html>').encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
            return
        name = path.removeprefix("/calc/assets/")
        file = ROOT / "genplan_assets" / name
        if "/" in name or not file.is_file():
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/css" if name.endswith(".css")
                         else "application/javascript")
        self.end_headers()
        self.wfile.write(file.read_bytes())


@pytest.fixture(scope="module")
def calc_page():
    if not (ROOT / "genplan_assets" / "index-B0jIwkVO.js").is_file():
        pytest.skip("нет локальной копии калькулятора")
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Calc)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    analysis = (FIXTURES / "glavapu_analysis_stub_nagatino.json").read_text(encoding="utf-8")
    manager, browser = _chromium()

    def route(r):
        url = r.request.url
        if url.startswith(base):
            return r.continue_()
        if url.endswith("/api/analysis"):
            return r.fulfill(status=200, content_type="application/json", body=analysis)
        return r.abort()

    def open_page():
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.set_default_timeout(15000)
        page.route("**/*", route)
        page.goto(base + "/calc/?terrArea=17.8109&restrictArea=0")
        page.get_by_role("button", name="Пропустить тур").click()
        page.get_by_role("button", name="Участок").click()
        page.locator("#id-cad-numbers-text-field").fill(NUMBERS[0])
        page.get_by_role("button", name="Отправить").click()
        page.wait_for_timeout(800)
        page.get_by_role("button", name="Перейти к расчётам").click()
        page.locator('table[aria-label="calc table"]').wait_for()
        try:
            page.get_by_role("button", name="Закрыть справку").click(timeout=2000)
        except Exception:
            pass
        return page

    yield types.SimpleNamespace(open=open_page, base=base, analysis=analysis)
    browser.close()
    manager.stop()
    server.shutdown()


def test_the_driver_sets_the_nagatino_scenario_on_the_calculator(calc_page) -> None:
    inputs, tep = _nagatino()
    params = gs.build_scenario(inputs, tep, numbers=NUMBERS)["params"]
    page = calc_page.open()
    report = gs.apply_scenario(page, params)
    assert report["refused"] == [], report["refused"]
    rows = gs.read_rows(page)
    assert rows["1"] == pytest.approx(14.62)
    assert rows["7"] == pytest.approx(229.49, abs=gs.TOL_THS)
    assert rows["7.2"] == pytest.approx(13.769, abs=gs.TOL_THS)
    assert rows["8.1"] == pytest.approx(185.69, abs=gs.TOL_THS)
    assert (rows["18"], rows["22"]) == (350, 1000)
    # Ползунок «Соотношение жилых / нежилых зданий» ушёл со 100/0 под наш сценарий.
    ratio = next(x for x in report["applied"] if x["param"] == "ratio")
    assert ratio["got"].startswith("Жилые 52") and "Нежилые 47" in ratio["got"]
    data = gs.export_xlsx(page)
    mpt = {i["vri"] for i in gs.mpt_by_vri(data)["items"]}
    assert {"Деловое управление (4.1)", "Объекты торговли (4.2)"} <= mpt
    page.close()


def test_a_refused_field_is_named_with_its_place(calc_page, monkeypatch) -> None:
    """Контрпример: пункта ВРИ нет в меню — отказ с местом, а не тихий успех."""
    inputs, tep = _nagatino()
    params = gs.build_scenario(inputs, tep, numbers=NUMBERS)["params"]
    params["nonres"][1] = dict(params["nonres"][1], menu="Несуществующий ВРИ (9.9)",
                               code="9_9")
    page = calc_page.open()
    report = gs.apply_scenario(page, params)
    places = {(r["param"], r["place"]) for r in report["refused"]}
    assert ("nonres.9_9", "раздел «Детализировать СПП», меню «Добавить категорию»") in places
    page.close()


def test_the_engine_browser_thread_runs_the_scenario(calc_page, monkeypatch) -> None:
    """Сквозь поток-владелец браузера движка: очередь, сценарий, книга.

    Подменено только открытие страницы участка — оно идёт на локальную копию
    калькулятора вместо genplan.tech, до которого песочница не достаёт.
    """
    import main as wrapper
    core = wrapper.core
    server_url, analysis = calc_page.base, calc_page.analysis

    def drive(page, numbers, area_ha, timings):
        def route(r):
            url = r.request.url
            if url.startswith(server_url):
                return r.continue_()
            if url.endswith("/api/analysis"):
                return r.fulfill(status=200, content_type="application/json", body=analysis)
            return r.abort()
        page.route("**/*", route)
        page.goto(server_url + "/calc/?terrArea=1&restrictArea=0")
        page.get_by_role("button", name="Пропустить тур").click()
        page.get_by_role("button", name="Участок").click()
        page.locator("#id-cad-numbers-text-field").fill(", ".join(numbers))
        page.get_by_role("button", name="Отправить").click()
        page.wait_for_timeout(800)
        page.get_by_role("button", name="Перейти к расчётам").click()
        page.locator('table[aria-label="calc table"]').wait_for()
        try:
            page.get_by_role("button", name="Закрыть справку").click(timeout=2000)
        except Exception:
            pass
        return [{"code": "1", "name": "Площадь", "unit": "га", "value": "1"}]

    monkeypatch.setattr(core, "_glavapu_drive_page", drive)
    inputs, tep = _nagatino()
    params = gs.build_scenario(inputs, tep, numbers=NUMBERS)["params"]
    holder = core._glavapu_headless_run(NUMBERS, params["area_ha"], params)
    assert holder["scenario_report"]["refused"] == []
    assert holder["scenario_rows"]["8.1"] == pytest.approx(185.69, abs=gs.TOL_THS)
    parsed = core.parse_glavapu_xlsx(holder["scenario_xlsx"], "scenario.xlsx")
    side = gs.glavapu_side(parsed["normalized"], holder["scenario_rows"],
                           holder["scenario_xlsx"])
    assert side["spp"]["nonres"][0] == pytest.approx(185.69, abs=gs.TOL_THS)
    assert side["mpt"][0] and side["parking"]["permanent"][0]


# ----------------------------------------------------------------- страница --

def test_the_page_shows_ours_and_glavapu_side_by_side(core, monkeypatch) -> None:
    """Настоящий код PAGE рисует настоящий ответ маршрута."""
    import page_blocks

    calls: list = []
    monkeypatch.setattr(core, "_glavapu_headless_run", _fake_run(calls))
    inputs, tep = _nagatino()
    tep = copy.deepcopy(tep)
    tep["other_mandatory"] = {"label": "Прочие обязательные объекты", "gns": 5000.0}
    req = core.GlavapuScenarioRequest(inputs=inputs, tep=tep)
    core.glavapu_scenario_check(req)
    answer = _wait_done(core, req)
    answer["applied"] = {"refused": [{"param": "land_right", "reason": "нет такого варианта",
                                      "place": "раздел «Стоимость смены ВРИ»"}]}
    prelude = "const answer=%s;" % json.dumps(answer, ensure_ascii=False, default=str)
    tail = "console.log(JSON.stringify({html:glavapuScenarioHtml(answer)," \
           "summary:glavapuScenarioSummaryHtml(answer)," \
           "noSummary:glavapuScenarioSummaryHtml({state:'refused',error:'нет площади'})," \
           "status:glavapuScenarioStatusText(answer)," \
           "refused:glavapuScenarioStatusText({state:'unavailable',error:'штатный калькулятор: выключен'," \
           "where:'считает сам',hint:'Нужны GLAVAPU_HEADLESS=1'})}));"
    out, _ = page_blocks.run(prelude, tail)
    got = json.loads(out)
    html = got["html"]
    assert "validation_only" in html and "ничего в проекте не заменяют" in html
    # Все шесть групп сверки на месте и в порядке задания владельца.
    order = [html.find(t) for t in ("СПП и ГНС по видам", "Соцобъекты", "Машино-места по видам",
                                    ">МПТ<", "Стоимость смены ВРИ", ">Плотность<")]
    assert all(i >= 0 for i in order) and order == sorted(order), order
    # Расхождение — с причиной; происхождение обеих сторон видно.
    assert 'data-kind="parking.permanent" data-status="diff"' in html
    assert "tep_derived_norms" in html and "строка 42.1" in html
    assert "кратковременной остановки" in html
    # Непринятое поле и непереданный продукт — с местом и причиной.
    assert "Калькулятор не принял" in html and "раздел «Стоимость смены ВРИ»" in html
    assert "Не передано в калькулятор" in html and "Прочие обязательные объекты" in html
    assert got["status"].startswith("Сверка готова")
    # Итог в карточке: счёт по статусам, предупреждение и кнопка окна.
    summary = got["summary"]
    assert "совпало:" in summary and "расходится:" in summary
    assert "Калькулятор не принял полей: 1" in summary and "Не передано: 1" in summary
    assert 'onclick="openGlavapuScenario()"' in summary
    assert got["noSummary"] == ""
    assert "Место: считает сам" in got["refused"] and "GLAVAPU_HEADLESS=1" in got["refused"]


def test_the_page_has_the_block_and_its_button_calls_the_check() -> None:
    import main_legacy as legacy
    page = legacy.PAGE
    # Сверка — на вкладке «ТЭП», под таблицей ТЭП: сначала наши числа, ниже
    # их проверка. Блок внутри панели tep, а не на «Вводных».
    tep = page.index('<div id="tep" class="panel">')
    vri = page.index('<div id="vri" class="panel">')
    start = page.find('id="glavapuScenarioBox"')
    assert tep < page.find('class="teptable"', tep) < start < vri
    block = page[start:page.find('id="glavapuScenarioSummary"', start)]
    assert 'onclick="glavapuScenarioCheck()"' in block
    # Полная таблица — окном (решение владельца, 06.10.2026); окно само не
    # всплывает: открывается только кнопкой итога.
    dialog = page.index('id="glavapuScenarioDialog"')
    assert dialog < page.index('id="glavapuScenarioResult"') < page.index("</div>", dialog) + 2000
    assert 'id="glavapuScenarioResult"' not in block
    check = page[page.index("async function glavapuScenarioCheck("):
                 page.index("function glavapuScenarioSummaryHtml(")]
    assert "openGlavapuScenario()" not in check
    assert "function glavapuScenarioCheck(" in page
    assert "fetch('/glavapu/scenario'" in page


def test_a_foreign_key_does_not_reach_the_disk(core) -> None:
    """Ключ из адреса — только хэш; путь за каталог заданий не выводится."""
    from fastapi import HTTPException
    for bad in ("../../etc/passwd", "..", "abc", "ABCDEF0123", "0123abcd/../x"):
        with pytest.raises(HTTPException) as err:
            core.glavapu_scenario_state(bad)
        assert err.value.status_code == 400
        with pytest.raises(ValueError):
            core._glavapu_scenario_file(bad)
    with pytest.raises(HTTPException) as err:
        core.glavapu_scenario_state("0123456789abcdef0123")
    assert err.value.status_code == 404


def test_a_missing_vri_fee_is_named_as_missing(core, monkeypatch) -> None:
    """Нет нашей платы за ВРИ — причина говорит «не задана», а не «задана вводными»."""
    calls: list = []
    monkeypatch.setattr(core, "_glavapu_headless_run", _fake_run(calls))
    inputs, tep = _nagatino()
    inputs.pop("land_rights_cost_mln", None)
    inputs.pop("vri_required", None)
    req = core.GlavapuScenarioRequest(inputs=inputs, tep=tep)
    core.glavapu_scenario_check(req)
    rows = {r["kind"]: r for r in _wait_done(core, req)["comparison"]["rows"]}
    row = rows["vri_cost_mln"]
    assert row["status"] == "ours_missing" and "не задана" in row["reason"]
    assert "от постоянных" in rows["parking.guest"]["reason"]


def test_money_and_parking_are_compared_by_kind(core, monkeypatch) -> None:
    """Компенсация суммой, места по ВРИ, плата за ВРИ по видам, баланс."""
    calls: list = []
    monkeypatch.setattr(core, "_glavapu_headless_run", _fake_run(calls))
    inputs, tep = _nagatino()
    inputs = dict(inputs, social_compensation_mln=1500.0)
    req = core.GlavapuScenarioRequest(inputs=inputs, tep=tep)
    core.glavapu_scenario_check(req)
    rows = {r["kind"]: r for r in _wait_done(core, req)["comparison"]["rows"]}
    # Соцнагрузка: итог сравнивается, по объектам — как посчитал калькулятор.
    total = rows["social_comp.total"]
    assert total["ours"] == 1500.0 and total["glavapu"] == 0.0 and total["status"] == "diff"
    assert "сверх потребности" in total["reason"]
    assert rows["social_comp.school"]["glavapu"] == pytest.approx(-3799.372)
    assert rows["social_comp.school"]["status"] == "reference"
    # Приобъектные по ВРИ: офис и ТЦ — каждый со своей строкой нормы.
    office, retail = rows["parking_vri.4_1.attached"], rows["parking_vri.4_2.attached"]
    assert office["glavapu"] == 199 and retail["glavapu"] == 233
    assert office["ours"] is not None and "parking_demand" in office["ours_origin"]
    assert rows["parking_vri.built_in.attached"]["glavapu"] == 21
    # ВРИ по видам и льготы — по названиям строк калькулятора, справочно.
    assert rows["vri.44"]["label"] == "Многоквартирная жилые здания"
    assert rows["vri.44"]["status"] == "reference"
    # Льготы калькулятор считает сам; его итог ВРИ — уже после них. Сверка
    # разводит «до льгот», «льгота» и «к оплате», чтобы не сравнить нашу
    # валовую плату с его чистой.
    assert rows["vri_cost_mln"]["glavapu"] == pytest.approx(14985.285)
    assert rows["vri_relief.mpt"]["glavapu"] == pytest.approx(1264.781)
    assert rows["vri_relief.mpt"]["status"] == "reference"
    relief = rows["vri_relief.total"]
    assert relief["status"] == "ours_missing" and "не задана" in relief["reason"]
    assert "МПТ" in relief["reason"]
    # Кзатр калькулятора расходится с приказом — и это сказано числом.
    assert "1,2036" in relief["reason"] and "138,11132" in relief["reason"]
    assert rows["vri_net_mln"]["glavapu"] == pytest.approx(13720.504)
    assert not any(k.startswith("vri.5") for k in rows), "льготы не числятся видами ВРИ"
    # Баланс территории — как калькулятор разложил её под наше соотношение.
    # Нули калькулятора по видам ВРИ — не строки, а шум: их нет.
    assert "vri.45" not in rows and "vri.53" not in rows
    assert "соцобъект" in rows["parking_vri.3_5.attached"]["reason"]
    assert rows["balance.12"]["glavapu"] == pytest.approx(7.659)
    assert rows["balance.14"]["status"] == "reference"
    groups = list(dict.fromkeys(r["group"] for r in rows.values()))
    assert groups.index("Соцнагрузка, млн ₽") < groups.index("Машино-места по видам") \
        < groups.index("Машино-места по ВРИ")


class _FakePage:
    """Страница калькулятора для `verify`: таблица и ползунок — что скажем."""

    def __init__(self, rows: dict[str, str], slider: dict | None) -> None:
        self.rows, self.slider = rows, slider

    def evaluate(self, script: str):
        if script == gs.READ_ROWS_JS:
            return self.rows
        if script == gs.RATIO_SLIDER_JS:
            return self.slider
        return [] if script == gs.PANEL_ERRORS_JS else {}


def test_a_slider_off_the_table_is_refused() -> None:
    """Контрпример: ползунок стоит не там, куда показывает таблица."""
    params = {"area_ha": 14.62, "spp_residential_ths": 229.49, "vpp_pct": 6.0,
              "spp_nonres_ths": 185.69, "nonres": [], "social": []}
    rows = {"1": "14,62", "6": "438,069", "7": "229,505", "7.2": "13,769", "8.1": "185,676"}
    good = gs.ScenarioStep()
    gs.verify(_FakePage(rows, {"value": "52.39", "text": "Жилые 52.39%, Нежилые 47.61%"}),
              params, good)
    assert not good.refused and any(x["param"] == "ratio" for x in good.applied)
    bad = gs.ScenarioStep()
    gs.verify(_FakePage(rows, {"value": "100", "text": "Жилые 100%, Нежилые 0%"}), params, bad)
    [refused] = bad.refused
    assert refused["param"] == "ratio" and "Жилые 100%" in refused["reason"]
    missing = gs.ScenarioStep()
    gs.verify(_FakePage(rows, None), params, missing)
    assert missing.refused[0]["reason"].startswith("ползунка нет")


def test_our_relief_is_compared_and_the_net_fee_follows(core, monkeypatch) -> None:
    """Наша льгота (доля от платы) против льгот калькулятора; к оплате — разность."""
    calls: list = []
    monkeypatch.setattr(core, "_glavapu_headless_run", _fake_run(calls))
    inputs, tep = _nagatino()
    inputs = dict(inputs, land_rights_cost_mln=15000.0, vri_required=True,
                  vri_relief_mode="percent", vri_relief_pct=10.0)
    req = core.GlavapuScenarioRequest(inputs=inputs, tep=tep)
    core.glavapu_scenario_check(req)
    rows = {r["kind"]: r for r in _wait_done(core, req)["comparison"]["rows"]}
    assert rows["vri_cost_mln"]["ours"] == 15000.0 and rows["vri_cost_mln"]["status"] == "match"
    assert rows["vri_relief.total"]["ours"] == 1500.0
    assert rows["vri_relief.total"]["glavapu"] == pytest.approx(1264.781)
    assert rows["vri_net_mln"]["ours"] == 13500.0
    assert rows["vri_net_mln"]["glavapu"] == pytest.approx(13720.504)


def test_flats_passed_to_the_city_are_named_as_not_sent() -> None:
    inputs, tep = _nagatino()
    tep = copy.deepcopy(tep)
    tep["apartments"]["transfer"] = 4000.0
    scenario = gs.build_scenario(inputs, tep, numbers=NUMBERS)
    assert any(i["param"] == "benefit_for_flats" and "4 000" in i["reason"]
               for i in scenario["not_sent"])

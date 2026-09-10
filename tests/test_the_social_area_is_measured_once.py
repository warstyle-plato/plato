"""Метры соцобъекта меряются одним ответом на всех поверхностях.

«Зачем движку площадь СОШ? она же в бюджет ложится по нормативу места»
(владелец, 03.09.2026) и его же решение по разбору: «логику, что бюджет
стройки берётся от места, а не от ГНС, сохраняем; ГНС нам нужен для контроля
общей площади». То есть у соцобъекта два разных числа: бюджет идёт от МЕСТ,
площадь — для контроля объёма застройки. Путать их нельзя, но и считать
площадь двумя способами тоже.

А считали именно двумя. Страница брала ступень РНГП по ёмкости здания
(ДОО 27/18/16, СОШ 18/15/13), движок очередей — зашитые 12 и 13 м²/место,
которые НИЖЕ городского минимума в любой ёмкости. Один и тот же садик получал
разный ТЭП в зависимости от того, считают проект одной очередью или
несколькими, и обе цифры выглядели одинаково достоверно. Ещё и ГНС соцстроки
в очереди был нулём — строительный объём очереди занижался ровно на объект,
который она строит.

Запуск: python3 -m pytest tests/test_the_social_area_is_measured_once.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main as _wrapper  # noqa: E402

core = _wrapper.core


def test_the_answer_is_declared_once():
    """Одна функция на все поверхности, и поля соцобъекта перечислены при ней."""
    assert set(core.SOCIAL_TEP_FIELDS) == {"kindergarten", "school", "clinic"}
    assert core.SOCIAL_TEP_FIELDS["school"] == (
        "school_places", "social_school_gba_sqm", "social_school_norm_sqm")


def test_the_requirement_of_the_contract_beats_the_norm():
    """Договор КРТ задаёт площадь — и она сама себе норматив: 5 000 ÷ 225."""
    x = {**core.DEFAULT_INPUTS, "social_area_source": "manual",
         "kindergarten_places": 225, "social_dou_gba_sqm": 5000}
    assert core.social_area_per_place(x, "kindergarten") == pytest.approx(22.22, abs=0.01)


def test_an_empty_field_falls_back_to_the_city_step():
    """Пустое поле — «не знаем», и тогда отвечает ступень РНГП по ёмкости."""
    x = {**core.DEFAULT_INPUTS, "school_places": 1000, "social_school_norm_sqm": 0}
    assert core.social_area_per_place(x, "school") == 15.0
    x["school_places"] = 1001
    assert core.social_area_per_place(x, "school") == 13.0
    x["school_places"] = 550
    assert core.social_area_per_place(x, "school") == 18.0


def test_zero_means_we_do_not_know_it():
    """У поликлиники норматива города нет: пустое поле даёт ноль, а не догадку."""
    x = {**core.DEFAULT_INPUTS, "clinic_capacity": 100, "social_clinic_norm_sqm": 0}
    assert core.social_area_per_place(x, "clinic") == 0.0


def test_no_default_is_below_the_city_minimum():
    """12 и 13 м²/место были НИЖЕ минимума РНГП в любой ёмкости — их больше нет."""
    for kind, key in (("kindergarten", "social_dou_norm_sqm"),
                      ("school", "social_school_norm_sqm")):
        value = float(core.DEFAULT_INPUTS[key] or 0.0)
        if value <= 0:
            continue  # ноль — «считаем ступенью», а не заниженное число
        floor = min(step for _, step in core.MOSCOW_SOCIAL_AREA_PER_PLACE[kind])
        assert value >= floor, (kind, value, floor)


def test_the_steps_are_not_copied_by_hand():
    """Ступени РНГП объявлены один раз — копия расходится на границе.

    Шестым писателем строки был разбор свободного ТЭП: там стояло
    `27 if places < 125 else …` вместо `<= 125`, и садик ровно на 125 мест
    получал 18 м²/место при 27 у города. Поликлинике там же было приписано
    27 м² на посещение — числа, которого у города нет вовсе.
    """
    src = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    for _kind, steps in core.MOSCOW_SOCIAL_AREA_PER_PLACE.items():
        for limit, value in steps:
            if limit == float("inf"):
                continue
            # Само объявление под этот образец не подходит — там `125.0, 27.0`,
            # и цифра в «.0» рвёт `\D`. Значит любое совпадение — копия.
            stray = re.findall(rf"{int(limit)}\D{{0,12}}{int(value)}\b", src)
            assert stray == [], (limit, value, stray[:4])


def test_the_engine_does_not_hardcode_the_norm():
    """Зашитое число рядом с полем норматива — это второй ответ на тот же вопрос."""
    src = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    for key in ("social_dou_norm_sqm", "social_school_norm_sqm", "social_clinic_norm_sqm"):
        stray = re.findall(rf'"{key}"\s*,\s*\d', src)
        assert stray == [], (key, stray)


def _phased(**extra):
    inputs = {**core.DEFAULT_INPUTS, "social_mode": "Строительство",
              "kindergarten_places": 250, "school_places": 1000,
              "clinic_capacity": 0, **extra}
    return core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=core.TEP_DEFAULT, rates=[],
        phasing={"enabled": True, "user_enabled": True, "phase_count": 2,
                 "target_size_sqm": 70000, "phase_gap_months": 12,
                 "cost_inflation_pct": 0, "sales_price_inflation_pct": 0},
    )), inputs


def _social_row(bundle, kind):
    for phase in bundle["phases"]:
        row = (phase.get("tep") or {}).get(kind) or {}
        if float(row.get("units") or 0) > 0:
            return row
    return {}


def test_the_queue_measures_the_object_the_same_way():
    """Садик очереди — те же метры, что садик проекта: 250 × 18, а не 250 × 12."""
    bundle, inputs = _phased()
    row = _social_row(bundle, "kindergarten")
    per_place = core.social_area_per_place(inputs, "kindergarten")
    assert per_place == 18.0
    assert row["units"] == pytest.approx(250, abs=0.5)
    assert row["total_area"] == pytest.approx(250 * per_place, rel=1e-6)
    assert row["total_area"] > 250 * 12, "очередь снова считает по зашитым 12 м²/место"


def test_the_queue_object_has_its_own_gns():
    """Ноль в ГНС занижал строительный объём очереди ровно на объект, который она строит."""
    bundle, _ = _phased()
    row = _social_row(bundle, "school")
    share = float((core.TEP_RATIOS.get("apartments") or {}).get("total_of_gns") or 0.9)
    assert row["gns"] == pytest.approx(row["total_area"] / share, rel=1e-6)
    assert row["gns"] > row["total_area"]


def test_the_contract_requirement_reaches_the_queue():
    """Вписанная руками площадь доезжает до очереди, а не подменяется нормативом."""
    bundle, _ = _phased(social_area_source="manual", social_dou_gba_sqm=7000,
                        social_school_gba_sqm=0)
    row = _social_row(bundle, "kindergarten")
    assert row["total_area"] == pytest.approx(7000, rel=1e-6), row


def test_the_budget_still_comes_from_the_places():
    """Бюджет объекта — места × себестоимость места; площадь в него не входит."""
    small, _ = _phased(social_dou_gba_sqm=3000, social_area_source="manual")
    large, _ = _phased(social_dou_gba_sqm=9000, social_area_source="manual")

    def social_capex(bundle):
        return round(sum(
            float(((phase.get("result") or {}).get("summary") or {}).get("social_capex") or 0.0)
            for phase in bundle["phases"]), 2)

    assert social_capex(small) == social_capex(large), (
        "себестоимость соцобъекта поехала за площадью — она обязана идти от мест")


# --- одиночный расчёт: строка соцобъекта — производная, а не присланное ------
#
# Правило было закрыто у страницы и у движка очередей и осталось незакрытым у
# одиночного расчёта: он не считал строку ВОВСЕ и брал, что прислали. На
# умолчаниях `TEP_DEFAULT` нёс садику 3 000 м² (250 × 12 — те самые снятые
# 12 м²/место) и ГНС 0, а свод очередей на тех же вводных давал 4 500 и 5 000.
# Строительный объём расходился на 5 017 м², и на него делятся ВСЕ удельные
# показатели проекта.


def _single(stale=False, **extra):
    inputs = {**core.DEFAULT_INPUTS, "social_mode": "Строительство",
              "kindergarten_places": 250, **extra}
    tep = {key: dict(row) for key, row in core.TEP_DEFAULT.items()}
    if stale:
        # Ровно то, что лежало в `TEP_DEFAULT` и в сохранённых у людей
        # проектах: 250 × 12 м²/место и ГНС нулём.
        tep["kindergarten"].update({"total_area": 3000, "transfer": 3000, "gns": 0})
    result = core.calculate(core.CalcRequest(inputs=dict(inputs), tep=tep, rates=[]))
    rows = {row["key"]: row for row in result["tep"]["rows"]}
    return rows, result["summary"], inputs


def test_the_default_row_agrees_with_the_measurement():
    """Литерал `TEP_DEFAULT` — не пятое число: он равен тому, что считает движок."""
    measured = core.social_tep_row(core.DEFAULT_INPUTS, "kindergarten")
    row = core.TEP_DEFAULT["kindergarten"]
    for field in ("units", "total_area", "transfer", "gns"):
        assert float(row[field]) == pytest.approx(measured[field], rel=1e-6), field
    floor = min(step for _, step in core.MOSCOW_SOCIAL_AREA_PER_PLACE["kindergarten"])
    assert row["total_area"] / row["units"] >= floor, (
        "в умолчаниях снова стоит площадь ниже городского минимума")


def test_the_single_project_measures_the_object_too():
    """Садик проекта — 250 × 18 и ГНС по пропорции, а не присланные 3 000 и 0."""
    rows, _, inputs = _single(stale=True)
    per_place = core.social_area_per_place(inputs, "kindergarten")
    share = float((core.TEP_RATIOS.get("apartments") or {}).get("total_of_gns") or 0.9)
    row = rows["kindergarten"]
    assert row["total_area"] == pytest.approx(250 * per_place, rel=1e-6)
    assert row["gns"] == pytest.approx(250 * per_place / share, rel=1e-6)
    assert row["gns"] > 0, "у объекта, который проект строит, нет строительного объёма"


def test_the_input_reaches_the_row_of_the_single_project():
    """Правка площади во вводных двигает строку и строительный объём.

    Прежде не двигала ничего: одиночный расчёт строку не считал.
    """
    small_rows, small, _ = _single(social_area_source="manual", social_dou_gba_sqm=4500)
    large_rows, large, _ = _single(social_area_source="manual", social_dou_gba_sqm=9000)
    assert small_rows["kindergarten"]["total_area"] == pytest.approx(4500, rel=1e-6)
    assert large_rows["kindergarten"]["total_area"] == pytest.approx(9000, rel=1e-6)
    assert (large["construction_volume_sqm"] - small["construction_volume_sqm"]
            == pytest.approx(4500 / 0.9, rel=1e-6)), (
        "строительный объём не пошёл за площадью объекта")


def test_the_single_and_the_phased_answer_the_same():
    """Один и тот же садик не бывает разным оттого, как проект нарезан.

    Сверяется РАЗНИЦА строк, а не итог: подземный паркинг округляет места до
    целого в каждой очереди и на своде честно даёт на 17 м² больше, чем в
    одиночном расчёте. Это округление неделимого места, а не расхождение
    методики, — поэтому сверяются строки соцобъектов, где округлять нечего.
    """
    single_rows, _, _ = _single(school_places=1000)
    bundle, _ = _phased()
    consolidated = {row["key"]: row
                    for row in ((bundle["consolidated"].get("tep") or {}).get("rows") or [])}
    for kind in ("kindergarten", "school"):
        for field in ("units", "total_area", "transfer", "gns"):
            assert single_rows[kind][field] == pytest.approx(
                consolidated[kind][field], rel=1e-6), (kind, field)


def test_money_instead_of_a_building_leaves_no_metres():
    """Денежная компенсация — не объект: метры прежнего режима не строятся молча."""
    rows, _, _ = _single(social_mode="Денежная компенсация")
    assert rows["kindergarten"]["total_area"] == 0.0
    assert rows["kindergarten"]["gns"] == 0.0


def test_the_city_export_beats_the_proportion():
    """Выгрузка ГлавАПУ несёт СВОЮ СПП объекта — пропорция её не подменяет.

    Наземную площадь импорт кладёт во вводные (`social_dou_gba_sqm`), и она
    остаётся площадью объекта: норматив её не перебивает, потому что у города
    своя. ГНС при этом равен СПП выгрузки, а не «общая ÷ 0,9».
    """
    rows, _, _ = _single(social_dou_gba_sqm=5400, _glavapu_import={"normalized": {
        "actual_kindergarten_spp_sqm": 6100, "actual_kindergarten_np_sqm": 5400}})
    assert rows["kindergarten"]["gns"] == pytest.approx(6100, rel=1e-6)
    assert rows["kindergarten"]["total_area"] == pytest.approx(5400, rel=1e-6)


def test_the_export_area_is_split_between_the_queues():
    """СПП выгрузки — площадь объекта ПРОЕКТА: очередь берёт свою долю мест."""
    row = core.social_tep_row(
        {**core.DEFAULT_INPUTS, "social_mode": "Строительство",
         "kindergarten_places": 250,
         "_glavapu_import": {"normalized": {"actual_kindergarten_spp_sqm": 6100,
                                            "actual_kindergarten_np_sqm": 5400}}},
        "kindergarten", 100)
    assert row["gns"] == pytest.approx(6100 * 100 / 250, rel=1e-6)


def test_the_step_is_taken_from_the_size_of_the_building():
    """Ступень РНГП идёт от размера ЗДАНИЯ, а не от ёмкости очереди.

    Садик на 300 мест стоит 16 м²/место. Нарезанный пополам, он не становится
    двумя садиками по 150 мест с их 18 м²/место — здание одно.
    """
    inputs = {**core.DEFAULT_INPUTS, "social_mode": "Строительство",
              "kindergarten_places": 300, "social_dou_norm_sqm": 0}
    whole = core.social_tep_row(inputs, "kindergarten")
    half = core.social_tep_row(inputs, "kindergarten", 150)
    assert whole["total_area"] == pytest.approx(300 * 16.0, rel=1e-6)
    assert half["total_area"] == pytest.approx(whole["total_area"] / 2, rel=1e-6)


def test_a_split_building_keeps_its_own_step():
    """Садик на 300 мест, разложенный по двум очередям, остаётся ОДНИМ зданием.

    Ступень РНГП идёт от размера здания: 300 мест — 16 м²/место. Пока очередь
    не несла ёмкость здания, повторный расчёт по её вводным брал ступень по её
    доле (150 мест — 18), и сумма очередей выходила 5 400 м² при 4 800 у
    проекта — то есть очереди строили больше, чем проект.
    """
    inputs = {**core.DEFAULT_INPUTS, "social_mode": "Строительство",
              "kindergarten_places": 300, "social_dou_gba_sqm": 0,
              "social_dou_norm_sqm": 0}
    whole = core.social_tep_row(inputs, "kindergarten")
    assert whole["total_area"] == pytest.approx(300 * 16.0, rel=1e-6)
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=dict(inputs), tep=core.TEP_DEFAULT, rates=[],
        phasing={"enabled": True, "phase_count": 2, "phase_gap_months": 24,
                 "phases": [{"name": "О1", "start_offset_months": 0},
                            {"name": "О2", "start_offset_months": 24}],
                 "social_objects": [
                     {"type": "kindergarten", "capacity": 150, "phase": 1},
                     {"type": "kindergarten", "capacity": 150, "phase": 2}]}))
    parts = 0.0
    for phase in bundle["phases"]:
        rows = {row["key"]: row
                for row in (((phase.get("result") or {}).get("tep") or {}).get("rows") or [])}
        parts += float(rows["kindergarten"]["total_area"])
    assert parts == pytest.approx(whole["total_area"], rel=1e-6), (
        "очереди построили садик больше, чем проект")


def test_a_stale_norm_field_does_not_beat_the_city():
    """В режиме «по нормативу» поле показывает норматив, а не спорит с ним.

    Оставшиеся в поле 12 м²/место — ниже городского минимума в любой ёмкости;
    «руками» выражается признаком `social_area_source`, а не числом в поле.
    Проверяется и сам ответ «м² на место»: книга печатает норматив им же, и
    два ответа разошлись бы — страница переписывает поле на ступень РНГП, а
    движок читал бы прежнее.
    """
    stale = {**core.DEFAULT_INPUTS, "social_mode": "Строительство",
             "kindergarten_places": 250, "social_dou_norm_sqm": 12}
    assert core.social_area_per_place(stale, "kindergarten") == 18.0
    row = core.social_tep_row(stale, "kindergarten")
    assert row["total_area"] == pytest.approx(250 * 18.0, rel=1e-6)


def test_the_metres_per_place_are_answered_once():
    """`social_tep_row` не считает метры на место сам — зовёт единственный ответ."""
    import inspect

    body = inspect.getsource(core.social_tep_row)
    assert "social_area_per_place(" in body, "снова свой порядок приоритетов"


def test_the_screening_gives_the_object_its_volume():
    """Скрининг КРТ писал площадь и НЕ писал ГНС: объект строился без объёма."""
    src = (ROOT / "auction_search" / "krt_screening.py").read_text(encoding="utf-8")
    assert "core.social_tep_row(" in src, "скрининг снова считает строку сам"
    assert '"total_area": area, "transfer": area, "units": places' not in src


# --- пятый писатель: страница ------------------------------------------------
#
# `syncTep` считает ту же строку своим кодом — иначе нельзя, JS движка не
# зовёт. Значит числа, из которых он считает, приходят из движка подстановкой
# (`TEP_RATIOS`, `SOCIAL_AREA_STEPS`), а совпадение ОТВЕТОВ проверяется здесь:
# в исходнике сломанная и починенная страница выглядят одинаково.

_PAGE_CASES = [
    ("норматив, садик 250", {"kindergarten_places": 250}, "kindergarten"),
    ("норматив, садик 300 — ступень 16", {"kindergarten_places": 300}, "kindergarten"),
    ("норматив, садик 100 — ступень 27", {"kindergarten_places": 100}, "kindergarten"),
    ("норматив, школа 1000", {"school_places": 1000}, "school"),
    ("норматив, школа 1200 — ступень 13", {"school_places": 1200}, "school"),
    ("требование КРТ", {"kindergarten_places": 225, "social_dou_gba_sqm": 5000,
                        "social_area_source": "manual"}, "kindergarten"),
    ("поликлиника — норматива города нет", {"clinic_capacity": 100,
                                            "social_clinic_norm_sqm": 15}, "clinic"),
    ("выгрузка ГлавАПУ", {"kindergarten_places": 250, "social_dou_gba_sqm": 5400,
                          "_glavapu_import": {"normalized": {
                              "actual_kindergarten_spp_sqm": 6100,
                              "actual_kindergarten_np_sqm": 5400}}}, "kindergarten"),
    ("денежная компенсация", {"kindergarten_places": 250,
                              "social_mode": "Денежная компенсация"}, "kindergarten"),
]


def test_in_a_real_browser_the_page_answers_the_same(tmp_path):
    """Страница и движок отвечают одно и то же о метрах соцобъекта."""
    playwright = pytest.importorskip("playwright.sync_api")
    sys.path.insert(0, str(ROOT))
    import browser_launch

    html = tmp_path / "page.html"
    html.write_text(core.PAGE.replace("__DEVELOPAID_VERSION__", "test"), encoding="utf-8")
    cases = [{"name": name, "patch": {"social_mode": "Строительство", **patch}, "kind": kind}
             for name, patch, kind in _PAGE_CASES]
    with playwright.sync_playwright() as pw:
        try:
            browser = browser_launch.launch(pw)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page()
            tab.route("**/*", lambda route: route.abort()
                      if route.request.url.startswith("http") else route.continue_())
            tab.goto(html.as_uri())
            tab.wait_for_function("() => typeof syncTep === 'function'", timeout=15000)
            said = tab.evaluate("""(cases) => cases.map(item => {
              inputs = cloneValue(INPUT_DEFAULT);
              tep = cloneValue(TEP_DEFAULT);
              Object.assign(inputs, item.patch);
              syncTep(false);
              const row = tep[item.kind] || {};
              return {name: item.name, units: Number(row.units||0),
                      total_area: Number(row.total_area||0),
                      transfer: Number(row.transfer||0), gns: Number(row.gns||0)};
            })""", cases)
        finally:
            browser.close()

    assert len(said) == len(cases)
    for item, page_row in zip(cases, said):
        inputs = {**core.DEFAULT_INPUTS, "kindergarten_places": 0, "school_places": 0,
                  "clinic_capacity": 0, "social_dou_gba_sqm": 0,
                  "social_school_gba_sqm": 0, "social_clinic_gba_sqm": 0,
                  **item["patch"]}
        engine = core.social_tep_row(inputs, item["kind"])
        for field in ("units", "total_area", "transfer", "gns"):
            assert page_row[field] == pytest.approx(engine[field], rel=1e-6), (
                item["name"], field, page_row[field], engine[field])

"""Благоустройство меряется площадью ДВОРА, а не строительным объёмом.

«Благоустройство — 5 метров на человека, далее по площади комфорт 10, бизнес
25, элитный 50 на метр» (решение владельца, 10.09.2026). Прежняя ставка 11,5
тыс ₽ умножалась на строительный объём: на умолчаниях это 2 060,2 млн ₽ против
121,2 по норме — в семнадцать раз больше. Число было посчитано верно и
прочитано неверно, потому что подпись звала базу «строительный объём», а
благоустраивают двор.

Мера одна — м² на человека, — и заданная руками площадь приводится к ней: тогда
очередь считает свою площадь своим населением, и сумма очередей сходится с
проектом без второго списка «что делить долями».

Запуск: python3 -m pytest tests/test_landscaping_is_measured_by_the_yard.py -q
"""

from __future__ import annotations

import copy
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402
import page_blocks  # noqa: E402


def _tep():
    return copy.deepcopy(core.TEP_DEFAULT)


def _single(**extra):
    inputs = {**core.DEFAULT_INPUTS, **extra}
    return core.calculate(core.CalcRequest(inputs=inputs, tep=_tep(), rates=[]))


def _phased(count: int, **extra):
    inputs = {**core.DEFAULT_INPUTS, **extra}
    return core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=_tep(), rates=[],
        phasing={"enabled": True, "phase_count": count, "phase_gap_months": 24}))


def test_the_area_is_the_population_times_the_norm():
    result = _single()
    summary = result["summary"]
    # 80 000 м² квартир ÷ 33 = 2 425 человек; 5 м² на человека.
    assert summary["landscaping_area_sqm"] == pytest.approx(2425 * 5)
    assert "2425 чел" in summary["landscaping_basis"], summary["landscaping_basis"]
    assert result["capex"]["landscaping"] == pytest.approx(2425 * 5 * 10 * 1000)


def test_the_rate_follows_the_class():
    """Ставка класса — 10 / 25 / 50, и на странице копии её нет."""
    rates = {key: preset["landscaping_th_per_sqm"]
             for key, preset in core.PROJECT_CLASS_PRESETS.items()}
    assert rates == {"comfort": 10, "business": 25, "elite": 50}
    for key, rate in rates.items():
        preset = {k: v for k, v in core.PROJECT_CLASS_PRESETS[key].items() if k != "label"}
        money = _single(project_class=key, **preset)["capex"]["landscaping"]
        assert money == pytest.approx(2425 * 5 * rate * 1000), key


def test_the_base_is_not_the_construction_volume():
    """Сторож, не падающий на прежней базе, — не сторож.

    Прежняя база дала бы на умолчаниях 1,79 млн м² × ставку: разница в
    семнадцать раз, и на экране она выглядела бы обычным числом.
    """
    result = _single()
    volume = result["summary"]["construction_volume_sqm"]
    assert volume > 100_000, volume
    assert result["summary"]["landscaping_area_sqm"] < volume / 10, (
        "база благоустройства подозрительно похожа на строительный объём")


def test_a_given_area_wins_over_the_norm():
    result = _single(landscaping_area_sqm=20_000)
    assert result["summary"]["landscaping_area_sqm"] == pytest.approx(20_000, rel=1e-9)
    assert "задана площадь" in result["summary"]["landscaping_basis"]


def test_the_queues_do_not_landscape_the_same_yard_twice():
    """Заданная площадь — величина ПРОЕКТА: оставленная очереди целиком, она
    благоустроила бы один двор столько раз, сколько очередей."""
    project = _single(landscaping_area_sqm=20_000)["summary"]["landscaping_area_sqm"]
    per_person, _ = core.landscaping_area_per_person(
        {**core.DEFAULT_INPUTS, "landscaping_area_sqm": 20_000}, core.TEP_DEFAULT)
    for count in (2, 3, 4):
        total = _phased(count, landscaping_area_sqm=20_000)["consolidated"]["summary"][
            "landscaping_area_sqm"]
        # Население очереди округляется ВВЕРХ — человек неделим, — и сумма
        # очередей выходит больше проектной не более чем на одного человека с
        # очереди. Это округление неделимого, а не расхождение методики.
        assert total >= project
        assert total - project <= per_person * count, (count, total, project)


def test_the_norm_path_also_adds_up_by_queues():
    project = _single()["summary"]["landscaping_area_sqm"]
    total = _phased(3)["consolidated"]["summary"]["landscaping_area_sqm"]
    assert total == pytest.approx(project, rel=1e-6)


def test_the_region_norm_is_declared_once():
    """Население — от площади квартир нормой региона, и норма не копия."""
    msk = core.project_population(core.TEP_DEFAULT, "msk")
    mo = core.project_population(core.TEP_DEFAULT, "mo")
    assert msk[0] == 2425 and "945-ПП" in msk[1]
    assert mo[0] == 2858 and "РНГП" in mo[1]
    assert str(int(core._PARKING_2118_SQM_PER_PERSON)) in msk[1]
    assert str(int(core.MO_NORMS_DEFAULT["living_space_per_person_sqm"])) in mo[1]


def test_the_fields_name_their_base():
    """Подпись ставки называет свою базу: на прежней стояло «строительного
    объёма», и человек вписал бы ставку на метр двора."""
    hints = {field[0]: field[2] for group in core.FIELD_GROUPS for field in group[1]
             if str(field[0]).startswith("landscaping")}
    assert set(hints) == {"landscaping_th_per_sqm", "landscaping_area_sqm",
                          "landscaping_area_per_person_sqm"}
    # Утверждение здесь — «подпись называет базой двор», а не «в подписи есть
    # такое-то слово»: заглавные буквы переехали с «БЛАГОУСТРОЕННОЙ» на «ДВОР»,
    # когда первая часть подсказки стала единицей в таблице классов, — и
    # проверка на форму записи упала бы на верном поведении.
    assert "благоустроенной территории" in hints["landscaping_th_per_sqm"].lower()
    # Запрещается МЕСТО, а не слово: прежняя подпись ОБЪЯВЛЯЛА базой
    # строительный объём, а нынешняя называет его, чтобы сказать «не он».
    assert "м² строительного объёма" not in hints["landscaping_th_per_sqm"]
    # Единица — первая часть подсказки, и она обязана быть единицей, а не
    # объяснением: её показывает таблица классов рядом с числом.
    assert core.class_field_unit("landscaping_area_per_person_sqm") == "м²/чел."
    assert core.class_field_unit("landscaping_th_per_sqm") == (
        "тыс. ₽/м² благоустроенной территории")


def test_the_workbook_reads_the_same_base():
    """Книга не придаток веб-сервиса: площадь двора она считает формулой."""
    openpyxl = pytest.importorskip("openpyxl")
    import v4_entry_sheet

    content, _name, report = core.build_project_workbook(
        dict(core.DEFAULT_INPUTS), _tep(), [], {}, project_name="Двор")
    assert not [one for one in (report.get("missing") or [])
                if "благоустрой" in str(one).lower()], report.get("missing")
    book = openpyxl.load_workbook(io.BytesIO(content))
    formula = book["CAPEX"]["B24"].value
    # База — население очереди, а не сумма трёх ГНС.
    queue_flats = v4_entry_sheet.rename_in_formula("'Вводные'!$L$88")
    assert "ROUNDUP" in formula and queue_flats in formula, formula
    assert v4_entry_sheet.rename_in_formula("'Вводные'!$I$88") not in formula, formula

    sys.setrecursionlimit(400_000)
    from xlsx_eval import Evaluator

    ev = Evaluator(book)
    engine = _single()["capex"]["landscaping"] / 1e6
    assert float(ev.cell("CAPEX", "B24")) == pytest.approx(engine, rel=1e-6)


def test_an_unrecognised_template_formula_is_named():
    """Не опознали формулу — это `missing`, а не тихий счёт по прежней базе."""
    missing: list[str] = []
    core._v4_apply_landscaping_base("<x:sheetData/>", "$B$1", "$B$2", missing)
    assert len(missing) == core._V4_CAPEX_PHASES, missing
    assert all("благоустрой" in one.lower() for one in missing), missing

def test_the_norm_lives_in_the_class_profile():
    """Методика — в настройках класса (владелец, 10.09.2026).

    Список полей окна — сам пресет, поэтому достаточно, чтобы норматив стоял в
    профиле каждого класса: он появится в таблице и станет перекрываемым
    личным значением, которое переживёт выпуск. База одна на все классы — 5
    м²/чел., как назвал владелец; заданная руками ПЛОЩАДЬ в профиль не идёт —
    она сильнее норматива и принадлежит участку, а не классу.
    """
    for key, preset in core.PROJECT_CLASS_PRESETS.items():
        assert preset["landscaping_area_per_person_sqm"] == pytest.approx(5.0), key
        assert "landscaping_area_sqm" not in preset, key
    # Умолчания движка и есть «Комфорт» — иначе расчёт на них покажет
    # отклонение от базы класса на ровном месте.
    assert core.DEFAULT_INPUTS["landscaping_area_per_person_sqm"] == pytest.approx(
        core.PROJECT_CLASS_PRESETS["comfort"]["landscaping_area_per_person_sqm"])
    # Сверка отклонений читает пресет, значит норматив попал и в неё — а с ним
    # обязана приехать единица: «5 → 8» без неё читается ставкой.
    changed = {**core.DEFAULT_INPUTS, "project_class": "comfort",
               "landscaping_area_per_person_sqm": 8.0}
    rows = core.project_class_deviations(changed)["rows"]
    assert [one["field"] for one in rows] == ["landscaping_area_per_person_sqm"]
    assert rows[0]["unit"] == "м²/чел." and rows[0]["base"] == pytest.approx(5.0)


def test_the_units_are_declared_once_and_reach_the_page():
    """Единицу считает движок, страница берёт готовую карту подстановкой.

    Свой разрез подсказки на JS был бы второй реализацией одного правила, и
    разошлись бы они молча. Проверяется собранная страница: плейсхолдер там
    уже подставлен, а литерала единицы в ней быть не должно.
    """
    units = core.class_field_units()
    keys = {field for preset in core.PROJECT_CLASS_PRESETS.values()
            for field in preset if field != "label"}
    assert set(units) == keys, (set(units) ^ keys)
    page = core.PAGE
    assert core.CLASS_FIELD_UNITS_PLACEHOLDER not in page
    assert json.dumps(units, ensure_ascii=False) in page
    # Разреза подсказки на странице нет — он объявлен один раз, в движке.
    assert "classFieldHint" not in page
    body = page_blocks.function("classFieldUnit", page)
    assert "CLASS_FIELD_UNITS[k]" in body.replace(" ", ""), body


def test_the_class_window_shows_the_norm_with_its_unit():
    """Проверяется то, что видно: строка норматива в таблице классов и единица.

    Строковой проверки тут мало — таблицу рисует `renderClassDialog` по
    подставленному пресету, и вопрос ровно в том, что человек увидит, открыв
    окно. Профиль был весь в тыс ₽: бесподписное 5 рядом с 10/25/50 читается
    как ставка.
    """
    chrome = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    if not chrome.exists():
        pytest.skip("chromium в образе не найден")
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        pytest.skip("playwright недоступен")

    import threading
    import time

    import uvicorn

    import main as _wrapper

    config = uvicorn.Config(_wrapper.app, host="127.0.0.1", port=18746, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(400):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "локальный сервер не поднялся"

    read_rows = r"""() => [...document.querySelectorAll('#classDialogBody tr')].map(row => {
      const first = row.querySelector('input');
      const key = first
        ? (/'([a-z0-9_]+)',this\.value/.exec(first.getAttribute('onchange') || '') || [])[1]
        : null;
      return {key, label: (row.querySelector('td') || {}).innerText || '',
              values: [...row.querySelectorAll('input')].map(one => one.value)};
    }).filter(one => one.key)"""

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chrome))
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto("http://127.0.0.1:18746/", wait_until="networkidle")
            page.evaluate("openClassDialog()")
            rows = page.evaluate(read_rows)
            # Норматив применяется вместе с классом — как и всякое поле профиля.
            page.evaluate("inputs.landscaping_area_per_person_sqm=99")
            page.evaluate("applyProjectClassPreset('elite')")
            applied = page.evaluate("inputs.landscaping_area_per_person_sqm")
            # Личное значение класса сильнее общей базы.
            page.evaluate("setClassBase('elite','landscaping_area_per_person_sqm',8)")
            page.evaluate("applyProjectClassPreset('elite')")
            owned = page.evaluate("inputs.landscaping_area_per_person_sqm")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert not errors, errors
    by_key = {one["key"]: one for one in rows}
    norm = by_key.get("landscaping_area_per_person_sqm")
    assert norm, f"строки норматива в окне нет: {sorted(by_key)}"
    assert norm["values"][:3] == ["5", "5", "5"], norm
    assert "м²/чел." in norm["label"], norm["label"]
    # Единица стоит у КАЖДОЙ строки: одна подписанная среди восьми безымянных
    # читается как исключение, а не как мера.
    for key, row in by_key.items():
        assert core.class_field_unit(key) in row["label"], (key, row["label"])
    assert applied == pytest.approx(5.0), applied
    assert owned == pytest.approx(8.0), owned

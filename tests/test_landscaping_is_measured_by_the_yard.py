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
    # 80 000 м² квартир ÷ 33 = 2 425 человек. Норма берётся у умолчаний, а не
    # пишется числом: пример, взятый у умолчания, умирает вместе с его правкой,
    # а утверждение здесь — «площадь есть население × норма», а не «норма 5».
    norm = core.DEFAULT_INPUTS["landscaping_area_per_person_sqm"]
    assert summary["landscaping_area_sqm"] == pytest.approx(2425 * norm)
    assert "2425 чел" in summary["landscaping_basis"], summary["landscaping_basis"]
    rate = core.DEFAULT_INPUTS["landscaping_th_per_sqm"]
    assert result["capex"]["landscaping"] == pytest.approx(2425 * norm * rate * 1000)


def test_the_class_sets_both_the_yard_and_its_rate():
    """Класс различает И площадь двора, И ставку метра (владелец, 12.09.2026:
    «Ставка разная как и площадь — 5-15-20, 15-35-50»).

    Прежде по классу шла одна ставка 10/25/50 при общих 5 м²/чел — то есть
    предполагалось, что у элитки двор такой же, как у комфорта, просто дороже
    замощён. Владелец поправил: у бизнеса и элита двора БОЛЬШЕ, а метр его
    стоит около сорока тысяч, а не десяти.
    """
    profile = {key: (preset["landscaping_area_per_person_sqm"],
                     preset["landscaping_th_per_sqm"])
               for key, preset in core.PROJECT_CLASS_PRESETS.items()}
    # Комфорт — 11 м²/чел., а не 5: прежняя норма была придумана и на
    # умолчаниях давала 1 251 ₽/м² ГНС там, где прямой замер комфорта
    # (core-xp-moscow-comfort-2024-09, 4 500 ₽/м² продаваемой) даёт 2 718.
    assert profile == {"comfort": (11, 15), "business": (15, 35), "elite": (20, 50)}
    # Лестница монотонна по ОБЕИМ величинам. Свод «Статистики» для комфорта
    # (5 782,6 ₽/м² ГНС) её ломает: чтобы его воспроизвести, комфортный двор
    # должен стать 23,1 м²/чел. — больше элитных 20. Потому и взят не он.
    ladder = [profile[key] for key in ("comfort", "business", "elite")]
    assert [item[0] for item in ladder] == sorted(item[0] for item in ladder)
    assert [item[1] for item in ladder] == sorted(item[1] for item in ladder)
    for key, (per_person, rate) in profile.items():
        preset = {k: v for k, v in core.PROJECT_CLASS_PRESETS[key].items() if k != "label"}
        money = _single(project_class=key, **preset)["capex"]["landscaping"]
        assert money == pytest.approx(2425 * per_person * rate * 1000), key
    # Умолчания движка и есть комфорт: иначе расчёт на них покажет отклонение
    # от базы класса на ровном месте.
    assert (core.DEFAULT_INPUTS["landscaping_area_per_person_sqm"],
            core.DEFAULT_INPUTS["landscaping_th_per_sqm"]) == profile["comfort"]


def test_the_base_is_not_the_construction_volume():
    """Сторож, не падающий на прежней базе, — не сторож.

    Прежняя база дала бы на умолчаниях 1,79 млн м² × ставку: разница в
    семнадцать раз, и на экране она выглядела бы обычным числом.
    """
    result = _single()
    volume = result["summary"]["construction_volume_sqm"]
    assert volume > 100_000, volume
    # Порогом «меньше десятой доли объёма» это держать нельзя: он был верен
    # ровно при норме 5 м²/чел. и упал на её законной правке до 11, ничего не
    # сказав о том, что сломалось (ничего). Утверждение здесь — площадь равна
    # населению × норму и объёмом НЕ является; так оно и проверяется.
    norm = core.DEFAULT_INPUTS["landscaping_area_per_person_sqm"]
    area = result["summary"]["landscaping_area_sqm"]
    assert area == pytest.approx(2425 * norm)
    assert abs(area - volume) > volume * 0.5, (
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
    # Равенством целиком тут утверждать нечего: проверка падала бы, когда рядом
    # что-то ДОБАВИЛИ, а не когда что-то сломали, — так она и упала на второй
    # мере статьи. Утверждение у неё другое: у КАЖДОГО поля благоустройства
    # подпись называет свою базу, и двух полей под одной базой нет.
    assert {"landscaping_th_per_sqm", "landscaping_area_sqm",
            "landscaping_area_per_person_sqm"} <= set(hints)
    bases = {"landscaping_th_per_sqm": "благоустроенной территории",
             "landscaping_area_sqm": "нормативу класса",
             "landscaping_area_per_person_sqm": "м²/чел.",
             "landscaping_gns_th_per_sqm": "наземной части"}
    assert set(hints) <= set(bases), (
        "у поля благоустройства нет названной базы: " + str(set(hints) - set(bases)))
    for field, base in bases.items():
        if field in hints:
            assert base in hints[field], (field, hints[field])
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
    # Сумма ГНС в формуле СНОВА есть — у статьи вторая мера, ставка на метр
    # наземной части (просьба владельца, 14.09.2026), — но базой двора она не
    # стала: стоит она только внутри `IF` по заданной ставке. Доказывает это не
    # текст, а счёт ниже: при пустой ставке книга обязана дать двор.
    above = v4_entry_sheet.rename_in_formula("'Вводные'!$I$88")
    assert "IF(" in formula, formula
    assert above not in formula[:formula.index("IF(")], formula

    sys.setrecursionlimit(400_000)
    from xlsx_eval import Evaluator

    ev = Evaluator(book)
    engine = _single()["capex"]["landscaping"] / 1e6
    assert float(ev.cell("CAPEX", "B24")) == pytest.approx(engine, rel=1e-6)


def test_an_unrecognised_template_formula_is_named():
    """Не опознали формулу — это `missing`, а не тихий счёт по прежней базе."""
    missing: list[str] = []
    core._v4_apply_landscaping_base("<x:sheetData/>", "$B$1", "$B$2", "$B$3", missing)
    assert len(missing) == core._V4_CAPEX_PHASES, missing
    assert all("благоустрой" in one.lower() for one in missing), missing

def test_the_norm_lives_in_the_class_profile():
    """Методика — в настройках класса (владелец, 10.09.2026).

    Список полей окна — сам пресет, поэтому достаточно, чтобы норматив стоял в
    профиле каждого класса: он появится в таблице и станет перекрываемым
    личным значением, которое переживёт выпуск. База у каждого класса своя;
    заданная руками ПЛОЩАДЬ в профиль не идёт —
    она сильнее норматива и принадлежит участку, а не классу.
    """
    # Площадь двора на человека — своя у каждого класса (владелец, 12.09.2026):
    # у бизнеса и элита двора больше, а не только метр дороже.
    for key, preset in core.PROJECT_CLASS_PRESETS.items():
        assert preset["landscaping_area_per_person_sqm"] > 0, key
        assert "landscaping_area_sqm" not in preset, key
    assert len({preset["landscaping_area_per_person_sqm"]
                for preset in core.PROJECT_CLASS_PRESETS.values()}) == 3, (
        "норматив снова одинаков у всех классов — класс перестал различать двор")
    # Умолчания движка и есть «Комфорт» — иначе расчёт на них покажет
    # отклонение от базы класса на ровном месте.
    assert core.DEFAULT_INPUTS["landscaping_area_per_person_sqm"] == pytest.approx(
        core.PROJECT_CLASS_PRESETS["comfort"]["landscaping_area_per_person_sqm"])
    # Сверка отклонений читает пресет, значит норматив попал и в неё — а с ним
    # обязана приехать единица: «5 → 8» без неё читается ставкой.
    base = core.PROJECT_CLASS_PRESETS["comfort"]["landscaping_area_per_person_sqm"]
    changed = {**core.DEFAULT_INPUTS, "project_class": "comfort",
               "landscaping_area_per_person_sqm": base + 3}
    rows = core.project_class_deviations(changed)["rows"]
    assert [one["field"] for one in rows] == ["landscaping_area_per_person_sqm"]
    assert rows[0]["unit"] == "м²/чел." and rows[0]["base"] == pytest.approx(base)


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
    import browser as browser_helper

    chrome = browser_helper.chromium_or_skip()
    from playwright.sync_api import sync_playwright

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
    expected = [str(core.PROJECT_CLASS_PRESETS[key]["landscaping_area_per_person_sqm"])
                for key in ("comfort", "business", "elite")]
    assert norm["values"][:3] == expected, norm
    assert "м²/чел." in norm["label"], norm["label"]
    # Единица стоит у КАЖДОЙ строки: одна подписанная среди восьми безымянных
    # читается как исключение, а не как мера.
    for key, row in by_key.items():
        assert core.class_field_unit(key) in row["label"], (key, row["label"])
    # Применяется норматив ВЫБРАННОГО класса, а не общее число: у элита
    # двор больше комфортного, и класс обязан это принести.
    assert applied == pytest.approx(
        core.PROJECT_CLASS_PRESETS["elite"]["landscaping_area_per_person_sqm"]), applied
    assert owned == pytest.approx(8.0), owned


def test_the_summary_of_statistics_is_not_pasted_into_a_field_of_another_base():
    """Свод меряет метр ГНС, а поле — метр двора: подставлять его нельзя.

    Кнопка «Вставить данные из статистики» писала его во все классы, и на
    экране 5,9 тыс ₽/м² выглядели ровно так же, как годная ставка (владелец,
    13.09.2026: «Почему тут 5.9? Мы же вроде не такие устанавливали»). Цена на
    умолчаниях бизнеса — 214,6 млн ₽ вместо 1 273,1, в шесть раз мимо.

    Отказ обязан НАЗЫВАТЬ причину: «нельзя» без «почему» чинят обходом, а
    обход выглядит правкой. И само число остаётся в ответе — оно ориентир
    порядка, просто в другой базе.
    """
    import developaid_cost_aggregation as agg

    for housing_class in ("comfort", "business", "elite"):
        answer = agg.build_cost_recommendation("Москва", housing_class)
        row = next(one for one in answer["recommendations"]
                   if one["key"] == "landscaping")
        assert row["recommended_rub_m2"] is not None, housing_class
        assert row["applyable"] is False, housing_class
        reason = row["not_applyable_reason"] or ""
        assert "двор" in reason and "ГНС" in reason, reason
        # В параметры модели статья не уезжает вовсе: там имена полей, и
        # попавшее туда число подставляется без единого вопроса.
        assert "landscaping_th_per_sqm" not in answer["model_parameters_th_rub_m2"]

    # Сторож обязан падать на подделке: совпади базы — статья снова
    # подставляема, и проверка выше значила бы ровно ничего.
    saved = dict(agg.MODEL_KEY_BASES)
    try:
        agg.MODEL_KEY_BASES.pop("landscaping_th_per_sqm", None)
        answer = agg.build_cost_recommendation("Москва", "comfort")
        row = next(one for one in answer["recommendations"]
                   if one["key"] == "landscaping")
        assert row["applyable"] is True
    finally:
        agg.MODEL_KEY_BASES.clear()
        agg.MODEL_KEY_BASES.update(saved)


def test_the_comfort_norm_reproduces_the_measured_comfort_source():
    """Комфортная норма сверена с прямым замером комфорта, а не со сводом.

    Свод по этой статье собран из ОДНОГО источника — Гродненская, класс
    business, 7 806,51 ₽/м² ГНС, — а комфортное его число это тот же источник,
    делённый на 1,35 из class_adjustments.json, где прямо написано «не
    статистическая оценка и не норматив». Воспроизвести его нормой нельзя, не
    сломав лестницу: комфортный двор пришлось бы поднять до 23,1 м²/чел., выше
    элитных 20.

    Прямой замер комфорта в источниках есть и в свод не попадает, потому что
    знаменатель у него другой: core-xp-moscow-comfort-2024-09, 4 000–5 000
    ₽/м² ПРОДАВАЕМОЙ. Норма сверяется с ним в его же мере.
    """
    source = json.loads((ROOT / "reference_data" / "statistics"
                         / "developaid_cost_structure.json").read_text(encoding="utf-8"))
    comfort = next(one for one in source["sources"]
                   if one.get("source_id") == "core-xp-moscow-comfort-2024-09")
    measured = comfort["components"]["landscaping"]
    assert measured["unit"] == "sellable", measured
    low = float(measured["value_low_rub_m2"]) / 1000.0
    high = float(measured["value_high_rub_m2"]) / 1000.0

    result = _single(project_class="comfort",
                     **{k: v for k, v in core.PROJECT_CLASS_PRESETS["comfort"].items()
                        if k != "label"})
    ours = float(result["summary"]["landscaping_per_saleable_th"])
    assert low <= ours <= high, (
        f"комфортная норма даёт {ours:.3f} тыс ₽/м² продаваемой при замере "
        f"{low:.1f}–{high:.1f}")

    # Сторож падает на прежней норме: 5 м²/чел. давали 2,07 — вдвое ниже
    # нижней границы замера, и это ровно та дыра, ради которой он написан.
    was = _single(project_class="comfort",
                  **{**{k: v for k, v in core.PROJECT_CLASS_PRESETS["comfort"].items()
                        if k != "label"},
                     "landscaping_area_per_person_sqm": 5})
    assert float(was["summary"]["landscaping_per_saleable_th"]) < low


def test_the_rate_per_metre_travels_as_a_pair():
    """Производную считает движок, и «на метр» живёт парой.

    Статья стоит на своей физической базе, а сравнивают её со сметой и со
    сводом на метр ГНС. Посчитанная на экране, производная была бы вторым
    счётом той же величины; одинокое «на метр» читается как другой показатель.
    """
    summary = _single()["summary"]
    gns = float(summary["landscaping_per_gns_th"])
    saleable = float(summary["landscaping_per_saleable_th"])
    money = float(_single()["capex"]["landscaping"])
    assert gns == pytest.approx(money / float(summary["project_gns_sqm"]) / 1000.0)
    assert saleable > gns > 0, (gns, saleable)


def test_the_page_skips_the_summary_it_may_not_paste():
    """Кнопка пропускает статью с чужой базой и называет это вслух.

    Молча пропущенная читается как «свода по ней нет», а подставленная молча
    уводит статью в шесть раз. Гоняется НАСТОЯЩАЯ функция страницы: строка
    пропуска есть в исходнике и у сломанного кода.
    """
    stand = """
    const PROJECT_CLASS_PRESETS={comfort:{label:'Комфорт',landscaping_th_per_sqm:15,main_above_th_per_sqm:110}};
    let CLASS_OVERRIDES={},CLASS_OVERRIDES_NOTE='',CLASS_STATS_BY={comfort:{recommendations:[
      {model_key:'landscaping_th_per_sqm',recommended_rub_m2:5782.6,applyable:false,
       not_applyable_reason:'свод меряет ₽/м² общей ГНС, а поле модели — м² двора'},
      {model_key:'main_above_th_per_sqm',recommended_rub_m2:120000,applyable:true}]}};
    const classBase=(c,k)=>PROJECT_CLASS_PRESETS[c][k];
    const classFieldLabel=k=>k;
    const renderProjectClassPreview=()=>{},renderClassDialog=()=>{};
    const activeSession=()=>false;let projectsAdminKey='';
    """
    tail = """
    fillClassesFromStats().then(()=>console.log(JSON.stringify(
      {overrides:CLASS_OVERRIDES,note:CLASS_OVERRIDES_NOTE})));
    """
    answer = page_blocks.run_json(stand, tail)
    assert "landscaping_th_per_sqm" not in (answer["overrides"].get("comfort") or {}), answer
    assert answer["overrides"]["comfort"]["main_above_th_per_sqm"] == 120, answer
    assert "landscaping_th_per_sqm" in answer["note"] and "двор" in answer["note"], answer

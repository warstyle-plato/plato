"""Строка ТЭП соцобъекта следует за вводными — на всех поверхностях.

Владелец (08.09.2026): «Получается что площади в водных в тэп по соц объектам
не синхронизированы никак». Так и было: у одного садика на 250 мест жило
ЧЕТЫРЕ ответа сразу.

  строка `TEP_DEFAULT`      3 000 м² — то есть 12 м²/место, ниже городского
                            минимума в любой ёмкости;
  поле «Вводных»            4 500 м² — 250 × 18 по ступени РНГП;
  страница (`syncTep`)      4 500 м² — она синхронизирует обе стороны;
  свод очередей             4 500 м² при ГНС 5 000, а у одиночного расчёта
                            ГНС соцстроки не было вовсе.

Расчёт СО СТРАНИЦЫ был верен — там синхронизирует `syncTep`. А тот же проект,
пришедший файлом, ссылкой, мостом КРТ или из бота, считался по строке, которая
с местами и площадью во «Вводных» не связана ничем: `syncTep` эти пути не
проходят. Одна и та же площадка давала разный строительный объём в зависимости
от того, одна у неё очередь или две — 179 144 против 197 494 м².

Правило то же, что у подземного паркинга: таблица приходит из браузера и бывает
устаревшей, поэтому `calculate` чинит строку из вводных ПЕРЕД каждым расчётом.
Ответ на «сколько метров у этого объекта» один — `social_tep_row`, — и
приоритет в нём по полю: руками > выгрузка ГлавАПУ > норматив.

Запуск: python3 -m pytest tests/test_social_rows_follow_the_inputs.py -q
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
from tests import page_blocks  # noqa: E402


def _inputs(**over):
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x["social_mode"] = "Строительство"
    x.update(over)
    return x


def _rows(result):
    return {row.get("key"): row for row in result["tep"]["rows"]}


def _single(inputs, tep=None):
    request = core.CalcRequest(inputs=copy.deepcopy(inputs),
                              tep=copy.deepcopy(tep or core.TEP_DEFAULT))
    return _rows(core.calculate(request))


def _stale_table():
    """Таблица, какой её присылает вкладка, открытая до починки.

    Пример строится здесь, а не берётся у `TEP_DEFAULT`: само умолчание с
    0.22.85 приведено к своим вводным той же функцией, и на нём проверять
    устаревшую строку стало нечем. Числа — те, что стояли в умолчании и на
    которые жаловался владелец: 3 000 м² на 250 мест (12 м² на место, ниже
    городского минимума в любой ёмкости) и ГНС 0.
    """
    stale = copy.deepcopy(core.TEP_DEFAULT)
    stale["kindergarten"].update(total_area=3000, transfer=3000, gns=0, units=250)
    return stale


def test_the_default_agrees_with_its_own_inputs():
    """Умолчание — тоже строка, и расходиться со своими вводными не вправе.

    `TEP_DEFAULT` нёс 3 000 м² при 4 500 во «Вводных» и нормативе 18 м² на
    место: пока страница не позвала `syncTep`, человек видел одно, а движок
    считал другое — подвал таблицы ТЭП расходился с отчётом на 5 000 м².
    """
    fresh = copy.deepcopy(core.TEP_DEFAULT)
    core.apply_social_tep_rows(copy.deepcopy(core.DEFAULT_INPUTS), fresh)
    for kind in core.SOCIAL_TEP_FIELDS:
        assert fresh[kind] == core.TEP_DEFAULT[kind], kind


def test_a_stale_table_does_not_decide_the_social_area():
    """Строка из браузера устарела — считает вводная, а не она.

    Это и есть та поломка, на которую жаловался владелец: вкладка присылает
    3 000 м² на 250 мест, и без починки расчёт шёл по ним.
    """
    stale = _stale_table()
    rows = _single(_inputs(kindergarten_places=250, social_dou_norm_sqm=18), stale)
    kindergarten = rows["kindergarten"]
    assert kindergarten["units"] == pytest.approx(250)
    assert kindergarten["total_area"] == pytest.approx(4500)
    # ГНС считается по той же пропорции, что и остальной ТЭП: ноль здесь
    # занижал бы строительный объём ровно на объект, который проект строит.
    assert kindergarten["gns"] > kindergarten["total_area"]
    # Соцобъект передаётся городу целиком: метры строятся и не продаются.
    assert kindergarten["saleable"] == pytest.approx(0)
    assert kindergarten["transfer"] == pytest.approx(kindergarten["total_area"])


def test_the_check_falls_over_when_the_repair_is_gone(monkeypatch):
    """Проверка, которая не падает на поломке, — не проверка.

    Снимаем починку и убеждаемся, что расчёт снова считает по устаревшей
    строке: иначе зелёный тест выше не значил бы ничего.
    """
    monkeypatch.setattr(core, "apply_social_tep_rows", lambda inputs, tep: None)
    rows = _single(_inputs(kindergarten_places=250, social_dou_norm_sqm=18),
                   _stale_table())
    assert rows["kindergarten"]["total_area"] == pytest.approx(3000), (
        "без починки строка обязана остаться устаревшей — иначе проверка "
        "выше сторожит не то")


def test_places_without_an_area_still_build_the_object():
    """Места ввели, площадь — нет: объект считается нормативом, а не нулём."""
    rows = _single(_inputs(school_places=800, social_school_gba_sqm=0,
                           social_school_norm_sqm=0))
    # 800 мест — ступень 15 м²/место (РНГП, редакция 2579-ПП).
    assert rows["school"]["total_area"] == pytest.approx(800 * 15)


def test_a_compensation_only_project_builds_nothing():
    """Форма «Компенсация» — объект не строится, и строка нулевая."""
    rows = _single(_inputs(kindergarten_places=250, social_mode="Компенсация"))
    assert rows["kindergarten"]["total_area"] == pytest.approx(0)
    assert rows["kindergarten"]["units"] == pytest.approx(0)


def test_the_krt_requirement_is_stronger_than_the_norm():
    """Вписанная руками площадь сильнее норматива — требование договора КРТ."""
    rows = _single(_inputs(kindergarten_places=250, social_dou_gba_sqm=5550,
                           social_area_source="manual"))
    assert rows["kindergarten"]["total_area"] == pytest.approx(5550)
    # Ноль в ручном режиме значит «объекта нет», а не «посчитай за меня».
    zero = _single(_inputs(kindergarten_places=250, social_dou_gba_sqm=0,
                           social_area_source="manual"))
    assert zero["kindergarten"]["total_area"] == pytest.approx(0)


def _phased(inputs, social_objects, phases=2):
    phasing = {"enabled": True, "step_months": 24,
               "phases": [{"name": f"О{i + 1}"} for i in range(phases)],
               "social_objects": social_objects}
    return core.calculate_phased(core.PhasedCalcRequest(
        inputs=copy.deepcopy(inputs), tep=copy.deepcopy(core.TEP_DEFAULT),
        phasing=phasing))


def test_one_queue_or_two_the_school_is_the_same_school():
    """Свод очередей и одиночный расчёт меряют объект одинаково.

    И отдельно — ступень РНГП идёт по ёмкости, поэтому очередь обязана взять
    норматив ПРОЕКТА: школа на 800 мест, разрезанная надвое, мерилась бы
    ступенью на 400 (18 м²/место против 15) и свод разошёлся бы с проектом на
    2 400 м² при тех же вводных.
    """
    inputs = _inputs(kindergarten_places=0, school_places=800,
                     social_school_norm_sqm=0)
    assert core.moscow_social_area_per_place("school", 800) == 15
    assert core.moscow_social_area_per_place("school", 400) == 18, (
        "пример перестал пересекать ступень — проверять стало нечего")

    single = _single(inputs)["school"]
    phased = _phased(inputs, [{"type": "school", "capacity": 400, "phase": 1},
                              {"type": "school", "capacity": 400, "phase": 2}])
    rows = {row.get("key"): row for row in phased["consolidated"]["tep"]["rows"]}
    assert rows["school"]["total_area"] == pytest.approx(single["total_area"])
    assert rows["school"]["units"] == pytest.approx(single["units"])

    # Строка, которую видит человек в карточке очереди, — та же, по которой
    # считает движок: `p_tep` уезжает в расчёт копией, и разойдись они, экран
    # показывал бы одно, а экономика считалась бы по другому.
    shown = sum(float((phase.get("tep") or {}).get("school", {}).get("total_area") or 0.0)
                for phase in phased["phases"])
    assert shown == pytest.approx(single["total_area"])


def test_the_book_reads_the_same_area_as_the_row():
    """Книга берёт ту же площадь, что и строка ТЭП, а не поле «Вводных».

    Поле пусто, а объект строится по нормативу: читая поле, книга показывала
    ноль там, где модель строит школу.
    """
    inputs = _inputs(school_places=800, social_school_gba_sqm=0,
                     social_school_norm_sqm=0)
    assert core.n(inputs, "social_school_gba_sqm", 0.0) == 0
    assert core.social_tep_row(inputs, "school")["total_area"] == pytest.approx(800 * 15)


def test_the_city_area_is_a_requirement_not_a_norm():
    """Площадь, названную документом, норматив не перебивает.

    Правило «требование договора КРТ сильнее норматива» записано 03.09.2026 и
    жило только на странице: писатели вводных признака не ставили, и школа на
    1 000 мест (22 220 м² по решению — 22,22 м²/место против 15 по РНГП)
    считалась нормативом. Признак ставит один ответ на всех писателей.
    """
    from auction_search import krt_screening

    def screened(objects):
        inputs = copy.deepcopy(core.DEFAULT_INPUTS)
        krt_screening._programme(
            core, {"housing_gfa_sqm": 100000}, {"social_objects": objects, "volumes": {}},
            inputs, copy.deepcopy(core.TEP_DEFAULT),
            {"apartments": core.TEP_RATIOS["apartments"]}, 60000.0)
        return inputs

    assert core.moscow_social_area_per_place("school", 1000) == 15, (
        "пример держится на том, что требование с нормативом НЕ совпадает")

    named = screened([{"kind": "school", "places": 1000, "area_sqm": 22220}])
    assert core.social_tep_row(named, "school")["total_area"] == pytest.approx(22220)

    # Площадь документ не назвал — считаем нормативом, и признак не ставим:
    # «ручной» режим прочёл бы правку мест как «площадь не следует за ними».
    plain = screened([{"kind": "school", "places": 1000}])
    assert plain.get("social_area_source") != core.SOCIAL_AREA_BY_REQUIREMENT
    assert core.social_tep_row(plain, "school")["total_area"] == pytest.approx(1000 * 15)


def test_the_badge_does_not_wipe_an_object_it_did_not_name():
    """Признак один на три объекта — значит безымянному сперва считают площадь.

    Иначе «ручной» режим прочтёт пустое поле как «объекта нет» и снесёт объект,
    о котором документ просто не говорил.
    """
    inputs = _inputs(school_places=1000, social_school_gba_sqm=22220,
                     social_school_norm_sqm=0,
                     kindergarten_places=250, social_dou_gba_sqm=0)
    assert core.declare_social_requirement(inputs) is True
    assert core.social_tep_row(inputs, "school")["total_area"] == pytest.approx(22220)
    assert core.social_tep_row(
        inputs, "kindergarten")["total_area"] == pytest.approx(250 * 18)


def test_the_queue_editor_does_not_overlay_a_social_row():
    """Соцстрока очереди меряется местами — вписанные метры её не подменяют.

    Таблица ТЭП во вкладке «Очерёдность» рисует соцстроки наравне с
    продуктами, и вписанное туда доезжало до движка ПОВЕРХ норматива —
    `_apply_explicit_phase_products` накладывает поля после соцблока. Но
    накладывались только те три поля, что есть в редакторе (ГНС, продаваемая,
    штуки), а общая площадь оставалась от норматива: строка выходила из двух
    источников разом — ГНС 9 999 при общей 4 500 и 111 местах, где ни одно
    число не отвечает двум другим, а метры уходят в строительный объём.
    """
    inputs = _inputs(kindergarten_places=250, school_places=0,
                     social_dou_norm_sqm=18)
    phasing = {"enabled": True, "step_months": 24,
               "phases": [{"name": "О1", "products": {
                              "kindergarten": {"gns": 9999, "saleable": 777, "units": 111}}},
                          {"name": "О2"}],
               "social_objects": [{"type": "kindergarten", "capacity": 250, "phase": 1}]}
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=copy.deepcopy(inputs), tep=copy.deepcopy(core.TEP_DEFAULT),
        phasing=phasing))
    row = (bundle["phases"][0].get("tep") or {})["kindergarten"]
    assert row["units"] == pytest.approx(250), "места очереди задаёт таблица соцобъектов"
    assert row["total_area"] == pytest.approx(250 * 18)
    # Строка целая: ГНС отвечает своей же общей площади, а не вписанному числу.
    assert row["gns"] == pytest.approx(row["total_area"] / 0.9, rel=1e-6)
    assert row["saleable"] == pytest.approx(0), "соцобъект передаётся городу целиком"


PAGE_CASES = [
    # места, норматив в поле, площадь в поле, режим площади, форма соцнагрузки
    (250, 18, 4500, "norm", "Строительство"),
    (800, 0, 0, "norm", "Строительство"),
    (120, 0, 0, "norm", "Строительство"),
    (250, 0, 5550, "manual", "Строительство"),
    (0, 0, 0, "norm", "Строительство"),
    (1200, 0, 0, "norm", "Строительство"),
    (250, 0, 0, "norm", "Компенсация"),
    (250, 0, 0, "norm", "Строительство и компенсация"),
]

PRELUDE = "\n".join([
    "const TEP_RATIOS=" + json.dumps(core.TEP_RATIOS, ensure_ascii=False) + ";",
    "const SOCIAL_AREA_STEPS="
    + json.dumps(core.MOSCOW_SOCIAL_AREA_PER_PLACE, ensure_ascii=False) + ";",
    "const TEP_SOCIAL_INPUTS={kindergarten:'social_dou_gba_sqm',"
    "school:'social_school_gba_sqm',clinic:'social_clinic_gba_sqm'};",
    "let inputs={},tep={},storageInsideParking=0;",
    "let tepBody=null;const document={activeElement:null};",
    # Отрисовка к ответу отношения не имеет — синхронизация считается до неё.
    "function renderTep(){}",
    "function updateTepTotals(){}",
])


def _run_page(tail: str):
    """Гоняет НАСТОЯЩИЙ `syncTep` со страницы, добирая зависимости по именам.

    Список зависимостей не перечисляется: перечисленный, он отстаёт от
    страницы, и стенд падает на своей неполноте вместо своего утверждения.
    Имени нет на странице — падаем с этим именем, а не подсовываем заглушку:
    заглушка ответила бы за страницу.
    """
    taken: list[str] = []
    bodies: list[str] = []
    for _ in range(60):
        script = PRELUDE + "\n" + "\n".join(bodies) + "\n" + tail
        done = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        if done.returncode == 0:
            return json.loads(done.stdout), taken
        error = done.stderr
        if "ReferenceError" not in error or " is not defined" not in error:
            raise AssertionError(error[-2500:])
        name = error.split("ReferenceError: ")[1].split(" is not defined")[0].strip()
        if name in taken:
            raise AssertionError(f"{name} не разрешается\n{error[-1500:]}")
        bodies.append(page_blocks.piece(name))
        taken.append(name)
    raise AssertionError("зависимостей больше, чем разумно разрешать")


def test_the_queue_tab_shows_what_the_engine_builds():
    """Вкладка «Очерёдность» меряет соцстроку тем же, чем движок.

    Ячейки там заперты — метры считаются от мест, — и потому обязаны совпадать
    с расчётом: показанное, разошедшееся с посчитанным, и есть та поломка,
    ради которой всё это чинится. Отдельный случай — пустая таблица
    соцобъектов: движок размещает объект сам («поздняя раскладка»), и вкладка
    берёт ПРИМЕНЁННОЕ размещение из его же ответа, а не переписывает умолчание
    вторым правилом.
    """
    script = "\n".join([
        "const TEP_RATIOS=" + json.dumps(core.TEP_RATIOS, ensure_ascii=False) + ";",
        "const SOCIAL_TEP_PRODUCTS="
        + json.dumps(list(core.SOCIAL_TEP_FIELDS), ensure_ascii=False) + ";",
        page_blocks.constant("SOCIAL_TEP_NORM_INPUTS"),
        page_blocks.function("socialTotalShare"),
        page_blocks.function("phaseSocialTepRow"),
        "let inputs={},phasing={},phaseBundle=null;",
    ])
    placements = [
        [{"type": "kindergarten", "capacity": 250, "phase": 1}],
        [{"type": "kindergarten", "capacity": 125, "phase": 1},
         {"type": "kindergarten", "capacity": 125, "phase": 2}],
        [],  # размещает движок
    ]
    for objects in placements:
        inputs = _inputs(kindergarten_places=250, school_places=0,
                         social_dou_norm_sqm=18)
        phasing = {"enabled": True, "step_months": 24,
                   "phases": [{"name": "О1"}, {"name": "О2"}],
                   "social_objects": objects}
        bundle = core.calculate_phased(core.PhasedCalcRequest(
            inputs=copy.deepcopy(inputs), tep=copy.deepcopy(core.TEP_DEFAULT),
            phasing=phasing))
        tail = ("inputs=%s;phasing=%s;phaseBundle=%s;"
                "console.log(JSON.stringify([0,1].map("
                "i=>phaseSocialTepRow('kindergarten',i))));" % (
                    json.dumps(inputs, ensure_ascii=False),
                    json.dumps(phasing, ensure_ascii=False),
                    json.dumps({"social_allocation": bundle.get("social_allocation")},
                               ensure_ascii=False)))
        done = subprocess.run(["node", "-e", script + tail],
                              capture_output=True, text=True)
        assert done.returncode == 0, done.stderr[-2000:]
        shown = json.loads(done.stdout)
        for index, phase in enumerate(bundle["phases"]):
            row = (phase.get("tep") or {}).get("kindergarten", {})
            where = f"размещение {objects or 'умолчанием движка'}, очередь {index + 1}"
            assert shown[index]["units"] == pytest.approx(
                float(row.get("units") or 0.0)), where
            assert shown[index]["gns"] == pytest.approx(
                float(row.get("gns") or 0.0), abs=0.01), where

    # Предохранитель: пример обязан ловить разницу между очередями, иначе
    # совпадение ничего не значит.
    assert placements[1][0]["phase"] != placements[1][1]["phase"]


def test_the_page_and_the_engine_measure_the_object_the_same():
    """Одно правило на две стороны — иначе они разойдутся молча.

    Страница синхронизирует ТЭП и «Вводные» сама, движок — своим ответом; пока
    правил было два, они совпадали ровно до первой правки одного из них.
    """
    cases = [_inputs(kindergarten_places=places, social_dou_norm_sqm=norm,
                     social_dou_gba_sqm=area, social_area_source=source,
                     social_mode=mode)
             for places, norm, area, source, mode in PAGE_CASES]
    tail = """
const CASES=%s;
console.log(JSON.stringify(CASES.map(x=>{
  inputs=JSON.parse(JSON.stringify(x));
  tep=JSON.parse(JSON.stringify(%s));
  syncTep(false);
  const row=tep.kindergarten;
  return {units:row.units,total_area:row.total_area,gns:row.gns};
})));
""" % (json.dumps(cases, ensure_ascii=False),
       json.dumps(core.TEP_DEFAULT, ensure_ascii=False))

    page_rows, taken = _run_page(tail)
    assert "syncTep" in taken, "стенд обязан гонять сам `syncTep`, а не его пересказ"

    for inputs, shown in zip(cases, page_rows):
        row = {"kindergarten": copy.deepcopy(core.TEP_DEFAULT["kindergarten"])}
        core.apply_social_tep_rows(inputs, row)
        engine = row["kindergarten"]
        where = (f'мест {inputs["kindergarten_places"]}, '
                 f'норматив {inputs["social_dou_norm_sqm"]}, '
                 f'поле {inputs["social_dou_gba_sqm"]}, '
                 f'{inputs["social_area_source"]}, {inputs["social_mode"]}')
        assert shown["total_area"] == pytest.approx(engine["total_area"]), where
        assert shown["gns"] == pytest.approx(engine["gns"]), where
        assert float(shown["units"]) == pytest.approx(engine["units"]), where

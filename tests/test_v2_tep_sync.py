from pathlib import Path

import main_legacy as engine
from developaid_v2_account_projects import TepSyncRequest, _sync_tep


ROOT = Path(__file__).resolve().parents[1]


class FakeCore:
    TEP_DEFAULT = {
        "apartments": {
            "label": "Квартиры", "gns": 130716.6, "total_area": 117647.1,
            "useful": 80000, "saleable": 80000, "transfer": 0, "units": 1361.8,
        },
        "ground_commercial": {
            "label": "Коммерция 1 этажа", "gns": 0, "total_area": 0,
            "useful": 0, "saleable": 0, "transfer": 0, "units": 0,
        },
        "underground_parking": {
            "label": "Подземный паркинг", "gns": 0, "total_area": 0,
            "useful": 0, "saleable": 0, "transfer": 0, "units": 0,
        },
        "above_parking": {
            "label": "Наземный паркинг", "gns": 0, "total_area": 0,
            "useful": 0, "saleable": 0, "transfer": 0, "units": 0,
        },
    }
    TEP_RATIOS = {
        "apartments": {"total_of_gns": 0.90, "saleable_of_gns": 0.65, "source": "ГлавАПУ"},
        "ground_commercial": {"total_of_gns": 0.90, "saleable_of_gns": 0.90, "source": "ГлавАПУ"},
    }

    @staticmethod
    def tep_ratios_applied(_raw):
        return {}, []

    @staticmethod
    def average_flat_sqm(_source):
        return 60.0, "рынок — 60 м² на квартиру"

    # Объявленные один раз ответы заглушка не подделывает, а БЕРЁТ: подделка со
    # своей сигнатурой проверяет себя, а не наш код, — так проверка нормативов
    # однажды позеленела на гейте, который не опознавал владельца ни разу.
    # Ровно ради того, чтобы /v2 звал движок, эти имена здесь настоящие.
    tep_row_inputs = staticmethod(engine.tep_row_inputs)
    saleable_after_transfer = staticmethod(engine.saleable_after_transfer)
    social_tep_row = staticmethod(engine.social_tep_row)
    SOCIAL_TEP_FIELDS = engine.SOCIAL_TEP_FIELDS
    STANDALONE_OBJECTS = engine.STANDALONE_OBJECTS
    DEFAULT_INPUTS = engine.DEFAULT_INPUTS


def test_teaser_gns_replaces_stale_default_dependants():
    request = TepSyncRequest(
        inputs={"vri_region": "msk"},
        tep={
            "apartments": {
                "label": "Квартиры", "gns": 31000,
                "total_area": 117647.0588235, "useful": 80000,
                "saleable": 80000, "transfer": 0, "units": 1361.8157,
            }
        },
        row_key="apartments",
        field_key="gns",
        value=31000,
    )

    result = _sync_tep(FakeCore(), request)
    row = result["tep"]["apartments"]

    assert row["gns"] == 31000
    assert row["total_area"] == 27900
    assert row["saleable"] == 20150
    assert row["useful"] == 20150
    assert row["units"] == 336
    assert "total_area" in result["derived"]
    assert "saleable" in result["derived"]
    assert "units" in result["derived"]


def _transferred(given, **row):
    base = {"label": "Квартиры", "gns": 31000, "total_area": 27900,
            "useful": 20150, "saleable": 20150, "transfer": 0, "units": 336}
    base.update(row)
    request = TepSyncRequest(
        inputs={"vri_region": "msk"},
        tep={"apartments": base},
        row_key="apartments",
        field_key="transfer",
        value=given,
    )
    return _sync_tep(FakeCore(), request)["tep"]["apartments"]


def test_transfer_reduces_saleable_and_not_the_built_area():
    """Полезная от передачи НЕ уменьшается — решение владельца (10.09.2026).

    Прежде эта проверка держала обратное: `useful == saleable` и после
    передачи. Утверждение было верно ровно до того, как владелец прочитал
    экран: метры построены и полезны, просто не наши. Тождество «полезная
    равна продаваемой» осталось там, где передачи нет, — соседней проверкой.
    """
    row = _transferred(1500)
    assert row["gns"] == 31000, "ГНС не меняется: переданные метры строятся"
    assert row["total_area"] == 27900
    assert row["transfer"] == 1500
    assert row["saleable"] == 18650
    assert row["useful"] == 20150, "полезная площадь потеряла переданные метры"
    assert row["units"] == 311


def test_without_a_transfer_the_useful_area_equals_the_saleable_one():
    row = _transferred(0)
    assert row["useful"] == row["saleable"] == 20150



def test_a_second_edit_of_the_transfer_is_not_counted_twice():
    """Дельту помнить не надо: продаваемая считается заново.

    Прежде здесь стояло «минус разница с прошлым числом», и подпись называла
    именно разницу: в поле 5 000, на экране «переданные 4 000».
    """
    once = _transferred(5000)
    again = _transferred(5000, **{"useful": once["useful"],
                                  "saleable": once["saleable"],
                                  "transfer": 5000})
    assert again["saleable"] == once["saleable"] == 15150
    assert again["useful"] == once["useful"] == 20150


def test_v2_shell_loads_sync_after_stock_app():
    """Пересчёт грузится ПОСЛЕ штатного приложения — на собранной странице.

    Утверждение было то же, а меряло себя: позиции двух строк в ИСХОДНИКЕ.
    `shell.index('/v2/assets/tep-sync.js')` находит первым объявление маршрута
    отдачи файла, а не подстановку в страницу, — и порядок объявлений в файле
    выдавался за порядок скриптов у читателя. Стоило маршрут поднять выше
    сборщика страницы, и проверка покраснела на верном коде: собранная `/v2`
    всё это время несла `app.js` перед `tep-sync.js`, а сборка образа из main
    падала дважды подряд, то есть тег `prod` оставался на прошлом выпуске.
    Правило записано дважды и оба раза этим же: проверять надо то, что видно,
    а не соседнюю строку.
    """
    from fastapi.testclient import TestClient

    import main_registry

    page = TestClient(main_registry.app).get("/v2")
    assert page.status_code == 200
    stock = page.text.find("/v2/assets/app.js")
    sync = page.text.find("/v2/assets/tep-sync.js")
    assert stock >= 0, "штатный app.js не доехал до собранной /v2"
    assert sync >= 0, "tep-sync.js не доехал до собранной /v2"
    assert stock < sync, "пересчёт грузится раньше штатного приложения"
    # Маршруты при этом объявлены — иначе собранная страница ссылалась бы
    # на файл, которого никто не отдаёт.
    assert TestClient(main_registry.app).get("/v2/assets/tep-sync.js").status_code == 200


def test_v2_renames_duplicate_tep_tab_and_marks_derived_values():
    source = (ROOT / "frontend_v2" / "tep_sync.js").read_text(encoding="utf-8")

    assert "Участок и ВРИ" in source
    assert "Участок, ВРИ и обязательства" in source
    assert "авто · ${rule}" in source
    assert "из тизера" in source
    assert "/api/v2/tep-sync" in source


def _project_with_offices():
    """Включённые офисы: на нуле метров правка ничего не двигает и проверка
    зелена на сломанном коде — перестановка нулей невидима."""
    import copy

    inputs = dict(engine.DEFAULT_INPUTS)
    inputs["offices_enabled"] = True
    tep = copy.deepcopy(engine.TEP_DEFAULT)
    tep["offices"] = dict(
        tep["offices"], gns=inputs["offices_gba_sqm"],
        total_area=inputs["offices_gba_sqm"] * 0.94,
        saleable=inputs["offices_saleable_sqm"], useful=inputs["offices_saleable_sqm"])
    assert inputs["offices_gba_sqm"] > 0, "без метров офисов проверка не проверяет ничего"
    return inputs, tep


def test_a_v2_edit_reaches_the_input_the_engine_reads():
    """Правка строки доезжает до вводной — деньги считаются на ней, не на прежней.

    Мерено в рублях: правка ГНС офисов 10 000 → 20 000 давала на экране 20 000
    при CAPEX 2 920,9 млн ₽ вместо 4 920,9 — ровно 10 000 м² по ставке
    200 тыс ₽/м². Половина последствий за правкой шла (приобъектная норма
    читает общую площадь строки), половина нет.
    """
    import copy

    inputs, tep = _project_with_offices()
    answer = _sync_tep(engine, TepSyncRequest(
        inputs=copy.deepcopy(inputs), tep=copy.deepcopy(tep),
        row_key="offices", field_key="gns", value=20000.0))

    assert answer["tep"]["offices"]["gns"] == 20000.0
    assert answer["inputs"]["offices_gba_sqm"] == 20000.0
    assert answer["inputs"]["offices_saleable_sqm"] == answer["tep"]["offices"]["saleable"]

    ours = engine.calculate(engine.CalcRequest(
        inputs=answer["inputs"], tep=answer["tep"]))
    # Та же правка, доведённая до вводных руками, — это и есть ответ страницы.
    page_inputs = copy.deepcopy(answer["inputs"])
    page_inputs["offices_gba_sqm"] = 20000.0
    page_inputs["offices_saleable_sqm"] = answer["tep"]["offices"]["saleable"]
    theirs = engine.calculate(engine.CalcRequest(
        inputs=page_inputs, tep=copy.deepcopy(answer["tep"])))
    assert ours["capex"]["offices"] == theirs["capex"]["offices"]


def test_a_social_row_comes_from_the_engine_answer():
    """Строка соцобъекта — объявленный ответ движка, а не пятое число."""
    import copy

    inputs = dict(engine.DEFAULT_INPUTS)
    inputs["social_mode"] = "Строительство"
    answer = _sync_tep(engine, TepSyncRequest(
        inputs=copy.deepcopy(inputs), tep=copy.deepcopy(engine.TEP_DEFAULT),
        row_key="kindergarten", field_key="units", value=300))

    assert answer["inputs"]["kindergarten_places"] == 300
    want = engine.social_tep_row({**inputs, "kindergarten_places": 300}, "kindergarten")
    got = answer["tep"]["kindergarten"]
    for field in ("units", "total_area", "gns", "transfer"):
        assert round(float(got[field]), 3) == round(float(want[field]), 3), field
    assert float(want["gns"]) > 0, "на нулевой ГНС проверка не различает ответы"


def test_a_disabled_object_says_so_instead_of_saving_silently():
    """Площади ушли во вводные выключенного объекта — и об этом сказано.

    Включать объект за человека нельзя: это меняет экономику проекта. Но
    молчание читается как принятая правка, а строка обнулится на первом же
    пересчёте — ровно то же говорит страница.
    """
    import copy

    inputs, tep = _project_with_offices()
    inputs["offices_enabled"] = False
    answer = _sync_tep(engine, TepSyncRequest(
        inputs=copy.deepcopy(inputs), tep=copy.deepcopy(tep),
        row_key="offices", field_key="gns", value=20000.0))

    assert answer["inputs"]["offices_gba_sqm"] == 20000.0
    said = " ".join(answer.get("notes") or [])
    assert "выключен" in said, said


def test_the_row_input_map_is_declared_once():
    """«Какая вводная за каким полем» — один ответ, и страница берёт его.

    Карт было две неполные (страница и очереди движка) плюс третья, которая
    вводные не писала вовсе. Литерала на странице больше нет: он приходит
    подстановкой, как `VERSION` и доли ТЭП.
    """
    page = engine.PAGE
    assert "const TEP_ROW_INPUTS=" in page
    assert engine.TEP_ROW_INPUTS_PLACEHOLDER not in page, "подстановка не выполнена"
    assert "offices_gba_sqm'" not in page.split("const TEP_ROW_INPUTS=")[1][:200], (
        "карта снова написана руками")
    for obj in engine.standalone_objects():
        if obj.measure != "sqm":
            continue
        assert engine.tep_row_inputs(obj.key) == obj.aliases, obj.key


def test_the_per_space_area_is_not_hard_coded():
    """Ставка площади на место — у движка: копию негде обновлять."""
    source = (ROOT / "developaid_v2_account_projects.py").read_text(encoding="utf-8")
    body = source.split("def _per_space")[1]
    assert "core.DEFAULT_INPUTS" in body.split("def ")[0]
    for literal in ("35.0", "25.0"):
        assert literal not in source, f"в модуле снова литерал {literal}"
    assert engine.DEFAULT_INPUTS["underground_area_per_space_sqm"] > 0
    assert engine.DEFAULT_INPUTS["above_parking_area_per_space_sqm"] > 0


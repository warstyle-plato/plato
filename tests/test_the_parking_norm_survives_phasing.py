"""Норматив паркинга — обязательство объекта, и вид на экране его не меняет.

Владелец прислал экран блока «МФОЦ / офисы» (14.09.2026): ГНС 186 180,
продаваемая 87 504,6, поля паркинга заполнены — а под ними «Расчёт не выполнен
— норматив появится после пересчёта. Если модель не считается, проверьте вход»
и вопрос «куда пропала сверка с нормативом парковок??? мы же делали».

Сверка была на месте и молчала по другой причине: у свода очередей блока
`parking` не было ВОВСЕ. Подпись читала его из `lastResult`, а `lastResult`
идёт за выбранной вкладкой отчёта — при очерёдности это `consolidated`, где
паркинга нет, и подпись честно уходила в холодное состояние. Хуже, что она при
этом винила вход: человек шёл искать поломку там, где всё цело.

И вторая половина, дороже первой: `renderObjectParkingNote` не только
объясняет, но и ПИШЕТ норму в поля проекта. На вкладке отдельной очереди там
лежит её собственный паркинг — у очереди без объекта это ноль, — то есть
переключение вида молча обнуляло бы гараж проекта.

Запуск: python3 -m pytest tests/test_the_parking_norm_survives_phasing.py -q
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import page_blocks  # noqa: E402

import main_legacy as core  # noqa: E402

OFFICES_GBA = 186180.0
SALEABLE = 87504.6


def _case() -> tuple[dict, dict]:
    inputs = dict(core.DEFAULT_INPUTS)
    inputs["offices_enabled"] = True
    inputs["offices_gba_sqm"] = OFFICES_GBA
    tep = copy.deepcopy(core.TEP_DEFAULT)
    tep["offices"].update({"gns": OFFICES_GBA,
                           "total_area": round(OFFICES_GBA * 0.94, 1),
                           "useful": SALEABLE, "saleable": SALEABLE})
    return inputs, tep


def _phased(phases: list[dict]) -> dict:
    inputs, tep = _case()
    return core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep,
        phasing={"enabled": True, "phases": phases, "step_months": 24}))


def _offices(block: dict) -> dict:
    own = (block or {}).get("own") or []
    found = [item for item in own if item.get("prefix") == "offices"]
    assert found, own
    return found[0]


def test_the_consolidated_answer_carries_the_norm() -> None:
    """У свода очередей блок паркинга есть, и он равен проектному.

    Норматив считается на ТЭП ПРОЕКТА, а не складывается из очередей: офисник,
    разрезанный надвое, не становится двумя офисниками со своими нормами — то
    же правило, что у ступени площади соцобъекта.
    """
    inputs, tep = _case()
    single = core.calculate(core.CalcRequest(inputs=copy.deepcopy(inputs),
                                             tep=copy.deepcopy(tep)))
    consolidated = _phased([{"name": "О1"}, {"name": "О2"}])["consolidated"]
    assert "parking" in consolidated, sorted(consolidated.keys())
    assert _offices(consolidated["parking"]) == _offices(single["parking"])
    assert (consolidated["parking"].get("required_total")
            == single["parking"].get("required_total"))
    # Предохранитель: норма должна быть НЕнулевой, иначе равенство сошлось бы
    # и на пустом блоке, и проверка не значила бы ничего.
    assert _offices(consolidated["parking"])["required_spaces"] > 0


def test_the_project_saleable_does_not_slide() -> None:
    """Блок свода считается на копиях: `apply_object_parking` не идемпотентна.

    Метры первых этажей вычитаются из продаваемой при КАЖДОМ вызове, и второй
    проход по мастер-строке увёл бы продаваемую объекта вниз — молча, потому
    что число осталось бы правдоподобным.
    """
    inputs, tep = _case()
    single = core.calculate(core.CalcRequest(inputs=copy.deepcopy(inputs),
                                             tep=copy.deepcopy(tep)))
    consolidated = _phased([{"name": "О1"}, {"name": "О2"}])["consolidated"]

    def saleable(result: dict) -> float:
        rows = [r for r in (result["tep"]["rows"] or []) if r.get("key") == "offices"]
        assert rows, result["tep"]["rows"]
        return float(rows[0]["saleable"])

    assert saleable(consolidated) == saleable(single)


def _trim(consolidated: dict) -> dict:
    """Связка в том виде, в каком её читает страница.

    Полный ответ очередей — это помесячные ряды на сотни килобайт, и node
    отказывает от длины командной строки. Форма при этом та же: страница берёт
    у связки признак режима и блок паркинга свода, больше ничего.
    """
    return {"mode": "phased", "consolidated": {"parking": consolidated["parking"]}}


def _stand(bundle: dict, last: dict, fields: dict) -> dict:
    """Настоящие функции страницы на подставленном состоянии.

    Состояние задаётся таким, каким его оставляет страница: `phaseBundle` от
    `calculate`, `lastResult` — тем, что ставит `selectReportView`.
    """
    # Груз идёт тем же `jsonable_encoder`, которым отвечает маршрут: свой
    # `json.dumps` — это второй ответ на «что видит страница», и он уже
    # подавал даты записью, которой у браузера не бывает.
    from fastapi.encoders import jsonable_encoder  # noqa: PLC0415

    def js(value: object) -> str:
        return json.dumps(jsonable_encoder(value), ensure_ascii=False)

    prelude = """
const num=v=>String(v);
let inputs=%s;
let lastResult=%s;
let phaseBundle=%s;
""" % (js(fields), js({"parking": (last or {}).get("parking")}), js(bundle))
    tail = """
console.log(JSON.stringify({note:objectParkingFieldNote('offices'),
                            own:(projectParking().own||[]).length}));
"""
    return page_blocks.run_json(prelude, tail)


def test_the_note_speaks_the_project_norm_under_phasing() -> None:
    """При очерёдности подпись говорит норму, а не «расчёт не выполнен».

    Именно эту фразу владелец видел на посчитанной модели, и она вдобавок
    отправляла проверять вход.
    """
    bundle = _phased([{"name": "О1"}, {"name": "О2"}])
    fields = {"offices_enabled": True}
    said = _stand(_trim(bundle["consolidated"]), bundle["consolidated"], fields)
    assert said["own"] > 0, said
    assert "Расчёт не выполнен" not in said["note"], said["note"]
    assert "945-ПП" in said["note"], said["note"]


def test_a_phase_view_does_not_speak_for_the_project() -> None:
    """Вкладка очереди без объекта не отвечает за проектное поле.

    `lastResult` там — паркинг ЭТОЙ очереди, у неё офисов нет, и подпись
    сказала бы «мест не требуется» под полем, где стоит проектное число; а
    писатель нормы вписал бы в проектное поле её ноль.
    """
    bundle = _phased([{"name": "О1"}, {"name": "О2"}])
    empty = [p for p in bundle["phases"]
             if not _offices((p["result"].get("parking") or {}))["units"]]
    assert empty, "нужна очередь без объекта — иначе проверять нечего"
    said = _stand(_trim(bundle["consolidated"]), empty[0]["result"],
                  {"offices_enabled": True})
    assert "не требуется" not in said["note"], said["note"]
    assert "945-ПП" in said["note"], said["note"]


def test_a_phase_view_does_not_zero_the_project_garage() -> None:
    """Писатель нормы вписывает ПРОЕКТНОЕ число, а не число открытой вкладки.

    Это половина дороже подписи: `renderObjectParkingNote` не объясняет, а
    ПИШЕТ — и в `inputs`, и в само поле. На вкладке очереди без объекта там
    ноль, помеченный `by_norm`, и переключение вида молча обнуляло бы гараж
    проекта. Ноль в этом поле читается как «гаража нет» — то есть решение,
    которого человек не принимал.
    """
    bundle = _phased([{"name": "О1"}, {"name": "О2"}])
    empty = [p for p in bundle["phases"]
             if not _offices((p["result"].get("parking") or {}))["units"]]
    assert empty, "нужна очередь без объекта — иначе проверять нечего"
    project = _offices(bundle["consolidated"]["parking"])
    assert project["under_spaces"] > 0, project

    from fastapi.encoders import jsonable_encoder  # noqa: PLC0415

    def js(value: object) -> str:
        return json.dumps(jsonable_encoder(value), ensure_ascii=False)

    prelude = """
const cells={};
const num=v=>String(v);
global.document={getElementById:id=>cells[id]||null,activeElement:null};
let inputs=%s;
let lastResult=%s;
let phaseBundle=%s;
""" % (js({"offices_enabled": True}),
       js({"parking": empty[0]["result"].get("parking")}),
       js(_trim(bundle["consolidated"])))
    tail = """
renderObjectParkingNote();
console.log(JSON.stringify({under:inputs.offices_parking_under_spaces,
                            over:inputs.offices_parking_over_spaces}));
"""
    wrote = page_blocks.run_json(prelude, tail)
    assert wrote["under"] == project["under_spaces"], (wrote, project)

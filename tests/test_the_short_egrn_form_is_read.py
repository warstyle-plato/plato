"""Краткая выписка ЕГРН читается так же, как полная. Форм у реестра две.

До 14.09.2026 читалась одна. На лоте 21000005000000032801/1 (1-я Горловская
ул., вл. 4) лотовая документация несёт два зипа выписок — «для здания»
(56 записей) и «для земельного участка» (48), — и из 104 записей прочиталась
ОДНА: остальные отвечали отказом «не выписка ЕГРН об объекте:
<extract_base_params_build>». На экране площадки при этом стояло 19 участков с
подписью «выписки на объект нет», то есть НАШ пробел был выдан за молчание
документа — ровно то, что это правило запрещает.

Вторая форма — «выписка об основных характеристиках и зарегистрированных
правах». Внутри она устроена так же, и это не догадка: имена элементов сверены
с официальными схемами Росреестра (пакеты `extract_base_params_land_v01` и
`extract_base_params_build_v01`, версия 01) поле в поле — `land_record` /
`build_record`, `params`, `cost/value`, `right_records/right_record/
right_holder/legal_entity|public_formation|individual`, `restrict_records`,
`readable_address`, `status`, `special_notes`, `cad_links`.

Поэтому и проверка идёт на ЖИВЫХ выписках квартала 77:05:0004001: у настоящего
документа меняется только корень — то единственное, чем краткая форма
отличается от полной на входе разбора. Собранная руками выписка подтвердила бы
лишь саму себя.

Запуск: python3 -m pytest tests/test_the_short_egrn_form_is_read.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import egrn_extracts  # noqa: E402

EXTRACTS = ROOT / "reference_data" / "krt" / "egrn"
LAND = "77:05:0004001:15"
# Строение с зарегистрированным правом — «УНИКС», ИНН 9724179743.
OWNED = "77:05:0004001:1038"


def live(number: str) -> bytes:
    return (EXTRACTS / f"{number.replace(':', '_')}.xml").read_bytes()


def as_short_form(raw: bytes) -> bytes:
    """Та же живая выписка, объявленная краткой формой.

    Меняется РОВНО корень: `extract_about_property_land` →
    `extract_base_params_land`. Всё остальное — настоящий документ Роскадастра.
    """
    text = raw.decode("utf-8")
    short = re.sub(r"extract_about_property_(land|build)",
                   r"extract_base_params_\1", text)
    assert "extract_base_params_" in short
    return short.encode("utf-8")


def test_the_short_form_of_a_land_extract_is_read():
    full = egrn_extracts.read(live(LAND))
    short = egrn_extracts.read(as_short_form(live(LAND)))
    # Величины те же — это один и тот же документ.
    for field in ("kind", "cadastral_number", "area_sqm", "category",
                  "permitted_use", "address", "cadastral_value_rub", "objects"):
        assert short[field] == full[field], field
    # А вид документа назван, и он разный: краткая форма не публикует того, что
    # публикует полная, и поверхность обязана знать это, не спрашивая второй раз.
    assert full["form"] == "about_property"
    assert short["form"] == "base_params"


def test_the_short_form_of_a_build_extract_keeps_the_owner():
    """Собственник — то, ради чего всё это: он лежит в правах, а не в корне."""
    full = egrn_extracts.read(live(OWNED))
    short = egrn_extracts.read(as_short_form(live(OWNED)))
    assert short["kind"] == "build" == full["kind"]
    assert short["cadastral_number"] == full["cadastral_number"]
    assert short["lands"] == full["lands"]
    owner = egrn_extracts.owner_of(short)
    assert owner is not None and owner == egrn_extracts.owner_of(full)
    assert owner["inn"] == "9724179743"
    assert egrn_extracts.owner_state(short) == egrn_extracts.owner_state(full)


def test_an_unknown_form_names_what_came_instead():
    """Чужой вид документа объясняет себя сам — иначе за ним лезут на прод.

    Форм у ЕГРН больше двух (помещение, машино-место, сооружение), и каждая
    следующая стоила бы отдельного захода к складу документов прода. Отказ
    называет корень И пути элементов; значения не печатаются намеренно — в
    выписке стоят имена правообладателей, а отказ уезжает в свод и в чат.
    """
    raw = (b"<extract_about_property_room><room_record><object><common_data>"
           b"<cad_number>77:05:0004001:9999</cad_number></common_data></object>"
           b"</room_record></extract_about_property_room>")
    try:
        egrn_extracts.read(raw)
    except ValueError as exc:
        said = str(exc)
    else:  # pragma: no cover — чужая форма обязана быть отказом
        raise AssertionError("чужой вид документа прошёл как выписка об объекте")
    assert "extract_about_property_room" in said
    assert "room_record/object/common_data/cad_number" in said
    assert "77:05:0004001:9999" not in said, "значения в отказ не идут"


def test_the_shape_stops_at_its_limit():
    """Отказ уезжает в чат и в отчёт — длина у него названа, а не «сколько выйдет»."""
    deep = "".join(f"<t{n}>" for n in range(60)) + "".join(
        f"</t{n}>" for n in reversed(range(60)))
    paths = egrn_extracts.shape(
        __import__("xml.etree.ElementTree", fromlist=["ElementTree"]).fromstring(
            f"<extract_unknown>{deep}</extract_unknown>"), limit=7)
    assert len(paths) == 7

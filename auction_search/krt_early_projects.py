"""Early KRT prospects supplied by the owner before city publication.

These rows are deliberately not presented as official krt.mos.ru records.
They participate in the same market/model/rating pipeline as planned KRT sites,
but carry an explicit source/status marker until an official city record
appears.  When an official row with the same address + passport appears, the
early row is suppressed to avoid duplicate opportunities.
"""
from __future__ import annotations

import re
from typing import Any

SOURCE = "KRT.pdf · 23.09.2026"

_ROWS: list[dict[str, Any]] = [
    {"lot":2,"okrug":"САО","name":"Дмитровское ш., влд. 60","area_ha":4.10,"start_price_mln":178.36,"seizure_mln":3680.0,"total_gfa_sqm":94400,"housing_gfa_sqm":94400,"nonresidential_gfa_sqm":0,"load_housing_rub_sqm":40872.46,"load_total_rub_sqm":40872.46,"source_market_rub_sqm":376832,"note":"ЛОС + инфраструктурный договор. Ближайшие ориентиры около 375–377 тыс. ₽/м²; в записке проект имеет смысл только при ожидании 475–500 тыс. ₽/м²."},
    {"lot":6,"okrug":"СВАО","name":"Алтуфьевское шоссе, проект 2, территория 1","area_ha":11.19,"start_price_mln":170.0,"seizure_mln":4830.0,"total_gfa_sqm":219300,"housing_gfa_sqm":146720,"nonresidential_gfa_sqm":72580,"load_housing_rub_sqm":34078.52,"load_total_rub_sqm":22799.82,"source_market_rub_sqm":486000,"note":"Инфраструктурный договор, школа/ДОО на 825 мест, 5 000 м² помещений для городских нужд."},
    {"lot":10,"okrug":"ЮАО","name":"Шипиловский пр-д, влд. 55","area_ha":6.61,"start_price_mln":410.0,"seizure_mln":1000.0,"total_gfa_sqm":55760,"housing_gfa_sqm":0,"nonresidential_gfa_sqm":55760,"load_housing_rub_sqm":None,"load_total_rub_sqm":25286.94,"source_market_rub_sqm":None,"live_tender_start_mln":4.11334042,"note":"50 090 м² спортивный кластер + 5 670 м² ФОК с бассейном. В исходной записке отмечен повторный аукцион."},
    {"lot":11,"okrug":"ВАО","name":"ул. Рубцовско-Дворцовая, влд. 1/3","area_ha":6.93,"start_price_mln":114.29,"seizure_mln":2040.0,"total_gfa_sqm":58020,"housing_gfa_sqm":28350,"nonresidential_gfa_sqm":29670,"load_housing_rub_sqm":75989.07,"load_total_rub_sqm":37130.13,"source_market_rub_sqm":533154,"note":"Инфраструктурный договор + реставрация 5 ОКН площадью 6 550 м²."},
    {"lot":12,"okrug":"ЮАО","name":"ул. Красного Маяка, влд. 16","area_ha":13.56,"start_price_mln":730.0,"seizure_mln":4020.0,"total_gfa_sqm":241670,"housing_gfa_sqm":194340,"nonresidential_gfa_sqm":47330,"load_housing_rub_sqm":24441.70,"load_total_rub_sqm":19654.90,"source_market_rub_sqm":380000,"note":"7 территориально разрозненных зон. ОДЦ/ФОК, помещения для ВОИ и молочно-раздаточного пункта, перебазирование ГБУ."},
    {"lot":14,"okrug":"ЮАО","name":"Харьковский пр-д, влд. 1–9","area_ha":22.79,"start_price_mln":2190.0,"seizure_mln":2060.0,"total_gfa_sqm":441570,"housing_gfa_sqm":201850,"nonresidential_gfa_sqm":239720,"load_housing_rub_sqm":35843.81,"load_total_rub_sqm":9624.75,"source_market_rub_sqm":None,"note":"Из 239 720 м² нежилой застройки 193 680 м² — административно-деловая функция. Инфраструктурный договор + перенос ВЛ в кабель."},
    {"lot":16,"okrug":"ЮАО","name":"МКАД, 26 км; ул. Липецкая, влд. 27","area_ha":11.15,"start_price_mln":4800.0,"seizure_mln":100.0,"total_gfa_sqm":255270,"housing_gfa_sqm":181560,"nonresidential_gfa_sqm":73710,"load_housing_rub_sqm":20514.11,"load_total_rub_sqm":19195.36,"source_market_rub_sqm":None,"note":"Эконом-класс; 16 410 м² реновации, перехватывающий паркинг на 300 м/м и подстанция медпомощи."},
    {"lot":18,"okrug":"ЮАО","name":"Производственная зона Ленино","area_ha":31.32,"start_price_mln":5200.0,"seizure_mln":6600.0,"total_gfa_sqm":504670,"housing_gfa_sqm":381150,"nonresidential_gfa_sqm":123520,"load_housing_rub_sqm":34106.02,"load_total_rub_sqm":23381.62,"source_market_rub_sqm":390046,"note":"35 170 м² реновации, 3 ДОУ, очистные, каток, тяговая подстанция метро, перебазирование ГБУ, ЦОД и инфраструктурный договор."},
    {"lot":21,"okrug":"ЮЗАО","name":"ул. Архитектора Власова, влд. 59","area_ha":3.66,"start_price_mln":810.11,"seizure_mln":83.22,"total_gfa_sqm":27915,"housing_gfa_sqm":26260,"nonresidential_gfa_sqm":1655,"load_housing_rub_sqm":34018.66,"load_total_rub_sqm":32001.79,"source_market_rub_sqm":594548,"note":"Инфраструктурный договор, 800 м² для ГБУ Жилищника, парк не менее 1,57 га, сокращение СЗЗ."},
    {"lot":28,"okrug":"ТиНАО","name":"п. Знамя Октября, мкр. Родники, территория 1","area_ha":14.49,"start_price_mln":1120.0,"seizure_mln":1360.0,"total_gfa_sqm":233430,"housing_gfa_sqm":166880,"nonresidential_gfa_sqm":66550,"load_housing_rub_sqm":14860.98,"load_total_rub_sqm":10624.17,"source_market_rub_sqm":None,"note":"В исходной сравнительной записке дана краткая предварительная оценка без дополнительной детализации."},
    {"lot":31,"okrug":"ЮАО","name":"ул. Каспийская, влд. 22","area_ha":1.10,"start_price_mln":24.09,"seizure_mln":676.16,"total_gfa_sqm":22890,"housing_gfa_sqm":6890,"nonresidential_gfa_sqm":16000,"load_housing_rub_sqm":101632.80,"load_total_rub_sqm":30591.96,"source_market_rub_sqm":390046,"note":"Около 6,9 тыс. м² жилья и 16 тыс. м² общественной функции; береговая линия."},
    {"lot":42,"okrug":"ЮЗАО","name":"Новоясеневский пр-кт, влд. 42, стр. 9","area_ha":0.69,"start_price_mln":4.36,"seizure_mln":606.16,"total_gfa_sqm":10380,"housing_gfa_sqm":0,"nonresidential_gfa_sqm":10380,"load_housing_rub_sqm":None,"load_total_rub_sqm":58816.96,"source_market_rub_sqm":None,"note":"5 860 м² МФК со спортивным объектом + 4 060 м² торгово-бытовой комплекс."},
]

_SPACE = re.compile(r"\s+")
_PUNCT = re.compile(r"[^0-9а-яё]+", re.I)


def _key(value: Any) -> str:
    return _SPACE.sub(" ", _PUNCT.sub(" ", str(value or "").casefold())).strip()


def _published_match(early: dict[str, Any], official: dict[str, Any]) -> bool:
    a, b = _key(early.get("name")), _key(official.get("name") or official.get("address"))
    if not a or not b:
        return False
    exact = a == b
    try:
        area_close = abs(float(early.get("area_ha") or 0) - float(official.get("area_ha") or 0)) < 0.08
    except (TypeError, ValueError):
        area_close = False
    return exact or (area_close and (a in b or b in a))


def projects(official_rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    # Ранний список живёт только ДО появления той же площадки в официальном
    # каталоге/проектах решений. Раньше аргумент official_rows вообще не
    # использовался, поэтому Архитектора Власова, влд. 59 стояла двумя
    # одинаковыми строками: уже опубликованный проект решения + старый ранний
    # prospect. Подавляем только сильное совпадение адреса/паспорта.
    official = [row for row in (official_rows or []) if isinstance(row, dict)]
    out: list[dict[str, Any]] = []
    for raw in _ROWS:
        if any(_published_match(raw, one) for one in official):
            continue
        row = dict(raw)
        lot = int(row.pop("lot"))
        name = str(row.get("name") or "")
        row.update({
            "slug": f"early:{lot}",
            "address": name,
            "address_known": True,
            "status": "Не опубликован",
            # Для финансового отбора это тот же класс возможностей, что
            # «Планируемый»: стройка ещё не начата, оценивать можно.
            "status_kind": "planned",
            "early_unpublished": True,
            "no_card": True,
            "source_kind": "early_unpublished",
            "source_label": SOURCE,
            "name_source": "предварительный список владельца",
            "draft_decision_at": 0,
        })
        out.append(row)
    return out

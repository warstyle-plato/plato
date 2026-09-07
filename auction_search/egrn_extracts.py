"""Выписки ЕГРН (КУВИ, XML) — разбор одного файла. Своего клиента НСПД здесь нет.

Владелец прислал 59 официальных выписок Роскадастра от 18.08.2026 по кварталу
77:05:0004001: 39 объектов капитального строительства и 20 земельных участков.
Они отвечают на то, чего публичный ответ НСПД не отдаёт вовсе:

- **какой участок под зданием.** У здания есть поле «кадастровый номер ЗУ», и в
  ответе НСПД оно пустое по всем тридцати девяти; в выписке оно заполнено — и
  восемь зданий стоят сразу на нескольких участках;
- **кто правообладатель.** НСПД отдаёт только форму собственности;
- **чем обременён участок.** Аренда до 2051–2073, ипотека, сервитуты — со
  сроком, номером договора и арендатором.

Три ловушки разбора, каждая ловится только на живом файле.

**Перечень лежит в ОДНОМ поле через запятую.** У здания 77:05:0004001:1098 в
`<cad_number>` стоит «77:05:0004001:15, 77:05:0004001:40, …» — четыре участка
одним узлом. Разбор по узлам давал один номер вместо четырёх и молча терял три.

**Личность — это ИНН, а не написание имени.** Одна и та же компания приходит и
капсом, и обычным письмом («ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ "УНИКС"» и
«Общество с ограниченной ответственностью "УНИКС"»), а «Автокомбинат № 19» —
то ЗАО, то АО. Сложенные по имени, они дают двух владельцев вместо одного.

**Публичный собственник записан иначе, чем юрлицо.** У города нет ни ИНН, ни
ОГРН: он лежит в `public_formation`, и разбор, ищущий `<name>` внутри
`legal_entity`, отвечает «держатель не назван» — то есть выдаёт наш пробел за
молчание документа.

Запуск проверок: python3 -m pytest tests/test_the_egrn_extract_is_read.py -q
"""

from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree as ET

_CAD = re.compile(r"\d+:\d+:\d+:\d+")


def _numbers(nodes) -> list[str]:
    """Кадастровые номера из узлов, где перечень бывает в одном поле."""
    out: list[str] = []
    for node in nodes:
        for part in re.split(r"[,;]\s*", (node.text or "")):
            part = part.strip()
            if _CAD.fullmatch(part):
                out.append(part)
    return list(dict.fromkeys(out))


def _holder(node: ET.Element) -> dict[str, Any]:
    """Правообладатель. Публичное образование записано не как юрлицо."""
    legal = node.find("legal_entity")
    if legal is not None:
        return {"kind": "legal",
                "name": (legal.findtext(".//name") or "").strip(),
                "inn": (legal.findtext(".//inn") or "").strip(),
                "ogrn": (legal.findtext(".//ogrn") or "").strip()}
    public = node.find("public_formation")
    if public is not None:
        return {"kind": "public",
                "name": (public.findtext(".//name/value") or "").strip(),
                "inn": "", "ogrn": ""}
    if node.find("individual") is not None or node.find("person") is not None:
        # Имя физического лица — персональные данные, и наружу оно не идёт.
        return {"kind": "person", "name": "физическое лицо", "inn": "", "ogrn": ""}
    return {"kind": "other", "name": "", "inn": "", "ogrn": ""}


def holder_key(holder: dict[str, Any]) -> str:
    """Ключ личности: ИНН, затем ОГРН, и только потом имя.

    Складывать по имени нельзя — одна компания приходит в разном написании.
    """
    return (str(holder.get("inn") or "").strip()
            or str(holder.get("ogrn") or "").strip()
            or ("public:" + str(holder.get("name") or "").strip()
                if holder.get("kind") == "public" else "")
            or ("name:" + str(holder.get("name") or "").strip()))


def _rights(root: ET.Element) -> list[dict[str, Any]]:
    return [{
        "type": (node.findtext(".//right_type/value") or "").strip(),
        "number": (node.findtext(".//right_number") or "").strip(),
        "date": (node.findtext(".//record_info/registration_date") or "")[:10],
        "share": (node.findtext(".//share_text") or "").strip(),
        "holders": [_holder(h) for h in node.findall(".//right_holder")],
    } for node in root.findall(".//right_records/right_record")]


def _restrictions(root: ET.Element) -> list[dict[str, Any]]:
    return [{
        "type": (node.findtext(".//restriction_encumbrance_type/value") or "").strip(),
        "number": (node.findtext(".//restriction_encumbrance_number") or "").strip(),
        "start": (node.findtext(".//period/period_info/start_date") or "").strip(),
        "end": (node.findtext(".//period/period_info/end_date") or "").strip(),
        "term": (node.findtext(".//deal_validity_time") or "").strip(),
        "subject": (node.findtext(".//restriction_subject") or "").strip(),
        "document": (node.findtext(".//underlying_document/document_name") or "").strip(),
        "document_number": (node.findtext(".//underlying_document/document_number") or "").strip(),
        "holders": [_holder(h) for h in node.findall(".//right_holder")],
    } for node in root.findall(".//restrict_records/restrict_record")]


def _float(text: str) -> float | None:
    clean = (text or "").replace(",", ".").strip()
    try:
        return float(clean)
    except ValueError:
        return None


def read(raw: bytes) -> dict[str, Any]:
    """Одна выписка → запись. Чужой вид документа — отказ, а не пустая запись."""
    root = ET.fromstring(raw)
    if root.tag == "extract_about_property_land":
        kind, base = "land", ".//land_record"
    elif root.tag == "extract_about_property_build":
        kind, base = "build", ".//build_record"
    else:
        raise ValueError(f"не выписка ЕГРН об объекте: <{root.tag}>")
    text = lambda path: (root.findtext(path) or "").strip()  # noqa: E731
    record: dict[str, Any] = {
        "kind": kind,
        "cadastral_number": text(base + "/object/common_data/cad_number"),
        "quarter": text(base + "/object/common_data/quarter_cad_number"),
        "address": text(".//readable_address"),
        "cadastral_value_rub": _float(text(".//cost/value")),
        "status": text(".//status"),
        "special_notes": text(".//special_notes"),
        "formed_at": text(".//date_formation"),
        "extract_number": text(".//registration_number"),
        "rights": _rights(root),
        "restrictions": _restrictions(root),
    }
    if kind == "land":
        record.update({
            "area_sqm": _float(text(".//params/area/value")),
            "area_kind": text(".//params/area/type/value"),
            "category": text(".//params/category/type/value"),
            "permitted_use": text(".//params/permitted_use/permitted_use_established/by_document"),
            "objects": _numbers(root.findall(
                ".//cad_links/included_objects/included_object/cad_number")),
        })
    else:
        record.update({
            "area_sqm": _float(text(".//params/area")),
            "name": text(".//params/name"),
            "purpose": text(".//params/purpose/value"),
            "floors": text(".//params/floors"),
            "underground_floors": text(".//params/underground_floors"),
            "year_built": text(".//params/year_commisioning"),
            "lands": _numbers(root.findall(
                ".//cad_links/land_cad_numbers/land_cad_number/cad_number")),
            "rooms": _numbers(root.findall(
                ".//cad_links/room_cad_numbers/room_cad_number/cad_number")),
        })
    return record


def owner_of(record: dict[str, Any]) -> dict[str, Any] | None:
    """Собственник объекта, если право зарегистрировано.

    Пусто — это ответ документа: у 14 участков из 20 собственность не
    зарегистрирована вовсе (земля города), и показывать это как «не знаем»
    нельзя.
    """
    for right in record.get("rights") or []:
        if "обственност" not in right.get("type", ""):
            continue
        for holder in right.get("holders") or []:
            if holder.get("name"):
                return {**holder, "key": holder_key(holder),
                        "right_type": right.get("type"), "since": right.get("date")}
    return None


def other_rights(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Права, кроме собственности: оперативное управление, хозяйственное ведение.

    Девять строений квартала записаны за городом Москвой, а держит их ГБУ
    «Жилищник района Нагатино-Садовники» на праве оперативного управления.
    Назвать учреждение собственником — не приближение, а неправда: договариваться
    о таком объекте и распоряжаться им будут разные лица.
    """
    out = []
    for right in record.get("rights") or []:
        if "обственност" in right.get("type", ""):
            continue
        for holder in right.get("holders") or []:
            if not holder.get("name"):
                continue
            out.append({**holder, "key": holder_key(holder),
                        "right_type": right.get("type") or "", "since": right.get("date") or ""})
    return out


def leases(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Аренда участка: кто, по какому договору и до какого срока."""
    out = []
    for item in record.get("restrictions") or []:
        if "ренд" not in item.get("type", ""):
            continue
        for holder in item.get("holders") or [{}]:
            out.append({
                "name": holder.get("name") or "",
                "key": holder_key(holder) if holder.get("name") else "",
                "until": item.get("end") or "",
                "term": item.get("term") or "",
                "document": item.get("document") or "",
                "document_number": item.get("document_number") or "",
                "subject": item.get("subject") or "",
            })
    return out

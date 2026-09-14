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
        # У публичного образования нет ни ИНН, ни ОГРН, и опознаётся оно ВИДОМ
        # и КОДОМ, а не написанием имени: у одного и того же субъекта РФ 77 в
        # выписке по земле стоит «Москва» с кодом, а в выписке по зданию —
        # «город Москва» без кода. Сложенные по имени, они дают двух
        # собственников вместо одного (замечание владельца, 07.09.2026:
        # «город Москва и Москва — это одно и то же»).
        kinds = [child.tag for child in (public.find("public_formation_type") or public)]
        return {"kind": "public",
                "public_kind": kinds[0] if kinds else "",
                "code": (public.findtext(".//name/code") or "").strip(),
                "name": (public.findtext(".//name/value") or "").strip(),
                "inn": "", "ogrn": ""}
    if node.find("individual") is not None or node.find("person") is not None:
        # Имя физического лица — персональные данные, и наружу оно не идёт.
        return {"kind": "person", "name": "физическое лицо", "inn": "", "ogrn": ""}
    return {"kind": "other", "name": "", "inn": "", "ogrn": ""}


# Слова, которыми публичное образование называют по-разному: «Москва» и
# «город Москва» — один и тот же субъект РФ.
_PUBLIC_PREFIX = re.compile(r"^(?:город(?:ской округ)?|г\.|гор\.)\s+", re.I)


def public_name_key(name: str) -> str:
    """Имя публичного образования без слова, которым его называют по-разному."""
    return _PUBLIC_PREFIX.sub("", str(name or "").strip()).casefold()


def holder_key(holder: dict[str, Any]) -> str:
    """Ключ личности: ИНН, затем ОГРН, и только потом вид с кодом.

    Складывать по имени нельзя — одно и то же лицо приходит в разном
    написании: компания и капсом, и обычным письмом, а субъект РФ то «Москва»,
    то «город Москва». У публичного образования ИНН нет вовсе, и его опознаёт
    вид (субъект РФ, муниципалитет) плюс код; кода нет — имя без слова
    «город», по которому эти двое и расходились.
    """
    if str(holder.get("inn") or "").strip():
        return str(holder["inn"]).strip()
    if str(holder.get("ogrn") or "").strip():
        return str(holder["ogrn"]).strip()
    if holder.get("kind") == "public":
        # Ключом служит ИМЯ без слова «город», а не код: код проставлен не
        # везде — у «города Москвы» в выписке по зданию его нет вовсе, и
        # ключ «по коду, а иначе по имени» разводил бы одно лицо на двоих
        # ровно там, где его и надо свести. Код остаётся при записи и годится
        # для сверки: два разных кода под одним именем — это столкновение, и
        # его видно.
        kind = str(holder.get("public_kind") or "public")
        return f"public:{kind}:{public_name_key(holder.get('name'))}"
    return "name:" + str(holder.get("name") or "").strip()


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


# Виды выписки, которые читаются. Форм у ЕГРН две, и до 14.09.2026 читалась
# ОДНА: на лоте 21000005000000032801/1 (1-я Горловская ул., вл. 4) два зипа
# несли 104 записи, прочиталась одна, а на экране площадки стояло 19 участков
# с «выписки на объект нет» — то есть НАШ пробел был выдан за молчание
# документа. Вторая форма — «об основных характеристиках и зарегистрированных
# правах» (`extract_base_params_*`), и внутри она устроена так же: имена
# элементов сверены с официальными схемами Росреестра (пакеты
# `extract_base_params_land_v01` и `extract_base_params_build_v01`, версия 01)
# поле в поле — `land_record`/`build_record`, `params`, `cost`,
# `right_records/right_record/right_holder`, `restrict_records`,
# `readable_address`, `status`, `special_notes`, `cad_links`. Поэтому здесь
# добавлен ВИД документа, а не второй разбор: две реализации одной выписки
# однажды ответили бы про один объект разное.
#
# Чем прочитана запись — часть записи (`form`): полная выписка отвечает на то,
# чего краткая не публикует, и поверхность обязана знать это, не спрашивая
# документ второй раз.
_FORMS: dict[str, tuple[str, str, str]] = {
    "extract_about_property_land": ("land", ".//land_record", "about_property"),
    "extract_about_property_build": ("build", ".//build_record", "about_property"),
    "extract_base_params_land": ("land", ".//land_record", "base_params"),
    "extract_base_params_build": ("build", ".//build_record", "base_params"),
}


def shape(root: ET.Element, *, limit: int = 30) -> list[str]:
    """Пути элементов документа БЕЗ значений — чтобы чужой вид объяснил себя сам.

    Отказ «не выписка ЕГРН об объекте: <корень>» называл только корень, и
    узнать, что за документ пришёл, можно было единственным способом — достать
    файл с прода руками. Форм у ЕГРН больше двух (помещение, машино-место,
    сооружение), и каждая следующая стоила бы того же захода.

    Значения не печатаются намеренно: в выписке стоят имена правообладателей,
    и отказ уезжает в свод, в отчёт и в чат. Путь без значения — это контракт
    документа, а не его содержание.
    """
    paths: list[str] = []
    seen: set[str] = set()

    def walk(node: ET.Element, prefix: str) -> None:
        for child in node:
            tag = str(child.tag)
            path = f"{prefix}/{tag}" if prefix else tag
            if path not in seen:
                seen.add(path)
                paths.append(path)
                if len(paths) >= limit:
                    return
            walk(child, path)
            if len(paths) >= limit:
                return

    walk(root, "")
    return paths


def read(raw: bytes) -> dict[str, Any]:
    """Одна выписка → запись. Чужой вид документа — отказ, а не пустая запись."""
    root = ET.fromstring(raw)
    known = _FORMS.get(str(root.tag))
    if known is None:
        digest = ", ".join(shape(root)) or "внутри нет ни одного элемента"
        raise ValueError(
            f"не выписка ЕГРН об объекте: <{root.tag}>; что внутри: {digest}")
    kind, base, form = known
    text = lambda path: (root.findtext(path) or "").strip()  # noqa: E731
    record: dict[str, Any] = {
        "kind": kind,
        # Чем прочитана запись — часть записи: печатная форма отвечает не на
        # все вопросы машинной, и поверхность обязана это знать, не спрашивая
        # второй раз (`egrn_print_form` ставит здесь "print_form").
        "source": "xml",
        # Вид выписки: полная («об объекте недвижимости») или краткая («об
        # основных характеристиках»). Читаются обе, и путать их нельзя.
        "form": form,
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


def owner_state(record: dict[str, Any]) -> str:
    """Что документ говорит о собственнике: назван, не раскрыт или права нет.

    Ответов три, и слить их в «владельца нет» нельзя.

    `named` — собственность зарегистрирована и держатель назван.

    `withheld` — собственность ЗАРЕГИСТРИРОВАНА (вид, номер и дата стоят), а
    имени в документе нет. Так устроена печатная форма выписки «об объекте
    недвижимости»: у 77:05:0012007:2054 стоит «Собственность
    77-77/005-77/009/277/2016-603/2 от 23.12.2016», а клетка «Правообладатель»
    пуста — проверено отрисовкой страницы, там нет ни текста, ни картинки. Это
    свойство ВИДА выписки, а не молчание реестра, и лечится оно своим запросом
    в ЕГРН, а не перечитыванием того же файла.

    `unregistered` — права собственности нет вовсе. Это ответ реестра: у 14
    участков квартала 77:05:0004001 из 20 собственность не зарегистрирована.

    Выдать второе за третье значит сказать «право не зарегистрировано» там, где
    оно зарегистрировано, — и на экране эти два ответа неразличимы.
    """
    if (owner_of(record) or {}).get("name"):
        return "named"
    for right in record.get("rights") or []:
        if "обственност" not in (right.get("type") or ""):
            continue
        if not any((holder or {}).get("name") for holder in right.get("holders") or []):
            return "withheld"
    return "unregistered"


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


def encumbrances(record: dict[str, Any], *, lease: bool | None = None) -> list[dict[str, Any]]:
    """Обременения: кто, чем, по какому документу и до какого срока.

    `lease=True` — только аренда, `False` — всё остальное, `None` — всё.
    Показывать одну аренду нельзя: на 77:05:0004001:2045 и на здании
    77:05:0004001:1046 висит ипотека Совкомбанка до 2034 года, а на :9 и :2121
    — «прочие ограничения». Молча выброшенное ограничение читается как его
    отсутствие, а у залога это худший вид молчания.
    """
    out = []
    for item in record.get("restrictions") or []:
        is_lease = "ренд" in item.get("type", "")
        if lease is not None and is_lease is not lease:
            continue
        for holder in item.get("holders") or [{}]:
            out.append({
                "kind": item.get("type") or "",
                "lease": is_lease,
                "name": holder.get("name") or "",
                "key": holder_key(holder) if holder.get("name") else "",
                "until": item.get("end") or "",
                "since": item.get("start") or "",
                "term": item.get("term") or "",
                "number": item.get("number") or "",
                "document": item.get("document") or "",
                "document_number": item.get("document_number") or "",
                "subject": item.get("subject") or "",
            })
    return out


def leases(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Только аренда. Второго разбора обременений здесь нет."""
    return encumbrances(record, lease=True)

"""Объекты КРТ Нагатино с их правообладателями — реестр и контуры.

Владелец прислал выгрузку по кварталу 77:05:0004001 (39 участков: площадь,
кадастровая стоимость, правообладатель) и попросил отдельную страницу с картой
Москвы, где эти участки нанесены, а по наведению видно, чей участок
(07.09.2026). Группы он назвал сам: «Новый проект, УНИКС покрасить как
Брынцалов, Россети, жилищник и автокомбинат как прочее», следом «Причал там же
ген дир» и «Москва зелёная, остальные разной гаммы жёлтого». Про «Жилищник» он
в тот же день сказал иначе — «город Москва по зданиям Жилищника конечно красим
в зелёный цвет Москвы», — и это отменяет первое слово: собственник у этих
строений город, у ГБУ оперативное управление.

Что здесь чьё:

- **правообладатель, площадь и кадастровая стоимость — из выгрузки.** Она
  лежит и файлом (`docs/krt/nagatino-parcels-2026-09-07.xlsx` — его приложение не
  читает), и разобранным
  рядом (`reference_data/krt/nagatino_parcels.json`) — как нормативный пакет:
  ссылки протухают, файл нет;
- **контур участка — из ЕГРН** по кадастровому номеру, тем же путём движка
  (`_land_lookup_by_numbers`), которым собирает контур `decision_outline`.
  Второго клиента НСПД здесь нет.

Четыре правила, за которые отвечает именно этот модуль.

**Кто владелец — один ответ, и его даёт выписка.** Прежде строка выгрузки
красилась по владельцу ИЗ ФАЙЛА, а то же здание на карте — по собственнику из
выписки: на 27 объектах из 39 они расходились, и оба ответа выглядели верными.
Восемь строений «Жилищника» на строке были жёлтыми при зелёных на карте.
Выгрузка при этом не выброшена: её владелец стоит своей колонкой, а расхождение
названо словами («в выгрузке назван ГБУ — у него оперативное управление;
собственник по ЕГРН — город Москва»). Молчание расхождением не считается: у
объекта без выписки ответ один, и его даёт файл.

**Группа — утверждение о владельце участка, а не наша догадка.** ООО «Причал»
владелец ни к «Брынцалову», ни к «прочему» не отнёс — оно стоит своей группой
«группа не назначена», а не подмешивается к прочему. Приписанная группа на
экране выглядит ровно так же уверенно, как названная.

**Итог самой выгрузки не сходится с её же строками, и это сказано вслух.**
`D41` считает `SUM(D2:D40)` и даёт 33 543,1 м², а строки дают 54 753,1: шесть
площадей (`D2`, `D3`, `D5`, `D10`, `D23`, `D25`) лежат в книге ТЕКСТОМ с
неразрывным пробелом, и `SUM` их пропускает. Кадастровая стоимость при этом
сходится до рубля — то есть расходится ровно одна колонка. Молча взять свою
сумму нельзя: человек смотрит в файл и видит другое число.

**Что это по ЕГРН — часть ответа, а не подробность.** Выгрузка названа
«участками», а живой ответ прода 07.09.2026 по всем тридцати девяти номерам —
объекты капитального строительства: нежилые здания на Варшавском ш., д. 37А и
в 1-м Нагатинском пр-де, д. 6. Земельных участков среди них нет ни одного.
Здание меряется площадью здания, участок — площадью земли, и пока вид не
назван, колонка «пл» читается как земля и уезжает в плотность и в цену за метр
земли. Вид едет из ответа ЕГРН и печатается у каждой строки.

**Земля под строением берётся из ЕГРН по точке, а не по полю.** У здания есть
поле «кадастровый номер земельного участка», и оно выглядит готовым ответом —
но по всем тридцати девяти номерам выгрузки оно пустое. Зато ЕГРН отвечает на
вопрос «что стоит в этой точке»: центр здания даёт участок под ним. Так 39
строений сели на 16 участков (17,86 га, контуры у всех шестнадцати), и зип с
участками для привязки не понадобился вовсе. Два участка под одной точкой —
это выбор, сделанный за источник, и он назван; ни одного — причина, а не
пропуск.

**Правообладатель земли и правообладатель строения — разные лица.** Выгрузка
называет владельцев СТРОЕНИЙ; по земле ЕГРН отдаёт только форму собственности
(и ту у 12 участков из 16 не отдаёт). Поэтому у участка колонки владельца нет
вовсе, а не заполнена владельцем стоящего на нём здания: подписать одно другим
значит сказать неправду. Рядом стоит другой, отвечаемый вопрос — чьи на нём
строения.

**Ненайденный в ЕГРН объект называется числом и причиной.** Пустая карта и
карта, где не нарисовано пять объектов, выглядят одинаково. На 07.09.2026 из
39 номеров контур дали 36, у трёх его нет.

**Контур самой площадки КРТ не рисуется вторым путём.** Его уже умеет реестр
(`krt_registry`: официальный файл карты города, а где его нет — перечень
проекта решения), и берётся он оттуда. Какая из 268 записей реестра наша,
решает геометрия, а не имя: та, в чей полигон попадает середина участков. Имя
площадки в реестре записано не так, как в выгрузке владельца, и совпадение по
слову однажды привело бы чужой полигон с уверенным видом.

**ЕГРН не спрашивается внутри запроса страницы.** Тридцать девять номеров по
три в потоке — это до пяти минут, а шлюз держит шестьдесят секунд: страница
отдала бы свою же ошибку вместо карты. Ответы копятся порциями на диске
(`DATA_DIR/market/krt/parcels/`), дочитывает фон, а страница показывает, чего
ещё не спрашивали.

Запуск проверок: python3 -m pytest tests/test_the_nagatino_parcels_page.py -q
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

from market_search.http import load_json, save_json

REGISTRY_PATH = (Path(__file__).resolve().parent.parent
                 / "reference_data" / "krt" / "nagatino_parcels.json")

# Контур участка меняется реже, чем живёт кэш; неответ ЕГРН — свойство минуты,
# а не участка, поэтому у отказа свой короткий срок. Тот же расклад, что у
# карточки города: разовый сбой не должен обрекать участок на пустоту до конца
# недели, но и стучаться в НСПД при каждом открытии страницы незачем.
ANSWER_TTL_SECONDS = 7 * 24 * 3600
REFUSAL_TTL_SECONDS = 30 * 60
# Порция фонового чтения. Мала намеренно: за каждым номером свой запрос в
# НСПД, и тридцать девять подряд портал вправе счесть налётом. Порция ложится
# на диск целиком — перезапуск контейнера посреди чтения не теряет всё.
CHUNK = 6

_LOCK = threading.Lock()
_READING = False


class RegistryProblem(RuntimeError):
    """Реестра нет или он не читается. Это поломка, а не пустая карта."""


def registry() -> dict[str, Any]:
    """Разобранная выгрузка владельца. Копии её чисел на странице нет."""
    try:
        with REGISTRY_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryProblem(f"реестр участков не прочитан: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise RegistryProblem("у реестра участков чужая схема")
    return data


def numbers() -> list[str]:
    """Номера, по которым спрашивается контур: строения И участки территории.

    Состав берётся из извещения о торгах — это официальный состав территории;
    строки присланного владельцем файла добавляются к нему, а не заменяют его:
    один объект есть в файле и нет в извещении.
    """
    out = [str(row.get("cadastral_number") or "")
           for row in registry().get("parcels") or []
           if row.get("cadastral_number")]
    notice = documents()["notice"]
    out += [str(item["cadastral_number"]) for item in notice.get("objects") or []]
    out += [str(item["cadastral_number"]) for item in notice.get("lands") or []]
    return list(dict.fromkeys(number for number in out if number))


def cache_path() -> Path:
    """Где лежат ответы ЕГРН. `DATA_DIR` спрашивается на вызове, а не на
    импорте: в прогоне он подменяется временным каталогом, и запомненный путь
    увёл бы тесты писать в рабочее дерево репозитория."""
    return Path(os.getenv("DATA_DIR", "data")) / "market" / "krt" / "parcels" / "nagatino.json"


def _answers() -> dict[str, Any]:
    cached = load_json(cache_path())
    if isinstance(cached, dict) and cached.get("schema_version") == 1:
        answers = cached.get("answers")
        return dict(answers) if isinstance(answers, dict) else {}
    return {}


def _stale(answer: Any) -> bool:
    """Пора ли спрашивать номер заново. Незаданный ответ — всегда пора."""
    if not isinstance(answer, dict):
        return True
    ttl = ANSWER_TTL_SECONDS if answer.get("rings") else REFUSAL_TTL_SECONDS
    asked = answer.get("asked_at")
    return not isinstance(asked, (int, float)) or time.time() - float(asked) > ttl


def unread(answers: dict[str, Any] | None = None) -> list[str]:
    """Номера, по которым ответа ЕГРН нет или он протух."""
    known = _answers() if answers is None else answers
    return [number for number in numbers() if _stale(known.get(number))]


def _record(item: Any) -> dict[str, Any]:
    """Ответ ЕГРН по одному номеру — в том виде, в каком он ложится на диск."""
    now = int(time.time())
    if not isinstance(item, dict) or not item.get("found"):
        reason = str((item or {}).get("note") or "") if isinstance(item, dict) else ""
        return {"asked_at": now, "rings": [],
                "reason": reason or "в ЕГРН по этому номеру сведений не найдено"}
    rings = [ring for ring in (item.get("contour_merc") or [])
             if isinstance(ring, list) and len(ring) >= 3]
    return {
        "asked_at": now,
        "rings": rings,
        "reason": "" if rings else "в ЕГРН есть сведения, но контура у объекта нет",
        # Площадь и стоимость ЕГРН кладутся РЯДОМ с числами файла, а не вместо
        # них: два источника на одну величину — расхождение называется вслух, а
        # не выбирается молча.
        "egrn": {
            "address": str(item.get("address") or ""),
            "area_sqm": item.get("area_sqm"),
            "cadastral_value_rub": item.get("cadastral_value_rub"),
            "permitted_use": str(item.get("permitted_use") or ""),
            "map_url": str(item.get("map_url") or ""),
            # Вид объекта — часть ответа, а не подробность: выгрузка названа
            # «участками», а ЕГРН по всем тридцати девяти номерам отвечает
            # «объект капитального строительства». Здание и участок меряются
            # разной площадью, и подписать одно другим значит сказать неправду.
            "kind": str(item.get("kind") or ""),
            "kind_label": str(item.get("kind_label") or ""),
            # Центр объекта нужен, чтобы спросить, что под ним: поле «кадастровый
            # номер ЗУ» у здания ЕГРН отдаёт пустым по всем 39 номерам, и
            # опираться на него нельзя.
            "center": item.get("center") if isinstance(item.get("center"), dict) else None,
            "purpose": str(item.get("purpose") or ""),
            "land_parcel": str(item.get("land_parcel") or ""),
        },
    }


def read_chunk(lookup: Callable[[list[str]], list[dict[str, Any]]],
               *, limit: int = CHUNK) -> dict[str, Any]:
    """Спросить ЕГРН по очередной порции номеров и положить ответы на диск.

    Возвращает состояние кэша. Отказ ЕГРН на одном номере не отменяет
    остальные: он ложится своей строкой с причиной.
    """
    known = _answers()
    ask = unread(known)[:max(1, int(limit))]
    state: dict[str, Any] = {"schema_version": 1, "answers": known,
                             "problem": "", "updated_at": int(time.time())}
    if not ask:
        save_json(cache_path(), state)
        return state
    try:
        found = list(lookup(ask) or [])
    except Exception as exc:  # noqa: BLE001 — неответ ЕГРН называется, а не молчит
        state["problem"] = f"ЕГРН не ответил: {type(exc).__name__}: {exc}"[:300]
        save_json(cache_path(), state)
        return state
    by_number = {str(item.get("cadastral_number") or ""): item
                 for item in found if isinstance(item, dict)}
    for number in ask:
        known[number] = _record(by_number.get(number))
    state["answers"] = known
    save_json(cache_path(), state)
    return state


# --- официальные документы: выписки ЕГРН и извещение о торгах -----------------
# Контуры по-прежнему приходят из НСПД: геометрия в выписках записана в ПМСК
# Москвы, а не в веб-меркаторе, и переводить её нам нечем. Всё остальное —
# площадь, собственник, аренда, участок под зданием, судьба объекта — из
# документов: они отвечают на то, чего публичный ответ НСПД не отдаёт.

# Первоисточники лежат в `reference_data`, а НЕ в `docs`, и это не вкусовщина:
# `.dockerignore` исключает `docs` целиком — «для человека, не для
# контейнера», — и на стенде страница вышла с нулями во всех плитках при
# тридцати шести полученных контурах. Разбор был исправен, читать было нечего.
# Файл, который читает приложение, это данные, а не документация, и лежать он
# обязан там, куда его копирует сборка.
EXTRACTS_DIR = Path(__file__).resolve().parent.parent / "reference_data" / "krt" / "egrn"
NOTICE_PATH = (Path(__file__).resolve().parent.parent / "reference_data" / "krt"
               / "nagatino-auction-notice-2026-08-14.pdf")
# Проект решения о КРТ (mos.ru). Его приложение 1 — картинка границ на снимке
# города, и она лежит здесь же по той же причине, что и извещение: ссылка
# протухает, файл нет.
DECISION_PATH = (Path(__file__).resolve().parent.parent / "reference_data" / "krt"
                 / "nagatino-decision-draft.pdf")


class OutlinePictureProblem(RuntimeError):
    """Картинки границ в документе нет. Это отказ, а не пустая картинка."""


def decision_outline_picture() -> bytes:
    """Приложение 1 к проекту решения — рисунок границ, как его напечатал город.

    Наложить его на нашу карту НЕЛЬЗЯ: это растр без координат, и совмещать
    его на глаз значит рисовать геометрию, которой у нас нет, — а выглядела бы
    она ровно так же уверенно, как настоящая. Поэтому картинка стоит рядом с
    картой, а не поверх неё, и подписана своим происхождением.

    Настоящий контур площадки при этом собирается из ПЕРЕЧНЯ того же решения:
    приложение 2 называет участки поимённо, а их границы отдаёт ЕГРН.
    """
    try:
        import pymupdf
    except Exception as exc:  # noqa: BLE001
        raise OutlinePictureProblem(f"нечем прочитать PDF: {exc}") from exc
    try:
        document = pymupdf.open(DECISION_PATH)
    except Exception as exc:  # noqa: BLE001
        raise OutlinePictureProblem(f"проект решения не открылся: {exc}") from exc
    for page in document:
        for info in page.get_images(full=True):
            pix = pymupdf.Pixmap(document, info[0])
            if pix.n > 4:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            # Мелкие картинки — это гербы и подписи, а не карта: берём первую
            # крупную. Порог назван числом, а не «на глаз»: приложение 1 идёт
            # снимком города почти на всю страницу.
            if pix.width >= 500 and pix.height >= 500:
                return pix.tobytes("png")
    raise OutlinePictureProblem("в проекте решения не нашлось крупной картинки границ")

_DOCS: dict[str, Any] = {}


def documents() -> dict[str, Any]:
    """Разобранные первоисточники. Читаются один раз на процесс.

    Разобранной копии на диске не заводим: копию негде обновлять, а разбор
    59 файлов стоит десятки миллисекунд. Извещение — PDF на 46 страниц, и его
    разбор кэшируется здесь же, а не пересчитывается на каждый запрос.
    """
    if _DOCS:
        return _DOCS
    from auction_search import egrn_extracts, krt_notice

    builds: dict[str, Any] = {}
    lands: dict[str, Any] = {}
    problems: list[str] = []
    for path in sorted(EXTRACTS_DIR.glob("*.xml")):
        try:
            record = egrn_extracts.read(path.read_bytes())
        except Exception as exc:  # noqa: BLE001 — негодный файл называется поимённо
            problems.append(f"{path.name}: {type(exc).__name__}: {exc}"[:200])
            continue
        (lands if record["kind"] == "land" else builds)[record["cadastral_number"]] = record
    try:
        notice = krt_notice.read(NOTICE_PATH)
    except Exception as exc:  # noqa: BLE001
        notice = {"lands": [], "objects": [], "rows": 0,
                  "problem": f"{type(exc).__name__}: {exc}"[:200]}
    _DOCS.update({"builds": builds, "lands": lands, "notice": notice, "problems": problems})
    return _DOCS


def _palette() -> dict[str, str]:
    """Оттенок каждому владельцу. Считается один раз и не зависит от порядка чтения.

    Брынцалов красный, Москва зелёная, остальные — жёлтая гамма по своему
    оттенку на владельца (решение владельца, 07.09.2026). Оттенок достаётся по
    УБЫВАНИЮ метров: любой другой порядок — например порядок файлов в каталоге —
    перекрашивал бы карту сама собой от прогона к прогону.
    """
    from auction_search import egrn_extracts

    data = registry()
    groups = {str(g.get("key")): g for g in data.get("groups") or []}
    by_key = {str(k): str(v) for k, v in (data.get("owner_groups") or {}).items()}
    shades = list(data.get("other_shades") or []) or ["#C9922A"]
    docs = documents()
    weight: dict[str, float] = {}
    named: dict[str, dict[str, Any]] = {}
    for record in list(docs["builds"].values()) + list(docs["lands"].values()):
        owner = egrn_extracts.owner_of(record)
        if not owner:
            continue
        key = owner["key"]
        named.setdefault(key, owner)
        weight[key] = weight.get(key, 0.0) + float(record.get("area_sqm") or 0)
    colours: dict[str, str] = {}
    rest: list[str] = []
    for key in sorted(weight, key=lambda item: (-weight[item], item)):
        group = by_key.get(str(named[key].get("inn") or "")) or by_key.get(key) or "other"
        if group in ("bryntsalov", "moscow"):
            colours[key] = str((groups.get(group) or {}).get("colour") or "#8a8a8a")
        else:
            rest.append(key)
    for index, key in enumerate(rest):
        colours[key] = shades[index % len(shades)]
    return colours


def group_of(owner: dict[str, Any]) -> str:
    """Группа владельца: по ИНН, а у публичного лица — по его ключу."""
    data = registry()
    by_key = {str(k): str(v) for k, v in (data.get("owner_groups") or {}).items()}
    return (by_key.get(str(owner.get("inn") or ""))
            or by_key.get(str(owner.get("key") or "")) or "other")


def _owner_view(record: dict[str, Any], groups_by_inn: dict[str, str],
                groups: dict[str, Any]) -> dict[str, Any]:
    """Собственник объекта в том виде, в каком его показывают.

    Пусто — ответ документа, а не наш пробел: у 14 участков из 20 право
    собственности не зарегистрировано вовсе. Так и написано.
    """
    from auction_search import egrn_extracts

    owner = egrn_extracts.owner_of(record) if record else None
    # Иное право — не собственность: девять строений записаны за городом, а
    # держит их ГБУ «Жилищник» на оперативном управлении. Назвать учреждение
    # собственником значит показать не то лицо.
    others = egrn_extracts.other_rights(record) if record else []
    if not owner:
        return {"name": "", "inn": "", "ogrn": "", "kind": "", "others": others,
                "note": ("право собственности не зарегистрировано"
                         if record else "выписки на объект нет"),
                "group": "none", "colour": str((groups.get("none") or {}).get("colour") or "#8a8a8a"),
                "group_title": str((groups.get("none") or {}).get("title") or "")}
    group = group_of(owner)
    return {"name": owner.get("name") or "", "inn": owner.get("inn") or "",
            "ogrn": owner.get("ogrn") or "", "kind": owner.get("kind") or "",
            "code": owner.get("code") or "", "key": owner.get("key") or "",
            "since": owner.get("since") or "", "note": "", "others": others,
            "group": group,
            # Оттенок — свойство ВЛАДЕЛЬЦА, а не группы: у «прочих» их семеро, и
            # одним цветом они на карте неразличимы.
            "colour": _palette().get(owner.get("key") or "")
                      or str((groups.get(group) or {}).get("colour") or "#8a8a8a"),
            "group_title": str((groups.get(group) or {}).get("title") or "")}


def _owner_conflict(file_owner: dict[str, Any], egrn_owner: dict[str, Any],
                    record: dict[str, Any]) -> str:
    """Что говорят о владельце выгрузка и выписка, когда они говорят разное.

    Молчание расхождением не считается: у объекта без выписки или без
    зарегистрированного права ответ один, а не два. Совпадение по ИНН — тоже
    согласие, даже если имена написаны по-разному.
    """
    file_name = str(file_owner.get("short") or file_owner.get("name") or "")
    egrn_name = str(egrn_owner.get("name") or "")
    if not file_name or not egrn_name:
        return ""
    if str(file_owner.get("inn") or "") and str(file_owner.get("inn") or "") == str(egrn_owner.get("inn") or ""):
        return ""
    # Чаще всего это не спор, а разные вопросы: выгрузка называет того, кто
    # зданием ПОЛЬЗУЕТСЯ, выписка — того, за кем оно записано. Так у восьми
    # строений «Жилищника»: собственник город Москва, у ГБУ оперативное
    # управление. Если названный выгрузкой держит на объекте иное право, так и
    # сказано — иначе это настоящее расхождение источников.
    inn = str(file_owner.get("inn") or "")
    for right in (record.get("owner") or {}).get("others") or []:
        holder = right if isinstance(right, dict) else {}
        same = (inn and str(holder.get("inn") or "") == inn) or (
            file_owner.get("name") and str(holder.get("name") or "") == str(file_owner.get("name")))
        if same:
            # Право называется тем словом, которым его назвала выписка:
            # «оперативное управление» и «иное право» — разные утверждения.
            right_type = str(holder.get("right_type") or "").strip()
            named = right_type[:1].lower() + right_type[1:] if right_type else "иное право"
            return (f"в выгрузке назван {file_name} — у него {named}; "
                    f"собственник по ЕГРН — {egrn_name}")
    return f"в выгрузке — {file_name}, собственник по ЕГРН — {egrn_name}"


def fill_in_background(lookup: Callable[[list[str]], list[dict[str, Any]]],
                       *, find_site: Callable[[], dict[str, Any]] | None = None) -> bool:
    """Дочитать недостающие контуры фоном. Работу берёт один.

    Воркеров два, память у них раздельная: без замка оба пошли бы спрашивать
    портал об одном и том же. Возвращает, началось ли чтение, — страница на
    это опирается, когда говорит «читаю ЕГРН».

    Площадка КРТ ищется здесь же и после участков: искать её не по чему, пока
    не прочитан ни один контур, а файл карты города — ещё один поход наружу,
    и в запросе страницы ему не место.
    """
    global _READING
    # Выключатель — не осторожность, а правило: поход в ЕГРН начинается сам,
    # при открытии страницы, и в прогоне тестов ему делать нечего ровно по той
    # же причине, по которой там не должно быть недельного обхода каталога.
    if os.getenv("NAGATINO_EGRN_READ", "1").strip().lower() in ("0", "no", "off", "false"):
        return False
    if not unread() and (find_site is None or cached_site().get("rings_merc")):
        return False
    with _LOCK:
        if _READING:
            return False
        _READING = True

    def run() -> None:
        global _READING
        try:
            while unread():
                before = len(unread())
                state = read_chunk(lookup)
                if state.get("problem") or len(unread()) >= before:
                    break  # портал молчит — не долбимся, следующее открытие повторит
            if find_site is not None and not cached_site().get("rings_merc"):
                try:
                    store_site(find_site())
                except Exception as exc:  # noqa: BLE001 — отказ называется, а не молчит
                    store_site({"problem": f"площадка не опознана: {type(exc).__name__}: {exc}"[:200]})
        finally:
            with _LOCK:
                _READING = False

    threading.Thread(target=run, name="nagatino-parcel-outlines", daemon=True).start()
    return True


def _centre(answers: dict[str, Any]) -> list[float] | None:
    """Середина прочитанных участков. Нет ни одного — не по чему искать."""
    points = [point for answer in answers.values()
              if isinstance(answer, dict)
              for ring in (answer.get("rings") or [])
              for point in ring
              if isinstance(point, (list, tuple)) and len(point) >= 2]
    if not points:
        return None
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    return [(min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0]


def resolve_site(sites: list[dict[str, Any]],
                 crossings: Callable[[list[Any], float], list[float]]) -> dict[str, Any]:
    """Запись реестра КРТ, в чей полигон попадает середина участков.

    Опознаём геометрией, а не именем: у площадки в реестре имя записано иначе,
    чем в выгрузке владельца, и совпадение по слову привело бы чужой полигон —
    ошибка того же рода, что «улица опознаёт квартал, а не площадку». Полигоны
    и правило пересечения — чужие: реестра и движка (`_row_crossings`), своей
    геометрии здесь нет.
    """
    centre = _centre(_answers())
    if not centre:
        return {"problem": "участки ещё не прочитаны — искать площадку не по чему"}
    x, y = float(centre[0]), float(centre[1])
    for site in sites or []:
        rings = [ring for ring in (site.get("rings_merc") or [])
                 if isinstance(ring, list) and len(ring) >= 3]
        if not rings:
            continue
        if sum(1 for cx in crossings([[ring] for ring in rings], y) if cx > x) % 2 == 1:
            return {"slug": str(site.get("slug") or ""), "name": str(site.get("name") or ""),
                    "okrug": str(site.get("okrug") or ""), "district": str(site.get("district") or ""),
                    "status": str(site.get("status") or ""), "area_ha": site.get("area_ha"),
                    "rings_merc": rings, "matched": "geometry", "problem": ""}
    return {"problem": ("середина участков не попала ни в один полигон реестра КРТ — "
                        "площадки в файле карты города нет либо её границы другие")}


def store_site(site: dict[str, Any]) -> None:
    """Положить опознанную площадку рядом с ответами ЕГРН, в тот же кэш."""
    state = load_json(cache_path())
    state = dict(state) if isinstance(state, dict) and state.get("schema_version") == 1 else {
        "schema_version": 1, "answers": {}, "problem": ""}
    state["site"] = dict(site)
    state["updated_at"] = int(time.time())
    save_json(cache_path(), state)


def cached_site() -> dict[str, Any]:
    state = load_json(cache_path())
    site = (state or {}).get("site") if isinstance(state, dict) else None
    return dict(site) if isinstance(site, dict) else {"problem": "площадку ещё не искали"}


def reading() -> bool:
    return _READING


def _kinds(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Что это по ЕГРН — здания или участки, и сколько чего.

    Выгрузка названа «участками», а ЕГРН по каждому номеру отвечает своим
    видом. Здание меряется площадью здания, участок — площадью земли: пока вид
    не назван, одна колонка «пл» читается как земля и попадает в плотность.
    """
    seen: dict[str, int] = {}
    for row in rows:
        label = str(((row.get("egrn") or {}).get("kind_label") or "")) or "не спрашивали"
        seen[label] = seen.get(label, 0) + 1
    asked = sum(count for label, count in seen.items() if label != "не спрашивали")
    return {"counts": seen, "asked": asked,
            "land": len([r for r in rows if (r.get("egrn") or {}).get("kind") == "land"]),
            "buildings": len([r for r in rows if (r.get("egrn") or {}).get("kind") == "building"])}


# Договор аренды городской земли в Москве нумеруется по-своему: «М-05-…»
# (Департамент городского имущества) и «…-05 ДГИ» / «…-05 ДЗР» — его прежние
# имена. По этому номеру видно арендодателя, которого сама выписка не называет.
_CITY_CONTRACT = re.compile(r"^\s*(?:М-\d{2}-|\d+\s*-\s*\d{2}\s*(?:ДГИ|ДЗР))", re.I)


def disposal_note(land: dict[str, Any]) -> dict[str, str]:
    """Кто распоряжается участком — НАШ вывод, и он подписан как наш.

    Владелец, 07.09.2026: «и твоё про „распоряжается город“ там тоже должно быть
    отмечено». Отмечено — но отдельной графой: в клетке «статус земли» стоит
    ответ ЕГРН, а здесь наше суждение с его основанием. Слитые в одну клетку,
    они читались бы как одна запись реестра.

    Оснований два, и они разной силы. Номер договора аренды городского вида —
    это документ: арендодателем выступает город. Без такого договора остаётся
    общее правило (в Москве неразграниченная госсобственность в распоряжении
    города), и это сказано именно как правило, а не как факт об участке.
    """
    if land["owner"].get("name"):
        return {"who": "", "ground": "распоряжается собственник"}
    for item in land.get("leases") or []:
        number = str(item.get("document_number") or "")
        if number and _CITY_CONTRACT.match(number):
            return {"who": "город Москва",
                    "ground": f"вывод DevelopAid: договор аренды {number} — городской"}
    if land.get("leases"):
        return {"who": "город Москва",
                "ground": ("вывод DevelopAid: участок сдан в аренду, а собственность не "
                           "зарегистрирована — распоряжается город")}
    return {"who": "вероятно город Москва",
            "ground": ("вывод DevelopAid по общему правилу: в Москве неразграниченная "
                       "государственная собственность в распоряжении города. "
                       "По этому участку подтверждения в документах нет")}


def territory() -> dict[str, Any]:
    """Свод «земельный участок → объекты на нём» по официальным документам.

    Состав территории берётся из ИЗВЕЩЕНИЯ (оно свежее проекта решения и оно
    основание торгов), а свойства объектов — из выписок ЕГРН. Расхождение
    между документами называется вслух, а не выбирается молча: в извещении
    есть объект, которого нет в выписках, и наоборот.

    Складывать площадь земли с площадью строений нельзя — это разные величины;
    объект, стоящий на нескольких участках, повторяется у каждого, и его метры
    в итог территории входят ОДИН раз.
    """
    data = registry()
    docs = documents()
    groups = {str(g.get("key")): g for g in data.get("groups") or []}
    by_inn = {str(k): str(v) for k, v in (data.get("owner_groups") or {}).items()}
    notice = docs["notice"]
    answers = _answers()

    from auction_search import egrn_extracts

    objects_by_cad: dict[str, dict[str, Any]] = {}
    for item in notice.get("objects") or []:
        cad = item["cadastral_number"]
        extract = docs["builds"].get(cad)
        objects_by_cad[cad] = {
            "cadastral_number": cad,
            # Площадь объекта — из выписки, а рядом та, что стоит в извещении:
            # два источника на одну величину, и расхождение видно, а не выбрано.
            "area_sqm": (extract or {}).get("area_sqm"),
            "notice_area_sqm": item.get("area_sqm"),
            "notice_area_raw": item.get("area_raw") or "",
            "fate": item.get("fate") or "",
            "part": bool(item.get("part")),
            "lands": list(item.get("lands") or []),
            "name": (extract or {}).get("name") or "",
            "purpose": (extract or {}).get("purpose") or "",
            "floors": (extract or {}).get("floors") or "",
            "year_built": (extract or {}).get("year_built") or "",
            "address": (extract or {}).get("address") or "",
            "cadastral_value_rub": (extract or {}).get("cadastral_value_rub"),
            "owner": _owner_view(extract, by_inn, groups),
            "leases": egrn_extracts.leases(extract) if extract else [],
            "encumbrances": (egrn_extracts.encumbrances(extract, lease=False)
                             if extract else []),
            "colour": _owner_view(extract, by_inn, groups)["colour"],
            "colour_from": ("свой собственник"
                            if _owner_view(extract, by_inn, groups).get("name")
                            else "владелец не назван"),
            "extract": bool(extract),
            "rings_merc": list(((answers.get(cad) or {}).get("rings")) or []),
        }
    # Объект, на который выписка есть, а в извещении его нет, — это ответ
    # документа о составе территории, и он называется отдельно.
    # У объекта, которого нет в извещении, называются и участки под ним: у
    # 77:05:0004001:2077 это 77:05:0004001:7 и 77:05:0004001:2841, и второго в
    # территории нет вовсе. «В списках нигде нет 77:05:0004001:2841» (владелец,
    # 07.09.2026) — он и не должен там быть, но раз номер встречается в наших
    # документах, молчать о нём нельзя: молчание читается как пропажа.
    outside = sorted(set(docs["builds"]) - set(objects_by_cad))
    lands_by_cad = {item["cadastral_number"] for item in notice.get("lands") or []}

    lands = []
    for land in notice.get("lands") or []:
        cad = land["cadastral_number"]
        extract = docs["lands"].get(cad)
        here = [objects_by_cad[o["cadastral_number"]] for o in land.get("objects") or []
                if o["cadastral_number"] in objects_by_cad]
        seen: dict[str, dict[str, Any]] = {}
        for item in here:
            seen.setdefault(item["cadastral_number"], item)
        here = list(seen.values())
        # Цвет участка: свой собственник, если право зарегистрировано; иначе —
        # владелец строений на нём, когда он один («участки под его зданиями
        # такого же оттенка», владелец 07.09.2026). Строения разных владельцев
        # на одном участке одним цветом не красим: это было бы утверждением о
        # владельце земли, которого никто не делал.
        own = _owner_view(extract, by_inn, groups)
        keys = {item["owner"].get("key") for item in here if item["owner"].get("name")}
        borrowed = ""
        colour = own["colour"]
        if not own.get("name") and len(keys) == 1:
            source_owner = next(item["owner"] for item in here if item["owner"].get("key"))
            borrowed = source_owner.get("name") or ""
            colour = source_owner.get("colour") or own["colour"]
        elif not own.get("name") and len(keys) > 1:
            # Лица разные, а группа одна — участок красится ГРУППОЙ. «Почему
            # этот участок не красный?» (владелец, 07.09.2026): на 77:05:0004001:15
            # стоят «Причал» и «Новый проект», оба у Брынцалова, и правило
            # «владелец должен быть один» красило землю серым — то есть
            # «неизвестно чья» там, где известно, чья группа. Оттенок берётся
            # групповой, а не личный: личный принадлежит одному из них, а
            # участок общий.
            near_groups = {str((item["owner"] or {}).get("group") or "")
                           for item in here if item["owner"].get("key")}
            if len(near_groups) == 1 and near_groups != {""}:
                key = near_groups.pop()
                colour = str((groups.get(key) or {}).get("colour") or own["colour"])
                borrowed = f"группа {(groups.get(key) or {}).get('title') or key}"
        lands.append({
            "cadastral_number": cad,
            "part": bool(land.get("part")),
            "colour": colour,
            "colour_from": ("свой собственник" if own.get("name")
                            else f"строения одной группы: {borrowed.split('группа ')[-1]}"
                            if borrowed.startswith("группа ")
                            else f"владелец строений: {borrowed}" if borrowed
                            else "строения разных владельцев" if len(keys) > 1
                            else "владелец не назван"),
            "area_sqm": (extract or {}).get("area_sqm"),
            "notice_area_sqm": land.get("area_sqm"),
            "area_kind": (extract or {}).get("area_kind") or "",
            "category": (extract or {}).get("category") or "",
            "permitted_use": (extract or {}).get("permitted_use") or "",
            "address": (extract or {}).get("address") or "",
            "cadastral_value_rub": (extract or {}).get("cadastral_value_rub"),
            "special_notes": (extract or {}).get("special_notes") or "",
            "owner": _owner_view(extract, by_inn, groups),
            "leases": egrn_extracts.leases(extract) if extract else [],
            "encumbrances": (egrn_extracts.encumbrances(extract, lease=False)
                             if extract else []),
            "objects": here,
            "objects_area_sqm": _sum([item.get("area_sqm") for item in here]),
            "rings_merc": list(((answers.get(cad) or {}).get("rings")) or []),
            "extract": bool(extract),
        })
    # Строение без зарегистрированного права красится по СВОЕМУ участку, когда
    # у того собственник назван и он один («очевидно, что это всё на участке и
    # рядом с Автокомбинатом и к нему относится» — владелец, 07.09.2026). Это
    # соседство по документу, а не право: в графе собственника по-прежнему
    # стоит ответ ЕГРН, а цвет подписан «по владельцу участка». Круга здесь
    # нет: участок занимает цвет только у строений с НАЗВАННЫМ владельцем, а
    # строение — только у участка с названным.
    owner_of_land = {item["cadastral_number"]: item["owner"] for item in lands
                     if item["owner"].get("name")}
    for item in objects_by_cad.values():
        if item["owner"].get("name"):
            continue
        near = {owner_of_land[cad]["key"]: owner_of_land[cad]
                for cad in item.get("lands") or [] if cad in owner_of_land}
        if len(near) != 1:
            continue
        source_owner = next(iter(near.values()))
        item["colour"] = source_owner.get("colour")
        item["colour_from"] = f"владелец участка: {source_owner.get('name')}"
    for land in lands:
        land["disposal"] = disposal_note(land)
        # Право не зарегистрировано — строка не должна кончаться молчанием:
        # «может писать мелко, что судя по договору аренды с ДГИ это тоже
        # Москва» (владелец, 07.09.2026). Вывод стоит МЕЛКИМ и подписан своим
        # именем: запись реестра и наше прочтение под одной строкой читались бы
        # как одно утверждение.
        if not (land["owner"] or {}).get("name") and land["disposal"].get("who"):
            # Подпись «вывод DevelopAid» уже стоит в самом основании — второй
            # раз её не приписываем.
            land["owner"]["guess"] = (f"{land['disposal']['ground']} — "
                                      f"распоряжается {land['disposal']['who']}")
    # То же у строения без своего права: оно стоит на чьей-то земле, и чьей —
    # сказано. «Судя по тому, что на участке автокомбината, это их
    # собственность» — вывод, а не запись ЕГРН, и так и написано.
    for item in objects_by_cad.values():
        owner = item.get("owner") or {}
        if owner.get("name") or not item.get("colour_from", "").startswith("владелец участка"):
            continue
        near = [cad for cad in item.get("lands") or [] if cad in owner_of_land]
        holder = owner_of_land.get(near[0]) if near else None
        if holder:
            owner["guess"] = (f"вывод DevelopAid: участок под ним — {holder.get('name')}; "
                              "вероятно, строение его же")
    lands.sort(key=lambda item: -(item.get("area_sqm") or item.get("notice_area_sqm") or 0))
    objects = list(objects_by_cad.values())
    # Номер участка и номер строения — чтобы связать карту с таблицей глазами
    # («прономеруй от 1 до 20 все участки и здания от 1 до 39 на карте и в
    # таблице, чтобы можно было привязью визуализировать», владелец,
    # 07.09.2026). Считаются ЗДЕСЬ, а не на странице: у одного объекта один
    # номер на карте, в таблице, в подсказке и в книге, а второй счёт дал бы
    # свою нумерацию каждой поверхности. Ряды независимые: участок и строение —
    # разные вещи, и общий счётчик читался бы как один список из 59 штук.
    #
    # Порядок — тот, в котором строки уже стоят: участки по убыванию площади,
    # строения по составу извещения. Номер не свойство объекта, а место в
    # ЭТОМ списке, поэтому и присваивается после сортировки.
    for index, land in enumerate(lands, start=1):
        land["no"] = index
    # Строения нумеруются обходом участков в их порядке: у одного участка номера
    # идут подряд, и на карте соседние здания подписаны соседними числами.
    # Объект на нескольких участках получает номер у первого — считается он один
    # раз, как и его метры.
    order: list[str] = []
    for land in lands:
        for item in land["objects"]:
            if item["cadastral_number"] not in order:
                order.append(item["cadastral_number"])
    for item in objects:
        if item["cadastral_number"] not in order:
            order.append(item["cadastral_number"])
    numbered = {number: index for index, number in enumerate(order, start=1)}
    for item in objects:
        item["no"] = numbered.get(item["cadastral_number"])
    objects.sort(key=lambda item: item["no"] or 0)
    for land in lands:
        for item in land["objects"]:
            item["no"] = numbered.get(item["cadastral_number"])
    return {
        "lands": lands,
        "objects": objects,
        "objects_outside_notice": [
            {"cadastral_number": cad,
             "area_sqm": docs["builds"][cad].get("area_sqm"),
             "owner": _owner_view(docs["builds"][cad], by_inn, groups),
             "lands": list(docs["builds"][cad].get("lands") or []),
             # Участок под таким объектом может не входить в территорию вовсе —
             # тогда он назван, а не пропущен.
             "lands_outside": [number for number in docs["builds"][cad].get("lands") or []
                               if number not in lands_by_cad]}
            for cad in outside],
        "totals": {
            "lands": len(lands),
            "land_area_sqm": _sum([item.get("area_sqm") for item in lands]),
            # Два участка входят в территорию ЧАСТЬЮ, и по ЕГРН они считаются
            # целыми: 18,69 га против 14,01 по извещению. «По решению 14 га
            # отдают, а у тебя сумма участков 19 почти» (владелец, 07.09.2026)
            # — обе величины верны, но отвечают на разные вопросы: сколько
            # земли у участков и сколько её входит в площадку.
            "land_area_in_notice_sqm": _sum([item.get("notice_area_sqm") for item in lands]),
            "lands_partly_inside": len([item for item in lands if item.get("part")]),
            # Плюс земля без кадастрового номера: «территории, в границах
            # которых земельные участки не сформированы». Вместе они дают
            # ровно ту площадку, которую извещение называет в шапке.
            "land_unformed_sqm": _sum([item.get("area_sqm")
                                       for item in notice.get("unformed") or []]),
            "site_area_sqm": round(
                _sum([item.get("notice_area_sqm") for item in lands])
                + _sum([item.get("area_sqm") for item in notice.get("unformed") or []]), 1),
            "land_value_rub": _sum([item.get("cadastral_value_rub") for item in lands]),
            "objects": len(objects),
            # Объект на нескольких участках считается ОДИН раз: строк в таблице
            # извещения 47, объектов 39.
            "objects_area_sqm": _sum([item.get("area_sqm") for item in objects]),
            "objects_notice_area_sqm": _sum([item.get("notice_area_sqm") for item in objects]),
            "objects_value_rub": _sum([item.get("cadastral_value_rub") for item in objects]),
            "rows_in_notice": notice.get("rows") or 0,
            "objects_without_extract": len([o for o in objects if not o["extract"]]),
            "lands_without_extract": len([item for item in lands if not item["extract"]]),
        },
        "source": {**dict(data.get("source") or {}), "notice_problem": notice.get("problem", "")},
        "problems": list(docs.get("problems") or []),
    }


def owners_summary(view: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Кто чем владеет — по ИНН, а не по написанию имени."""
    view = territory() if view is None else view
    seen: dict[str, dict[str, Any]] = {}

    from auction_search import egrn_extracts

    def add(bucket: str, owner: dict[str, Any], area: Any, value: Any) -> None:
        # Ключ личности объявлен один раз — в разборе выписок. Свой второй
        # слепил бы разных владельцев: у публичного образования нет ни ИНН, ни
        # ОГРН, и все они сошлись бы в одну строку.
        key = (egrn_extracts.holder_key(owner) if owner.get("name")
               else "нет:" + (owner.get("note") or ""))
        # Одно лицо приходит в разном написании — показываем то, при котором
        # источник проставил код: у субъекта РФ 77 это «Москва».
        row = seen.get(key)
        if row is not None and owner.get("code") and not row.get("code"):
            row["name"] = owner.get("name") or row["name"]
            row["code"] = owner.get("code")
        row = seen.setdefault(key, {"name": owner.get("name") or owner.get("note") or "",
                                    "code": owner.get("code") or "",
                                    "inn": owner.get("inn") or "", "ogrn": owner.get("ogrn") or "",
                                    "kind": owner.get("kind") or "", "group": owner.get("group"),
                                    "group_title": owner.get("group_title"),
                                    "colour": owner.get("colour"),
                                    "lands": 0, "land_area_sqm": 0.0, "land_value_rub": 0.0,
                                    "objects": 0, "objects_area_sqm": 0.0, "objects_value_rub": 0.0})
        row[bucket] += 1
        row[f"{'land' if bucket == 'lands' else 'objects'}_area_sqm"] += float(area or 0)
        row[f"{'land' if bucket == 'lands' else 'objects'}_value_rub"] += float(value or 0)

    for land in view["lands"]:
        add("lands", land["owner"], land.get("area_sqm"), land.get("cadastral_value_rub"))
    for item in view["objects"]:
        add("objects", item["owner"], item.get("area_sqm"), item.get("cadastral_value_rub"))
    under = land_under_buildings(view)["by_owner"]
    rows = list(seen.values())
    for key, row in seen.items():
        # Справочно: земля ПОД строениями этого владельца. Своей она ему не
        # становится — колонка «Земли» рядом отвечает на другой вопрос.
        row["under_lands"] = (under.get(key) or {}).get("lands", 0)
        row["under_land_area_sqm"] = (under.get(key) or {}).get("area_sqm", 0.0)
    for row in rows:
        for key in ("land_area_sqm", "objects_area_sqm", "land_value_rub", "objects_value_rub"):
            row[key] = round(row[key], 1)
    rows.sort(key=lambda row: -(row["land_area_sqm"] + row["objects_area_sqm"]))
    return rows


def _land_area_in_site(land: dict[str, Any]) -> float:
    """Площадь участка В ГРАНИЦАХ ПЛОЩАДКИ, а не по ЕГРН.

    «Если этот участок с 40 на конце не Брынцалова, значит под его зданиями не
    половина всех площадей» (владелец, 07.09.2026). Он прав, и разница тут в
    три порядка: дорога 77:05:0004001:40 — 43 288,13 м² по ЕГРН, а в площадку
    входит 61 м², ровно там, где на неё заходят два сносимых строения. Пока
    справочная земля считалась площадью участка ЦЕЛИКОМ, у Брынцалова выходило
    97 563 м² — 52% всей земли территории, — из которых 43 288 это чужая
    улично-дорожная сеть, в площадке не участвующая. По площади, входящей в
    площадку, у него 54 336 м², то есть 29%.

    Правило объявлено один раз и служит обеим таблицам: два ответа на «сколько
    земли под его строениями» разошлись бы молча, и оба выглядели бы верными.
    Участок, входящий целиком, отвечает своей площадью — вопрос к нему тот же.
    """
    if land.get("part") and land.get("notice_area_sqm") is not None:
        return float(land["notice_area_sqm"])
    return float(land.get("area_sqm") or 0)


def land_under_buildings(view: dict[str, Any] | None = None) -> dict[str, Any]:
    """Справочно: на какой земле стоят строения владельца и всей группы.

    «Надо наверное на сводной второй вкладке справочно указывать какая площадь
    участков под всеми зданиями группы?» (владелец, 07.09.2026). У Брынцалова
    земли по документам нет вовсе — его семнадцать строений стоят на чужой и
    неразграниченной, — и без этой строки колонка «Земли» читается как «этот
    владелец к земле отношения не имеет».

    Число **не складывается**, и это свойство вопроса, а не ошибка счёта: на
    участке Автокомбината стоят и три строения без зарегистрированного права,
    поэтому его 43 288 м² считаются и у него, и у группы «право не
    зарегистрировано». Поэтому участки собираются МНОЖЕСТВОМ, а итог группы
    считается объединением, а не суммой строк: сумма дала бы 232 919 м² при
    186 860 существующих. Складывать эту колонку нельзя, и так и написано.
    """
    from auction_search import egrn_extracts

    view = territory() if view is None else view
    lands = {land["cadastral_number"]: land for land in view["lands"]}
    by_owner: dict[str, set[str]] = {}
    by_group: dict[str, set[str]] = {}
    everything: set[str] = set()
    for item in view["objects"]:
        owner = item.get("owner") or {}
        key = (egrn_extracts.holder_key(owner) if owner.get("name")
               else "нет:" + str(owner.get("note") or ""))
        numbers = {number for number in item.get("lands") or [] if number in lands}
        by_owner.setdefault(key, set()).update(numbers)
        by_group.setdefault(str(owner.get("group") or ""), set()).update(numbers)
        everything |= numbers

    def measure(numbers: set[str]) -> dict[str, Any]:
        inside = [lands[number] for number in sorted(numbers) if number in lands]
        return {"lands": len(numbers),
                "area_sqm": round(sum(_land_area_in_site(land) for land in inside), 1),
                # Площадь по ЕГРН стоит рядом, а не вместо: оба числа верны и
                # отвечают на разные вопросы, и выбрать одно молча нельзя.
                "egrn_area_sqm": round(sum(float(land.get("area_sqm") or 0)
                                           for land in inside), 1),
                "parts": [land["cadastral_number"] for land in inside if land.get("part")]}

    return {"by_owner": {key: measure(value) for key, value in by_owner.items()},
            "by_group": {key: measure(value) for key, value in by_group.items()},
            "total": measure(everything)}


def land_holdings(view: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Второй взгляд: чьё это, если считать по участку.

    Правило владельца (07.09.2026) узкое, и шире его брать нельзя: «разница
    только в том, что бесхозные строения на земле автокомбината — явно
    автокомбината. А правообладатель там, где не указано, что собственность
    Москвы, но есть договор аренды с ДГИ, — ставим Москву».

    Отсюда ровно две правки к документам, и обе названы у каждой строки:

    1. **Земля.** Собственник по ЕГРН; записи нет, но участок сдан городом в
       аренду (договор «М-05-…» или «…-05 ДГИ») — Москва. Договора нет вовсе —
       тоже Москва, но по общему правилу: неразграниченной землёй в Москве
       распоряжается город, и основание у такой строки слабее, о чём сказано.
    2. **Строения.** Своё право сильнее всего: собственник остаётся собой.
       Приписывается только то, у чего права нет вовсе, — хозяину участка, на
       котором стоит.

    Чего здесь НЕ делается: земля не приписывается владельцу стоящих на ней
    строений. Первая версия так и считала — и нарисовала владельцами земли
    «Фабрику швейных изделий», НИИОГАЗ, «Каллисто» и «Россети», которых в
    реестре нет: «а у тебя куча владельцев земли нарисовалась, откуда?»
    Приписанное владение выглядит на экране ровно так же уверенно, как
    записанное.
    """
    from auction_search import egrn_extracts

    view = territory() if view is None else view
    groups = {str(g.get("key")): g for g in registry().get("groups") or []}
    lands = {land["cadastral_number"]: land for land in view["lands"]}

    def key_of(owner: dict[str, Any]) -> str:
        return egrn_extracts.holder_key(owner) if owner.get("name") else ""

    def city(ground: str) -> dict[str, Any]:
        return {"name": "Москва", "inn": "", "group": "moscow",
                "group_title": str((groups.get("moscow") or {}).get("title") or ""),
                "colour": str((groups.get("moscow") or {}).get("colour") or "#8a8a8a"),
                "by": ground}

    holder_of: dict[str, dict[str, Any]] = {}
    for number, land in lands.items():
        owner = dict(land.get("owner") or {})
        if owner.get("name"):
            holder_of[number] = {**owner, "by": "собственник по ЕГРН"}
            continue
        # Договор аренды с городом — это ответ документа, а не наша догадка:
        # его номер напечатан в выписке и стоит в основании строки.
        disposal = land.get("disposal") or {}
        ground = str(disposal.get("ground") or "")
        contract = re.search(r"договор аренды ([^\s—]+)", ground)
        if contract:
            holder_of[number] = city(f"аренда у города, договор {contract.group(1)}")
        elif str(disposal.get("who") or ""):
            holder_of[number] = city("неразграниченная земля — общее правило, "
                                     "договора в выписке нет")
        else:
            holder_of[number] = {"name": "", "note": "хозяин участка не назван",
                                 "group": None, "by": "не определён",
                                 "group_title": "Хозяин по участку не определён",
                                 "colour": str((groups.get("none") or {}).get("colour") or "#8a8a8a")}

    rows: dict[str, dict[str, Any]] = {}

    def bucket(holder: dict[str, Any]) -> dict[str, Any]:
        key = key_of(holder) or ("нет:" + str(holder.get("note") or holder.get("by") or ""))
        return rows.setdefault(key, {
            "name": holder.get("name") or holder.get("note") or "",
            "inn": holder.get("inn") or "", "group": holder.get("group"),
            "group_title": holder.get("group_title"), "colour": holder.get("colour"),
            "by": holder.get("by") or "", "lands": 0, "land_area_sqm": 0.0,
            # Стоимость земли и стоимость строений — РАЗНЫЕ величины, и в одну
            # колонку не складываются: «можно понять, где кадастровая стоимость
            # участков, а где строений?» (владелец, 07.09.2026). Сложенные, они
            # отвечают на вопрос, которого никто не задавал: у города своя земля
            # и свои строения, и выкупать не надо ни то ни другое, а у соседа
            # земли нет вовсе — вся его стоимость в строениях. Правило то же,
            # что у площадей, и здесь оно было нарушено.
            "objects": 0, "objects_area_sqm": 0.0,
            "land_value_rub": 0.0, "objects_value_rub": 0.0,
            # Участки ПОД строениями этой строки — множеством, а не суммой:
            # то же справочное число, что и в верхней таблице, и по той же
            # причине несложимое.
            "under_numbers": set()})

    for number, land in lands.items():
        row = bucket(holder_of[number])
        row["lands"] += 1
        row["land_area_sqm"] += float(land.get("area_sqm") or 0)
        row["land_value_rub"] += float(land.get("cadastral_value_rub") or 0)

    for item in view["objects"]:
        owner = dict(item.get("owner") or {})
        if owner.get("name"):
            # Собственник строения записан — приписывать его земле незачем.
            row = bucket({**owner, "by": "собственник по ЕГРН"})
        else:
            # Права нет: строение живёт судьбой земли под собой. Участки
            # разошлись — так и сказано, а не выбрано за источник.
            under = [holder_of[number] for number in item.get("lands") or []
                     if number in holder_of]
            keys = {key_of(holder) or ("нет:" + str(holder.get("by") or "")) for holder in under}
            if len(keys) == 1:
                row = bucket({**under[0], "by": f"строение без права — {under[0].get('by')}"})
            else:
                row = bucket({"name": "", "note": "строение без права на участках разных хозяев",
                              "group": None, "by": "не определён",
                              "group_title": "Хозяин по участку не определён"})
        row["objects"] += 1
        row["objects_area_sqm"] += float(item.get("area_sqm") or 0)
        row["objects_value_rub"] += float(item.get("cadastral_value_rub") or 0)
        row["under_numbers"].update(number for number in item.get("lands") or []
                                    if number in lands)

    out = list(rows.values())
    for row in out:
        for field in ("land_area_sqm", "objects_area_sqm",
                      "land_value_rub", "objects_value_rub"):
            row[field] = round(row[field], 1)
        numbers = row.pop("under_numbers")
        row["under_numbers"] = sorted(numbers)
        row["under_lands"] = len(numbers)
        # По той же мере, что и верхняя таблица: площадь, входящая в площадку.
        row["under_land_area_sqm"] = round(
            sum(_land_area_in_site(lands[number]) for number in numbers), 1)
        row["under_egrn_area_sqm"] = round(
            sum(float(lands[number].get("area_sqm") or 0) for number in numbers), 1)
        row["under_parts"] = [number for number in sorted(numbers) if lands[number].get("part")]
    out.sort(key=lambda row: -(row["land_area_sqm"] + row["objects_area_sqm"]))
    return out


def buyout(rows: list[dict[str, Any]] | None = None,
           view: dict[str, Any] | None = None) -> dict[str, Any]:
    """Что у города, а что придётся выкупать. По взгляду «по участку».

    «Очевидно, что у Москвы ничего выкупать не надо» (владелец, 07.09.2026).
    Верно, и потому вопрос сводится к остальному: сколько там участков,
    строений и какая у них кадастровая стоимость. Считается ЗДЕСЬ, рядом с
    числами: собранная на экране, эта фраза была бы вторым счётом той же
    величины, и разойтись с таблицей ей ничего не мешало бы.

    **Кадастровая стоимость — не цена выкупа**, и так и сказано вслух. Она
    берётся из ЕГРН, а выкуп идёт по соглашению или по оценке; называть её
    ценой значит выдать справочное число за коммерческое.
    """
    view = territory() if view is None else view
    rows = land_holdings(view) if rows is None else rows
    city = [row for row in rows if str(row.get("group") or "") == "moscow"]
    rest = [row for row in rows if str(row.get("group") or "") != "moscow"]

    def fold(part: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "holders": len(part),
            "lands": sum(int(row.get("lands") or 0) for row in part),
            "objects": sum(int(row.get("objects") or 0) for row in part),
            "land_area_sqm": round(sum(float(row.get("land_area_sqm") or 0)
                                       for row in part), 1),
            "objects_area_sqm": round(sum(float(row.get("objects_area_sqm") or 0)
                                          for row in part), 1),
            "land_value_rub": round(sum(float(row.get("land_value_rub") or 0)
                                        for row in part), 1),
            "objects_value_rub": round(sum(float(row.get("objects_value_rub") or 0)
                                           for row in part), 1),
        }

    return {"city": fold(city), "others": fold(rest),
            "names": [str(row.get("name") or row.get("group_title") or "") for row in rest]}


def holdings_under(view: dict[str, Any] | None = None,
                   rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Справочная земля под строениями для взгляда «по участку».

    Считается из тех же строк, что показаны, — второй проход по объектам дал бы
    вторую приписку и разошёлся бы с таблицей. Итог группы, как и в верхней
    таблице, объединение участков, а не сумма строк.
    """
    view = territory() if view is None else view
    rows = land_holdings(view) if rows is None else rows
    lands = {land["cadastral_number"]: land for land in view["lands"]}
    by_group: dict[str, set[str]] = {}
    everything: set[str] = set()
    for row in rows:
        numbers = set(row.get("under_numbers") or [])
        by_group.setdefault(str(row.get("group") or ""), set()).update(numbers)
        everything |= numbers

    def measure(numbers: set[str]) -> dict[str, Any]:
        inside = [lands[number] for number in sorted(numbers) if number in lands]
        return {"lands": len(numbers),
                "area_sqm": round(sum(_land_area_in_site(land) for land in inside), 1),
                "egrn_area_sqm": round(sum(float(land.get("area_sqm") or 0)
                                           for land in inside), 1),
                "parts": [land["cadastral_number"] for land in inside if land.get("part")]}

    return {"by_group": {key: measure(value) for key, value in by_group.items()},
            "total": measure(everything)}


def _sum(values: list[Any]) -> float:
    return round(sum(float(v) for v in values if isinstance(v, (int, float))), 1)


def payload() -> dict[str, Any]:
    """Всё, что нужно странице: участки, группы, контуры и чего не хватает.

    Сеть здесь не трогается: страница показывает прочитанное, дочитывает фон.
    """
    data = registry()
    owners = {str(o.get("key")): o for o in data.get("owners") or []}
    groups = {str(g.get("key")): g for g in data.get("groups") or []}
    answers = _answers()
    # Свод по документам считается ОДИН раз: он же даёт участок под зданием и
    # он же отвечает, кто собственник. Второй вызов — второй счёт того же.
    lands_and_objects = territory()
    by_number = {item["cadastral_number"]: item
                 for item in lands_and_objects["objects"]}
    parcels = []
    for row in data.get("parcels") or []:
        number = str(row.get("cadastral_number") or "")
        owner_key = row.get("owner")
        owner = owners.get(owner_key) or {}
        answer = answers.get(number) if isinstance(answers.get(number), dict) else None
        # Кто владелец — ОДИН ответ на весь модуль, и его даёт выписка ЕГРН.
        # Прежде цвет строки считался по владельцу из выгрузки, а цвет того же
        # здания на карте — по собственнику из выписки, и на 27 объектах из 39
        # они расходились: восемь строений «Жилищника» выгрузка красила жёлтым
        # («прочие»), а выписка — зелёным, потому что собственник там город
        # Москва, а у ГБУ оперативное управление. Два достоверных на вид ответа
        # об одном здании: владелец 07.09.2026 назвал верный — зелёный.
        # Выгрузка при этом не выброшена: её владелец стоит рядом своей
        # колонкой, и расхождение названо вслух, а не выбрано молча.
        drawn = by_number.get(number) or {}
        egrn_owner = drawn.get("owner") or {}
        colour_from = str(drawn.get("colour_from") or "")
        if drawn:
            group = str(egrn_owner.get("group") or "none")
            # Цвет берётся у ТОГО ЖЕ объекта, что нарисован на карте, а не
            # считается вторым разом по его владельцу: у строения без своего
            # права он занят у владельца участка, и пересчёт по владельцу дал
            # бы серый на строке при жёлтом на карте.
            colour = str(drawn.get("colour")
                         or egrn_owner.get("colour")
                         or (groups.get(group) or {}).get("colour") or "#8a8a8a")
            owner_source = "выписка ЕГРН" if egrn_owner.get("name") else ""
        else:
            # Выписки на объект нет или право не зарегистрировано — тогда
            # отвечает выгрузка. «Не спрашивали» и «нет права» — разные ответы,
            # и первый не отменяет того, что назвал человек.
            group = (group_of(owner) if owner_key else "none")
            colour = str((groups.get(group) or {}).get("colour") or "#8a8a8a")
            owner_source = "выгрузка владельца" if owner_key else ""
            colour_from = "владелец из выгрузки" if owner_key else "владелец не назван"
        parcels.append({
            **row,
            "group": group,
            "group_title": str((groups.get(group) or {}).get("title") or ""),
            "colour": colour,
            "owner_source": owner_source,
            # Чем покрашено — часть ответа: у строения без своего права цвет
            # занят у владельца участка, и без подписи он читается как право.
            "colour_from": colour_from,
            "egrn_owner_name": str(egrn_owner.get("name") or ""),
            "egrn_owner_inn": str(egrn_owner.get("inn") or ""),
            # Расхождение двух источников об одном лице. Пусто — они согласны
            # либо один из них молчит; молчание расхождением не считается.
            "owner_conflict": _owner_conflict(owner, egrn_owner,
                                              (by_number.get(number) or {})),
            "owner_short": str(owner.get("short") or ""),
            "owner_name": str(owner.get("name") or ""),
            "inn": owner.get("inn"),
            "ogrn": owner.get("ogrn"),
            "rings_merc": list((answer or {}).get("rings") or []),
            # Три состояния разные: нарисован, спросили и контура нет, ещё не
            # спрашивали. Слитые в «не нарисован», они читаются как отсутствие
            # участка в территории.
            "outline_state": ("drawn" if (answer or {}).get("rings")
                              else "empty" if answer else "unread"),
            "outline_reason": str((answer or {}).get("reason") or ""),
            "egrn": (answer or {}).get("egrn") or None,
            # Участок под зданием называет ВЫПИСКА, а не наша геометрия:
            # точечный опрос отвечал на тот же вопрос вторым голосом и на двух
            # объектах из 39 расходился с документом.
            "lands": list((by_number.get(number) or {}).get("lands") or []),
        })
    totals_by_group = []
    for group in data.get("groups") or []:
        rows = [p for p in parcels if p["group"] == group["key"]]
        if not rows:
            continue
        totals_by_group.append({
            **group,
            "parcels": len(rows),
            "drawn": len([p for p in rows if p["rings_merc"]]),
            "area_sqm": _sum([p.get("area_sqm") for p in rows]),
            "cadastral_value_rub": _sum([p.get("cadastral_value_rub") for p in rows]),
            "owners": [owners[key]["short"]
                       for key in dict.fromkeys(p["owner"] for p in rows if p["owner"])
                       if key in owners],
        })
    holdings = land_holdings(lands_and_objects)
    source = dict(data.get("source") or {})
    area_by_rows = _sum([p.get("area_sqm") for p in parcels])
    value_by_rows = _sum([p.get("cadastral_value_rub") for p in parcels])
    own_area = source.get("own_total_area_sqm")
    own_value = source.get("own_total_value_rub")
    return {
        "site": data.get("site") or {},
        "source": source,
        "groups": totals_by_group,
        "parcels": parcels,
        # Контур площадки КРТ — подложка под участками: он отвечает на «что из
        # квартала входит в территорию», а сами участки на этот вопрос не
        # отвечают. Берётся у реестра, второго пути к нему нет.
        "krt_site": cached_site(),
        "kinds": _kinds(parcels),
        # Свод по официальным документам: состав территории из извещения о
        # торгах, свойства и права — из выписок ЕГРН.
        "territory": lands_and_objects,
        "owners": owners_summary(lands_and_objects),
        # Второй взгляд на тех же владельцев — по участку. Считается один раз
        # и здесь: экран и книга показывают посчитанное, а не считают порознь.
        "holdings": holdings,
        # Справочная земля под строениями — объединениями, а не суммами: строки
        # перекрываются, и сложение назвало бы метры, которых нет.
        "under": land_under_buildings(lands_and_objects),
        "holdings_under": holdings_under(lands_and_objects, holdings),
        # «Очевидно, что у Москвы ничего выкупать не надо» (владелец,
        # 07.09.2026): что городское, а что нет, — по взгляду «по участку».
        "buyout": buyout(holdings, lands_and_objects),
        "outlines": {
            "parcels": len(parcels),
            "drawn": len([p for p in parcels if p["rings_merc"]]),
            "empty": len([p for p in parcels if p["outline_state"] == "empty"]),
            "unread": len([p for p in parcels if p["outline_state"] == "unread"]),
            # Земельные участки считаются ОТДЕЛЬНО: счётчик выше идёт по
            # строкам присланного файла, а это здания. Пока участки в него не
            # входили, ненарисованный участок нигде не назывался — и «почему
            # зелёной подложки Москвы нет под строениями Москвы?» (владелец,
            # 07.09.2026) ответа на экране не имело: участок 77:05:0004001:7
            # покрашен городским зелёным, а контур его ещё не спрашивали.
            "lands": len(lands_and_objects["lands"]),
            "lands_drawn": len([land for land in lands_and_objects["lands"]
                                if land.get("rings_merc")]),
            "reading": reading(),
            "problem": str((load_json(cache_path()) or {}).get("problem") or ""),
        },
        "totals": {
            "parcels": len(parcels),
            "area_sqm": area_by_rows,
            "cadastral_value_rub": value_by_rows,
            # Итог самой выгрузки стоит РЯДОМ, а не вместо: он посчитан её же
            # формулой и меньше суммы строк, потому что шесть площадей лежат в
            # книге текстом и `SUM` их пропускает.
            "own_total_area_sqm": own_area,
            "own_total_value_rub": own_value,
            "area_gap_sqm": (round(area_by_rows - float(own_area), 1)
                             if isinstance(own_area, (int, float)) else None),
            "value_gap_rub": (round(value_by_rows - float(own_value), 1)
                              if isinstance(own_value, (int, float)) else None),
            "text_cells_skipped_by_sum": list(source.get("text_cells_skipped_by_sum") or []),
        },
    }

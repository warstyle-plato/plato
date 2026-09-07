"""Объекты КРТ Нагатино с их правообладателями — реестр и контуры.

Владелец прислал выгрузку по кварталу 77:05:0004001 (39 участков: площадь,
кадастровая стоимость, правообладатель) и попросил отдельную страницу с картой
Москвы, где эти участки нанесены, а по наведению видно, чей участок
(07.09.2026). Группы он назвал сам: «Новый проект, УНИКС покрасить как
Брынцалов, Россети, жилищник и автокомбинат как прочее».

Что здесь чьё:

- **правообладатель, площадь и кадастровая стоимость — из выгрузки.** Она
  лежит и файлом (`docs/krt/nagatino-parcels-2026-09-07.xlsx`), и разобранным
  рядом (`reference_data/krt/nagatino_parcels.json`) — как нормативный пакет:
  ссылки протухают, файл нет;
- **контур участка — из ЕГРН** по кадастровому номеру, тем же путём движка
  (`_land_lookup_by_numbers`), которым собирает контур `decision_outline`.
  Второго клиента НСПД здесь нет.

Четыре правила, за которые отвечает именно этот модуль.

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
    return [str(row.get("cadastral_number") or "")
            for row in registry().get("parcels") or []
            if row.get("cadastral_number")]


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

EXTRACTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "krt" / "egrn"
NOTICE_PATH = (Path(__file__).resolve().parent.parent / "docs" / "krt"
               / "nagatino-auction-notice-2026-08-14.pdf")

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
    group = groups_by_inn.get(str(owner.get("inn") or "")) or "unassigned"
    return {"name": owner.get("name") or "", "inn": owner.get("inn") or "",
            "ogrn": owner.get("ogrn") or "", "kind": owner.get("kind") or "",
            "since": owner.get("since") or "", "note": "", "others": others,
            "group": group,
            "colour": str((groups.get(group) or {}).get("colour") or "#8a8a8a"),
            "group_title": str((groups.get(group) or {}).get("title") or "")}


def _lands_state() -> tuple[dict[str, Any], dict[str, Any]]:
    """Что уже спрошено про землю: ответ по каждому зданию и сами участки."""
    cached = load_json(cache_path())
    if not (isinstance(cached, dict) and cached.get("schema_version") == 1):
        return {}, {}
    asked = cached.get("land_answers")
    lands = cached.get("lands")
    return (dict(asked) if isinstance(asked, dict) else {},
            dict(lands) if isinstance(lands, dict) else {})


def land_unread() -> list[str]:
    """Здания, под которыми землю ещё не спрашивали или ответ протух.

    Спрашивать можно только у прочитанного здания: точки у непрочитанного нет,
    и «не спрашивали» здесь — наш пробел, а не отсутствие участка.
    """
    answers = _answers()
    asked, _ = _lands_state()
    out = []
    for number in numbers():
        answer = answers.get(number)
        if not isinstance(answer, dict) or not (answer.get("egrn") or {}).get("center"):
            continue
        known = asked.get(number)
        if not isinstance(known, dict):
            out.append(number)
            continue
        ttl = ANSWER_TTL_SECONDS if known.get("land") else REFUSAL_TTL_SECONDS
        at = known.get("asked_at")
        if not isinstance(at, (int, float)) or time.time() - float(at) > ttl:
            out.append(number)
    return out


def read_land_chunk(point_lookup: Callable[[float, float], list[dict[str, Any]]],
                    *, limit: int = CHUNK) -> dict[str, Any]:
    """Спросить ЕГРН, какой участок лежит под очередной порцией зданий.

    Привязка считается ГЕОМЕТРИЕЙ источника — что стоит в точке центра здания,
    — а не полем «кадастровый номер ЗУ»: по этим объектам оно пустое во всех
    тридцати девяти. Здание, под которым участка не нашлось, называется
    причиной: молча потерянное читается как отсутствие земли под ним.
    """
    answers = _answers()
    asked, lands = _lands_state()
    todo = land_unread()[:max(1, int(limit))]
    state = load_json(cache_path())
    state = dict(state) if isinstance(state, dict) and state.get("schema_version") == 1 else {
        "schema_version": 1, "answers": answers, "problem": ""}
    for number in todo:
        centre = ((answers.get(number) or {}).get("egrn") or {}).get("center") or {}
        try:
            found = list(point_lookup(float(centre["lat"]), float(centre["lng"])) or [])
        except Exception as exc:  # noqa: BLE001 — неответ называется, а не молчит
            state["problem"] = f"ЕГРН не ответил про землю: {type(exc).__name__}: {exc}"[:300]
            break
        parcels_here = [item for item in found
                        if isinstance(item, dict) and item.get("found")
                        and str(item.get("kind") or "") == "land"]
        if not parcels_here:
            asked[number] = {"asked_at": int(time.time()), "land": "",
                             "reason": "в точке центра здания ЕГРН участка не показал"}
            continue
        first = parcels_here[0]
        cad = str(first.get("cadastral_number") or "")
        asked[number] = {"asked_at": int(time.time()), "land": cad, "reason": "",
                         # Сколько участков вернулось — часть ответа: два под
                         # одной точкой значит, что выбор сделан за источник.
                         "others": [str(x.get("cadastral_number") or "")
                                    for x in parcels_here[1:]]}
        lands[cad] = {
            "cadastral_number": cad,
            "area_sqm": first.get("area_sqm"),
            "cadastral_value_rub": first.get("cadastral_value_rub"),
            "permitted_use": str(first.get("permitted_use") or ""),
            "ownership": str(first.get("ownership") or ""),
            "address": str(first.get("address") or ""),
            "map_url": str(first.get("map_url") or ""),
            "rings": [ring for ring in (first.get("contour_merc") or [])
                      if isinstance(ring, list) and len(ring) >= 3],
        }
    state["land_answers"] = asked
    state["lands"] = lands
    state["updated_at"] = int(time.time())
    save_json(cache_path(), state)
    return state


def fill_in_background(lookup: Callable[[list[str]], list[dict[str, Any]]],
                       *, find_site: Callable[[], dict[str, Any]] | None = None,
                       point_lookup: Callable[[float, float], list[dict[str, Any]]] | None = None
                       ) -> bool:
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
    if (not unread() and not (point_lookup is not None and land_unread())
            and (find_site is None or cached_site().get("rings_merc"))):
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
            # Земля под зданиями читается ПОСЛЕ них: точки у непрочитанного
            # здания нет, и спрашивать не по чему.
            if point_lookup is not None:
                while land_unread():
                    before = len(land_unread())
                    state = read_land_chunk(point_lookup)
                    if state.get("problem") or len(land_unread()) >= before:
                        break
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
    _asked, cached_lands = _lands_state()

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
            "extract": bool(extract),
            "rings_merc": list(((answers.get(cad) or {}).get("rings")) or []),
        }
    # Объект, на который выписка есть, а в извещении его нет, — это ответ
    # документа о составе территории, и он называется отдельно.
    outside = sorted(set(docs["builds"]) - set(objects_by_cad))

    from auction_search import egrn_extracts

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
        lands.append({
            "cadastral_number": cad,
            "part": bool(land.get("part")),
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
            "objects": here,
            "objects_area_sqm": _sum([item.get("area_sqm") for item in here]),
            "rings_merc": list(((cached_lands.get(cad) or {}).get("rings")) or []),
            "extract": bool(extract),
        })
    lands.sort(key=lambda item: -(item.get("area_sqm") or item.get("notice_area_sqm") or 0))
    objects = list(objects_by_cad.values())
    return {
        "lands": lands,
        "objects": objects,
        "objects_outside_notice": [{"cadastral_number": cad,
                                    "area_sqm": docs["builds"][cad].get("area_sqm"),
                                    "owner": _owner_view(docs["builds"][cad], by_inn, groups)}
                                   for cad in outside],
        "totals": {
            "lands": len(lands),
            "land_area_sqm": _sum([item.get("area_sqm") for item in lands]),
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


def owners_summary() -> list[dict[str, Any]]:
    """Кто чем владеет — по ИНН, а не по написанию имени."""
    view = territory()
    seen: dict[str, dict[str, Any]] = {}

    from auction_search import egrn_extracts

    def add(bucket: str, owner: dict[str, Any], area: Any, value: Any) -> None:
        # Ключ личности объявлен один раз — в разборе выписок. Свой второй
        # слепил бы разных владельцев: у публичного образования нет ни ИНН, ни
        # ОГРН, и все они сошлись бы в одну строку.
        key = (egrn_extracts.holder_key(owner) if owner.get("name")
               else "нет:" + (owner.get("note") or ""))
        row = seen.setdefault(key, {"name": owner.get("name") or owner.get("note") or "",
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
    rows = list(seen.values())
    for row in rows:
        for key in ("land_area_sqm", "objects_area_sqm", "land_value_rub", "objects_value_rub"):
            row[key] = round(row[key], 1)
    rows.sort(key=lambda row: -(row["land_area_sqm"] + row["objects_area_sqm"]))
    return rows


def _land_rows(lands: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Участки со зданиями, которые на них стоят, и с их владельцами.

    Правообладателя САМОГО участка здесь нет и быть не может: выгрузка
    называет владельцев ЗДАНИЙ, а ЕГРН по земле отдаёт только форму
    собственности. Чьи участки — приедет отдельным источником, и до тех пор
    колонка честно пуста, а не заполнена владельцем здания: это разные лица, и
    подписать одно другим значит сказать неправду.
    """
    out = []
    for cad, land in lands.items():
        here = [row for row in rows if row.get("land") == cad]
        out.append({
            **land,
            "buildings": len(here),
            "buildings_area_sqm": _sum([row.get("area_sqm") for row in here]),
            "building_owners": [name for name in dict.fromkeys(
                row.get("owner_short") or "" for row in here) if name],
            "unowned_buildings": len([row for row in here if not row.get("owner")]),
            "groups": [key for key in dict.fromkeys(row.get("group") for row in here)],
        })
    return sorted(out, key=lambda item: -(item.get("area_sqm") or 0))


def _land_totals(lands: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Земля своей мерой. Складывать её с площадью строений нельзя — это
    разные величины, и «плотность» считается только по земле."""
    return {
        "parcels": len(lands),
        "area_sqm": _sum([land.get("area_sqm") for land in lands.values()]),
        "cadastral_value_rub": _sum([land.get("cadastral_value_rub")
                                     for land in lands.values()]),
        "drawn": len([land for land in lands.values() if land.get("rings")]),
        "linked": len([row for row in rows if row.get("land_state") == "linked"]),
        "empty": len([row for row in rows if row.get("land_state") == "empty"]),
        "unread": len([row for row in rows if row.get("land_state") == "unread"]),
    }


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
    land_answers, lands = _lands_state()
    parcels = []
    for row in data.get("parcels") or []:
        number = str(row.get("cadastral_number") or "")
        owner_key = row.get("owner")
        owner = owners.get(owner_key) or {}
        group = str(owner.get("group") or "none") if owner_key else "none"
        answer = answers.get(number) if isinstance(answers.get(number), dict) else None
        parcels.append({
            **row,
            "group": group,
            "group_title": str((groups.get(group) or {}).get("title") or ""),
            "colour": str((groups.get(group) or {}).get("colour") or "#8a8a8a"),
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
            # Участок под зданием и КАК он найден: «по точке ЕГРН» — это
            # геометрия источника, а не поле «кадастровый номер ЗУ», которое у
            # этих объектов пустое во всех тридцати девяти.
            "land": str((land_answers.get(number) or {}).get("land") or ""),
            "land_state": ("linked" if (land_answers.get(number) or {}).get("land")
                           else "empty" if number in land_answers else "unread"),
            "land_reason": str((land_answers.get(number) or {}).get("reason") or ""),
            "land_others": list((land_answers.get(number) or {}).get("others") or []),
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
        "lands": _land_rows(lands, parcels),
        "land_totals": _land_totals(lands, parcels),
        # Свод по официальным документам: состав территории из извещения о
        # торгах, свойства и права — из выписок ЕГРН.
        "territory": territory(),
        "owners": owners_summary(),
        "outlines": {
            "parcels": len(parcels),
            "drawn": len([p for p in parcels if p["rings_merc"]]),
            "empty": len([p for p in parcels if p["outline_state"] == "empty"]),
            "unread": len([p for p in parcels if p["outline_state"] == "unread"]),
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

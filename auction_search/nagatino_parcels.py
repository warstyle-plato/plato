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

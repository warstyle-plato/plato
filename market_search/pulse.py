"""«Пульс Продаж Новостроек» — источник, знающий то, что мы добывали угадыванием.

Весь прежний конвейер рынка отвечал на вопросы, которые здесь просто даны:
как называется проект, где он стоит, какого он класса, сколько стоит метр и
сколько лотов осталось. Мы вытаскивали это из поисковых сниппетов — по
заголовку, по обрывку текста, по совпадению названия, — и каждая сборка
приносила новый вид мусора: чужой адрес, цену соседа, статью вместо проекта.

Здесь у каждого проекта есть числовой идентификатор, координаты, строительный
адрес, девелопер и класс, а цена приходит с датой прайса и числом лотов, из
которых она посчитана. Угадывать больше нечего.

Правила, которым модуль обязан подчиняться:

* **Худший исход совпадает с прежним поведением.** Не заданы доступы, не
  открылся сайт, истекла сессия — методы возвращают пустоту, а не исключение.
  Источник дополняет конвейер, а не заменяет его собой на живом стенде.
* **Доступ живёт в окружении.** `PULSE_LOGIN` и `PULSE_PASSWORD` читаются из
  среды; в репозитории их нет и быть не может.
* **Воркеров два, память у них раздельная.** Куки и справочник лежат на диске,
  иначе каждый запрос заходил бы на сайт заново.
"""

from __future__ import annotations

import datetime
import html
import http.cookiejar
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .http import fresh, load_json, save_json


PULSE_BASE = "https://pulsprodaj.ru"

_LOGIN_PATH = "/accounts/login/"
_MAP_PATH = "/map/"
# Адреса карты по очереди: у московского кабинета — со слэшем, у
# всероссийского (`russia.pulsprodaj.ru/map`, адрес из браузера владельца) —
# без. Берётся первый, на котором есть данные; что ответил каждый — в пробе.
_MAP_PATHS = ("/map/", "/map")
_SEARCH_PATH = "/api/search/"

# Класс проекта не лежит ни в точке карты, ни в карточке: он живёт фильтром.
# Спрашиваем выборку по каждому классу и получаем принадлежность из того, что
# в неё попало. Пять запросов в сутки против справочника, который пришлось бы
# обновлять руками вместе с книгой.
_CLASS_FILTERS = {
    1: "Стандарт/Эконом",
    2: "Комфорт",
    3: "Бизнес",
    4: "Премиум",
    5: "Элит/De Luxe",
}

_LZ_KEY64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
_CSRF_RE = re.compile(r"csrfmiddlewaretoken['\"]?\s+value=['\"]([^'\"]+)")
_GEOJSON_MARK = '{"type":"FeatureCollection"'
# Заглушка, которую поддомен отдаёт гостю: 403 и «Сайт находится в
# разработке». Это не отказ в пароле, а закрытая дверь — и говорить о ней
# надо так, а не «вход не удался».
_CLOSED_MARK = "в разработке"

# Номер проекта во всероссийском кабинете выглядит как «50-004184»: код
# региона, дефис, номер. Московский кабинет отдавал голое число. Формат
# распознаётся только целиком — код региона из чего-то другого не выводится.
# Объект строительства всероссийского кабинета — «50-004184-1»: номер
# проектной декларации и номер объекта в ней (адрес `/object/50-004184-1`).
_REGION_ID_RE = re.compile(r"^(\d{2,3})-(\d+)(?:-(\d+))?$")


def pulse_id(value: Any) -> str | None:
    """Идентификатор проекта — всегда строка, как его дал источник.

    Прежде он приводился к `int`, и номер «50-004184» с всероссийского
    кабинета ронял весь справочник на первой же строке. Старые сохранённые
    числовые id (4184, 4184.0, "4184") дают ту же строку «4184», поэтому
    прежние проекты и выгрузки находят свои строки без миграции.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not value.is_integer():
            return None
        value = int(value)
    text = str(value).strip()
    return text or None


def pulse_declaration(complex_id: Any) -> str | None:
    """Номер проектной декларации из «50-004184» или «50-004184-1»."""
    found = _REGION_ID_RE.match(pulse_id(complex_id) or "")
    return f"{found.group(1)}-{found.group(2)}" if found else None


def pulse_region(complex_id: Any) -> str | None:
    """Код региона из номера вида «50-004184»; у голого числа — нет."""
    found = _REGION_ID_RE.match(pulse_id(complex_id) or "")
    return found.group(1) if found else None


def _api_id(complex_id: Any) -> int | str:
    """Id для тела запроса к API — в том виде, в каком его дала карта.

    Голое число уходит числом (так API принимал его всегда), номер с регионом
    — строкой. Перевода одного в другое здесь нет: соответствия номера и
    числа мы не знаем, и угадывать его значит спрашивать чужой проект.
    """
    text = pulse_id(complex_id) or ""
    return int(text) if text.isdigit() else text


def _id_file(complex_id: Any) -> str:
    """Безопасное имя файла кэша: у числа — то же, что прежде."""
    return re.sub(r"[^0-9A-Za-z_-]", "_", pulse_id(complex_id) or "none")


def parse_bases(value: str | None) -> list[str]:
    """Список баз из `PULSE_BASE_URL`: через запятую, порядок — приоритет.

    Первая база владеет проектом, если тот же id пришёл из двух: так
    всероссийский кабинет можно поставить первым, оставив московский
    запасным, пока не видно, покрывает ли первый Москву.
    """
    out: list[str] = []
    for item in str(value or "").replace(";", ",").split(","):
        base = item.strip().rstrip("/")
        if base and base not in out:
            out.append(base)
    return out or [PULSE_BASE]


def site_key(base: str) -> str:
    """Каталог кэша базы — её хост: «pulsprodaj.ru», «russia.pulsprodaj.ru»."""
    host = urllib.parse.urlparse(base).netloc or base
    return re.sub(r"[^0-9A-Za-z_.-]", "_", host.lower()) or "default"


_ADDRESS_REGION_RE = re.compile(
    r"(?:г\.?\s*)?(москва|санкт-петербург|севастополь)|("
    r"[а-яё -]+\s(?:область|обл\.?|край|округ|ао)|"
    r"(?:республика|респ\.?)\s[а-яё -]+)",
    re.IGNORECASE,
)


def address_region(address: str | None) -> str | None:
    """Регион из строительного адреса — для диагностики, не для решений."""
    for part in str(address or "").split(","):
        found = _ADDRESS_REGION_RE.fullmatch(part.strip())
        if found:
            if found.group(1):
                return found.group(1).capitalize().replace("-п", "-П")
            text = " ".join(found.group(2).split())
            return re.sub(r"\sобл\.?$", " область", text, flags=re.IGNORECASE)
    return None


@dataclass(frozen=True)
class PulseProject:
    """Проект справочника: идентификатор, место и вывеска."""

    complex_id: str
    name: str
    latitude: float
    longitude: float
    developer: str | None = None
    builder: str | None = None
    address: str | None = None
    sales_start: str | None = None
    commissioning: str | None = None
    # Сырой текст стадии строительства, если карта его несёт. Приводит его к
    # стадии `stage.stage_from_text`, а не этот класс.
    construction_stage: str | None = None
    # База, из чьего справочника пришёл проект: по ней же спрашиваются его
    # цена и остатки — номер одной базы в другой ничего не значит.
    base: str = PULSE_BASE

    @property
    def region(self) -> str | None:
        return pulse_region(self.complex_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "complex_id": self.complex_id,
            "region": self.region,
            "base": self.base,
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "developer": self.developer,
            "builder": self.builder,
            "address": self.address,
            "sales_start": self.sales_start,
            "commissioning": self.commissioning,
            "construction_stage": self.construction_stage,
            "url": f"{self.base}/complex/{self.complex_id}/",
        }


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    rad = math.radians
    return 2 * radius * math.asin(
        math.sqrt(
            math.sin(rad(lat2 - lat1) / 2) ** 2
            + math.cos(rad(lat1)) * math.cos(rad(lat2)) * math.sin(rad(lon2 - lon1) / 2) ** 2
        )
    )


def _balanced_json(text: str, start: int) -> str:
    """Вырезать JSON-объект от `{` до его пары.

    Регулярным выражением это не берётся: внутри вложенные скобки и кавычки, а
    объект тянется на два мегабайта. Считать одни скобки тоже мало — скобка
    может стоять внутри строки, и тогда разбор оборвётся на середине данных.
    """
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError("незакрытый JSON в странице карты")


def _pulse_date(value: Any) -> str | None:
    """Нормализовать дату, которую ЛК Пульса показывает человеку.

    API и HTML Пульса используют несколько форм: ISO, российскую дату,
    месяц/год и квартал. Для стадийной модели достаточно месяца; если
    источник даёт только квартал, берём его последний месяц.
    """
    if value in (None, ""):
        return None
    text = html.unescape(str(value)).replace("\u00a0", " ")
    text = " ".join(text.split()).strip().lower().replace("ё", "е")
    # ISO в JSON нередко приходит со временем.
    found = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})(?:[tT ][^\s<]*)?", text)
    if found:
        try:
            return datetime.date(*map(int, found.groups()[:3])).isoformat()
        except ValueError:
            return None
    found = re.search(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b", text)
    if found:
        day, month, year = map(int, found.groups())
        try:
            return datetime.date(year, month, day).isoformat()
        except ValueError:
            return None
    found = re.search(r"\b(20\d{2})[./-](\d{1,2})\b", text)
    if found:
        year, month = map(int, found.groups())
        try:
            return datetime.date(year, month, 1).isoformat()
        except ValueError:
            return None
    found = re.search(r"\b(\d{1,2})[./-](20\d{2})\b", text)
    if found:
        month, year = map(int, found.groups())
        try:
            return datetime.date(year, month, 1).isoformat()
        except ValueError:
            return None
    # Месяц словом («Ноябрь 2015» — так карточка ЛК пишет старт продаж).
    # Прежде такое значение отбрасывалось молча, и в отчёт попадала дата
    # из другого источника.
    from .pulse_page import month_date  # noqa: PLC0415 — один разбор месяцев

    worded = month_date(text)
    if worded:
        return worded
    romans = {"i": 1, "ii": 2, "iii": 3, "iv": 4}
    quarter = None
    year = None
    found = re.search(r"\b(i{1,3}|iv|[1-4])\s*(?:кв(?:артал)?\.?|q)\s*(?:г(?:ода)?\.?)?\s*(20\d{2})\b", text)
    if found:
        raw, raw_year = found.groups()
        quarter = romans.get(raw, int(raw) if raw.isdigit() else None)
        year = int(raw_year)
    else:
        found = re.search(r"\b(20\d{2})\s*(?:г(?:ода)?\.?)?\s*(?:q|кв(?:артал)?\.?)\s*(i{1,3}|iv|[1-4])\b", text)
        if found:
            raw_year, raw = found.groups()
            quarter = romans.get(raw, int(raw) if raw.isdigit() else None)
            year = int(raw_year)
    if quarter and year:
        return datetime.date(year, quarter * 3, 1).isoformat()
    return None


# Источники дат проекта по старшинству. Страница проекта — первой: это то,
# что человек видит в ЛК; прежний разбор той же страницы по ключам JSON —
# последним, он угадывает имя поля.
_DATE_SOURCES = ("pulse_project_page", "pulse_api_table", "pulse_map", "pulse_project_page_keys")


def _date_key_score(path: str, kind: str) -> int:
    key = re.sub(r"[^a-zа-я0-9]+", " ", str(path).lower().replace("ё", "е"))
    if kind == "sales_start":
        if not any(word in key for word in ("sale", "sales", "продаж")):
            return -100
        score = 0
        if any(word in key for word in ("start", "begin", "launch", "старт", "начал")):
            score += 12
        if "date" in key or "дата" in key:
            score += 3
        if any(word in key for word in ("end", "finish", "predict", "оконч", "конец")):
            score -= 15
        return score
    if not any(word in key for word in (
        "commission", "completion", "delivery", "handover", "deadline",
        "finish", "construction end", "ввод", "эксплуатац", "сдач", "заверш"
    )):
        return -100
    score = 0
    if any(word in key for word in ("planned", "plan", "план", "срок", "deadline")):
        score += 10
    if any(word in key for word in ("commission", "ввод", "эксплуатац")):
        score += 8
    if any(word in key for word in ("delivery", "handover", "сдач", "заверш", "completion")):
        score += 5
    if "date" in key or "дата" in key:
        score += 2
    if any(word in key for word in ("actual", "fact", "факт")):
        score -= 8
    if any(word in key for word in ("sale", "sales", "продаж")):
        score -= 15
    return score


def _stage_key(key: str) -> bool:
    """Ключ, который по смыслу несёт стадию строительства."""
    low = str(key).lower().replace("ё", "е")
    if any(word in low for word in ("sale", "продаж", "price", "цен")):
        return False
    return any(word in low for word in (
        "stage", "стади", "build_status", "construction_status", "constr_status",
        "building_status", "этап строит", "ход строит",
    ))


def _stage_from_payload(payload: Any) -> str | None:
    """Сырой текст стадии строительства из ответа Пульса, если он там есть.

    Пульс отбирает проекты по стадии фильтром на своём сайте, но в ответах,
    которые читает наш маршрут (карта, таблица проекта), поле стадии не
    подтверждено: имя его неизвестно. Поэтому ключ ищется по смыслу, а
    значение отдаётся сырым — к стадии его приводит `stage.stage_from_text`,
    и нераспознанный текст остаётся видимым, а не превращается в стадию.
    Ничего не нашлось — `None`, и это «стадия не указана», а не «любая».
    """
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(child, (dict, list)):
                    walk(child)
                elif _stage_key(key) and isinstance(child, str) and child.strip():
                    found.append(" ".join(html.unescape(child).split()))
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    if not found:
        return None
    from .stage import stage_from_text  # noqa: PLC0415 — словарь стадий один

    # Корпуса одного ЖК бывают на разных стадиях; проект целиком стоит на
    # самой ранней — так же, как его старт продаж берётся самым ранним.
    order = {code: index for index, code in enumerate(("pit", "frame", "finish", "done"))}
    known = [(order[code], text) for text in found if (code := stage_from_text(text))]
    if known:
        return min(known)[1]
    return found[0]


def _dates_from_payload(payload: Any) -> dict[str, str]:
    """Найти даты в JSON-ответе без привязки к текущему имени поля.

    Ключ обязан семантически совпасть с датой. Если у проекта несколько
    корпусов, старт берём самый ранний, а плановый ввод — самый поздний:
    стадия всего ЖК иначе закончится на первом сданном корпусе.

    Вес ключа выбирает лучшее поле ВНУТРИ одного объекта (корпуса/проекта):
    у разных корпусов API бывает разная форма (дата у одного, год+квартал
    у другого), и сравнивать веса между корпусами нельзя — иначе корпус с
    «красивым» именем поля скрыл бы более поздний ввод соседнего.
    """
    # (владелец — ближайший объемлющий dict, вид даты) -> (вес, дата)
    found: dict[tuple[int, str], tuple[int, str]] = {}

    def remember(owner: int, kind: str, score: int, date: str) -> None:
        if score <= 0:
            return
        slot = (owner, kind)
        current = found.get(slot)
        if current is None or score > current[0]:
            found[slot] = (score, date)
            return
        if score == current[0]:
            if kind == "sales_start" and date < current[1]:
                found[slot] = (score, date)
            elif kind == "commissioning" and date > current[1]:
                found[slot] = (score, date)

    def scalar_date(value: Any, kind: str, score: int) -> str | None:
        date = _pulse_date(value)
        if date:
            return date
        # Некоторые API раскладывают срок на год без дня/месяца. Год можно
        # трактовать только после того, как КЛЮЧ уже доказал смысл поля.
        text = str(value or "").strip()
        if score > 0 and re.fullmatch(r"20\d{2}", text):
            year = int(text)
            month = 1 if kind == "sales_start" else 12
            return datetime.date(year, month, 1).isoformat()
        return None

    def walk(value: Any, path: str = "", owner: int = 0) -> None:
        if isinstance(value, dict):
            owner = id(value)
            # Частая форма API: commissioning_year + commissioning_quarter.
            scalars = {str(k): v for k, v in value.items() if not isinstance(v, (dict, list))}
            for kind in ("sales_start", "commissioning"):
                year_items = []
                quarter_items = []
                for key, child in scalars.items():
                    child_path = f"{path}.{key}" if path else key
                    score = _date_key_score(child_path, kind)
                    low = key.lower()
                    if score > 0 and ("year" in low or "год" in low):
                        try:
                            year = int(float(str(child).replace(",", ".")))
                        except (TypeError, ValueError):
                            year = 0
                        if 2000 <= year <= 2100:
                            year_items.append((score, year))
                    if score > 0 and any(word in low for word in ("quarter", "кварт", "_q", " q")):
                        raw = str(child).strip().lower().replace("iv", "4").replace("iii", "3").replace("ii", "2").replace("i", "1")
                        found_q = re.search(r"[1-4]", raw)
                        if found_q:
                            quarter_items.append((score, int(found_q.group(0))))
                if year_items and quarter_items:
                    score_y, year = max(year_items)
                    score_q, quarter = max(quarter_items)
                    month = 1 if kind == "sales_start" else quarter * 3
                    if kind == "sales_start":
                        month = (quarter - 1) * 3 + 1
                    remember(owner, kind, max(score_y, score_q) + 1, datetime.date(year, month, 1).isoformat())
            for key, child in value.items():
                walk(child, f"{path}.{key}" if path else str(key), owner)
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]", owner)
            return
        for kind in ("sales_start", "commissioning"):
            score = _date_key_score(path, kind)
            date = scalar_date(value, kind, score)
            if date:
                remember(owner, kind, score, date)

    walk(payload)
    out: dict[str, str] = {}
    for (_owner, kind), (_score, date) in found.items():
        current = out.get(kind)
        if current is None:
            out[kind] = date
        elif kind == "sales_start" and date < current:
            out[kind] = date
        elif kind == "commissioning" and date > current:
            out[kind] = date
    return out

def _dates_from_project_html(page: str) -> dict[str, str]:
    """Даты из самой карточки ЖК, если отдельный JSON их не отдал."""
    if not page:
        return {}
    text = html.unescape(page).replace("\u00a0", " ")
    # Сначала embedded JSON/JS: ключ рядом со значением надёжнее видимой верстки.
    out: dict[str, str] = {}
    key_patterns = {
        "sales_start": r"(?:sales?_?start|start_?sales?|sale_?start|date_?start_?sales?)",
        "commissioning": r"(?:commission(?:ing)?_?date|planned_?commission(?:ing)?|completion_?date|planned_?completion|delivery_?date|handover_?date|deadline)",
    }
    token = r"(20\d{2}-\d{1,2}-\d{1,2}(?:[T ][^\"<,}]*)?|\d{1,2}[./-]\d{1,2}[./-]20\d{2}|(?:I{1,3}|IV|[1-4])\s*(?:кв(?:артал)?\.?|Q)\s*20\d{2})"
    for kind, key in key_patterns.items():
        found = re.search(key + r".{0,100}?" + token, text, flags=re.I | re.S)
        if found:
            date = _pulse_date(found.group(1))
            if date:
                out[kind] = date
    # Затем человекочитаемые подписи карточки.
    plain = re.sub(r"<[^>]+>", " ", text)
    plain = " ".join(plain.split())
    labels = {
        "sales_start": r"(?:старт|начало)\s+продаж",
        "commissioning": r"(?:планов(?:ый|ая)\s+)?(?:срок|дата)?\s*(?:ввода(?:\s+в\s+эксплуатацию)?|сдачи|завершения\s+строительства)",
    }
    for kind, label in labels.items():
        if kind in out:
            continue
        found = re.search(label + r".{0,100}?" + token, plain, flags=re.I)
        if found:
            date = _pulse_date(found.group(1))
            if date:
                out[kind] = date
    return out

def lz_decompress_base64(text: str) -> str | None:
    """Разжать ответ карты: он приходит сжатым LZ-string в base64.

    Библиотеку для этого ставить незачем — алгоритм короткий и неизменный, а
    лишняя зависимость в образе живёт дольше, чем причина, по которой её взяли.
    """
    if not text:
        return "" if text == "" else None
    lookup = {char: index for index, char in enumerate(_LZ_KEY64)}
    try:
        return _lz_decompress(len(text), 32, lambda i: lookup[text[i]])
    except (KeyError, IndexError, ValueError):
        return None


def _lz_decompress(length: int, reset: int, get) -> str | None:
    dictionary: dict[int, str | int] = {index: index for index in range(3)}
    enlarge, size, bits_n = 4, 4, 3
    out: list[str] = []
    state = {"val": get(0), "pos": reset, "index": 1}

    def read(count: int) -> int:
        bits, power, maxpower = 0, 1, 1 << count
        while power != maxpower:
            resb = state["val"] & state["pos"]
            state["pos"] >>= 1
            if state["pos"] == 0:
                state["pos"] = reset
                state["val"] = get(state["index"])
                state["index"] += 1
            bits |= (1 if resb > 0 else 0) * power
            power <<= 1
        return bits

    first = read(2)
    if first == 2:
        return ""
    current = chr(read(8 if first == 0 else 16))
    dictionary[3] = current
    word = current
    out.append(current)

    while True:
        if state["index"] > length:
            return ""
        code = read(bits_n)
        if code in (0, 1):
            dictionary[size] = chr(read(8 if code == 0 else 16))
            size += 1
            code = size - 1
            enlarge -= 1
        elif code == 2:
            return "".join(out)

        if enlarge == 0:
            enlarge = 1 << bits_n
            bits_n += 1

        if code in dictionary:
            entry = dictionary[code]
        elif code == size:
            entry = word + word[0]
        else:
            return None

        out.append(str(entry))
        dictionary[size] = word + str(entry)[0]
        size += 1
        enlarge -= 1
        word = str(entry)
        if enlarge == 0:
            enlarge = 1 << bits_n
            bits_n += 1


def _describe_map_page(path: str, page: str, index: int) -> dict[str, Any]:
    """Что лежит на странице карты — для пробы, без разбора данных."""
    title = re.search(r"<title>(.*?)</title>", page, re.I | re.S)
    api = re.findall(r"""["'`](/api/[A-Za-z0-9_\-/.?=&{}$]+)""", page)
    scripts = re.findall(r"""<script[^>]+src=["']([^"']+)["']""", page, re.I)
    data_files = re.findall(r"""["'`](/[A-Za-z0-9_\-/]+\.(?:geo)?json)\b""", page)
    return {
        "path": path,
        "status": 200,
        "bytes": len(page),
        "title": " ".join(html.unescape(title.group(1)).split())[:120] if title else None,
        "geojson": index >= 0,
        "api_paths": list(dict.fromkeys(api))[:20],
        "data_files": list(dict.fromkeys(data_files))[:10],
        "scripts": list(dict.fromkeys(scripts))[:10],
    }


_BUNDLE_PATH_RE = re.compile(
    r"""["'`]((?:https?://[A-Za-z0-9.\-]+)?/(?:api|v\d|graphql|map|complex|objects?)"""
    r"""(?:/[A-Za-z0-9_\-.{}$:]*)*/?(?:\?[A-Za-z0-9_=&\-]*)?)["'`]"""
)
_BUNDLE_HOST_RE = re.compile(r"""["'`](https?://[A-Za-z0-9.\-]*pulsprodaj\.ru[^"'`\s]{0,80})["'`]""")


def _bundle_endpoints(code: str) -> dict[str, Any]:
    """Пути запросов и хосты, названные в собранном скрипте приложения."""
    paths = list(dict.fromkeys(_BUNDLE_PATH_RE.findall(code)))
    hosts = list(dict.fromkeys(_BUNDLE_HOST_RE.findall(code)))
    # Клиент может звать относительные пути от своего `baseURL` («complex/map/»).
    bases = list(dict.fromkeys(re.findall(r"""baseURL\s*:\s*["'`]([^"'`]{1,80})""", code)))
    relative = list(dict.fromkeys(
        found for found in re.findall(r"""["'`]([a-z][a-z0-9_\-]*/[a-z0-9_\-/{}$]*)["'`]""", code)
        if re.search(r"complex|map|object|price|sale|region|search|building", found)
    ))
    return {
        "paths": paths[:60],
        "paths_total": len(paths),
        "hosts": hosts[:10],
        "base_urls": bases[:5],
        "relative": relative[:40],
    }


class PulseClient:
    """Клиент с сессией на диске и молчаливым отказом."""

    def __init__(
        self,
        data_dir: Path,
        *,
        login: str | None = None,
        password: str | None = None,
        base: str | None = None,
        timeout: float = 30.0,
        ttl_seconds: int = 86_400,
        detail_ttl_seconds: int = 43_200,
        auth: "PulseClient | None" = None,
    ):
        # Одна база на клиента. Несколько баз из `PULSE_BASE_URL` собирает
        # `PulseNetwork`; здесь берётся первая.
        self.base = (base or parse_bases(os.getenv("PULSE_BASE_URL"))[0]).rstrip("/")
        self.login = login if login is not None else os.getenv("PULSE_LOGIN", "")
        self.password = password if password is not None else os.getenv("PULSE_PASSWORD", "")
        self.timeout = timeout
        self.ttl_seconds = ttl_seconds
        self.detail_ttl_seconds = detail_ttl_seconds
        # Кэш, куки и справочник — в каталоге своей базы. Прежде всё лежало
        # в общем, и справочник московского кабинета после смены базы
        # выдавался бы за всероссийский ещё сутки.
        self.root = Path(data_dir)
        self.dir = self.root / site_key(self.base)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.errors: list[str] = []
        self._jar: http.cookiejar.MozillaCookieJar | None = None
        self._opener: urllib.request.OpenerDirector | None = None
        self._projects: list[PulseProject] | None = None
        # Клиент, чья форма входа и чья банка кук обслуживают эту базу. У
        # поддомена (`russia.pulsprodaj.ru`) это корневая база: своей формы
        # входа для гостя у поддомена нет — он отдаёт 403 «в разработке», —
        # а сессия выдаётся при входе на `pulsprodaj.ru`. `None` — сама.
        self.auth = auth if auth is not self else None
        # Причина закрытого доступа, если поддомен ответил заглушкой.
        self.access_closed: str | None = None
        # Что ответили адреса карты при последнем чтении и какой из них дал данные.
        self.map_probe: list[dict[str, Any]] = []
        self.map_path: str | None = None

    @property
    def host(self) -> str:
        return (urllib.parse.urlparse(self.base).hostname or "").lower()

    @property
    def available(self) -> bool:
        """Заданы ли доступы. Их отсутствие — не поломка, а выключенный источник."""
        return bool(self.login and self.password)

    # --- сеть -----------------------------------------------------------------

    def _build_opener(self) -> urllib.request.OpenerDirector:
        if self._opener is not None:
            return self._opener
        if self.auth is not None:
            # Одна банка кук на домен: сессия, выданная корневой базой, уходит
            # на поддомен ровно по тем правилам, по которым её шлёт браузер.
            self.auth._build_opener()
            jar = self.auth._jar
        else:
            jar = http.cookiejar.MozillaCookieJar(str(self.dir / "cookies.txt"))
            try:
                jar.load(ignore_discard=True, ignore_expires=True)
            except (OSError, http.cookiejar.LoadError):
                pass
        self._jar = jar
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self._opener.addheaders = [
            ("User-Agent", os.getenv("MARKET_HTTP_USER_AGENT", "DevelopAid/1.0")),
            ("Accept-Language", "ru-RU,ru;q=0.9"),
        ]
        return self._opener

    def _save_cookies(self) -> None:
        if self._jar is None:
            return
        try:
            self._jar.save(ignore_discard=True, ignore_expires=True)
        except OSError:
            pass

    def _cookie(self, name: str) -> str | None:
        """Кука, которая уйдёт с запросом НА ЭТУ базу.

        Банка общая на домен, поэтому «в банке есть кука с таким именем» больше
        не значит «она уйдёт». Решает сама банка — тем же `add_cookie_header`,
        которым urllib собирает заголовок запроса: два разных ответа на один
        вопрос однажды разошлись бы. (Политика `http.cookiejar` мягче
        браузерной: куку без домена она шлёт и на поддомены. Это оставлено —
        лишняя попытка не вредит, а диагностика называет домен куки.)
        """
        if self._jar is None:
            self._build_opener()
        request = urllib.request.Request(f"{self.base}/")
        self._jar.add_cookie_header(request)
        header = request.get_header("Cookie") or ""
        for part in header.split(";"):
            key, _, value = part.strip().partition("=")
            if key == name:
                return value
        return None

    def _cookie_record(self, name: str) -> dict[str, Any] | None:
        """Где лежит кука и уходит ли она на эту базу — для диагностики."""
        if self._jar is None:
            self._build_opener()
        for cookie in self._jar or []:
            if cookie.name == name:
                return {
                    "domain": cookie.domain,
                    "for_subdomains": bool(cookie.domain_specified),
                    "sent_here": self._cookie(name) is not None,
                }
        return None

    def _closed(self, exc: BaseException, body: str | None = None) -> str | None:
        """403 с заглушкой «Сайт находится в разработке» — закрытый поддомен.

        Возвращает причину словами и запоминает её; любой другой ответ —
        `None`, и его разбирает вызывающий код как прежде.
        """
        if not isinstance(exc, urllib.error.HTTPError) or exc.code != 403:
            return None
        if body is None:
            try:
                body = exc.read(4000).decode("utf-8", errors="ignore")
            except Exception:  # noqa: BLE001 — тело ответа не обязано читаться
                body = ""
        if _CLOSED_MARK not in (body or "").lower():
            return None
        session = self._cookie_record("sessionid")
        owner = self.auth.host if self.auth is not None else self.host
        if session is None:
            tail = (
                f"сессии {owner} нет: вход на основную базу не удался"
                if self.auth is not None else "входа с этой базы нет"
            )
        elif session["sent_here"]:
            tail = f"сессия {owner} отправлена, доступа она не даёт"
            if not session["for_subdomains"] and self.auth is not None:
                tail += (
                    f" (кука выдана без домена — браузер на {self.host} "
                    "её бы не отправил)"
                )
        else:
            tail = f"сессия {owner} на {self.host} не уходит"
        what = "поддомен" if self.auth is not None else "база"
        self.access_closed = (
            f"{what} {self.host} закрыт{'а' if what == 'база' else ''} для нашего сервера: "
            f"403 «Сайт находится в разработке»; {tail}"
        )
        return self.access_closed

    def _open(
        self,
        path: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        url = path if path.startswith("http") else f"{self.base}{path}"
        request = urllib.request.Request(url, data=data, headers=headers or {})
        with self._build_opener().open(request, timeout=self.timeout) as response:
            body = response.read()
        self._save_cookies()
        return body

    def sign_in(self) -> bool:
        """Войти под доступами из окружения. Возвращает успех, не бросает."""
        if not self.available:
            return False
        if self.auth is not None:
            # Вход — на основной базе, её формой: у поддомена формы для гостя
            # нет. Успех здесь — сессия, которая уходит и на этот хост.
            if not self.auth.sign_in():
                self.errors.append(
                    f"вход на основную базу {self.auth.host} не удался: "
                    + (self.auth.errors[-1] if self.auth.errors else "причина не названа")
                )
                return False
            if self._cookie("sessionid"):
                return True
            self.errors.append(
                f"сессия {self.auth.host} выдана только для {self.auth.host} "
                f"и на {self.host} не уходит"
            )
            return False
        try:
            page = self._open(_LOGIN_PATH).decode("utf-8", errors="ignore")
            match = _CSRF_RE.search(page)
            if not match:
                self.errors.append("на странице входа нет CSRF-токена")
                return False
            payload = urllib.parse.urlencode(
                {
                    "csrfmiddlewaretoken": match.group(1),
                    "username": self.login,
                    "password": self.password,
                }
            ).encode("utf-8")
            self._open(
                _LOGIN_PATH,
                data=payload,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": f"{self.base}{_LOGIN_PATH}",
                },
            )
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.errors.append(self._closed(exc) or f"вход не удался: {exc}")
            return False
        # Признак входа — кука сессии. Страница после неудачи возвращается та же,
        # с кодом 200, поэтому по коду ответа судить нельзя.
        if self._cookie("sessionid"):
            return True
        # И сказать об этом надо вслух. Прежде эта ветка отдавала «нет» молча:
        # доступы заданы, сеть жива, ошибок нет — а данных нет тоже. Наружу это
        # выходило как «источник ничего не знает», хотя верный ответ — «пароль
        # не подошёл». Единственный молчаливый отказ во всей цепочке.
        self.errors.append(
            "вход не удался: сессия не выдана — проверьте PULSE_LOGIN и PULSE_PASSWORD"
        )
        return False

    def _post_json(self, path: str, payload: dict[str, Any]) -> Any:
        """POST в API. Один повтор после повторного входа: сессия истекает."""
        for attempt in (1, 2):
            csrf = self._cookie("csrftoken")
            if not csrf and not self.sign_in():
                return None
            csrf = self._cookie("csrftoken") or ""
            try:
                body = self._open(
                    path,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "X-CSRFToken": csrf,
                        "Referer": f"{self.base}/",
                    },
                )
            except urllib.error.HTTPError as exc:
                # 403 у Django — это чаще всего протухшая сессия или CSRF, а не
                # запрет на сам метод. Прежде такой ответ ловился общим
                # `URLError` и возвращал `None` без повтора: вход не
                # переспрашивался, и отказ выглядел отсутствием данных.
                detail = ""
                try:
                    detail = exc.read(4000).decode("utf-8", errors="ignore").strip()
                except Exception:  # noqa: BLE001 — тело ответа не обязано читаться
                    detail = ""
                closed = self._closed(exc, detail)
                if closed:
                    self.errors.append(f"{path}: {closed}")
                    return None
                if exc.code in (401, 403) and attempt == 1 and self.sign_in():
                    continue
                self.errors.append(
                    f"{path}: {exc}" + (f" — {detail[:200]}" if detail else "")
                )
                return None
            except (urllib.error.URLError, OSError) as exc:
                self.errors.append(f"{path}: {exc}")
                return None
            try:
                return json.loads(body.decode("utf-8", errors="ignore"))
            except ValueError:
                # Пришла HTML-страница входа вместо JSON — сессия протухла.
                if attempt == 1 and self.sign_in():
                    continue
                self.errors.append(f"{path}: ответ не JSON")
                return None
        return None

    # --- справочник проектов ---------------------------------------------------

    def projects(self, *, refresh: bool = False, fetch: bool = True) -> list[PulseProject]:
        """Все проекты с координатами. Страница карты несёт их одним GeoJSON.

        `fetch=False` — только то, что уже лежит рядом, без обращения к сети.
        Это для путей, которые ходят по нажатию клавиши: страница карты весит
        мегабайты, и когда кэш протухал, первая же подсказка тянула её целиком.
        Ответ не успевал прийти, и вместо списка человек видел «502» — притом
        что от подсказки требовался список, который и так лежал на диске
        часом раньше.
        """
        if self._projects is not None and not refresh:
            return self._projects
        path = self.dir / "projects.json"
        cached = load_json(path) if (fresh(path, self.ttl_seconds) and not refresh) else None
        if not isinstance(cached, list) and not fetch:
            # Протухший кэш для подсказки лучше пустоты: список проектов за
            # вчера отличается от сегодняшнего на единицы, а ждать нельзя.
            stale = load_json(path)
            cached = stale if isinstance(stale, list) else None
            if cached is None:
                return []
        if not isinstance(cached, list):
            cached = self._fetch_projects()
            if cached is None:
                return []
            save_json(path, cached)
        self._projects = [
            PulseProject(
                complex_id=pulse_id(row["complex_id"]) or "",
                name=str(row.get("name") or "").strip(),
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
                developer=(row.get("developer") or None),
                builder=(row.get("builder") or None),
                address=(row.get("address") or None),
                sales_start=(row.get("sales_start") or None),
                commissioning=(row.get("commissioning") or None),
                construction_stage=(row.get("construction_stage") or None),
                base=self.base,
            )
            for row in cached
            if pulse_id(row.get("complex_id")) and row.get("latitude") is not None
        ]
        return self._projects

    @property
    def catalog_path(self) -> Path:
        return self.dir / "projects.json"

    def _map_collection(self) -> dict[str, Any] | None:
        """Сырой GeoJSON карты — как он пришёл, без отбора полей.

        Отдельным методом, потому что его смотрят двое: разбор проектов, где
        берётся семь полей, и проба полей, где нужно ровно обратное — узнать,
        что ещё лежит в ответе и выбрасывается. Пока метода не было, ответ
        разбирался на месте, и «что там есть» никто спросить не мог.
        """
        if not self.available and not self._cookie("sessionid"):
            return None
        if self.auth is not None and not self._cookie("sessionid"):
            # Поддомен гостю отдаёт заглушку, а не карту: сначала сессия.
            self.sign_in()
        self.map_probe = []
        page, index = self._read_map()
        if index < 0 and page is not None:
            # Не вошли — карта отдаётся и гостю, но без данных.
            if self.sign_in():
                page, index = self._read_map()
            if index < 0 and page is not None:
                self.errors.append(
                    "на странице карты нет встроенных данных проектов (GeoJSON): "
                    "что на ней есть — в map_probe отчёта справочника"
                )
        if index < 0:
            return None
        # Карта пришла — дверь открыта, прежняя причина закрытия устарела.
        self.access_closed = None
        try:
            return json.loads(_balanced_json(page, page.index("{", index)))
        except ValueError as exc:
            self.errors.append(f"данные карты не разобрались: {exc}")
            return None

    def _probe_bundle(self, src: str) -> dict[str, Any]:
        """Адреса запросов, зашитые в скрипт страницы карты — для пробы."""
        try:
            code = self._open(src).decode("utf-8", errors="ignore")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return {"script": src, "error": str(exc)[:200]}
        return {"script": src, "bytes": len(code), **_bundle_endpoints(code)}

    def _read_map(self) -> tuple[str | None, int]:
        """Первая страница карты с данными: (страница, позиция GeoJSON).

        Пробует `_MAP_PATHS` по очереди и записывает в `map_probe`, что
        ответил каждый адрес: код, заголовок, адреса `/api/…` и скрипты.
        Без входа в ЛК мы не видели, откуда всероссийская карта берёт свои
        объекты; проба показывает это с прода, а не по догадке.
        Страницы нет вовсе (сеть, отказ) — `(None, -1)` и причина в ошибках.
        """
        last_page: str | None = None
        failures: list[str] = []
        closed: str | None = None
        for path in _MAP_PATHS:
            try:
                page = self._open(path).decode("utf-8", errors="ignore")
            except urllib.error.HTTPError as exc:
                closed = self._closed(exc) or closed
                self.map_probe.append({"path": path, "status": exc.code})
                failures.append(f"{path} → {exc.code}")
                continue
            except (urllib.error.URLError, OSError) as exc:
                self.errors.append(f"карта недоступна: {exc}")
                return None, -1
            index = page.find(_GEOJSON_MARK)
            described = _describe_map_page(path, page, index)
            if index < 0:
                # Всероссийская карта — одностраничное приложение: страница в
                # 828 байт и один скрипт `/assets/index-*.js`, а проекты оно
                # тянет запросами, которые знает только этот скрипт. Скрипт
                # открыт только вошедшему, поэтому читаем его отсюда, с прода,
                # и выписываем адреса, по которым он ходит.
                described["bundles"] = [
                    self._probe_bundle(src) for src in described["scripts"][:2]
                    if src.startswith("/") and not src.startswith("//")
                ]
            self.map_probe.append(described)
            if index >= 0:
                self.map_path = path
                return page, index
            last_page = page
        if last_page is None:
            self.errors.append(closed or f"карта недоступна: {', '.join(failures)}")
        return last_page, -1

    def _fetch_projects(self) -> list[dict[str, Any]] | None:
        collection = self._map_collection()
        if collection is None:
            return None

        out: list[dict[str, Any]] = []
        for feature in collection.get("features") or []:
            coords = (feature.get("geometry") or {}).get("coordinates") or []
            props = feature.get("properties") or {}
            if len(coords) != 2 or feature.get("id") is None:
                continue
            project_dates = _dates_from_payload(props)
            out.append(
                {
                    "complex_id": feature["id"],
                    "name": str(props.get("name") or "").strip(),
                    "latitude": coords[0],
                    "longitude": coords[1],
                    "developer": (props.get("developer") or "").strip() or None,
                    "builder": (props.get("zastroychik") or "").strip() or None,
                    "address": (props.get("construction_address") or "").strip() or None,
                    "sales_start": project_dates.get("sales_start"),
                    "commissioning": project_dates.get("commissioning"),
                    "construction_stage": _stage_from_payload(props),
                }
            )
        return out

    def near(self, latitude: float, longitude: float, radius_km: float) -> list[tuple[float, PulseProject]]:
        """Проекты в радиусе, ближние первыми. Расстояние считаем сами."""
        found = [
            (round(_distance_km(latitude, longitude, item.latitude, item.longitude), 3), item)
            for item in self.projects()
        ]
        return sorted((row for row in found if row[0] <= radius_km), key=lambda row: row[0])

    def _class_collection(self, code: Any, title: str) -> dict[str, Any] | None:
        """Выборка одного класса, как она пришла. Отбор полей — не здесь.

        Тот же довод, что у карты: разбору классов нужен только `id`, а пробе
        полей — всё остальное. Пока разбор жил внутри цикла, посмотреть на
        ответ было нельзя, не переписав его.
        """
        payload = urllib.parse.urlencode(
            {"data": json.dumps({"classes_ppn_list": [code]})}
        ).encode("utf-8")
        if not self._cookie("csrftoken") and not self.sign_in():
            return None
        try:
            body = self._open(
                _SEARCH_PATH,
                data=payload,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-CSRFToken": self._cookie("csrftoken") or "",
                    "Referer": f"{self.base}{_MAP_PATH}",
                },
            )
        except (urllib.error.URLError, OSError) as exc:
            self.errors.append(f"класс «{title}»: {self._closed(exc) or exc}")
            return None
        raw = lz_decompress_base64(body.decode("utf-8", errors="ignore"))
        if not raw:
            self.errors.append(f"класс «{title}»: ответ не разжался")
            return None
        try:
            return json.loads(raw)
        except ValueError:
            self.errors.append(f"класс «{title}»: ответ не разобрался")
            return None

    def segments(self, *, refresh: bool = False, fetch: bool = True) -> dict[str, str]:
        """Класс каждого проекта: идентификатор → «Бизнес», «Премиум»…

        Спрашивается пять раз, по разу на класс, и складывается на сутки.
        Класса нет ни в точке карты, ни в карточке проекта — он существует
        только как фильтр, поэтому принадлежность выводится из выборки.

        `fetch=False` — только кэш, без пяти запросов: у путей, которые ходят
        по нажатию клавиши, времени на это нет.
        """
        path = self.dir / "segments.json"
        if not refresh and fresh(path, self.ttl_seconds):
            cached = load_json(path)
            if isinstance(cached, dict):
                return {pulse_id(k): str(v) for k, v in cached.items() if pulse_id(k)}
        if not fetch:
            stale = load_json(path)
            return {pulse_id(k): str(v) for k, v in stale.items() if pulse_id(k)} if isinstance(stale, dict) else {}

        out: dict[str, str] = {}
        for code, title in _CLASS_FILTERS.items():
            collection = self._class_collection(code, title)
            if collection is None:
                continue
            for feature in collection.get("features") or []:
                if pulse_id(feature.get("id")):
                    out[pulse_id(feature["id"])] = title

        if out:
            save_json(path, dict(out))
        return out

    def find_project(self, query: str) -> dict[str, Any] | None:
        """Проект по строке: название или застройщик.

        Поиск сервиса отдаёт обычный JSON, без сжатия, и возвращает
        идентификатор — с ним из справочника берутся координаты и адрес.
        """
        text = " ".join(str(query or "").split())
        if len(text) < 3:
            return None
        payload = urllib.parse.urlencode({"query": text, "only_owned": "false"}).encode("utf-8")
        csrf = self._cookie("csrftoken")
        if not csrf and not self.sign_in():
            return None
        try:
            body = self._open(
                "/api/searchbyquery/",
                data=payload,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-CSRFToken": self._cookie("csrftoken") or "",
                    "Referer": f"{self.base}{_MAP_PATH}",
                },
            )
            found = json.loads(body.decode("utf-8", errors="ignore"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.errors.append(f"поиск «{text}»: {exc}")
            return None
        if not isinstance(found, dict):
            return None
        # Совпадения приходят раздельно: по названию и по застройщику. Проект
        # надёжнее имени компании, поэтому имя спрашивается первым.
        for key in ("name", "developer"):
            for row in found.get(key) or []:
                if not isinstance(row, dict) or not pulse_id(row.get("id")):
                    continue
                project = self.project(row["id"])
                if project:
                    return {
                        **project.to_dict(),
                        "segment": self.segments().get(project.complex_id),
                        "matched_by": key,
                    }
        return None

    def price_history(self, complex_ids: list[Any], months: int = 12) -> dict[str, list[dict[str, Any]]]:
        """Помесячная цена метра по каждому проекту.

        Один запрос на весь набор: источник умеет отдавать сразу несколько
        проектов, и опрашивать их поштучно значило бы ждать по разу на соседа.

        Ответ сжат тем же LZ, что и поиск. Пустой список — не ошибка: у нового
        проекта истории может не быть вовсе, и это надо показать, а не скрыть.
        """
        ids = [_api_id(value) for value in complex_ids if pulse_id(value)]
        if not ids:
            return {}
        payload = {
            "ids": ids,
            "opts": {
                "result_value": "sqm_price",
                "object_type": "living",
                "rooms": None,
                # Источник сам добавляет запас к окну, поэтому просим ровно то,
                # что нужно показать, и режем лишнее уже у себя.
                "only_last_months": int(months),
                "area_min": None,
                "area_max": None,
            },
        }
        try:
            raw = self._post_json("/api/compare/price-dynamic-chart/", payload)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.errors.append(f"история цен {ids[:3]}…: {exc}")
            return {}
        if isinstance(raw, str):
            decoded = lz_decompress_base64(raw)
            try:
                raw = json.loads(decoded) if decoded else None
            except ValueError:
                raw = None
        if not isinstance(raw, list):
            return {}
        series: dict[str, list[dict[str, Any]]] = {}
        for row in raw:
            if not isinstance(row, dict) or not pulse_id(row.get("id")):
                continue
            points = []
            for point in row.get("values") or []:
                month = str(point.get("month") or "")[:7]
                value = point.get("value")
                if month and value:
                    points.append({"month": month, "value": int(value)})
            points.sort(key=lambda item: item["month"])
            series[pulse_id(row["id"])] = points[-months:]
        return series

    def suggest(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Подсказки по названию и адресу — из своего справочника, не по сети.

        Полный список проектов уже лежит рядом, поэтому подсказка не стоит ни
        запроса, ни ожидания: обращение к источнику на каждую букву заметно
        замедлило бы ввод и ничего не добавило.

        Порядок сортировки — не украшение. Совпадение с начала имени вернее
        совпадения в середине, а имя вернее адреса: человек, набравший «кутуз»,
        ищет «Кутузов Сити», а не десяток домов на Кутузовском проспекте.
        """
        text = " ".join(str(query or "").split()).casefold()
        if len(text) < 2:
            return []
        # Ни справочник, ни классы здесь по сети не запрашиваются: подсказка
        # ходит на каждую вторую букву, а обе выгрузки тяжёлые.
        return _rank_suggestions(
            self.projects(fetch=False), self.segments(fetch=False), text, limit
        )

    def project(self, complex_id: Any) -> PulseProject | None:
        """Проект справочника по идентификатору (старый числовой — тоже)."""
        wanted = pulse_id(complex_id)
        for item in self.projects():
            if item.complex_id == wanted:
                return item
        return None

    # --- данные проекта --------------------------------------------------------

    def _cached(self, name: str, complex_id: Any, build) -> Any:
        """Ответ по проекту на диске: отчёт спрашивает одно и то же по кругу.

        Двадцать соседей — это сорок обращений к сервису; без кэша сборка
        отчёта ждала бы минуту, а повторная — столько же. Срок короче суток:
        прайс меняется чаще, чем справочник проектов.
        """
        path = self.dir / "cache" / f"{name}-{_id_file(complex_id)}.json"
        if fresh(path, self.detail_ttl_seconds):
            cached = load_json(path)
            if cached is not None:
                return cached.get("value") if isinstance(cached, dict) else cached
        value = build()
        path.parent.mkdir(parents=True, exist_ok=True)
        save_json(path, {"value": value})
        return value

    def metrics(self, complex_id: Any) -> dict[str, Any]:
        """Всё, что нужно блокам отчёта, одним словарём.

        Поглощение в метрах источник считает сам (`avg_sale_speed_living_area`),
        а средний проданный лот выводится из него и темпа в штуках: делить
        метры на штуки корректно, потому что оба числа посчитаны по одному и
        тому же периоду.
        """
        price = self.price(complex_id) or {}
        sales = self.sales(complex_id) or {}
        units = sales.get("units_per_month")
        area = sales.get("area_per_month")
        return {
            "complex_id": pulse_id(complex_id),
            "price_per_sqm": price.get("price_per_sqm"),
            "price_per_sqm_min": price.get("price_per_sqm_min"),
            "price_per_sqm_max": price.get("price_per_sqm_max"),
            "lot_count": price.get("lot_count"),
            "observed_at": price.get("observed_at"),
            "units_per_month": units,
            "units_per_month_3m": sales.get("units_per_month_3m"),
            "area_per_month": area,
            "sales_end_forecast": sales.get("sales_end_forecast"),
            "known_sales_for": sales.get("known_sales_for"),
            "sold_lot_avg": round(area / units, 1) if area and units else None,
        }

    def project_totals(self, complex_id: Any) -> dict[str, Any]:
        """ТЭП проекта: сколько всего жилья и какого размера лоты."""
        data = self._cached(
            "table",
            complex_id,
            lambda: self._post_json("/api/app/complex/table/", {"complex_id": _api_id(complex_id)}),
        )
        if not isinstance(data, dict):
            return {}
        return {
            "living_units": _as_int(data.get("living_count")),
            "living_area": data.get("living_area"),
            "buildings": _as_int(data.get("buildings_count")),
            "lot_area_avg": (
                round(float(data["living_lot_area_avg"]), 1)
                if data.get("living_lot_area_avg")
                else None
            ),
        }

    def project_page(self, complex_id: Any, *, refresh: bool = False) -> dict[str, Any]:
        """Страница проекта в ЛК, разобранная по подписям (`pulse_page`).

        Здесь живёт то, чего нет ни в карте, ни в таблице проекта: стадия,
        тип договора, статус и эскроу по корпусам, остатки с единицами,
        «по состоянию на». Кэшируется разобранный ответ, а не HTML, и только
        удачный: отказ сети не должен на полсуток выглядеть пустой страницей.
        """
        from . import pulse_page  # noqa: PLC0415 — разбор страницы отдельным модулем

        cid = pulse_id(complex_id) or ""
        path = self.dir / "cache" / f"page-{_id_file(cid)}.json"
        if not refresh and fresh(path, self.detail_ttl_seconds):
            cached = load_json(path)
            if isinstance(cached, dict) and isinstance(cached.get("value"), dict):
                return cached["value"]
        url = f"{self.base}/complex/{cid}/"
        if not cid:
            return {"url": None, "reason": "нет id проекта"}
        if not (self._cookie("sessionid") or self.sign_in()):
            return {"url": url, "reason": "страница проекта не открыта: нет входа в ЛК"}
        try:
            page = self._open(f"/complex/{cid}/").decode("utf-8", errors="ignore")
        except (urllib.error.URLError, OSError) as exc:
            self.errors.append(f"карточка проекта {cid}: {exc}")
            return {"url": url, "reason": f"страница проекта не открылась: {exc}"}
        value = {
            "url": url,
            "parsed": pulse_page.parse_project_page(page),
            # Прежний разбор по ключам JSON и подписям — как запасной источник дат.
            "dates_html": _dates_from_project_html(page),
            "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        save_json(path, {"value": value})
        return value

    def project_dates(self, complex_id: Any) -> dict[str, Any]:
        """Старт продаж и плановый ввод из ЛК Пульса — с источником каждого.

        Порядок источников объявлен здесь одним списком (`_DATE_SOURCES`):
        страница проекта, которую человек видит в ЛК, — первой; затем таблица
        API, точка карты и, последним, прежний разбор той же страницы по
        ключам JSON. Все найденные значения отдаются в `candidates`: когда два
        источника расходятся (сентябрь против ноября), видно, кто что сказал.

        Плановый ввод — последний корпус: «18/IV-27/IV» даёт IV кв. 2027, а
        первый корпус (IV кв. 2018) уходит полем `commissioning_first`.
        """
        cid = pulse_id(complex_id) or ""

        def build() -> dict[str, Any]:
            candidates: dict[str, dict[str, str]] = {"sales_start": {}, "commissioning": {}}
            out: dict[str, Any] = {}

            page = self.project_page(cid)
            parsed = page.get("parsed") or {}
            if parsed.get("sales_start"):
                candidates["sales_start"]["pulse_project_page"] = parsed["sales_start"]
            delivery = parsed.get("delivery") or {}
            if delivery.get("last"):
                candidates["commissioning"]["pulse_project_page"] = delivery["last"]
                out["commissioning_first"] = delivery.get("first")
                out["commissioning_raw"] = delivery.get("raw")
                out["commissioning_rule"] = "плановый ввод — последний корпус по сроку сдачи"

            # Этот ответ уже используется для ТЭП проекта; делим тот же cache key.
            table = self._cached(
                "table", cid,
                lambda: self._post_json("/api/app/complex/table/", {"complex_id": _api_id(cid)}),
            )
            if isinstance(table, dict):
                for key, value in _dates_from_payload(table).items():
                    candidates[key]["pulse_api_table"] = value

            known = self.project(cid)
            if known is not None:
                if known.sales_start:
                    candidates["sales_start"]["pulse_map"] = known.sales_start
                if known.commissioning:
                    candidates["commissioning"]["pulse_map"] = known.commissioning

            for key, value in (page.get("dates_html") or {}).items():
                candidates[key]["pulse_project_page_keys"] = value

            sources: dict[str, str] = {}
            for key, found in candidates.items():
                for source in _DATE_SOURCES:
                    if found.get(source):
                        out[key] = found[source]
                        sources[key] = source
                        break
            out["candidates"] = {key: value for key, value in candidates.items() if value}
            if parsed.get("as_of"):
                out["as_of"] = parsed["as_of"]
            if sources:
                out["sources"] = sources
                out["source"] = "Пульс Продаж Новостроек · онлайн"
            return out

        return self._cached("dates", cid, build) or {}

    def project_stage(self, complex_id: Any) -> dict[str, Any]:
        """Стадия строительства проекта — по корпусам, со страницы проекта.

        Карта и таблица проекта поля стадии не несут: прежний поиск ключа по
        смыслу в них на проде почти всегда отвечал «стадия не указана». Стадия
        живёт на странице проекта распределением «стадия → корпусов». `raw` —
        стадия для цены по правилу `pulse_page.stage_summary` (самая ранняя
        незавершённая), рядом — распределение целиком и самая поздняя.

        Страница берётся из кэша `project_page` (её уже открыл `project_dates`);
        таблица и карта остаются запасными источниками.
        """
        cid = pulse_id(complex_id) or ""
        page = self.project_page(cid)
        parsed = page.get("parsed") or {}
        summary = parsed.get("stage") or {}
        price_stage = summary.get("price_stage") or {}
        if price_stage.get("raw"):
            latest = summary.get("latest_stage") or {}
            return {
                "raw": price_stage["raw"],
                "source": "pulse_project_page",
                "as_of": parsed.get("as_of"),
                "distribution": summary.get("distribution") or [],
                "buildings": summary.get("buildings"),
                "latest_raw": latest.get("raw"),
                "rule": summary.get("rule"),
            }
        path = self.dir / "cache" / f"table-{_id_file(cid)}.json"
        cached = load_json(path) if path.exists() else None
        table = cached.get("value") if isinstance(cached, dict) else None
        raw = _stage_from_payload(table) if isinstance(table, dict) else None
        if raw:
            return {"raw": raw, "source": "pulse_api_table"}
        # Только то, что уже лежит рядом: справочник карты не тянется ради стадии.
        known = next((item for item in self.projects(fetch=False) if item.complex_id == cid), None)
        if known is not None and known.construction_stage:
            return {"raw": known.construction_stage, "source": "pulse_map"}
        reason = page.get("reason") or (
            "на странице проекта нет подписи «Стадия строительства»"
            if page.get("parsed") is not None else None
        )
        return {
            "raw": None,
            "source": None,
            "reason": reason or "стадии нет ни на странице проекта, ни в карте и таблице",
        }

    def project_facts(self, complex_id: Any) -> dict[str, Any]:
        """Поля страницы проекта по корпусам — с источником и датой состояния."""
        from . import pulse_page  # noqa: PLC0415

        page = self.project_page(complex_id)
        parsed = page.get("parsed") or {}
        if not parsed:
            return {"reason": page.get("reason")} if page.get("reason") else {}
        facts = {
            key: parsed[key]
            for key in ("contract", "status", "escrow", "finishing", "living", "flats",
                        "commercial", "parking", "storage", "buildings", "pace",
                        "exposure_price_per_sqm")
            if parsed.get(key) is not None
        }
        facts["remaining_figures"] = pulse_page.remaining_figures(parsed)
        facts["as_of"] = parsed.get("as_of")
        facts["source"] = "страница проекта Пульса"
        facts["url"] = page.get("url")
        return facts

    def remaining(self, complex_id: Any) -> dict[str, Any]:
        """Непроданный остаток по корпусам, сложенный в проект."""
        columns = ["building", "living_remaining_predict", "living_remaining_area_predict"]
        data = self._cached(
            "remaining",
            complex_id,
            lambda: self._post_json(
                "/api/app/complex/buildings_summary_table/",
                {"complex_id": _api_id(complex_id), "columns": columns},
            ),
        )
        rows = (data or {}).get("rows") if isinstance(data, dict) else None
        if not rows:
            return {}
        units = sum(int(row.get("living_remaining_predict") or 0) for row in rows)
        area = sum(float(row.get("living_remaining_area_predict") or 0) for row in rows)
        return {
            "remaining_units": units or None,
            "remaining_area": round(area) or None,
        }

    def price(self, complex_id: Any) -> dict[str, Any] | None:
        """Цена прайс-листа: средняя, границы, число лотов и дата среза."""
        data = self._cached(
            "price",
            complex_id,
            lambda: self._post_json(
                "/api/app/complex/price_stats/", {"complex_id": _api_id(complex_id)}
            ),
        )
        current = (data or {}).get("current_price") if isinstance(data, dict) else None
        if not isinstance(current, dict) or not current.get("flat_sqm_price"):
            return None
        return {
            "price_per_sqm": int(current["flat_sqm_price"]),
            "price_per_sqm_min": _as_int(current.get("flat_sqm_price_min")),
            "price_per_sqm_max": _as_int(current.get("flat_sqm_price_max")),
            "lot_count": _as_int(current.get("flat_lot_count")),
            "lot_area_avg": _as_int(current.get("flat_lot_area")),
            "observed_at": str(current.get("price_date") or "")[:10] or None,
            "source": "Пульс Продаж Новостроек",
            "basis": "pulse_price_list_average",
        }

    def sales(self, complex_id: Any) -> dict[str, Any] | None:
        """Темп продаж и прогноз их окончания."""
        data = self._cached(
            "sales",
            complex_id,
            lambda: self._post_json("/api/app/complex/sales/", {"complex_id": _api_id(complex_id)}),
        )
        if not isinstance(data, dict):
            return None
        speed = data.get("avg_sale_speed_living")
        if speed is None:
            return None
        return {
            "units_per_month": speed,
            "units_per_month_3m": data.get("avg_sale_speed_3_months_living"),
            "area_per_month": data.get("avg_sale_speed_living_area"),
            "sales_end_forecast": data.get("sales_end_predict_living"),
            "known_sales_for": data.get("known_sales_for"),
            "source": "Пульс Продаж Новостроек",
            "quality": "provider",
        }

    def exposure(self, complex_id: Any) -> list[dict[str, Any]]:
        """Откуда взят прайс: площадка, дата среза, объём предложения."""
        data = self._post_json("/api/app/complex/price_exposure/", {"complex_id": _api_id(complex_id)})
        if not isinstance(data, list):
            return []
        out: list[dict[str, Any]] = []
        for row in data:
            if not isinstance(row, dict) or not row.get("domain"):
                continue
            out.append(
                {
                    "domain": row.get("domain"),
                    "url": row.get("url"),
                    "primary": bool(row.get("primary")),
                    "observed_at": row.get("price_set_date"),
                    "lot_count": _as_int(row.get("living_count")),
                    "price_per_sqm": _as_int(row.get("living_sqm")),
                }
            )
        return out

    # Поля, которые разбор карты забирает себе. Всё остальное из ответа
    # выбрасывается — и до пробы никто не знал, что именно.
    _MAP_FIELDS_TAKEN = ("name", "developer", "zastroychik", "construction_address")

    def probe_fields(self) -> dict[str, Any]:
        """Что источник кладёт в общий ответ и что из этого мы не берём.

        Вопрос владельца, 19.08.2026: почему свод считается по скачанному
        файлу, если есть сам сайт. Ответ упирался в цену — её берут поштучно,
        и на семьсот проектов это семьсот запросов. Но проверено это не было:
        разбор карты читает четыре свойства, разбор классов — один `id`, а
        что ещё лежит в тех же ответах, никто не смотрел. Если цена и класс
        приходят вместе со списком, живой свод стоит пять запросов, а не
        семьсот, и спорить не о чем.

        Проба ничего не считает и не кэширует: она называет ключи и показывает
        по одному значению, чтобы решение принималось по факту, а не по
        догадке.
        """

        def describe(collection: dict[str, Any] | None) -> dict[str, Any]:
            if not collection:
                return {"features": 0, "keys": [], "sample": {}}
            features = collection.get("features") or []
            keys: dict[str, int] = {}
            sample: dict[str, Any] = {}
            for feature in features:
                props = (feature or {}).get("properties") or {}
                for key, value in props.items():
                    keys[key] = keys.get(key, 0) + 1
                    if key not in sample and value not in (None, ""):
                        sample[key] = value
            return {
                "features": len(features),
                # Ключ, который есть не у всех, — это не поле, а исключение;
                # доля показывается, чтобы это было видно сразу.
                "keys": [
                    {"key": key, "share_pct": round(100 * count / max(len(features), 1))}
                    for key, count in sorted(keys.items(), key=lambda item: (-item[1], item[0]))
                ],
                "sample": sample,
                "unused": sorted(set(keys) - set(self._MAP_FIELDS_TAKEN)),
                # Стадию строительства Пульс даёт фильтром на сайте; есть ли
                # она полем в этих ответах — видно здесь, а не по догадке.
                "stage_like": sorted(key for key in keys if _stage_key(key)),
            }

        if not self.available and not self._cookie("sessionid"):
            return {"available": False, "reason": "Источник выключен: не заданы доступы"}
        first = next(iter(_CLASS_FILTERS.items()), None)
        return {
            "available": True,
            "map": describe(self._map_collection()),
            "class_filter": describe(
                self._class_collection(first[0], first[1]) if first else None
            ),
        }

    # Значения `object_type`, которые имеет смысл спросить. Список — догадка, и
    # это нормально: задача пробы в том и состоит, чтобы догадку проверить.
    # «living» здесь как контроль: если и он пуст, дело не в типах, а в доступе
    # или в самом проекте.
    _OBJECT_TYPES = ("living", "commercial", "nonliving", "non_living",
                     "parking", "pantry", "storeroom", "apartment", "office")

    def probe_object_types(self, complex_id: Any) -> dict[str, Any]:
        """Есть ли у источника коммерция и машино-места — спросив, а не гадая.

        Всё, что мы из «Пульса» берём, прибито к жилью: цена запрашивается с
        `object_type: "living"`, а в таблице проекта читаются `living_count`,
        `living_area`, `living_lot_area_avg`. Приставка у каждого поля и сам
        параметр говорят, что типы источник различает, — но это признак, а не
        доказательство, и проверить его никто не пробовал.

        Проба ничего не считает и не кэширует. Она спрашивает историю цены по
        каждому типу и печатает сырые ключи таблицы проекта: если там лежит
        `commercial_count` или `parking_count`, ответ виден без всяких гипотез.
        """
        if not self.available and not self._cookie("sessionid"):
            return {"available": False, "reason": "Источник выключен: не заданы доступы"}
        cid = pulse_id(complex_id) or ""
        # Причина неудачи лежит в `self.errors`: `_post_json` возвращает `None`
        # и пишет туда, что случилось. Не прочитать её значит показать «точек
        # ноль» и там, где типа нет, и там, где запрос не прошёл, — а это
        # разные ответы. Запоминаем длину, чтобы отдать только своё.
        errors_before = len(self.errors)
        answers: dict[str, Any] = {}
        for kind in self._OBJECT_TYPES:
            payload = {
                "ids": [_api_id(cid)],
                "opts": {"result_value": "sqm_price", "object_type": kind, "rooms": None,
                         "only_last_months": 12, "area_min": None, "area_max": None},
            }
            try:
                raw = self._post_json("/api/compare/price-dynamic-chart/", payload)
            except Exception as exc:  # noqa: BLE001 — причина и есть ответ пробы
                answers[kind] = {"error": f"{type(exc).__name__}: {exc}"}
                continue
            if isinstance(raw, str):
                decoded = lz_decompress_base64(raw)
                try:
                    raw = json.loads(decoded) if decoded else None
                except ValueError:
                    raw = None
            points: list[Any] = []
            if isinstance(raw, list):
                for row in raw:
                    if isinstance(row, dict):
                        points.extend(row.get("values") or [])
            answers[kind] = {
                "points": len(points),
                # Одно значение важнее числа точек: пустой ряд и ряд из нулей
                # выглядят одинаково в счётчике и по-разному по сути.
                "sample": next((point for point in points if point.get("value")), None),
            }
        try:
            table = self._post_json("/api/app/complex/table/", {"complex_id": _api_id(cid)})
        except Exception as exc:  # noqa: BLE001
            table = {"error": f"{type(exc).__name__}: {exc}"}
        return {
            "available": True,
            "complex_id": cid,
            # Вошли ли мы вообще. Пустой ответ без сессии — это отказ доступа,
            # а не отсутствие данных, и путать их нельзя.
            "signed_in": bool(self._cookie("sessionid")),
            "errors": self.errors[errors_before:][:10],
            # Сырые ключи таблицы: `commercial_count` или `parking_count` в них
            # отвечают на вопрос без всякой интерпретации.
            "table_keys": sorted(table) if isinstance(table, dict) else [],
            "table_sample": {key: value for key, value in (table or {}).items()
                             if not isinstance(value, (list, dict))} if isinstance(table, dict) else table,
            "by_object_type": answers,
        }

    def diagnostics(self) -> dict[str, Any]:
        return {
            "base": self.base,
            "available": self.available,
            "projects": len(self._projects or []),
            "errors": self.errors[:5],
        }

    def catalog_report(self, *, refresh: bool = False) -> dict[str, Any]:
        """Что лежит в справочнике этой базы: сколько, откуда, когда, по регионам.

        `refresh=True` идёт за картой и классами заново, мимо суточного кэша.
        Без него — только диск: отчёт смотрят из кабинета, и тянуть
        мегабайтную карту на каждый взгляд незачем.
        """
        errors_before = len(self.errors)
        projects = self.projects(refresh=refresh, fetch=refresh)
        classes = self.segments(refresh=refresh, fetch=refresh)
        by_id: dict[str, int] = {}
        by_address: dict[str, int] = {}
        id_format = {"регион-номер": 0, "число": 0, "иное": 0}
        for item in projects:
            region = item.region
            if region:
                id_format["регион-номер"] += 1
            elif item.complex_id.isdigit():
                id_format["число"] += 1
            else:
                id_format["иное"] += 1
            key = region or "без кода в номере"
            by_id[key] = by_id.get(key, 0) + 1
            place = address_region(item.address) or "регион в адресе не распознан"
            by_address[place] = by_address.get(place, 0) + 1

        def stamp(path: Path) -> dict[str, Any]:
            if not path.exists():
                return {"updated_at": None, "age_hours": None, "fresh": False}
            mtime = path.stat().st_mtime
            age = max(0.0, datetime.datetime.now().timestamp() - mtime)
            return {
                "updated_at": datetime.datetime.fromtimestamp(
                    mtime, tz=datetime.timezone.utc
                ).isoformat(timespec="seconds"),
                "age_hours": round(age / 3600, 1),
                "fresh": age <= self.ttl_seconds,
            }

        def ranked(counts: dict[str, int]) -> dict[str, int]:
            return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

        return {
            "base": self.base,
            "cache_dir": self.dir.name,
            "available": self.available,
            "signed_in": bool(self._cookie("sessionid")),
            # Чьей формой входим и чья сессия уходит на эту базу.
            "auth_base": self.auth.base if self.auth is not None else self.base,
            "auth": (
                f"вход через сессию {self.auth.host}" if self.auth is not None
                else "своя форма входа"
            ),
            "map_path": self.map_path,
            "map_probe": self.map_probe,
            "session_cookie": self._cookie_record("sessionid"),
            "access": self.access_closed or "открыт",
            "projects": len(projects),
            "catalog": stamp(self.catalog_path),
            "segments": {"projects": len(classes), **stamp(self.dir / "segments.json")},
            "ttl_hours": round(self.ttl_seconds / 3600, 1),
            "id_format": id_format,
            "by_id_region": ranked(by_id),
            "by_address_region": ranked(by_address),
            "sample_ids": [item.complex_id for item in projects[:5]],
            # Одна причина — одна строка: пять одинаковых «403» прежде
            # заслоняли собой всё остальное.
            "errors": list(dict.fromkeys(self.errors[errors_before:]))[:10],
        }


class PulseNetwork:
    """Несколько баз «Пульса» под одной вывеской клиента.

    Всероссийский кабинет живёт на своём поддомене (`russia.pulsprodaj.ru`),
    московский — на корневом. Покрывает ли первый Москву, без входа не
    проверить, поэтому базы задаются списком в `PULSE_BASE_URL`, а здесь
    собираются в один справочник. У каждой базы — свой клиент: свои куки,
    свой вход, свой кэш. Порядок — приоритет: если один id пришёл из двух
    баз и это один проект (точки рядом), берётся первая; если разные —
    это конфликт, он не прячется, а считается и показывается в отчёте.

    Цена, остатки и карточка проекта спрашиваются у той базы, чей
    справочник проект принёс: номер одной базы в другой ничего не значит.
    """

    def __init__(self, sites: list[PulseClient]):
        if not sites:
            raise ValueError("нужна хотя бы одна база")
        self.sites = sites
        self._projects: list[PulseProject] | None = None
        self._owner: dict[str, PulseClient] = {}
        self.duplicates = 0
        self.conflicts: list[dict[str, Any]] = []

    # --- совместимость с одиночным клиентом -------------------------------------

    @property
    def base(self) -> str:
        return self.sites[0].base

    @property
    def available(self) -> bool:
        return any(site.available for site in self.sites)

    @property
    def errors(self) -> list[str]:
        return [f"{site_key(site.base)}: {text}" for site in self.sites for text in site.errors]

    @property
    def ttl_seconds(self) -> int:
        return self.sites[0].ttl_seconds

    def sign_in(self) -> bool:
        return any([site.sign_in() for site in self.sites])

    # --- справочник ---------------------------------------------------------

    def projects(self, *, refresh: bool = False, fetch: bool = True) -> list[PulseProject]:
        if self._projects is not None and not refresh:
            return self._projects
        merged: list[PulseProject] = []
        owner: dict[str, PulseClient] = {}
        kept: dict[str, PulseProject] = {}
        duplicates = 0
        conflicts: list[dict[str, Any]] = []
        for site in self.sites:
            for item in site.projects(refresh=refresh, fetch=fetch):
                first = kept.get(item.complex_id)
                if first is None:
                    kept[item.complex_id] = item
                    owner[item.complex_id] = site
                    merged.append(item)
                    continue
                gap = _distance_km(first.latitude, first.longitude, item.latitude, item.longitude)
                if gap <= 1.0:
                    duplicates += 1
                else:
                    conflicts.append({
                        "complex_id": item.complex_id,
                        "kept": {"base": first.base, "name": first.name},
                        "dropped": {"base": item.base, "name": item.name},
                        "distance_km": round(gap, 1),
                    })
        self._owner, self.duplicates, self.conflicts = owner, duplicates, conflicts
        # Пустой список не запоминается: база могла ещё не загрузиться.
        self._projects = merged or None
        return merged

    def _site(self, complex_id: Any) -> PulseClient:
        wanted = pulse_id(complex_id) or ""
        if wanted not in self._owner:
            self.projects(fetch=False)
        return self._owner.get(wanted) or self.sites[0]

    def project(self, complex_id: Any) -> PulseProject | None:
        wanted = pulse_id(complex_id)
        for item in self.projects():
            if item.complex_id == wanted:
                return item
        return None

    def near(self, latitude: float, longitude: float, radius_km: float) -> list[tuple[float, PulseProject]]:
        found = [
            (round(_distance_km(latitude, longitude, item.latitude, item.longitude), 3), item)
            for item in self.projects()
        ]
        return sorted((row for row in found if row[0] <= radius_km), key=lambda row: row[0])

    def segments(self, *, refresh: bool = False, fetch: bool = True) -> dict[str, str]:
        # Класс проекта — из той же базы, что и сам проект: первая база
        # пишется последней и перекрывает остальные, как и в справочнике.
        out: dict[str, str] = {}
        for site in reversed(self.sites):
            out.update(site.segments(refresh=refresh, fetch=fetch))
        return out

    def suggest(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        text = " ".join(str(query or "").split()).casefold()
        if len(text) < 2:
            return []
        return _rank_suggestions(
            self.projects(fetch=False), self.segments(fetch=False), text, limit
        )

    def find_project(self, query: str) -> dict[str, Any] | None:
        for site in self.sites:
            found = site.find_project(query)
            if found:
                return found
        return None

    def price_history(self, complex_ids: list[Any], months: int = 12) -> dict[str, list[dict[str, Any]]]:
        groups: dict[int, list[Any]] = {}
        for value in complex_ids:
            if pulse_id(value):
                groups.setdefault(self.sites.index(self._site(value)), []).append(value)
        out: dict[str, list[dict[str, Any]]] = {}
        for index, ids in groups.items():
            out.update(self.sites[index].price_history(ids, months))
        return out

    # --- данные проекта: у базы-владельца ----------------------------------------

    def metrics(self, complex_id: Any) -> dict[str, Any]:
        return self._site(complex_id).metrics(complex_id)

    def project_totals(self, complex_id: Any) -> dict[str, Any]:
        return self._site(complex_id).project_totals(complex_id)

    def project_dates(self, complex_id: Any) -> dict[str, Any]:
        return self._site(complex_id).project_dates(complex_id)

    def project_stage(self, complex_id: Any) -> dict[str, Any]:
        return self._site(complex_id).project_stage(complex_id)

    def project_page(self, complex_id: Any, *, refresh: bool = False) -> dict[str, Any]:
        return self._site(complex_id).project_page(complex_id, refresh=refresh)

    def project_facts(self, complex_id: Any) -> dict[str, Any]:
        return self._site(complex_id).project_facts(complex_id)

    def remaining(self, complex_id: Any) -> dict[str, Any]:
        return self._site(complex_id).remaining(complex_id)

    def price(self, complex_id: Any) -> dict[str, Any] | None:
        return self._site(complex_id).price(complex_id)

    def sales(self, complex_id: Any) -> dict[str, Any] | None:
        return self._site(complex_id).sales(complex_id)

    def exposure(self, complex_id: Any) -> list[dict[str, Any]]:
        return self._site(complex_id).exposure(complex_id)

    def probe_object_types(self, complex_id: Any) -> dict[str, Any]:
        return self._site(complex_id).probe_object_types(complex_id)

    def probe_fields(self) -> dict[str, Any]:
        return {"bases": {site.base: site.probe_fields() for site in self.sites}}

    def diagnostics(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "projects": len(self._projects or []),
            "errors": self.errors[:5],
            "bases": [site.diagnostics() for site in self.sites],
        }

    def catalog_report(self, *, refresh: bool = False) -> dict[str, Any]:
        bases = [site.catalog_report(refresh=refresh) for site in self.sites]
        merged = self.projects(refresh=refresh, fetch=refresh)
        return {
            "bases": bases,
            "projects": len(merged),
            "duplicates": self.duplicates,
            "conflicts": len(self.conflicts),
            "conflict_sample": self.conflicts[:5],
        }


def make_pulse_client(data_dir: Path, **kwargs: Any) -> PulseClient | PulseNetwork:
    """Клиент по `PULSE_BASE_URL`: одна база — как прежде, несколько — сеть."""
    bases = parse_bases(kwargs.pop("base", None) or os.getenv("PULSE_BASE_URL"))
    sites = [PulseClient(data_dir, base=base, **kwargs) for base in bases]
    # Поддомен входит через базу, чей хост — его суффикс: `russia.pulsprodaj.ru`
    # через `pulsprodaj.ru`. Связь берётся из списка баз, а не выводится из
    # имени. Поддомен без корневой базы в списке — `PULSE_AUTH_BASE_URL`.
    auth_base = (os.getenv("PULSE_AUTH_BASE_URL") or "").strip().rstrip("/")
    extra_auth: PulseClient | None = None
    for site in sites:
        parent = next(
            (other for other in sites
             if other is not site and site.host.endswith("." + other.host)),
            None,
        )
        if parent is None and auth_base and auth_base != site.base:
            if extra_auth is None:
                extra_auth = PulseClient(data_dir, base=auth_base, **kwargs)
            if site.host.endswith("." + extra_auth.host):
                parent = extra_auth
        site.auth = parent
    if len(sites) == 1:
        return sites[0]
    return PulseNetwork(sites)



def _rank_suggestions(
    projects: list[PulseProject], classes: dict[str, str], text: str, limit: int
) -> list[dict[str, Any]]:
    """Общий отбор подсказок: и для одной базы, и для нескольких сразу."""
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for project in projects:
        name = (project.name or "").casefold()
        address = (project.address or "").casefold()
        if name.startswith(text):
            rank = 0
        elif text in name:
            rank = 1
        elif text in address:
            rank = 2
        else:
            continue
        scored.append((
            rank,
            len(project.name or ""),
            {
                "complex_id": project.complex_id,
                "region": project.region,
                "name": project.name,
                "developer": project.developer,
                "address": project.address,
                "segment": classes.get(project.complex_id),
                "base": project.base,
            },
        ))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [row for _, _, row in scored[:limit]]

def _as_int(value: Any) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None

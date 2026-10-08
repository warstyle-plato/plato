"""Сверка нашего сценария со штатным калькулятором ГлавАПУ.

Калькулятор (genplan.tech/calc) считает в браузере. Отдельного API, которое
приняло бы параметры застройки, у него нет: с сервера ГлавАПУ он берёт только
анализ территории (`glavapu-api.ru/api/analysis`), а СПП, деление на жилое и
нежилое, ВРИ нежилья и соцобъекты задаются полями левой панели. Поэтому
сценарий выставляется теми же полями, что у человека, — фоновым браузером ядра,
— и забирается кнопкой «Excel» калькулятора: в книге есть всё, что сверяется
(листы «ТЭП», «МПТ», «Машино-места», «Параметры территории»).

Роль ГлавАПУ здесь — проверка (`ROLE = "validation_only"`): числа калькулятора
стоят рядом с нашими и НИЧЕГО в модели не заменяют.

Устройство:

* `build_scenario` — параметры нашего сценария из ТЭП проекта и явной карты
  «продукт → ВРИ калькулятора»; у каждого параметра записано, откуда он.
  Продукт без строки в карте не передаётся молча под чужим ВРИ — он уходит в
  `not_sent` с причиной.
* `scenario_key` — ключ кэша: одинаковые параметры дают один прогон браузера.
* `apply_scenario` / `read_rows` / `export_xlsx` — шаги браузера. Каждое поле
  после ввода сверяется с тем, что показал калькулятор; не принял — отказ с
  местом (раздел, поле, строка таблицы), а не тихий расчёт на его умолчаниях.
* `glavapu_side` — числа калькулятора из выгрузки (по видам).
* `compare` — сверка «наше / ГлавАПУ» с причиной каждого расхождения.

Порядок полей в калькуляторе важен и выяснен на его же коде
(`genplan_assets`, прогон 06.10.2026):

1. галочки «Состава территории» ПЕРЕСТАВЛЯЮТ деление жилое/нежилое (включение
   соцобъектов возвращает 90/10), поэтому они ставятся первыми;
2. соцобъект отрезает свою СПП из нежилой части (строка 8.2 растёт за счёт 8.1);
3. общий СПП держится плотностью × площадью, а поля «жилых/нежилых» делят его:
   правка одного меняет другое. Ставится общий СПП, затем жилые, нежилые —
   остаток, который проверяется;
4. «Детализировать СПП» по умолчанию кладёт всё нежильё в «Деловое управление
   (4.1)»; остальные ВРИ добавляются меню категории.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import time
from typing import Any, Callable, Iterable

ROLE = "validation_only"
SCHEMA = 1

# Нежилые продукты модели → категория «Детализировать СПП» калькулятора.
# Явная карта, а не догадка по имени: подпись меню — то, что выбирается, код —
# хвост id поля (`id-param-details-<код>-text-field`). Код 4_1 калькулятор
# заводит сам и по умолчанию держит в нём всё нежильё.
NONRES_VRI: dict[str, tuple[str, str]] = {
    "offices": ("Деловое управление (4.1)", "4_1"),
    "standalone_retail": ("Объекты торговли (4.2)", "4_2"),
    "sports": ("Спорт (5.1)", "5_1"),
    "above_parking": ("Хранение автотранспорта (2.7.1)", "2_7_1"),
}
DEFAULT_NONRES_CODE = "4_1"

# Соцобъекты: строка ТЭП модели → вид объекта калькулятора (хвосты id полей
# `handle-user-<вид>-places-0`, `id-typical-checkbox-<вид>-0`).
SOCIAL_KINDS: dict[str, str] = {
    "kindergarten": "doo",
    "school": "school",
    "clinic": "policlinic",
}
SOCIAL_LABELS = {"kindergarten": "ДОО", "school": "СОШ", "clinic": "поликлиника"}
# Строки таблицы калькулятора: размещённые места (18/22/26).
SOCIAL_PLACED_ROWS = {"kindergarten": "18", "school": "22", "clinic": "26"}

# Строки модели, которые относятся к жилым зданиям. Кладовые — помещения МКД:
# у калькулятора отдельной строки для них нет, и по 7.1 («СПП жилая») они идут
# вместе с квартирами. Это решение карты, а не вывод из имени поля.
RESIDENTIAL_LIVING_KEYS = ("apartments", "storage")
RESIDENTIAL_NONRES_KEY = "ground_commercial"
# Подписи строк ТЭП на случай, когда ТЭП пришёл без них (превью пресета).
TEP_LABELS = {"apartments": "Квартиры", "storage": "Кладовые",
              "ground_commercial": "Коммерция 1 этажа", "offices": "Офисы",
              "standalone_retail": "ТЦ", "sports": "ФОК / медцентр",
              "above_parking": "Наземный паркинг", "kindergarten": "ДОО",
              "school": "СОШ", "clinic": "Поликлиника",
              "other_mandatory": "Прочие обязательные объекты"}


def _label(tep: dict[str, Any], key: str) -> str:
    row = (tep or {}).get(key)
    label = row.get("label") if isinstance(row, dict) else ""
    return str(label or TEP_LABELS.get(key) or key)


# Строки, которых в СПП нет вовсе: подземный паркинг — под землёй, а СПП
# калькулятора — наземные этажи плюс подземные «в ГНС» только у зданий.
NOT_SPP_KEYS = ("underground_parking",)

LAND_RIGHT_OPTIONS = {"ownership": "собственность", "lease": "аренда"}

# Допуски проверки «калькулятор принял поле». Таблица печатает тыс. м² с
# тремя знаками, а плотность округляет — расхождение в последнем знаке не отказ.
TOL_THS = 0.05      # тыс. м²
TOL_HA = 0.001


def _num(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def ru_number(text: Any) -> float | None:
    """«18 265,873» / «17,811 (100,0%)» → число; пусто → None (не ноль)."""
    raw = str(text if text is not None else "").replace("\xa0", " ").strip()
    if not raw:
        return None
    raw = raw.split("(")[0].replace(" ", "").replace(",", ".")
    match = re.match(r"^-?\d+(?:\.\d+)?", raw)
    return float(match.group(0)) if match else None


def _sqm(value: float) -> str:
    """«5 000» — разряды пробелом; запятые текста вокруг не трогаются."""
    return f"{value:,.0f}".replace(",", " ")


def _gns(tep: dict[str, Any], key: str) -> float:
    row = (tep or {}).get(key)
    return _num(row.get("gns")) if isinstance(row, dict) else 0.0


# ---------------------------------------------------------------- сценарий --

def build_scenario(inputs: dict[str, Any], tep: dict[str, Any], *,
                   product_of: Callable[[str], str] | None = None,
                   numbers: Iterable[str] = ()) -> dict[str, Any]:
    """Параметры калькулятора из нашего сценария.

    `product_of(key)` — продукт строки ТЭП (второй офисник — «offices»);
    объявлен в движке реестром объектов, сюда приходит готовым.
    """
    inputs = inputs or {}
    tep = tep or {}
    product_of = product_of or (lambda key: key)
    origin: dict[str, str] = {}
    not_sent: list[dict[str, str]] = []

    living = sum(_gns(tep, key) for key in RESIDENTIAL_LIVING_KEYS)
    built_in = _gns(tep, RESIDENTIAL_NONRES_KEY)
    residential = living + built_in
    origin["spp_residential"] = ("ТЭП проекта: ГНС «Квартиры» + «Кладовые» + "
                                 "«Коммерция 1 этажа»")

    nonres: dict[str, dict[str, Any]] = {}
    social: dict[str, dict[str, Any]] = {}
    skip = set(RESIDENTIAL_LIVING_KEYS) | {RESIDENTIAL_NONRES_KEY} | set(NOT_SPP_KEYS)
    for key, row in tep.items():
        if key in skip or not isinstance(row, dict):
            continue
        gns = _num(row.get("gns"))
        if gns <= 0:
            continue
        label = _label(tep, key)
        if key in SOCIAL_KINDS:
            places = int(round(_num(row.get("units"))))
            if places <= 0:
                not_sent.append({"param": f"social.{key}", "label": label,
                                 "reason": (f"у строки ТЭП «{label}» есть ГНС {_sqm(gns)} м², "
                                            "но нет числа мест — калькулятору "
                                            "соцобъект задаётся местами")})
                continue
            social[key] = {"kind": SOCIAL_KINDS[key], "places": places,
                           "spp_ths": round(gns / 1000.0, 4), "label": label,
                           "origin": f"ТЭП проекта: «{label}», места и ГНС"}
            continue
        product = product_of(key)
        target = NONRES_VRI.get(product)
        if not target:
            not_sent.append({"param": f"nonres.{key}", "label": label,
                             "reason": (f"«{label}» ({_sqm(gns)} м²) не передан: для продукта "
                                        f"«{product}» нет ВРИ в карте NONRES_VRI — "
                                        "под чужим видом его не ставим")})
            continue
        menu, code = target
        slot = nonres.setdefault(code, {"code": code, "menu": menu, "spp_ths": 0.0,
                                         "keys": [], "origin": ""})
        slot["spp_ths"] = round(slot["spp_ths"] + gns / 1000.0, 4)
        slot["keys"].append(key)
        slot["origin"] = "ТЭП проекта: ГНС " + ", ".join(
            f"«{_label(tep, k)}»" for k in slot["keys"])

    transfer = _num(((tep.get("apartments") or {}) if isinstance(tep.get("apartments"), dict)
                     else {}).get("transfer"))
    if transfer > 0:
        # Льгота калькулятора за передачу квартир городу включается его
        # галочкой — сверка её пока не ставит, и это видно, а не молчит.
        not_sent.append({"param": "benefit_for_flats", "label": "Передача квартир городу",
                         "reason": (f"передаваемые городу квартиры ({_sqm(transfer)} м²) калькулятору "
                                    "не переданы: галочку «Передача жилых помещений в собственность "
                                    "города Москвы» сверка не ставит — льготы за передачу у ГлавАПУ нет")})
    nonres_ths = round(sum(item["spp_ths"] for item in nonres.values()), 4)
    social_ths = round(sum(item["spp_ths"] for item in social.values()), 4)
    area_ha = _num(inputs.get("site_area_ha"))
    if area_ha <= 0:
        territory = ((inputs.get("_glavapu_import") or {}).get("normalized") or {})
        area_ha = _num(territory.get("site_area_ha"))
        origin["area_ha"] = "выгрузка ГлавАПУ (площадь территории проектирования)"
    else:
        origin["area_ha"] = "вводные проекта: site_area_ha"
    land_right = str(inputs.get("land_right") or "").strip()
    params = {
        "area_ha": round(area_ha, 4),
        "restrict_ha": 0.0,
        "spp_residential_ths": round(residential / 1000.0, 4),
        "vpp_pct": round(built_in / residential * 100.0, 3) if residential > 0 else 0.0,
        "spp_nonres_ths": nonres_ths,
        "nonres": sorted(nonres.values(), key=lambda item: item["code"]),
        "social": [dict(item, key=key) for key, item in sorted(social.items())],
        "land_right": LAND_RIGHT_OPTIONS.get(land_right, ""),
    }
    origin["restrict_ha"] = "ограничений сохранения модель не ведёт — 0"
    origin["vpp_pct"] = "ТЭП проекта: «Коммерция 1 этажа» / СПП жилых зданий"
    origin["spp_nonres"] = "ТЭП проекта: ГНС нежилых объектов по карте NONRES_VRI"
    origin["land_right"] = ("вводные проекта: land_right" if params["land_right"]
                            else "право на участок не задано — у калькулятора его умолчание")
    problems: list[str] = []
    if area_ha <= 0:
        problems.append("нет площади территории (site_area_ha) — калькулятору нечего считать")
    if residential + nonres_ths * 1000 + social_ths * 1000 <= 0:
        problems.append("в ТЭП проекта нет наземных метров — сценарий пуст")
    return {
        "schema": SCHEMA,
        "role": ROLE,
        "numbers": sorted({str(n).strip() for n in numbers if str(n).strip()}),
        "params": params,
        "origin": origin,
        "not_sent": not_sent,
        "problems": problems,
        "spp_social_ths": social_ths,
    }


def scenario_key(scenario: dict[str, Any]) -> str:
    """Ключ кэша: набор параметров и участок, без подписей происхождения."""
    payload = {"schema": scenario.get("schema"), "numbers": scenario.get("numbers") or [],
               "params": scenario.get("params") or {}}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


# ------------------------------------------------------------------ браузер --

READ_ROWS_JS = """() => {
  const table = document.querySelector('table[aria-label="calc table"]');
  if (!table) return {};
  const out = {};
  table.querySelectorAll('tbody tr').forEach(row => {
    const cells = Array.from(row.children).map(c => String(c.textContent || '').replace(/\\s+/g, ' ').trim());
    if (cells.length >= 4 && /^\\d+(?:[.,]\\d+)*$/.test(cells[0])) out[cells[0].replace(/,/g, '.')] = cells[3];
  });
  return out;
}"""

# Поля категорий, которые человек может править. Категории соцобъектов
# (3.4, 3.5) калькулятор заводит сам и держит закрытыми — их не трогаем.
EDITABLE_DETAILS_JS = """() => Array.from(document.querySelectorAll('input[id^="id-param-details-"]'))
  .filter(e => !e.disabled && !e.readOnly)
  .map(e => e.id.replace('id-param-details-', '').replace('-text-field', ''))"""

DETAIL_FIELDS_JS = """() => Object.fromEntries(Array.from(
  document.querySelectorAll('input[id^="id-param-details-"]'))
  .map(e => [e.id.replace('id-param-details-', '').replace('-text-field', ''), e.value]))"""

OPTIONS_JS = """() => Array.from(document.querySelectorAll('[role="option"]'))
  .map(e => String(e.textContent || '').trim())"""

PANEL_ERRORS_JS = """() => Array.from(document.querySelectorAll('.Mui-error'))
  .map(e => String(e.textContent || '').replace(/\\s+/g, ' ').trim()).filter(Boolean).slice(0, 6)"""

RATIO_SLIDER_JS = """() => {
  const s = document.querySelector('[role="slider"][aria-label*="жилых и нежилых"]');
  return s ? {value: s.getAttribute('aria-valuenow'), text: s.getAttribute('aria-valuetext')} : null;
}"""

SECTION_COMPOSITION = "Состав территории"
SECTION_SOCIAL = "Определить социальные объекты"
SECTION_DETAILS = "Детализировать СПП"
SECTION_VRI = "Стоимость смены ВРИ"


class ScenarioStep:
    """Журнал шагов: что ставили, где, что калькулятор показал в ответ."""

    def __init__(self) -> None:
        self.applied: list[dict[str, Any]] = []
        self.refused: list[dict[str, Any]] = []

    def ok(self, param: str, place: str, want: Any, got: Any) -> None:
        self.applied.append({"param": param, "place": place, "want": want, "got": got})

    def refuse(self, param: str, place: str, reason: str, want: Any = None,
               got: Any = None) -> None:
        self.refused.append({"param": param, "place": place, "reason": reason,
                             "want": want, "got": got})


def read_rows(page: Any) -> dict[str, float | None]:
    raw = page.evaluate(READ_ROWS_JS) or {}
    return {str(code): ru_number(value) for code, value in raw.items()}


def _pause(page: Any, ms: int = 350) -> None:
    page.wait_for_timeout(ms)


def _expand(page: Any, title: str) -> None:
    """Раскрывает раздел левой панели, если он свёрнут.

    Разделы — пункты списка (role=button), а не заголовки: h6 с тем же текстом
    лежит в скрытой справке и не кликается.
    """
    header = page.locator("[role=button]:visible", has_text=title).first
    expanded = header.get_attribute("aria-expanded")
    if expanded == "true":
        return
    header.click(timeout=7000)
    _pause(page)


def _fill(page: Any, selector: str, value: Any) -> str:
    field = page.locator(selector).first
    field.click(timeout=7000)
    field.fill(_fmt(value))
    field.press("Tab")
    _pause(page)
    return field.input_value()


def _fmt(value: Any) -> str:
    number = _num(value)
    text = f"{number:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _set_checkbox(page: Any, selector: str, on: bool) -> bool:
    box = page.locator(selector).first
    if box.is_checked() != on:
        box.click(timeout=7000)
        _pause(page)
    return box.is_checked()


def _close_menu(page: Any) -> None:
    page.keyboard.press("Escape")
    _pause(page, 250)


def _choose_option(page: Any, field_selector: str, matcher: Callable[[str], bool]) -> str | None:
    """Открывает выпадающий список поля и выбирает первый подходящий пункт."""
    page.locator(field_selector).first.click(timeout=7000)
    _pause(page, 300)
    options = page.evaluate(OPTIONS_JS) or []
    for text in options:
        if matcher(text):
            page.get_by_role("option", name=text, exact=True).first.click(timeout=7000)
            _pause(page)
            return text
    _close_menu(page)
    return None


def _exc_reason(exc: Exception) -> str:
    """Причина срыва Playwright с тем, ЧТО он ждал: «Timeout 7000ms» без
    селектора не говорит, какое поле чужой страницы пропало."""
    lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
    head = f"{type(exc).__name__}: {lines[0][:160] if lines else ''}"
    waited = next((line for line in lines if line.startswith("- waiting for")), "")
    blocker = next((line for line in lines if "intercepts pointer events" in line), "")
    tail = "; ".join(part[:200] for part in (waited, blocker) if part)
    return head + (f" ({tail})" if tail else "")


def _near(a: float | None, b: float, tol: float) -> bool:
    return a is not None and abs(a - b) <= tol


def apply_scenario(page: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Выставляет сценарий на открытом экране расчёта и сверяет каждое поле.

    Порядок шагов — из докстринга модуля. Любой непринятый параметр — запись в
    `refused` с местом; исключение Playwright по одному полю не роняет весь
    прогон, но тоже становится отказом этого поля с местом.
    """
    log = ScenarioStep()
    started = time.monotonic()
    if _num(params.get("area_ha")) <= 0:
        log.refuse("area_ha", "сценарий", "нет площади территории — калькулятор не запускается")
        return {"applied": [], "refused": log.refused, "ms": 0}

    def guarded(param: str, place: str, step: Callable[[], None]) -> None:
        try:
            step()
        except Exception as exc:  # noqa: BLE001 — отказ поля, а не прогона
            log.refuse(param, place, _exc_reason(exc))

    # 1. Площадь территории — поле над разделами.
    def area() -> None:
        _fill(page, "#terrArea", params["area_ha"])
        _fill(page, "#restrictArea", params.get("restrict_ha") or 0)
    guarded("area_ha", "поле «Площадь территории рассмотрения, га» (#terrArea)", area)

    # 2. Режим «СПП в ГНС»: в «Едином показателе» поля СПП нет.
    def mode() -> None:
        button = page.locator("button[value='pl']").first
        if button.count() and button.get_attribute("aria-pressed") != "true":
            button.click(timeout=7000)
            _pause(page)
    guarded("mode", "переключатель «СПП в ГНС / Единый показатель»", mode)

    social = params.get("social") or []
    nonres = params.get("nonres") or []
    place_comp = f"раздел «{SECTION_COMPOSITION}»"

    # 3. Состав территории: галочки сначала — они переставляют деление.
    def composition() -> None:
        _expand(page, SECTION_COMPOSITION)
        if not _set_checkbox(page, "#check-vpp-builds-user", True):
            log.refuse("vpp_pct", place_comp + ", галочка «Нежилая часть в составе жилых зданий»",
                       "галочка не включилась")
        want_otd = bool(nonres) or bool(social)
        if _set_checkbox(page, "#check-otd-nzh-builds-user", want_otd) != want_otd:
            log.refuse("spp_nonres_ths", place_comp + ", галочка «Разместить отдельностоящие нежилые объекты»",
                       "галочка не переключилась", want_otd)
        if _set_checkbox(page, "#check-social-builds-user", bool(social)) != bool(social):
            log.refuse("social", place_comp + ", галочка «Разместить социальные объекты»",
                       "галочка не переключилась", bool(social))
        got = _fill(page, "#id-calc-vpp-input", params["vpp_pct"])
        if not _near(ru_number(got), params["vpp_pct"], 0.01):
            log.refuse("vpp_pct", place_comp + ", поле «Нежилая часть в составе жилых зданий, %»",
                       f"поле показывает {got!r}", params["vpp_pct"], got)
    guarded("composition", place_comp, composition)

    # 4. Соцобъекты: типовой объект нужной мощности, иначе — своё число мест.
    if social:
        def socials() -> None:
            _expand(page, SECTION_SOCIAL)
            for item in social:
                kind, places = item["kind"], int(item["places"])
                where = f"раздел «{SECTION_SOCIAL}», {item['label']}"
                typical = page.locator(f"#id-typical-checkbox-{kind}-0").first
                chosen = None
                if typical.count() and typical.is_checked():
                    chosen = _choose_option(
                        page, f"#handle-user-{kind}-places-0",
                        lambda text, p=places: re.match(rf"^{p}\s+мест", text) is not None)
                if chosen:
                    log.ok(f"social.{item['key']}", where + " (типовой объект)", places, chosen)
                    continue
                if typical.count() and typical.is_checked():
                    typical.click(timeout=7000)
                    _pause(page)
                got = _fill(page, f"#handle-input-{kind}-places-0", places)
                if ru_number(got) != places:
                    log.refuse(f"social.{item['key']}", where + " (своё число мест)",
                               f"поле показывает {got!r}", places, got)
                else:
                    log.ok(f"social.{item['key']}", where + " (своё число мест)", places, got)
        guarded("social", f"раздел «{SECTION_SOCIAL}»", socials)

    # 5. СПП: общий (плотность × площадь), затем жилые; нежилые — остаток.
    # Соцобъект калькулятор считает своей площадью, и она сидит в нежилой
    # части. Чтобы жильё и коммерция легли ровно нашими числами, общий СПП
    # собирается с СОЦИАЛЬНОЙ СПП КАЛЬКУЛЯТОРА — расхождение соцплощади
    # остаётся видимым в своей строке сверки, а не размазывается по жилью.
    def spp() -> None:
        calc_social = (read_rows(page).get("8.2") or 0.0) if social else 0.0
        total = params["spp_residential_ths"] + params["spp_nonres_ths"] + calc_social
        _fill(page, "#id-param-terr-text-field", total)
        _fill(page, "#id-param-zh-terr-text-field", params["spp_residential_ths"])
    guarded("spp", "поля «СПП в ГНС (тыс.кв.м.)» и «жилых зданий»", spp)

    # 6. Нежильё по ВРИ.
    if nonres:
        def details() -> None:
            _expand(page, SECTION_DETAILS)
            have = page.evaluate(DETAIL_FIELDS_JS) or {}
            for item in nonres:
                if item["code"] in have:
                    continue
                page.locator("#param-details-button-nzh").first.click(timeout=7000)
                _pause(page, 300)
                option = page.get_by_role("menuitem", name=item["menu"], exact=True)
                if not option.count():
                    log.refuse(f"nonres.{item['code']}",
                               f"раздел «{SECTION_DETAILS}», меню «Добавить категорию»",
                               f"в меню нет пункта «{item['menu']}»", item["spp_ths"])
                    _close_menu(page)
                    continue
                # Меню прокручивается внутри поповера, и обычный клик ловит
                # соседний пункт: выбираем сам элемент.
                option.first.evaluate("element => element.click()")
                _pause(page, 300)
                _close_menu(page)
            have = page.evaluate(DETAIL_FIELDS_JS) or {}
            wanted = {item["code"] for item in nonres}
            # Категории калькулятора, которых в сценарии нет (4.1 по умолчанию),
            # обнуляются: иначе в них остаётся прежний остаток нежилья.
            for code in sorted(page.evaluate(EDITABLE_DETAILS_JS) or []):
                if code.startswith("2_6") or code in wanted:
                    continue
                _fill(page, f"#id-param-details-{code}-text-field", 0)
            for item in nonres:
                if item["code"] in have:
                    _fill(page, f"#id-param-details-{item['code']}-text-field", item["spp_ths"])
        guarded("nonres", f"раздел «{SECTION_DETAILS}»", details)

    # 7. Вид права — плата за смену ВРИ от него зависит.
    if params.get("land_right"):
        def right() -> None:
            _expand(page, SECTION_VRI)
            current = page.locator("input[value='собственность'], input[value='аренда']").first
            if current.input_value() == params["land_right"]:
                log.ok("land_right", f"раздел «{SECTION_VRI}», «Вид права на землю»",
                       params["land_right"], params["land_right"])
                return
            chosen = _choose_option(page, "input[value='собственность'], input[value='аренда']",
                                    lambda text: text == params["land_right"])
            if chosen:
                log.ok("land_right", f"раздел «{SECTION_VRI}», «Вид права на землю»",
                       params["land_right"], chosen)
            else:
                log.refuse("land_right", f"раздел «{SECTION_VRI}», «Вид права на землю»",
                           "нет такого варианта в списке", params["land_right"])
        guarded("land_right", f"раздел «{SECTION_VRI}»", right)

    _pause(page, 600)
    verify(page, params, log)
    return {"applied": log.applied, "refused": log.refused,
            "ms": int((time.monotonic() - started) * 1000)}


def verify(page: Any, params: dict[str, Any], log: ScenarioStep) -> dict[str, float | None]:
    """Принял ли калькулятор сценарий — по его же таблице и полям.

    Проверяется результат, а не то, что мы нажали: поле могло принять число и
    тут же пересчитать соседнее.
    """
    rows = read_rows(page)
    table = "таблица ТЭП калькулятора"

    def check(param: str, code: str, want: float, tol: float, label: str) -> None:
        got = rows.get(code)
        if got is None:
            log.refuse(param, f"{table}, строка {code} «{label}»",
                       "строки нет в таблице — проверить нечем", want)
        elif abs(got - want) > tol:
            log.refuse(param, f"{table}, строка {code} «{label}»",
                       f"калькулятор показывает {got:g} вместо {want:g}", want, got)
        else:
            log.ok(param, f"{table}, строка {code}", want, got)

    check("area_ha", "1", params["area_ha"] - (params.get("restrict_ha") or 0.0), TOL_HA * 2,
          "Площадь территории проектирования")
    check("spp_residential_ths", "7", params["spp_residential_ths"], TOL_THS,
          "СПП жилых зданий")
    residential = params["spp_residential_ths"]
    built_in = residential * params["vpp_pct"] / 100.0
    check("vpp_pct", "7.2", built_in, TOL_THS, "СПП нежилой части жилых зданий")
    check("spp_nonres_ths", "8.1", params["spp_nonres_ths"], TOL_THS,
          "СПП общественных, производственных объектов")
    for item in params.get("social") or []:
        code = SOCIAL_PLACED_ROWS.get(item["key"])
        if code:
            check(f"social.{item['key']}", code, float(item["places"]), 0.5,
                  f"{item['label']}: количество мест")
    if params.get("nonres"):
        have = {code: ru_number(value) for code, value in
                (page.evaluate(DETAIL_FIELDS_JS) or {}).items()}
        for item in params["nonres"]:
            got = have.get(item["code"])
            place = f"раздел «{SECTION_DETAILS}», поле {item['menu']}"
            if got is None:
                log.refuse(f"nonres.{item['code']}", place, "поля категории нет", item["spp_ths"])
            elif abs(got - item["spp_ths"]) > TOL_THS:
                log.refuse(f"nonres.{item['code']}", place,
                           f"поле показывает {got:g} вместо {item['spp_ths']:g}",
                           item["spp_ths"], got)
            else:
                log.ok(f"nonres.{item['code']}", place, item["spp_ths"], got)
    # Ползунок «Соотношение жилых / нежилых зданий»: по умолчанию 100/0, наш
    # сценарий двигает его вписанным СПП жилых зданий. Проверяется, что он
    # встал туда, куда показывает таблица (строки 7 / 6).
    slider = page.evaluate(RATIO_SLIDER_JS)
    place = "ползунок «Соотношение жилых / нежилых зданий»"
    if not slider:
        log.refuse("ratio", place, "ползунка нет на панели — проверить соотношение нечем")
    elif rows.get("6") and rows.get("7") is not None:
        want = rows["7"] / rows["6"] * 100.0
        got = ru_number(slider.get("value"))
        if got is None or abs(got - want) > 0.2:
            log.refuse("ratio", place, f"ползунок показывает {slider.get('text')!r}, "
                       f"а по таблице жилых {want:.2f}%", round(want, 2), slider.get("text"))
        else:
            log.ok("ratio", place, round(want, 2), slider.get("text"))
    errors = page.evaluate(PANEL_ERRORS_JS) or []
    if errors:
        log.refuse("panel", "левая панель калькулятора",
                   "поля подсвечены ошибкой: " + "; ".join(errors))
    return rows


def export_xlsx(page: Any, timeout_ms: int = 30000) -> bytes:
    """Книга калькулятора кнопкой «Excel» — та же, что скачивает человек."""
    with page.expect_download(timeout=timeout_ms) as download:
        page.get_by_role("button", name="Excel", exact=True).first.click(timeout=7000)
    path = download.value.path()
    with open(path, "rb") as handle:
        return handle.read()


# --------------------------------------------------------- сторона ГлавАПУ --

def _sheet_rows(data: bytes, name: str) -> list[list[Any]]:
    import openpyxl

    book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        for sheet in book.worksheets:
            if sheet.title.strip().lower() == name.lower():
                return [list(row) for row in sheet.iter_rows(values_only=True)]
    finally:
        book.close()
    return []


def _header_map(header: list[Any]) -> dict[str, int]:
    return {str(cell or "").strip().lower(): index for index, cell in enumerate(header)}


def mpt_by_vri(data: bytes) -> dict[str, Any] | None:
    """Лист «МПТ»: рабочие места по ВРИ. Нет листа — None, а не ноль."""
    rows = _sheet_rows(data, "МПТ")
    if not rows:
        return None
    header = _header_map(rows[0])
    name_at, value_at = header.get("наименования", 1), header.get("показатель", 3)
    items = []
    for row in rows[1:]:
        if len(row) <= max(name_at, value_at) or not row[name_at]:
            continue
        value = ru_number(row[value_at])
        if value is not None:
            items.append({"vri": str(row[name_at]).strip(), "jobs": value})
    return {"items": items, "total": sum(item["jobs"] for item in items)}


PARKING_COLUMNS = {"всего": "total", "приобъектные": "attached", "постоянные": "permanent",
                   "гостевые": "guest", "кратковременные": "short_stop"}


def parking_by_vri(data: bytes) -> dict[str, Any] | None:
    """Лист «Машино-места»: виды мест по ВРИ (столбцы по заголовку, не по месту)."""
    rows = _sheet_rows(data, "Машино-места")
    if not rows:
        return None
    header = _header_map(rows[0])
    columns = {key: header[title] for title, key in PARKING_COLUMNS.items() if title in header}
    name_at = header.get("наименования", 1)
    items = []
    for row in rows[1:]:
        if len(row) <= name_at or not row[name_at]:
            continue
        item: dict[str, Any] = {"vri": str(row[name_at]).strip()}
        for key, index in columns.items():
            item[key] = ru_number(row[index]) if index < len(row) else None
        items.append(item)
    totals = {key: sum((item.get(key) or 0.0) for item in items) for key in columns}
    return {"items": items, "totals": totals, "columns": sorted(columns)}


# Лист «Социальные объекты»: типовые здания, которые калькулятор поставил.
# Столбцы — по началу заголовка («Площадь участка (га)», «СПП в ГНС
# (тыс.кв.м.)», «ДОО (мест)»…), а не по месту.
SOCIAL_SHEET_COLUMNS = (("площадь участка", "site_ha"), ("наземная площадь", "np_ths"),
                        ("спп", "spp_ths"), ("всего", "places"), ("доо", "kindergarten"),
                        ("школ", "school"), ("поликлин", "clinic"))


def social_buildings(data: bytes) -> list[dict[str, Any]] | None:
    """Типовые соцобъекты калькулятора. Нет листа — None, а не «объектов нет».

    Вид объекта — по столбцу мест его вида (ДОО / школа / поликлиника), а
    подпись — только если такого столбца нет: имя «Школьное здание…» — подсказка,
    столбец «Школа (мест)» — данные.
    """
    rows = _sheet_rows(data, "Социальные объекты")
    if not rows:
        return None
    header = [str(cell or "").strip().lower() for cell in rows[0]]
    columns: dict[str, int] = {}
    for prefix, key in SOCIAL_SHEET_COLUMNS:
        index = next((i for i, title in enumerate(header)
                      if title.startswith(prefix) and i not in columns.values()), None)
        if index is not None:
            columns[key] = index
    name_at = next((i for i, title in enumerate(header) if title.startswith("наименован")), 1)
    items = []
    for row in rows[1:]:
        if len(row) <= name_at or not row[name_at]:
            continue
        item: dict[str, Any] = {"name": str(row[name_at]).strip()}
        for key, index in columns.items():
            item[key] = ru_number(row[index]) if index < len(row) else None
        kind = next((k for k in ("kindergarten", "school", "clinic") if (item.get(k) or 0) > 0), "")
        if not kind and not any(k in columns for k in ("kindergarten", "school", "clinic")):
            low = item["name"].lower()
            kind = ("kindergarten" if low.startswith("дошкол") else "school" if low.startswith("школ")
                    else "clinic" if "поликлин" in low else "")
        item["kind"] = kind
        items.append(item)
    return items


def _name_key(text: Any) -> str:
    return " ".join(str(text or "").lower().replace("ё", "е").rstrip(":").split())


def tep_sections(data: bytes) -> dict[str, dict[str, Any]]:
    """Лист «ТЭП» по разделам: строка без номера — заголовок раздела, строки с
    номером под ним — его состав. Раздел ищется по НАЗВАНИЮ («расчет стоимости
    смены ври»), а не по номерам строк: номера калькулятор уже менял молча.
    """
    rows = _sheet_rows(data, "ТЭП") if data else []
    sections: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    for row in rows[1:]:
        if len(row) < 2 or not row[1]:
            continue
        code = str(row[0]).strip() if row[0] not in (None, "") else ""
        value = ru_number(row[3]) if len(row) > 3 else None
        if not code:
            current = {"name": str(row[1]).strip().rstrip(":"), "total": value, "items": []}
            sections[_name_key(row[1])] = current
            continue
        if current is not None:
            current["items"].append({"code": code, "name": str(row[1]).strip(), "value": value})
    return sections


def _section(sections: dict[str, dict[str, Any]], prefix: str) -> dict[str, Any]:
    for key, section in sections.items():
        if key.startswith(prefix):
            return section
    return {}


# Приобъектные места по ВРИ: строка листа «Машино-места» → вид сверки.
# Встроенные помещения МКД — наша «Коммерция 1 этажа».
BUILT_IN_VRI = "встроенно-пристроенные помещения"


def parking_vri_kind(vri_name: str) -> str:
    text = str(vri_name or "")
    if text.lower().startswith(BUILT_IN_VRI):
        return "parking_vri.built_in"
    match = re.search(r"\(([\d.]+)", text)
    return f"parking_vri.{match.group(1).replace('.', '_')}" if match else ""


def glavapu_side(normalized: dict[str, Any], rows: dict[str, float | None],
                 data: bytes | None) -> dict[str, Any]:
    """Числа калькулятора для сверки — по видам, с местом в его выгрузке."""
    n = normalized or {}

    def ths(key: str) -> float | None:
        value = n.get(key)
        return None if value is None else round(float(value) / 1000.0, 3)

    side: dict[str, Any] = {
        "spp": {
            "total": (ths("spp_total_sqm"), "строка 6"),
            "residential_living": (ths("residential_spp_sqm"), "строка 7.1"),
            "built_in": (ths("ground_commercial_spp_sqm"), "строка 7.2"),
            "nonres": (ths("standalone_nonres_spp_sqm"), "строка 8.1"),
            "social": (ths("social_spp_sqm"), "строка 8.2"),
        },
        "social": {
            "kindergarten": (n.get("required_kindergarten_places"), "строка 30"),
            "school": (n.get("required_school_places"), "строка 31"),
            "clinic": (n.get("required_clinic_capacity"), "строка 32"),
            "population": (n.get("population"), "строка 4"),
        },
        "parking": {
            "permanent": (n.get("parking_permanent"), "строка 42.1"),
            "guest": (n.get("parking_guest"), "строка 42.2"),
            "attached": (n.get("parking_attached"), "строка 42.3"),
            "short_stop": (n.get("parking_short_stop"), "строка 43"),
        },
        "vri_cost_mln": (n.get("change_vri_mln"), "«Расчёт стоимости смены ВРИ»"),
        "density": (n.get("density_spp_th_sqm_ha"), "строка 2"),
        "area_ha": (n.get("site_area_ha"), "строка 1"),
    }
    mpt = mpt_by_vri(data) if data else None
    side["mpt"] = ((mpt or {}).get("total"), "лист «МПТ»") if mpt else (None, "лист «МПТ»")
    side["mpt_items"] = (mpt or {}).get("items") or []
    side["parking_items"] = (parking_by_vri(data) or {}).get("items") if data else []
    side["rows"] = {code: value for code, value in (rows or {}).items()}
    labels: dict[str, str] = {}
    sections = tep_sections(data) if data else {}

    # Соцнагрузка деньгами: итог раздела и его строки (ДОО, школа, поликлиника).
    comp = _section(sections, "расчет компенсации за социальные объекты")
    side["social_comp"] = {"total": (comp.get("total"), "«Расчёт компенсации за социальные объекты»")}
    for item in comp.get("items") or []:
        name = _name_key(item["name"])
        kind = ("kindergarten" if name.startswith("доо") else "school" if name.startswith("школ")
                else "clinic" if name.startswith("поликлин") else "")
        if kind:
            side["social_comp"][kind] = (item["value"], f"строка {item['code']} «{item['name']}»")

    # Плата за ВРИ по видам и льготы — строки раздела как есть.
    # Льготы калькулятор считает сам (код его класса стоимости ВРИ): за МПТ —
    # нежилые ВРИ выше порога × коэффициент места (офисы и торговля вне ТТК
    # 0,7, внутри 0, соцобъекты 0,3); за передачу квартир городу — галочкой.
    # Обе срезают только плату за МКД. Итог раздела — уже ПОСЛЕ льгот.
    vri = _section(sections, "расчет стоимости смены ври")
    side["vri"], side["vri_relief"] = {}, {}
    gross: float | None = None
    relief_total: float | None = None
    for item in vri.get("items") or []:
        name = _name_key(item["name"])
        if name.startswith("льгота"):
            kind = "mpt" if "мпт" in name else "flats" if "передач" in name else ""
            if kind:
                side["vri_relief"][kind] = (item["value"], f"строка {item['code']}")
                relief_total = (relief_total or 0.0) + (item["value"] or 0.0)
            continue
        kind = item["code"].replace(".", "_")
        side["vri"][kind] = (item["value"], f"строка {item['code']}")
        labels[f"vri.{kind}"] = item["name"]
        if name.startswith("многоквартирн"):
            side["vri_mkd"] = (item["value"], f"строка {item['code']} «{item['name']}»")
        gross = (gross or 0.0) + (item["value"] or 0.0)
    if vri:
        side["vri_cost_mln"] = (None if gross is None else round(gross, 3),
                                "сумма строк по видам ВРИ — до льгот")
        side["vri_relief"]["total"] = (None if relief_total is None else round(relief_total, 3),
                                       "строки «Льгота…» раздела ВРИ")
        side["vri_net_mln"] = (vri.get("total"), "«Расчёт стоимости смены ВРИ» — к оплате после льгот")

    # Баланс территории — как калькулятор разложил её под наше соотношение.
    balance = _section(sections, "баланс территории")
    side["balance"] = {}
    for item in balance.get("items") or []:
        kind = item["code"].replace(".", "_")
        side["balance"][kind] = (item["value"], f"строка {item['code']}, га")
        labels[f"balance.{kind}"] = item["name"]

    # Машино-места по ВРИ — лист «Машино-места», ВСЕ виды по каждому ВРИ:
    # всего, приобъектные, постоянные, гостевые, кратковременные. Ноль
    # калькулятора — его ответ («этому ВРИ такого вида не положено»), а не
    # пропуск: он сохраняется, и пустая ячейка остаётся None.
    side["parking_vri"] = {}
    for item in side["parking_items"] or []:
        kind = parking_vri_kind(item.get("vri"))
        if not kind:
            continue
        code = kind.split(".", 1)[1]
        for column in PARKING_COLUMN_ORDER:
            if column not in item:
                continue
            side["parking_vri"][f"{code}.{column}"] = (
                item[column], f"лист «Машино-места», «{PARKING_COLUMN_TITLES[column]}»")
            labels[f"{kind}.{column}"] = f"{item['vri']}: {PARKING_COLUMN_TITLES[column].lower()}"

    # Соцобъекты, которые калькулятор поставил: разделы «ДОО:», «Школы:»,
    # «Поликлиники:» листа «ТЭП» (места, СПП, НП, участок) — по названиям.
    side["social_obj"] = {}
    for kind, prefix in SOCIAL_TEP_SECTIONS.items():
        section = _section(sections, prefix)
        for item in section.get("items") or []:
            field = _social_field(item["name"])
            if field:
                side["social_obj"][f"{kind}.{field}"] = (
                    item["value"], f"строка {item['code']} «{section['name']}: {item['name']}»")
    side["social_typical"] = social_buildings(data) if data else None

    # Расчёт объектов обслуживания — нормы калькулятора на население (33–41).
    service = _section(sections, "расчет объектов обслуживания")
    side["service"] = {}
    for item in service.get("items") or []:
        name = _name_key(item["name"])
        kind = next((key for key, needle in SERVICE_ROWS if name.startswith(needle)), "")
        if kind:
            side["service"][kind] = (item["value"], f"строка {item['code']} «{item['name']}»")
    need = [side["service"].get(k, (None, ""))[0] for k in SERVICE_COMMERCE]
    if side["service"] and all(v is not None for v in need):
        side["service"]["commerce_need"] = (
            round(sum(need), 3), "строки «Объекты торговли … городских служб (ННП)», сумма")

    # Элементы жилых территорий — справочно по строкам, озеленённые ЖК —
    # против нашей площади двора (покрывает ли она городскую норму).
    elements = _section(sections, "элементы жилых территорий")
    side["territory"] = {}
    for item in elements.get("items") or []:
        name = _name_key(item["name"])
        kind = "green_zhk" if name.startswith("озелененные территории жк") else item["code"].replace(".", "_")
        side["territory"][kind] = (item["value"], f"строка {item['code']}, га")
        if kind != "green_zhk":
            labels[f"territory.{kind}"] = item["name"]

    # Квартиры: всего (строка 5) и по размерам — по подписи строки, где бы
    # калькулятор их ни поставил.
    side["flats"] = {"total": (n.get("apartment_units"), "строка 5 «Количество квартир»")}
    for section in sections.values():
        for item in section.get("items") or []:
            size = flat_size_kind(item["name"], section["name"])
            if size:
                side["flats"][size] = (item["value"], f"строка {item['code']} «{item['name']}»")

    # Параметры территории — то, от чего калькулятор считает: К1/К2, зона и
    # нормативы соцобъектов, квартал, аренда, УПКС и базовые по типам.
    sheet = "лист «Параметры территории»"
    side["params"] = {
        "k1": (n.get("parking_k1_coefficient"), sheet + ", К1"),
        "k2": (n.get("parking_k2_coefficient"), f"{sheet}, {n.get('parking_k2_label') or 'К2'}"),
        "district": (n.get("district"), sheet + ", «Район»"),
        "zone": (n.get("calculation_zone"), sheet + ", «Расчётная зона»"),
        "kindergarten_norm": (n.get("kindergarten_norm_per_1000"), sheet + ", «Норматив ДОО»"),
        "school_norm": (n.get("school_norm_per_1000"), sheet + ", «Норматив школ»"),
        "quarter": (n.get("cadastral_quarter"), sheet + ", «Кадастровый квартал»"),
        "rent": (n.get("rent_coefficient"), sheet + ", «Коэффициент аренды»"),
        "mpt_coef": (n.get("mpt_coefficient"), sheet + ", «Коэффициент МПТ»"),
    }
    for use, value in (n.get("vri_upks_by_use") or {}).items():
        side["params"][f"upks_{use}"] = (value, f"{sheet}, УПКС, руб/м²")
    for use, value in (n.get("vri_base_costs_by_use") or {}).items():
        side["params"][f"base_{use}"] = (value, f"{sheet}, базовая стоимость")
    # Признак МПТ квартала — рядом с суммой льготы, как есть и с источником:
    # «не включён» при ненулевой льготе не ошибка (он меняет только
    # коэффициент места офисов и торговли), но читатель должен видеть оба.
    relief = side["vri_relief"].get("mpt")
    flag = side["params"]["mpt_coef"][0]
    if relief and flag not in (None, ""):
        side["vri_relief"]["mpt"] = (relief[0], f"{relief[1]}; {sheet}: «Коэффициент МПТ: {flag}»")
    side["labels"] = labels
    side["anomalies"] = anomalies(side)
    return side


PARKING_COLUMN_ORDER = ("total", "attached", "permanent", "guest", "short_stop")
PARKING_COLUMN_TITLES = {"total": "Всего", "attached": "Приобъектные", "permanent": "Постоянные",
                         "guest": "Гостевые", "short_stop": "Кратковременные"}

SOCIAL_TEP_SECTIONS = {"kindergarten": "доо", "school": "школ", "clinic": "поликлин"}
SOCIAL_FIELDS = (("количество мест", "places"), ("мощность", "places"), ("спп", "spp"),
                 ("наземная площадь", "np"), ("площадь земельного участка", "site"))


def _social_field(name: str) -> str:
    key = _name_key(name)
    return next((field for prefix, field in SOCIAL_FIELDS if key.startswith(prefix)), "")


SERVICE_ROWS = (("clinic_adult", "поликлиника взрослая"), ("clinic_child", "поликлиника детская"),
                ("sport_flat", "плоскостные спортивные"),
                ("sport_indoor", "крытые объекты спорта"),
                ("sport_indoor_500", "в радиусе пешеходной доступности до 500"),
                ("sport_indoor_1500", "в радиусе пешеходной доступности до 1500"),
                ("retail", "объекты торговли"), ("consumer", "объекты бытового"),
                ("catering", "объекты общественного питания"), ("culture", "объекты культуры"),
                ("city_services", "объекты для размещения городских служб"))
# Нежилая площадь обслуживания, которую в жилом квартале обычно несёт
# встроенная коммерция (строки 37–41 калькулятора).
SERVICE_COMMERCE = ("retail", "consumer", "catering", "culture", "city_services")


def flat_size_kind(name: str, section: str = "") -> str:
    """«до 70 м²» / «70–100 м²» / «более 100 м²» → small / medium / large.

    Только строки про квартиры (в подписи строки или её раздела): «до 500 м»
    крытого спорта сюда не попадает.
    """
    text = _name_key(name)
    if "квартир" not in text and "квартир" not in _name_key(section):
        return ""
    if re.search(r"(более|свыше|больше|>)\s*100", text):
        return "large"
    if re.search(r"70\s*[-–—]\s*100|от\s*70\s*до\s*100", text):
        return "medium"
    if re.search(r"(до|менее|<)\s*70", text):
        return "small"
    return ""


def _ru(value: float, digits: int = 0) -> str:
    """«23 253,958»: разряды пробелом, дробь запятой — пунктуацию не трогает."""
    text = f"{value:,.{digits}f}"
    return text.replace(",", " ").replace(".", ",")


def _value(side: dict[str, Any], group: str, kind: str) -> float | None:
    got = (side.get(group) or {}).get(kind)
    return got[0] if isinstance(got, (tuple, list)) and got else None


def anomalies(side: dict[str, Any]) -> list[dict[str, str]]:
    """Странности самой выгрузки калькулятора — показать, а не скрыть.

    Это не расхождение с нами: здесь калькулятор спорит сам с собой или
    делает то, что читатель книги поймёт неверно. Каждая — с местом.
    """
    found: list[dict[str, str]] = []
    labels = {"kindergarten": "ДОО", "school": "Школа", "clinic": "Поликлиника"}
    unit = {"kindergarten": "мест", "school": "мест", "clinic": "пос./см."}
    for kind, label in labels.items():
        placed = _value(side, "social_obj", f"{kind}.places")
        need = _value(side, "social", kind)
        comp = _value(side, "social_comp", kind)
        if placed and need is not None and placed > need:
            typical = next((item["name"] for item in side.get("social_typical") or []
                            if item.get("kind") == kind), "")
            found.append({
                "kind": f"social_surplus.{kind}",
                "text": (f"{label}: поставлено {_ru(placed)} {unit[kind]} при потребности "
                         f"{_ru(need)} — сверх потребности {_ru(placed - need)}"
                         + (f" ({typical})" if typical else "")
                         + (f"; компенсация по объекту {_ru(comp, 3)} млн ₽ — минус значит "
                            "профицит мест, он вычитается из дефицита других объектов"
                            if comp is not None and comp < 0 else "")),
                "where": "лист «ТЭП», разделы «" + label + "» и «Расчёт объектов обслуживания»"})
    total = _value(side, "social_comp", "total")
    parts = {k: _value(side, "social_comp", k) for k in labels}
    owed = {k: v for k, v in parts.items() if v is not None and v > 0}
    if total is not None and abs(total) < 1e-6 and owed:
        found.append({
            "kind": "social_comp_offset",
            "text": ("компенсация за соцобъекты итогом 0, хотя дефицит есть: "
                     + ", ".join(f"{labels[k]} +{_ru(v, 3)} млн ₽" for k, v in owed.items())
                     + ": калькулятор берёт итог как max(0, сумма по объектам), и профицит "
                       "одного объекта гасит дефицит другого"),
            "where": "лист «ТЭП», раздел «Расчёт компенсации за социальные объекты»"})
    # Льгота за МПТ больше платы за ВРИ под МКД — не странность: нежилья
    # (МФЦ, 4.1) бывает больше жилья, и 1874-ПП льготу размером платы не
    # ограничивает (владелец, 06.10.2026). Признак МПТ квартала показывается
    # рядом с суммой льготы, в её строке (`glavapu_side`), а не здесь.
    return found


# ------------------------------------------------------------------ сверка --

KIND_LABELS = {
    "spp.total": "СПП, всего",
    "spp.residential_living": "СПП жилая (квартиры, кладовые)",
    "spp.built_in": "СПП нежилой части жилых зданий",
    "spp.nonres": "СПП нежилых зданий",
    "spp.social": "СПП социальных объектов",
    "social.population": "Население",
    "social.kindergarten": "ДОО, требуется мест",
    "social.school": "СОШ, требуется мест",
    "social.clinic": "Поликлиника, пос./смену",
    "parking.permanent": "Машино-места постоянные",
    "parking.guest": "Машино-места гостевые",
    "parking.attached": "Машино-места приобъектные",
    "parking.short_stop": "Места кратковременной остановки",
    "social_comp.total": "Компенсация за соцобъекты, всего",
    "social_comp.kindergarten": "Компенсация: ДОО",
    "social_comp.school": "Компенсация: СОШ",
    "social_comp.clinic": "Компенсация: поликлиника",
    "flats.total": "Квартир, всего",
    "flats.small": "Квартиры до 70 м²",
    "flats.medium": "Квартиры 70–100 м²",
    "flats.large": "Квартиры более 100 м²",
    "social_obj.kindergarten.places": "ДОО: мест поставлено",
    "social_obj.kindergarten.spp": "ДОО: СПП, тыс. м²",
    "social_obj.kindergarten.np": "ДОО: наземная площадь, тыс. м²",
    "social_obj.kindergarten.site": "ДОО: участок, га",
    "social_obj.school.places": "Школа: мест поставлено",
    "social_obj.school.spp": "Школа: СПП, тыс. м²",
    "social_obj.school.np": "Школа: наземная площадь, тыс. м²",
    "social_obj.school.site": "Школа: участок, га",
    "social_obj.clinic.places": "Поликлиника: пос./смену поставлено",
    "social_obj.clinic.spp": "Поликлиника: СПП, тыс. м²",
    "social_obj.clinic.np": "Поликлиника: наземная площадь, тыс. м²",
    "social_obj.clinic.site": "Поликлиника: участок, га",
    "service.clinic_adult": "Поликлиника взрослая, пос./смену",
    "service.clinic_child": "Поликлиника детская, пос./смену",
    "service.sport_flat": "Плоскостные спортсооружения, га",
    "service.sport_indoor": "Крытый спорт (ННП), тыс. м²",
    "service.sport_indoor_500": "Крытый спорт до 500 м, тыс. м²",
    "service.sport_indoor_1500": "Крытый спорт до 1500 м, тыс. м²",
    "service.retail": "Торговля (ННП), тыс. м²",
    "service.consumer": "Бытовое обслуживание (ННП), тыс. м²",
    "service.catering": "Общепит (ННП), тыс. м²",
    "service.culture": "Культура и досуг (ННП), тыс. м²",
    "service.city_services": "Городские службы (ННП), тыс. м²",
    "service.commerce_need": "Обслуживание (торговля … городские службы) против встроенной коммерции, тыс. м²",
    "territory.green_zhk": "Озеленённые территории ЖК против нашего двора, га",
    "params.k1": "К1 — доступность рельсового каркаса",
    "params.k2": "К2 — деловая активность",
    "params.district": "Район",
    "params.zone": "Расчётная зона",
    "params.kindergarten_norm": "Норматив ДОО, мест / 1000 жит.",
    "params.school_norm": "Норматив школ, мест / 1000 жит.",
    "params.quarter": "Кадастровый квартал",
    "params.rent": "Коэффициент аренды",
    "params.mpt_coef": "Коэффициент МПТ",
    "params.upks_mkd": "УПКС: МКД, руб/м²",
    "params.base_mkd": "Базовая стоимость: МКД",
    "params.upks_office": "УПКС: офисы, руб/м²",
    "params.base_office": "Базовая стоимость: офисы",
    "params.upks_trade": "УПКС: торговля, руб/м²",
    "params.base_trade": "Базовая стоимость: торговля",
    "params.upks_garage": "УПКС: гаражи, руб/м²",
    "params.base_garage": "Базовая стоимость: гаражи",
    "params.upks_social": "УПКС: соцобъекты, руб/м²",
    "params.base_social": "Базовая стоимость: соцобъекты",
    "params.upks_hotel": "УПКС: временное проживание, руб/м²",
    "params.base_hotel": "Базовая стоимость: временное проживание",
    "params.upks_industry": "УПКС: производство, руб/м²",
    "params.base_industry": "Базовая стоимость: производство",
    "mpt": "МПТ, рабочих мест",
    "vri_cost_mln": "Стоимость смены ВРИ до льгот",
    "vri_relief.total": "Льгота по плате за ВРИ, всего",
    "vri_relief.mpt": "Льгота за создание МПТ",
    "vri_relief.flats": "Льгота за передачу квартир городу",
    "vri_net_mln": "Стоимость смены ВРИ к оплате",
    "density": "Плотность от СПП, тыс. м²/га",
}
# Группа сверки: заголовок и префиксы видов в ней (по порядку показа).
GROUPS = (("Параметры территории", ("params",)),
          ("СПП и ГНС по видам", ("spp",)),
          ("Квартиры", ("flats",)),
          ("Соцобъекты", ("social",)),
          ("Соцобъекты, которые поставил калькулятор", ("social_obj",)),
          ("Объекты обслуживания", ("service",)),
          ("Соцнагрузка, млн ₽", ("social_comp",)),
          ("Машино-места по видам", ("parking",)),
          ("Машино-места по ВРИ", ("parking_vri",)),
          ("МПТ", ("mpt",)),
          ("Стоимость смены ВРИ, млн ₽", ("vri_cost_mln", "vri_relief", "vri_net_mln", "vri")),
          ("Плотность", ("density",)),
          ("Баланс территории (как разложил калькулятор)", ("balance",)),
          ("Элементы жилых территорий", ("territory",)))
NESTED = ("params", "spp", "flats", "social", "social_obj", "service", "social_comp", "parking",
          "parking_vri", "vri", "vri_relief", "balance", "territory")

# Пояснение группы — строкой под её заголовком.
GROUP_NOTES = {
    "Машино-места по ВРИ": (
        "«Приобъектные» — места для посетителей и работников нежилого объекта "
        "(945-ПП), а не «уличные». Калькулятор считает ПОТРЕБНОСТЬ, а не "
        "размещение: где их поставить — подземный, надземный паркинг или открытая "
        "стоянка — решает проект. Постоянные и гостевые — места жителей МКД."),
    "Объекты обслуживания": (
        "Нормы калькулятора на население квартала. Своих норм на эти объекты в "
        "модели нет; встроенная коммерция и ФОК проверяются на то, покрывают ли "
        "они потребность."),
    "Соцнагрузка, млн ₽": (
        "Знак калькулятора: плюс — дефицит мест (недостающий объект, × 1,2 для ДОО "
        "и школы), минус — места сверх потребности. Итог раздела = max(0, сумма): "
        "профицит одного объекта гасит дефицит другого."),
}

# Допуск «совпало»: места — штучные, деньги и метры — доля.
TOLERANCE = {"spp": ("rel", 0.002), "social": ("abs", 1.0), "social_comp": ("rel", 0.005),
             "parking": ("abs", 1.0), "parking_vri": ("abs", 1.0), "mpt": ("abs", 1.0),
             "vri_cost_mln": ("rel", 0.005), "vri": ("rel", 0.005),
             "vri_relief": ("rel", 0.005), "vri_net_mln": ("rel", 0.005),
             "density": ("abs", 0.02), "balance": ("abs", 0.002),
             "params": ("rel", 0.0005), "flats": ("abs", 1.0), "social_obj": ("rel", 0.005),
             "service": ("rel", 0.005), "territory": ("abs", 0.002)}

# Виды, где наше число — не «то же самое», а запас: сверка спрашивает,
# ПОКРЫВАЕТ ли наше число потребность калькулятора (наше ≥ его).
AT_LEAST = ("service.commerce_need", "service.sport_indoor", "territory.green_zhk")

# Виды, у которых своей величины в модели нет ПО УСТРОЙСТВУ: плата за ВРИ в
# проекте одной суммой, компенсация — одной суммой, баланса территории нет.
# Число калькулятора здесь справочное, а не «расхождение» и не «нет нашей».
REFERENCE_PREFIXES = ("vri.", "vri_relief.mpt", "vri_relief.flats", "balance.",
                      "social_comp.kindergarten",
                      "social_comp.school", "social_comp.clinic",
                      "territory.", "params.mpt_coef", "social_obj.")
REFERENCE_REASON = {
    "vri.": "в проекте плата за ВРИ одной суммой — по видам показано, как посчитал калькулятор",
    "vri_relief.": "в проекте льгота одной суммой, без оснований — по основаниям показано, "
                   "как посчитал калькулятор. Льгота за МПТ может быть больше платы за МКД "
                   "(нежилья больше жилья) — 1874-ПП её платой не ограничивает. Признак МПТ "
                   "квартала меняет только коэффициент места офисов и торговли (0,8 при "
                   "признаке; без него вне ТТК 0,7, внутри 0); соцобъекты (0,3), спорт (0,8) "
                   "и производство дают льготу и без него",
    "balance.": "баланса территории в модели нет — калькулятор разложил её под наше "
                "соотношение жилых и нежилых зданий",
    "social_comp.": "в проекте компенсация одной суммой — по объектам показано, как посчитал "
                    "калькулятор (минус — объект строится сверх потребности)",
    "territory.": "своей величины в модели нет — показано, как посчитал калькулятор "
                  "(на жителя: озеленённые ЖК 5,0 м², из них насаждения 3,5; общего "
                  "пользования 0,7)",
    "params.mpt_coef": "признака МПТ квартала модель не ведёт — он меняет только "
                       "коэффициент места офисов и торговли в льготе за МПТ",
    "social_obj.": "соцобъекта этого вида в ТЭП проекта нет — калькулятор поставил свой",
}


# Почему своей величины нет — по виду, когда частной причины не дали.
MISSING_REASON = {
    "parking_vri.4_4.": ("ТЦ уходит в калькулятор как «Объекты торговли (4.2)» (карта "
                         "NONRES_VRI): строка 4.4 — магазины, такого продукта в модели нет"),
    "parking_vri.3_": ("машино-места соцобъектов (ДОО, школа, поликлиника) наша норма не "
                       "считает: своих приобъектных и мест остановки у них в модели нет"),
    "parking_vri.": ("этот вид мест по этому ВРИ модель не считает"),
    "service.": "своей нормы на этот вид обслуживания в модели нет",
    "params.upks_": ("в проекте нет принятой выгрузки ГлавАПУ по участку — УПКС квартала не "
                     "задан (плата за ВРИ проекта задаётся суммой)"),
    "params.base_": ("в проекте нет принятой выгрузки ГлавАПУ по участку — базовая стоимость "
                     "не задана (плата за ВРИ проекта задаётся суммой)"),
    "flats.": "состава квартир по размерам в модели нет",
}


def _flatten(side: dict[str, Any]) -> dict[str, tuple[Any, str]]:
    out: dict[str, tuple[Any, str]] = {}
    for group in NESTED:
        for kind, value in (side.get(group) or {}).items():
            out[f"{group}.{kind}"] = value
    for key in ("mpt", "vri_cost_mln", "vri_net_mln", "density"):
        if key in side:
            out[key] = side[key]
    return out


def _in_group(kind: str, prefixes: tuple[str, ...]) -> bool:
    return any(kind == p or kind.startswith(p + ".") for p in prefixes)


def _code_order(kind: str) -> tuple:
    """Порядок строк по коду ВРИ/строки, внутри кода — по виду мест."""
    tail = kind.split(".", 1)[1] if "." in kind else kind
    code, _, sub = tail.partition(".")
    rank = PARKING_COLUMN_ORDER.index(sub) if sub in PARKING_COLUMN_ORDER else len(PARKING_COLUMN_ORDER)
    return (tuple(int(x) if x.isdigit() else 10**6 for x in code.split("_")), code, rank, sub)


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return ru_number(value) if re.fullmatch(r"\s*-?[\d\s\xa0]+(?:[.,]\d+)?\s*", str(value or "")) else None


def _same_text(a: Any, b: Any) -> bool:
    norm = lambda v: " ".join(str(v).lower().replace("ё", "е").split())  # noqa: E731
    return norm(a) == norm(b)


def compare(ours: dict[str, Any], theirs: dict[str, Any],
            reasons: dict[str, str] | None = None,
            applied: dict[str, Any] | None = None) -> dict[str, Any]:
    """Строки сверки. `ours`/`theirs` — {вид: (значение, происхождение)}.

    Статусы: `match` — сошлось в допуске; `diff` — расходится, с причиной;
    `ours_missing` / `glavapu_missing` — одной стороны нет (и это не ноль);
    `not_applied` — калькулятор не принял параметр, от которого вид зависит,
    и его число сверять с нашим нельзя.
    """
    reasons = reasons or {}
    refused = [item for item in ((applied or {}).get("refused") or [])]
    refused_params = {str(item.get("param") or "") for item in refused}
    flat_ours, flat_theirs = _flatten(ours), _flatten(theirs)
    labels = dict(KIND_LABELS)
    labels.update((ours or {}).get("labels") or {})
    labels.update((theirs or {}).get("labels") or {})
    rows = []
    for title, prefixes in GROUPS:
        fixed = [k for k in KIND_LABELS if _in_group(k, prefixes)]
        extra = sorted((k for k in set(flat_ours) | set(flat_theirs)
                        if _in_group(k, prefixes) and k not in KIND_LABELS), key=_code_order)
        for kind in fixed + extra:
            mine, mine_origin = flat_ours.get(kind, (None, ""))
            them, them_origin = flat_theirs.get(kind, (None, ""))
            mode, tol = TOLERANCE[kind.split(".", 1)[0]]
            row = {"group": title, "kind": kind, "label": labels.get(kind, kind),
                   "ours": mine, "ours_origin": mine_origin,
                   "glavapu": them, "glavapu_origin": them_origin,
                   "delta": None, "status": "", "reason": ""}
            blocked = _blocked_by(kind, refused_params)
            if mine is None and them is None:
                continue
            them_num, mine_num = _as_number(them), _as_number(mine)
            if (mine is None and kind.startswith(REFERENCE_PREFIXES + ("parking_vri.",))
                    and them_num is not None and abs(them_num) < 1e-9):
                # Ноль калькулятора там, где своей величины у нас нет (ИЖС,
                # гаражи; приобъектные у МКД, постоянные у офиса) — шум: у
                # него этого вида нет, у нас тоже.
                continue
            if mine is None and them is not None and kind.startswith(REFERENCE_PREFIXES):
                why = reasons.get(kind) or next(v for k, v in REFERENCE_REASON.items()
                                                if kind.startswith(k))
                row.update(status="reference", reason=why)
            elif them is None:
                row.update(status="glavapu_missing",
                           reason=f"в выгрузке калькулятора нет величины ({them_origin or 'место не найдено'})")
            elif mine is None:
                row.update(status="ours_missing",
                           reason=reasons.get(kind) or next(
                               (v for k, v in MISSING_REASON.items() if kind.startswith(k)),
                               "в модели нет своей величины для сверки"))
            elif them_num is None or mine_num is None:
                # Текст (район, квартал, признак): совпало или нет, без разницы.
                if _same_text(mine, them):
                    row["status"] = "match"
                elif blocked:
                    row.update(status="not_applied",
                               reason="калькулятор не принял параметр сценария: " + blocked)
                else:
                    row.update(status="diff",
                               reason=reasons.get(kind) or "расхождение без известной причины — разбирать")
            else:
                delta = them_num - mine_num
                row["delta"] = round(delta, 3)
                limit = tol if mode == "abs" else max(abs(mine_num), abs(them_num)) * tol
                if kind in AT_LEAST:
                    # Запас, а не равенство: наше число покрывает потребность?
                    if mine_num + limit >= them_num:
                        row.update(status="covered", reason=reasons.get(kind, ""))
                    else:
                        row.update(status="short",
                                   reason=f"не хватает {_ru(them_num - mine_num, 3)}"
                                          + (f"; {reasons[kind]}" if reasons.get(kind) else ""))
                elif abs(delta) <= limit:
                    row["status"] = "match"
                elif blocked:
                    row.update(status="not_applied",
                               reason="калькулятор не принял параметр сценария: " + blocked)
                else:
                    row.update(status="diff",
                               reason=reasons.get(kind) or "расхождение без известной причины — разбирать")
            rows.append(row)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    shown = {row["group"] for row in rows}
    return {"rows": rows, "counts": counts,
            "notes": {title: note for title, note in GROUP_NOTES.items() if title in shown},
            # Странности самой выгрузки: старая запись кэша их не несла —
            # тогда они считаются заново из её же чисел.
            "anomalies": (theirs or {}).get("anomalies") if "anomalies" in (theirs or {})
            else anomalies(theirs or {})}


# Какие виды зависят от каких параметров сценария: непринятый параметр
# снимает доверие к виду, а не ко всей сверке.
_DEPENDS = {
    "social_comp.": ("spp", "vpp_pct", "spp_residential_ths", "composition", "social"),
    "parking_vri.": ("spp", "spp_residential_ths", "spp_nonres_ths", "nonres", "vpp_pct",
                     "composition", "social"),
    "vri.": ("spp", "spp_residential_ths", "spp_nonres_ths", "nonres", "land_right",
             "composition"),
    "vri_relief.": ("spp", "spp_nonres_ths", "nonres", "social", "composition"),
    "vri_net_mln": ("spp", "spp_residential_ths", "spp_nonres_ths", "nonres", "land_right",
                    "social", "composition"),
    "balance.": ("spp", "area_ha", "spp_residential_ths", "ratio", "composition"),
    "spp.": ("spp", "area_ha", "vpp_pct", "spp_residential_ths", "spp_nonres_ths",
             "nonres", "composition"),
    "social.": ("spp", "vpp_pct", "spp_residential_ths", "composition"),
    "parking.": ("spp", "vpp_pct", "spp_residential_ths", "spp_nonres_ths", "nonres",
                 "composition"),
    "mpt": ("spp_nonres_ths", "nonres", "vpp_pct", "composition"),
    "vri_cost_mln": ("spp", "spp_residential_ths", "spp_nonres_ths", "nonres", "land_right",
                     "composition"),
    "density": ("area_ha", "spp"),
    "flats.": ("spp", "spp_residential_ths", "vpp_pct", "composition"),
    "social_obj.": ("social", "composition"),
    "service.": ("spp", "vpp_pct", "spp_residential_ths", "spp_nonres_ths", "nonres",
                 "composition"),
    "territory.": ("spp", "vpp_pct", "spp_residential_ths", "composition"),
    "params.": (),
}


def _blocked_by(kind: str, refused: set[str]) -> str:
    for prefix, params in _DEPENDS.items():
        if kind == prefix or kind.startswith(prefix):
            hit = sorted(p for p in refused
                         if p in params or any(p.startswith(x + ".") for x in params))
            return ", ".join(hit)
    return ""

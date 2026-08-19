"""Импорт проекта из пресета: один файл вместо ручного ввода.

Пресет — это то, что собрано из ГПЗУ, ППТ, соглашений по ВРИ и МПТ и справок
по техприсоединению. Модель этих документов не знает: она знает продукты,
площади и деньги. Здесь и живёт перевод одного в другое.

Три правила, из которых всё остальное следует.

**Ничего не додумывать молча.** Пресет прямо просит `no_silent_inference`, и
это не формальность: коэффициент, применённый без ведома человека, выглядит
на экране точно так же, как цифра из документа. Поэтому каждое вычисленное
значение несёт своё происхождение (`derived`), а неизвестное остаётся `TBD` и
показывается, а не превращается в ноль.

**Не смешивать похожее.** Стадион регби — объект проекта Румянцево, его
техприсоединение проект оплачивает; СК им. Стрельцова (Торпедо) — чужой
объект, который строит продавец, и в периметре сделки его нет вовсе. Оба
называются «спортивный объект», и на этом сходство кончается.

**Считать деньги в рублях.** Модель живёт в миллионах, документы — в рублях
с копейками. Перевод делается один раз, на границе, а не в каждом месте.

Маппинг сверен с владельцем 14.08.2026 на проекте Румянцево.
"""

from __future__ import annotations

import math
import re
from typing import Any

SCHEMA_VERSIONS = {
    "developaid.project_preset.v1",
    "developaid.project_preset.v2",
    "developaid.project_preset.v3",
    # v4 добавляет то, без чего проект не считался: цены, себестоимость,
    # сроки и очереди. До неё пресет нёс только документы — планировку и
    # обязательства, — а экономику приходилось вводить руками, и «загрузить
    # проект одним файлом» кончалось на полпути.
    "developaid.project_preset.v4",
}

TBD = "TBD"

# Форма исполнения соцнагрузки, где обе формы разом. Имя должно совпадать с
# движком: расходится — режим молча не сработает.
SOCIAL_MODE_BOTH = "Строительство и компенсация"

# Коэффициенты перехода к продаваемой площади. Первые два — методика ГлавАПУ,
# та же, что в расчёте ТЭП по кадастровому номеру. Третий — решение владельца
# по Румянцеву: для башен 110 м усреднение 0,65 занижено.
SALEABLE_RATIO_APARTMENTS = 0.75
SALEABLE_RATIO_COMMERCIAL = 0.90
SALEABLE_RATIO_OFFICES = 0.678

# Паркинг: методика города с августа 2026 — одно постоянное место на 90 м²
# НП жилых зданий (НП — 90% ГНС), то есть на 100 м² жилой ГНС; гостевые —
# десятая часть. Сверено по двум выгрузкам штатного калькулятора ГлавАПУ от
# 16.08.2026; коэффициент рельсового каркаса К1 здесь принят 1,0 — пресет
# локационных коэффициентов не несёт.
PARKING_GNS_PER_SPACE = 100.0
PARKING_GUEST_SHARE = 0.10
UNDERGROUND_AREA_PER_SPACE = 35.0
ABOVE_AREA_PER_SPACE = 25.0
OFFICE_SQM_PER_SPACE = 100.0


class PresetError(ValueError):
    """Файл не пресет или пресет непригоден. Отличается от «поля не хватает»."""


def _number(value: Any) -> float | None:
    """Число или None. `TBD` — это «неизвестно», а не ноль."""
    if value is None or value == TBD:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mln(value: Any) -> float | None:
    rub = _number(value)
    return None if rub is None else rub / 1_000_000.0


class Field:
    """Значение вместе с его происхождением.

    Без происхождения на экране неразличимы площадь из ППТ и площадь,
    полученная умножением на коэффициент, — а решения по ним принимают разные.
    """

    __slots__ = ("value", "origin", "note", "input_key", "input_unit")

    def __init__(self, value: Any, origin: str, note: str = "") -> None:
        self.value = value
        self.origin = origin  # source | derived | assumption | tbd
        self.note = note
        # Незакрытое значение можно ввести прямо на экране проверки: документ
        # чаще есть, просто в файл его ещё не внесли, а править JSON руками
        # ради одного числа — способ его туда и не внести.
        self.input_key = ""
        self.input_unit = ""

    def as_dict(self) -> dict[str, Any]:
        return {"value": self.value, "origin": self.origin, "note": self.note,
                "input_key": self.input_key, "input_unit": self.input_unit}


def parse_preset(data: dict[str, Any]) -> dict[str, Any]:
    """Проверяет версию и целостность. Дальше работаем со словарём как есть."""
    if not isinstance(data, dict):
        raise PresetError("Файл не является объектом JSON")
    version = str(data.get("schema_version") or "")
    if version not in SCHEMA_VERSIONS:
        raise PresetError(
            f"Неизвестная версия пресета «{version or '—'}». "
            f"Поддерживаются: {', '.join(sorted(SCHEMA_VERSIONS))}")
    if not isinstance(data.get("planning"), dict):
        raise PresetError("В пресете нет раздела planning")
    return data


def _objects(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id") or ""): item
            for item in (data.get("planning", {}).get("objects") or [])
            if isinstance(item, dict)}


def _classification(item: dict[str, Any]) -> str:
    """Чем объект является для модели, а не как он называется."""
    return str(item.get("cost_classification") or "")


def map_tep(data: dict[str, Any]) -> tuple[dict[str, Any], list[Field]]:
    """Объекты пресета → продукты модели.

    Жилые корпуса дают квартиры и встроенную коммерцию, деловые — офисы,
    образовательный объект — школу и ДОО. Стадион, ЛОС и КНС продуктами не
    становятся: первый оплачивается деньгами, вторые входят в сети.
    """
    objects = _objects(data)
    residential_gns = commercial_gns = office_gns = 0.0
    garage_gns = 0.0
    school_places = preschool_places = 0.0
    education_gfa = 0.0
    notes: list[Field] = []

    for key, item in objects.items():
        if _classification(item) == "social_burden_cash":
            continue  # денежная нагрузка, не стройка проекта
        if item.get("in_deal_perimeter") is False:
            continue
        residential = _number(item.get("residential_part_m2"))
        embedded = _number(item.get("embedded_nonresidential_m2"))
        gfa = _number(item.get("gfa_m2")) or 0.0
        capacity = item.get("capacity") if isinstance(item.get("capacity"), dict) else None
        if residential is not None:
            residential_gns += residential
            commercial_gns += embedded or 0.0
        elif capacity:
            education_gfa += gfa
            school_places += _number(capacity.get("school_places")) or 0.0
            preschool_places += _number(capacity.get("preschool_places")) or 0.0
        elif key in {"LOS", "RP_KNS"}:
            notes.append(Field(gfa, "source",
                               f"{item.get('name')} — {gfa:,.0f} м² отнесены к наружным сетям"))
        elif "гараж" in str(item.get("name", "")).lower():
            garage_gns += gfa
        else:
            office_gns += gfa

    apartments = residential_gns * SALEABLE_RATIO_APARTMENTS
    commercial = commercial_gns * SALEABLE_RATIO_COMMERCIAL
    offices = office_gns * SALEABLE_RATIO_OFFICES
    # Потребность в машино-местах — у жилья и у офисов своя, и отдельно
    # стоящий гараж её закрывает: под землю уходит только остаток. Прежде
    # подземный паркинг считался от одних квартир, офисные места не
    # учитывались вовсе, а гараж стоял рядом продуктом и ничего не убавлял.
    permanent = math.ceil(residential_gns / PARKING_GNS_PER_SPACE)
    guest = math.ceil(permanent * PARKING_GUEST_SHARE)
    office_spaces = math.ceil(offices / OFFICE_SQM_PER_SPACE) if offices else 0
    above = math.ceil(garage_gns / ABOVE_AREA_PER_SPACE) if garage_gns else 0
    underground = max(0, permanent + guest + office_spaces - above)

    tep = {
        "apartments": {"gns": residential_gns, "saleable": apartments,
                       "total_area": residential_gns * 0.9, "useful": apartments},
        "ground_commercial": {"gns": commercial_gns, "saleable": commercial,
                              "total_area": commercial_gns, "useful": commercial},
        "offices": {"gns": office_gns, "saleable": offices,
                    "total_area": office_gns, "useful": offices},
        "underground_parking": {"gns": underground * UNDERGROUND_AREA_PER_SPACE,
                                "units": underground, "saleable": 0.0},
        "above_parking": {"gns": garage_gns, "units": above, "saleable": 0.0},
        "school": {"units": school_places,
                   "total_area": education_gfa * school_places / max(1.0, school_places + preschool_places)},
        "kindergarten": {"units": preschool_places,
                         "total_area": education_gfa * preschool_places / max(1.0, school_places + preschool_places)},
    }

    notes.extend([
        Field(apartments, "derived",
              f"квартиры — {residential_gns:,.0f} м² жилой части × {SALEABLE_RATIO_APARTMENTS}"),
        Field(commercial, "derived",
              f"встроенная коммерция — {commercial_gns:,.0f} м² × {SALEABLE_RATIO_COMMERCIAL}"),
        Field(offices, "derived",
              f"офисы — {office_gns:,.0f} м² × {SALEABLE_RATIO_OFFICES} (полезная по соглашению МПТ)"),
        Field(underground, "derived",
              f"подземный паркинг — потребность {permanent + guest + office_spaces} мест "
              f"({permanent} постоянных + {guest} гостевых жилья"
              + (f" + {office_spaces} офисных" if office_spaces else "")
              + (f") минус гараж {above}" if above else ")")
              + f" = {underground}, {underground * UNDERGROUND_AREA_PER_SPACE:,.0f} м²"),
    ])
    if above:
        notes.append(Field(above, "derived",
                           f"наземный гараж — {garage_gns:,.0f} м² ÷ {ABOVE_AREA_PER_SPACE:.0f} м²/место, "
                           "закрывает часть потребности"))
    return tep, notes


def map_inputs(data: dict[str, Any], tep: dict[str, Any]) -> tuple[dict[str, Any], list[Field]]:
    """Деньги и режимы: ВРИ, соцнагрузка, сети.

    Плата за ВРИ приходит посчитанной — с учётом льготы МПТ и уже сделанного
    платежа. Свой расчёт движка здесь выключается: пересчитав по методике, он
    получил бы другое число и молча заменил бы им документ.
    """
    notes: list[Field] = []
    inputs: dict[str, Any] = {}

    vri = data.get("vri") if isinstance(data.get("vri"), dict) else {}
    remaining = _mln(vri.get("remaining_cash_out_after_confirmed_payment_rub"))
    if remaining is None:
        remaining = _mln(vri.get("residual_principal_rub"))
    if remaining is not None:
        inputs["land_rights_cost_mln"] = remaining
        inputs["vri_required"] = False  # сумма задана, свой расчёт не нужен
        paid = _mln((vri.get("confirmed_payments") or [{}])[0].get("amount_rub")) if vri.get("confirmed_payments") else None
        notes.append(Field(remaining, "source",
                           "плата за ВРИ — остаток к оплате по соглашению"
                           + (f", уже уплачено {paid:,.1f} млн ₽" if paid else "")))

    cash_burden = 0.0
    for item in _objects(data).values():
        if _classification(item) != "social_burden_cash":
            continue
        amount = _mln(item.get("social_burden_cash_rub"))
        if amount is None:
            # Незакрытое поле дожидается числа на экране проверки, а не в
            # тексте файла: документ обычно есть, просто его ещё не внесли.
            field = Field(TBD, "tbd",
                          f"{item.get('name')} — денежная соцнагрузка не задана в пресете")
            field.note += ". Введите сумму, если обязательство известно"
            notes.append(field)
            notes[-1].input_key = "social_compensation_mln"
            notes[-1].input_unit = "млн ₽"
        else:
            cash_burden += amount
    if cash_burden:
        # Проект может и строить, и платить: школа с садиком строятся, а за
        # спортивный объект платят деньгами. Режим «Денежная компенсация» тут
        # отменил бы стройку целиком — расход добавился бы, а прибыль выросла.
        builds = any(float(tep.get(key, {}).get("units") or 0) > 0
                     for key in ("school", "kindergarten", "clinic"))
        inputs["social_mode"] = SOCIAL_MODE_BOTH if builds else "Денежная компенсация"
        inputs["social_compensation_mln"] = cash_burden
        notes.append(Field(cash_burden, "source",
                           "денежная социальная нагрузка"
                           + (" — вместе со стройкой соцобъектов" if builds else "")))
    due = str((data.get("social_infrastructure") or {}).get("rugby_stadium", {}).get("due_date")
              or "").strip() if isinstance(data.get("social_infrastructure"), dict) else ""
    if due:
        inputs["social_comp_date"] = due
        notes.append(Field(due, "source", f"срок денежной соцнагрузки — {due}"))

    tp = data.get("tp") if isinstance(data.get("tp"), dict) else {}
    tp_rub = _number(tp.get("planned_payments_project_perimeter_rub"))
    if tp_rub is None:
        tp_rub = _number(tp.get("planned_payments_rub"))
    if tp_rub is not None:
        gns = sum(float(row.get("gns") or 0.0) for row in tep.values())
        if gns > 0:
            inputs["utilities_th_per_sqm"] = tp_rub / gns / 1000.0
            notes.append(Field(tp_rub / 1_000_000.0, "source",
                               f"техприсоединение — {tp_rub / 1e6:,.1f} млн ₽ по договорам "
                               f"вместо удельной ставки ({tp_rub / gns / 1000:.3f} тыс ₽/м² ГНС)"))
        excluded = _number(tp.get("excluded_rugby_tp_rub"))
        if excluded:
            notes.append(Field(excluded / 1_000_000.0, "source",
                               f"из потребности исключено {excluded / 1e6:,.1f} млн ₽ — "
                               "техприсоединение объекта, который проект не строит"))

    if tep.get("offices", {}).get("gns"):
        inputs["offices_enabled"] = True
        inputs["offices_gba_sqm"] = tep["offices"]["gns"]
        inputs["offices_saleable_sqm"] = tep["offices"]["saleable"]
    if tep.get("above_parking", {}).get("units"):
        inputs["above_parking_enabled"] = True
        inputs["above_parking_spaces"] = tep["above_parking"]["units"]
        inputs["above_parking_area_per_space_sqm"] = ABOVE_AREA_PER_SPACE
    underground = tep.get("underground_parking", {})
    if underground.get("units"):
        inputs["underground_manual_spaces"] = underground["units"]
        inputs["underground_manual_gns_sqm"] = underground["gns"]
    inputs["school_places"] = tep.get("school", {}).get("units", 0.0)
    inputs["kindergarten_places"] = tep.get("kindergarten", {}).get("units", 0.0)
    inputs["social_school_gba_sqm"] = tep.get("school", {}).get("total_area", 0.0)
    inputs["social_dou_gba_sqm"] = tep.get("kindergarten", {}).get("total_area", 0.0)
    return inputs, notes


def reference_blocks(data: dict[str, Any]) -> list[dict[str, Any]]:
    """То, что в расчёт не идёт, но должно быть видно.

    Внешний объект МПТ даёт проекту льготу по ВРИ и ни рубля CAPEX. Убрать его
    совсем нельзя: льгота в три с половиной миллиарда объясняется именно им.
    """
    blocks: list[dict[str, Any]] = []
    torpedo = ((data.get("mpt") or {}).get("torpedo") or {}) if isinstance(data.get("mpt"), dict) else {}
    if torpedo:
        blocks.append({
            "title": str(torpedo.get("name") or "Внешний объект МПТ"),
            "capex_in_project": 0.0,
            "rows": [
                ("Строит и финансирует", str(torpedo.get("built_and_funded_by") or "—")),
                ("Что даёт проекту", str(torpedo.get("benefit_to_project") or "—")),
                ("Предельная льгота по ВРИ, млн ₽", _mln(torpedo.get("max_vri_benefit_rub"))),
                ("Минимальная площадь, м²", _number(torpedo.get("minimum_area_m2"))),
            ],
        })
    for item in _objects(data).values():
        if _classification(item) != "social_burden_cash":
            continue
        blocks.append({
            "title": str(item.get("name") or "Денежная социальная нагрузка"),
            "capex_in_project": 0.0,
            "rows": [
                ("Площадь по ППТ, м² (справочно)", _number(item.get("gfa_m2"))),
                ("Денежное обязательство, млн ₽", _mln(item.get("social_burden_cash_rub")) or TBD),
                ("Строительство в CAPEX проекта", "нет"),
            ],
        })
    return blocks


def open_items(data: dict[str, Any]) -> list[str]:
    """Всё, что пресет сам объявил незакрытым, плюс наши TBD."""
    items: list[str] = []
    # Верхнеуровневые — то, что автор пресета знает про проект целиком: чего
    # не хватает, что не подтверждено документом, что посчитано на глазок.
    items.extend(str(x) for x in (data.get("open_items") or []))
    tp = data.get("tp") if isinstance(data.get("tp"), dict) else {}
    items.extend(str(x) for x in (tp.get("open_items") or []))
    settings = data.get("construction_cost_settings")
    if isinstance(settings, dict):
        items.extend(str(x) for x in (settings.get("open_items") or []))
    for item in _objects(data).values():
        for requirement in (item.get("cost_settings", {}) or {}).get("special_requirements", []) or []:
            if _number(requirement.get("incremental_capex_rub")) is None:
                items.append(
                    f"{item.get('name')}: {requirement.get('type')} на "
                    f"{requirement.get('capacity_people')} чел. — стоимость не определена")
        if (item.get("cost_settings", {}) or {}).get("underground_gba_m2") == TBD:
            items.append(f"{item.get('name')}: подземная площадь не определена")
    return items


def cost_multipliers(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Множители себестоимости по объектам — предпосылки, а не данные.

    Глобальные умолчания сервиса они не меняют: пресет прямо это запрещает, и
    правильно — иначе один проект переписал бы ставки всем остальным.
    """
    out: list[dict[str, Any]] = []
    for item in _objects(data).values():
        settings = item.get("cost_settings") if isinstance(item.get("cost_settings"), dict) else None
        if not settings:
            continue
        multiplier = _number(settings.get("hard_cost_multiplier"))
        if multiplier is None:
            continue
        out.append({
            "object": str(item.get("name") or item.get("id")),
            "multiplier": multiplier,
            "status": str(settings.get("multiplier_status") or "assumption"),
            "applies_to": "строительная себестоимость",
        })
    return out


def map_economics(data: dict[str, Any]) -> tuple[dict[str, Any], list[Field]]:
    """Цены, себестоимость и сроки — то, чего в документах нет.

    ППТ и соглашения говорят про площади и обязательства; сколько метр стоит
    и за сколько продаётся — предпосылки аналитика. Поэтому они приходят
    отдельным разделом и помечаются иначе: не «из документа», а «предпосылка»,
    и каждая несёт, откуда взялась.
    """
    economics = data.get("economics")
    if not isinstance(economics, dict):
        return {}, []
    inputs: dict[str, Any] = {}
    notes: list[Field] = []
    known = {
        "apartment_price_th": "цена квартир",
        "commercial_price_th": "цена коммерции 1 этажа",
        "parking_price_th": "цена машино-места",
        "storage_price_th": "цена кладовой",
        "offices_price_th_per_sqm": "цена офисов",
        "above_parking_price_mln_per_space": "цена места в гараже",
        "main_above_th_per_sqm": "СМР наземной части",
        "main_under_th_per_sqm": "СМР подземной части",
        "offices_cost_th_per_sqm": "себестоимость офисов",
        "ird_months": "срок ИРД",
        "construction_months": "срок строительства",
        "share_before_rve_pct": "доля продаж до РВЭ",
        "project_start": "начало проекта",
        "social_comp_date": "дата денежной соцнагрузки",
    }
    for key, label in known.items():
        raw = economics.get(key)
        if raw is None or raw == TBD:
            if key in economics:
                notes.append(Field(TBD, "tbd", f"{label} — не задана в пресете"))
            continue
        value = raw if key in ("project_start", "social_comp_date") else _number(raw)
        if value is None:
            continue
        inputs[key] = value
        origin = str((economics.get("origins") or {}).get(key) or "assumption")
        notes.append(Field(value, origin if origin in ("source", "assumption") else "assumption",
                           f"{label} — {value}"
                           + (" (предпосылка, не из документа)" if origin != "source" else "")))
    return inputs, notes


CADASTRAL_RE = re.compile(r"(?<!\d)(\d{2}:\d{2}:\d{6,8}:\d+)(?!\d)")


def cadastral_numbers(preset: dict[str, Any]) -> list[str]:
    """Кадастровые номера проекта — списком, без домысливания диапазона.

    Запись «77:17:0110504:18151–18171» — сокращение человека, а не номер:
    НСПД знает номера, а не тире между ними, и раскрывать диапазон самим
    значит выдумать двадцать участков, которых, может быть, уже нет. Берём
    только то, что перечислено явно: сначала список, потом строка через
    запятую. Пресет несёт их и в `project`, и в `land` — читаем оба, порядок
    сохраняем, повторы убираем.
    """
    found: list[str] = []
    seen: set[str] = set()
    sources: list[Any] = []
    for section in ("project", "land"):
        block = preset.get(section)
        if not isinstance(block, dict):
            continue
        sources.extend([
            block.get("cadastral_numbers"),
            block.get("cadastral_numbers_input"),
            block.get("cadastral_numbers_csv"),
        ])
    for source in sources:
        if isinstance(source, list):
            text = " ".join(str(item) for item in source)
        elif isinstance(source, str):
            text = source
        else:
            continue
        for number in CADASTRAL_RE.findall(text):
            if number not in seen:
                seen.add(number)
                found.append(number)
    return found


def map_phasing(data: dict[str, Any]) -> tuple[dict[str, Any], list[Field]]:
    """Очереди: сколько, чем и с каким шагом.

    Очередь — не удобство финансирования, а ёмкость спроса: 166 500 м² квартир
    одной очередью требуют 65 продаж в месяц три с половиной года подряд, и
    столько рынок не берёт.
    """
    phasing = data.get("phasing")
    if not isinstance(phasing, dict) or not phasing.get("enabled"):
        return {}, []
    phases = [item for item in (phasing.get("phases") or []) if isinstance(item, dict)]
    if len(phases) < 2:
        return {}, []
    gap = int(_number(phasing.get("phase_gap_months")) or 12)
    out = {
        "enabled": True, "mode": "phased", "user_enabled": True,
        "phase_count": min(4, len(phases)), "phase_gap_months": gap,
        "phases": [{
            "name": str(item.get("name") or f"О{index + 1}"),
            "start_offset_months": int(_number(item.get("start_offset_months"))
                                       or index * gap),
            "construction_months": int(_number(item.get("construction_months")) or 24),
        } for index, item in enumerate(phases[:4])],
    }
    shared = phasing.get("shared_cash")
    if isinstance(shared, dict):
        out["shared_cash"] = shared
    notes = [Field(len(out["phases"]), "assumption",
                   "очереди: " + ", ".join(
                       f"{item['name']} через {item['start_offset_months']} мес., "
                       f"стройка {item['construction_months']} мес."
                       for item in out["phases"]))]
    return out, notes


def build_preview(data: dict[str, Any]) -> dict[str, Any]:
    """Что получится, если применить. Ничего не меняет."""
    preset = parse_preset(data)
    tep, tep_notes = map_tep(preset)
    inputs, input_notes = map_inputs(preset, tep)
    economics, economics_notes = map_economics(preset)
    # Предпосылки поверх документов, а не вместо: цена метра документом не
    # задаётся, но и площадь из ППТ ею не перебивается.
    inputs.update(economics)
    phasing, phasing_notes = map_phasing(preset)
    project = preset.get("project") if isinstance(preset.get("project"), dict) else {}
    cadastres = cadastral_numbers(preset)
    return {
        "schema_version": preset.get("schema_version"),
        "project_name": str(project.get("name") or ""),
        "region": str(project.get("region") or ""),
        "address": str(project.get("address") or ""),
        # Участок — часть проекта: без номеров пресет поднимает экономику, а
        # карточка участка и градостроительные ограничения остаются пустыми,
        # хотя номера в файле есть.
        "cadastral_numbers": cadastres,
        "tep": tep,
        "inputs": inputs,
        "phasing": phasing,
        "notes": [field.as_dict() for field in
                  (*tep_notes, *input_notes, *economics_notes, *phasing_notes)],
        "reference": reference_blocks(preset),
        "open_items": open_items(preset),
        "multipliers": cost_multipliers(preset),
        "controls": preset.get("validation_controls") or {},
    }

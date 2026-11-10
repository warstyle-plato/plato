"""Editable v4 land-lease accrual, separate from the one-off VRI payment.

The workbook repeats the explicit annual-rate convention of
``developaid_land_rent.build``. It does not infer a contract date, a statutory
rate or a payment deadline. Existing workbook parts/charts stay byte-identical
apart from the named CAPEX/VAT formulas, styles and the added worksheet.
"""
from __future__ import annotations

import datetime as dt
import io
import math
import re
import zipfile
from typing import Any
from xml.etree import ElementTree as ET

import project_regions
import project_types

SHEET = "Аренда ЗУ"
BLOCK_TITLE = "ВРИ и земельные отношения"
SHEET_PATH = "xl/worksheets/sheetLandRent.xml"
REL_ID = "RidLandRent0001"
SHEET_ID = 904
FIRST_YEAR_ROW = 22
YEARS = 100
MONTHS = 180
CAPEX_ROWS = (145, 146, 147, 148)
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
ET.register_namespace("x", NS)
ET.register_namespace("r", RNS)

MODES = {"unspecified": "Не задано", "not_applicable": "Не применяется",
         "manual": "Ручные ставки"}
TAILS = {"unknown": "Не задана", "repeat_last": "Повтор последней ставки"}
PREMIUMS = {"unknown":"Не подтверждена", "in_vri":"Учтена в ВРИ",
            "separate_required":"Нужен отдельный расчёт", "not_applicable":"Не применяется по основанию"}
RELATIONS = {"regular_only": "Первый год отдельно от ВРИ",
             "full_year_in_vri": "Первый год полностью включён в ВРИ"}


def _tag(name: str) -> str:
    return f"{{{NS}}}{name}"


def _xml(root: ET.Element, original: bytes | None = None) -> bytes:
    """Keep declarations used by mc:Ignorable and other QName-valued attrs."""
    text = ET.tostring(root, encoding="unicode")
    if original:
        match = re.search(r"<(?!\?)[^>]+>", original.decode("utf-8"))
        if match:
            for name, uri in re.findall(r'\s(xmlns(?::[\w]+)?)="([^"]+)"', match.group()):
                if not re.search(r"\s" + re.escape(name) + r"=", text.split(">", 1)[0]):
                    text = text.replace(">", f' {name}="{uri}">', 1)
    return ('<?xml version="1.0" encoding="utf-8"?>' + text).encode("utf-8")


def _col(n: int) -> str:
    result = ""
    while n:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def _append_xml(content: bytes, parent: str, child: str) -> bytes:
    """Retain existing namespace spelling used by the book's XML readers."""
    text = content.decode("utf-8")
    match = re.search(r"</(?P<prefix>(?:\w+:)?)" + parent + r">", text)
    if not match:
        raise ValueError(f"Аренда ЗУ: XML-узел {parent} не распознан")
    element = child.replace("<PREFIX", "<" + match.group("prefix"))
    return (text[:match.start()] + element + text[match.start():]).encode("utf-8")


def _serial(value: Any) -> float | None:
    try:
        day = value.date() if isinstance(value, dt.datetime) else value
        if not isinstance(day, dt.date):
            day = dt.date.fromisoformat(str(day))
        return float((day - dt.date(1899, 12, 30)).days)
    except (ValueError, TypeError):
        return None


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(",", "."))
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _cell(row: ET.Element, coord: str, value: Any = None, *,
          formula: str | None = None, style: int = 0) -> ET.Element:
    cell = ET.SubElement(row, _tag("c"), {"r": coord, "s": str(style)})
    if formula is not None:
        ET.SubElement(cell, _tag("f")).text = formula.lstrip("=")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        ET.SubElement(cell, _tag("v")).text = repr(float(value))
    elif value is not None:
        cell.set("t", "inlineStr")
        ET.SubElement(ET.SubElement(cell, _tag("is")), _tag("t")).text = str(value)
    return cell


def _styles(content: bytes) -> tuple[bytes, dict[str, int]]:
    root = ET.fromstring(content)
    fills, xfs = root.find(_tag("fills")), root.find(_tag("cellXfs"))
    if fills is None or xfs is None:
        raise ValueError("Аренда ЗУ: каталог стилей книги не распознан")
    fill_id = len(fills)
    fill = ET.SubElement(fills, _tag("fill"))
    pattern = ET.SubElement(fill, _tag("patternFill"), {"patternType": "solid"})
    ET.SubElement(pattern, _tag("fgColor"), {"rgb": "FFFFF2CC"})
    ET.SubElement(pattern, _tag("bgColor"), {"indexed": "64"})
    fills.set("count", str(len(fills)))
    styles = {}
    for name, fmt, editable in (("amount", 2, False), ("date", 14, False),
                                ("input", 2, True), ("input_date", 14, True),
                                ("input_text", 0, True)):
        styles[name] = len(xfs)
        ET.SubElement(xfs, _tag("xf"), {"numFmtId": str(fmt), "fontId": "0",
                      "fillId": str(fill_id if editable else 0), "borderId": "0",
                      "xfId": "0", "applyNumberFormat": "1", "applyFill": "1"})
    xfs.set("count", str(len(xfs)))
    return _xml(root, content), styles


def build_sheet(inputs: dict[str, Any], result: dict[str, Any], styles: dict[str, int], *,
                project_start_formula: str, rve_formula: str,
                project_end_formula: str | None = None, months: int = MONTHS,
                month_formulas: list[str] | None = None,
                hostvri_amount_formula: str | None = None,
                phase_rve_formulas: list[str] | None = None,
                layout: dict[str, Any] | None = None) -> bytes:
    """Editable Actual/Actual accrual and separately reconciled payment dates.

    Unknown portions never become zero-rate assumptions. The finite grid has
    the same 100-year boundary as the canonical calculator. Rates are entered
    in percentage points (3 means 3%); all amounts are million RUB.

    The leased base is one function of the day: each queue's share of the
    parcel stays on the lease until its commissioning, and from the VRI change
    date the base is the cadastral value after the change. A cell takes the
    difference of its cumulative "base × days" (``G``) between the ends of its
    interval — the same integral as ``developaid_land_rent.build``.
    ``layout`` receives the rows of the per-queue payments.
    """
    if not isinstance(months, int) or isinstance(months, bool) or not 1 <= months <= 600:
        raise ValueError("Аренда ЗУ: число месяцев должно быть от 1 до 600")
    if month_formulas is not None and len(month_formulas) != months:
        raise ValueError("Аренда ЗУ: календарь не соответствует числу месяцев")
    last_col, last_matrix_col = _col(3+months), _col(9+months)
    history = result.get("historical") or {}
    history_mode = history.get("mode") if isinstance(history, dict) else None
    if history_mode not in (None, "classified", "legacy_combined"):
        raise ValueError("Аренда ЗУ: исторический импорт не поддержан; требуется сверка исходных статей")
    if history_mode and _serial(history.get("cut")) is None:
        raise ValueError("Аренда ЗУ: не задан срез исторического импорта")
    observed = {}
    if history_mode == "classified":
        if not isinstance(history.get("monthly"), dict):
            raise ValueError("Аренда ЗУ: фактические месяцы не распознаны")
        for month, amount in history["monthly"].items():
            serial, value = _serial(month), _numeric(amount)
            if serial is None or value is None:
                raise ValueError("Аренда ЗУ: строка факта без даты или числовой суммы")
            if dt.date.fromisoformat(str(month)).day != 1 or serial >= _serial(history["cut"]):
                raise ValueError("Аренда ЗУ: фактический месяц не соответствует срезу импорта")
            observed[str(month)] = value
        if observed:
            start = dt.date.fromisoformat(str(result["project_start"])).replace(day=1)
            earliest = min(dt.date.fromisoformat(month) for month in observed)
            if earliest < start:
                raise ValueError("Аренда ЗУ: факт до начала календаря книги пока не поддержан; нужен календарь cash_start")
            month_index = start.year*12 + start.month-1 + months
            calendar_end = dt.date(month_index//12,month_index%12+1,1)
            if max(dt.date.fromisoformat(month) for month in observed) >= calendar_end:
                raise ValueError("Аренда ЗУ: факт выходит за конец календаря книги; нужна более длинная сетка")
            if str(history.get("covered_from")) != min(observed) or str(history.get("covered_to")) != max(observed):
                raise ValueError("Аренда ЗУ: диапазон покрытия факта не совпадает с исходными месяцами")
    phase_land = result.get("phase_land") or []
    phased = len(phase_land) > 1
    if phased and (phase_rve_formulas is None or len(phase_rve_formulas) != len(phase_land)):
        raise ValueError("Аренда ЗУ: в книгу не переданы даты ввода всех очередей")
    root = ET.Element(_tag("worksheet"))
    views = ET.SubElement(root, _tag("sheetViews"))
    view = ET.SubElement(views, _tag("sheetView"), {"workbookViewId": "0"})
    ET.SubElement(view, _tag("pane"), {"xSplit": "9", "ySplit": "21",
                  "topLeftCell": "J22", "activePane": "bottomRight", "state": "frozen"})
    cols = ET.SubElement(root, _tag("cols"))
    for first, last, width in ((1, 1, 42), (2, 2, 24), (3, 9, 19), (10, 9+months, 15)):
        ET.SubElement(cols, _tag("col"), {"min": str(first), "max": str(last),
                      "width": str(width), "customWidth": "1"})
    data = ET.SubElement(root, _tag("sheetData"))
    rows: dict[int, ET.Element] = {}

    def put(n: int, coord: str, value: Any = None, **kw: Any) -> None:
        if n not in rows:
            rows[n] = ET.SubElement(data, _tag("row"), {"r": str(n)})
        if any(c.get("r") == coord for c in rows[n]):
            raise ValueError(f"Аренда ЗУ: адрес {coord} задан дважды")
        _cell(rows[n], coord, value, **kw)

    mode = str(inputs.get("land_rent_mode") or "unspecified")
    preset = None
    if mode not in MODES:
        from developaid_land_rent import PRESETS
        preset = PRESETS.get(mode)
    displayed_mode = MODES.get(mode, preset["label"] if preset else "Неподтверждённый режим")
    if result.get("status") == "not_applicable":
        displayed_mode = MODES["not_applicable"]
    if inputs.get("land_right", "ownership") == "ownership":
        displayed_mode = MODES["not_applicable"]
    base_kind = str(inputs.get("land_rent_base_kind") or "cadastral_percent")
    base_key = "land_rent_cadastral_mln" if base_kind == "cadastral_percent" else "land_rent_annual_base_mln"
    settings = ((8, "Режим расчёта", displayed_mode, "input_text"),
                (9, "База начисления, млн ₽", _numeric(inputs.get(base_key)), "input"),
                (10, "Начало аренды по договору", _serial(result.get("regime_start") or inputs.get("land_rent_regime_start")), "input_date"),
                (11, "После последнего заданного года", "Повтор последней ставки" if preset else TAILS.get(str(inputs.get("land_rent_tail_rule") or "unknown"), "Не задана"), "input_text"),
                (12, "Первый год и ВРИ", RELATIONS.get(str(inputs.get("land_rent_first_year_relation") or "regular_only"), "Не задано"), "input_text"))
    for n, label, value, style in settings:
        put(n, f"A{n}", label)
        put(n, f"B{n}", value, style=styles[style])
    source = result.get("source") or "Ставки и дата — по документам проекта"
    if isinstance(source, dict):
        source = source.get("label") or source.get("text") or str(source)
    put(1, "A1", BLOCK_TITLE)
    put(2, "A2", "Аренда земли: годовой расчёт и план оплаты — отдельно от платы за ВРИ. Жёлтые ячейки редактируются. Начисление — расчётная конвенция; сроки оплаты — по договору. После ввода аренда не считается прекращённой.")
    for n, label in ((3, "Месяц"), (4, "Исходное начисление, млн ₽"),
                     (5, "Неполные интервалы"), (6, "Денежный поток с фактом, млн ₽" if history_mode else "Плановый платёж, млн ₽"),
                     (13, "Основание ставок"), (14, "Начало расчёта"), (15, "Ввод; граница исключается"),
                     (16, "Последний заданный год"), (17, "Расчёт до ввода полный"),
                     (18, "Начислено по ставкам: полный итог, млн ₽"), (19, "Денежный поток: известная часть, млн ₽"), (20, "Конвенция")):
        put(n, f"A{n}", label)
    put(13, "B13", str(source), style=styles["input_text"])
    put(14, "B14", formula=project_start_formula, style=styles["date"])
    manual_cutoff = inputs.get("land_rent_manual_cutoff")
    if phased:
        # Queues give their own commissioning dates; one manual date is not used.
        put(15, "B15", formula=rve_formula, style=styles["date"])
        put(15, "K15", "Ввод очередей — в таблице очередей ниже; одна общая дата не задаётся")
        put(15, "L15", None)
    else:
        put(15, "B15", formula=f'IF(COUNT($L$15)=1,$L$15,{rve_formula})', style=styles["date"])
        put(15, "K15", "Подтверждённый последний ввод на арендуемой земле")
        put(15, "L15", _serial(manual_cutoff) if _serial(manual_cutoff) is not None else manual_cutoff,
            style=styles["input_date"])
    convention = "Actual/Actual договорного года: ставка × дни / дни соответствующего года аренды; не юридический срок оплаты."
    if mode == "mo_housing_new_2026":
        mo_convention = "МО: дни / дни календарного года; индексы с 1 января. Это плановое начисление, не юридический срок оплаты."
        put(20, "B20", formula=f'IF($B$8="Ручные ставки","{convention}","{mo_convention}")')
    else:
        put(20, "B20", convention)
    put(18, "H18", "НДС аренды")
    vat = result.get("vat_treatment") or inputs.get("land_rent_vat_treatment")
    put(18, "I18", {"taxable": "Облагается НДС", "public_exempt": "Без НДС: публичный собственник"}.get(vat, "Не уточнён"), style=styles["input_text"])
    is_mo = mode == "mo_housing_new_2026"
    extra = ((8, "После ввода", "Отдельный режим; здесь не рассчитан", "amount"),
             (9, "Полнота после ввода", "Обязательство не считается прекращённым", "amount"),
             (10, "Подтверждённое прекращение", _serial(inputs.get("land_rent_termination_date")) if _serial(inputs.get("land_rent_termination_date")) is not None else inputs.get("land_rent_termination_date"), "input_date"),
             (12, "Первый год целиком в ВРИ подтверждён", "Да" if inputs.get("land_rent_first_year_confirmed") is True else "Нет", "input_text"),
             (13, "База", {"annual_amount":"Годовая сумма договора", "cadastral_percent":"Кадастровая стоимость"}.get(base_kind,"Не распознана"), "input_text"),
             (14, "Ставки региона сверены с договором", "Да" if inputs.get("land_rent_preset_confirmed") is True else "Нет", "input_text"),
             (15, "Регион норматива соответствует", "Да" if preset and project_regions.region_of(inputs) == preset.get("region") else "Нет", "amount"),
             (16, "Оплата", "Ручной график" if inputs.get("land_rent_payment_mode") == "manual" else "Плановое начисление", "input_text"))
    for n, label, value, style in extra:
        put(n, f"E{n}", label)
        put(n, f"F{n}", value, style=styles[style])
    scope, grant = inputs.get("land_rent_public_scope"), inputs.get("land_rent_grant_basis")
    mo_fields = ((8, "Дата договора для индексации", _serial(inputs.get("land_rent_contract_date")), "input_date"),
                 (9, "Публичная земля МО", "Не подтверждено" if scope in (None, "") else {"regional":"Областная", "undelimited":"Неразграниченная"}.get(scope, "Муниципальная или иная"), "input_text"),
                 (10, "Предоставление", "Не подтверждено" if grant in (None, "") else {"ordinary_nonauction":"Обычное, без торгов", "auction":"Торги", "krt":"КРТ"}.get(grant, "Специальный договор"), "input_text"),
                 (11, "Специальный КРТ", "Да" if inputs.get("_krt_site") else "Нет", "input_text"),
                 (12, "Регион", project_regions.region_of(inputs), "input_text"))
    for n, label, value, style in mo_fields:
        put(n, f"H{n}", label)
        put(n, f"I{n}", value, style=styles[style])
    # Without a contract date the indexation counts from the lease start.
    put(13, "H13", "Дата договора в расчёте индексации")
    put(13, "I13", formula='IF(COUNT($I$8)=1,$I$8,$B$10)', style=styles["date"])
    put(14, "H14", "Право на участок")
    put(14, "I14", "Собственность" if inputs.get("land_right", "ownership") == "ownership" else "Аренда")
    put(15, "H15", "Публикация источника")
    put(15, "I15", str(result.get("source_url") or "По документам проекта"))
    origins = inputs.get("_field_origin") if isinstance(inputs.get("_field_origin"), dict) else {}
    origin = result.get("base_origin") or origins.get("inputs.land_rent_cadastral_mln")
    if isinstance(origin, dict):
        origin = origin.get("text") or origin.get("label") or origin.get("source") or origin.get("kind")
    origin_label = str(origin or "Источник базы не указан")
    if base_kind == "annual_amount":
        origin_label = "Годовая сумма по договору"
    seeded_base = _numeric(inputs.get(base_key))
    put(19, "H19", "Источник базы начисления")
    if seeded_base is None:
        put(19, "I19", origin_label)
    else:
        origin_text = origin_label.replace('"', '""')
        put(19, "I19", formula=f'IF(AND(COUNT($B$9)=1,ABS($B$9-{seeded_base})<0.000000001),"{origin_text}","Изменено вручную в этой книге")')
    put(11, "E11", "Горизонт расчёта")
    put(11, "F11", formula=project_end_formula or rve_formula, style=styles["date"])
    put(17, "E17", "Ручной график сходится")
    put(18, "E18", "Расчёт после ввода полный")
    put(19, "E19", "Исходная таблица без ошибок")
    pre_first, pre_end = FIRST_YEAR_ROW, FIRST_YEAR_ROW + YEARS - 1
    pay_first, pay_end = pre_end + 4, pre_end + 503
    index_first, index_end = pay_end + 4, pay_end + 103
    actual_first = (index_end if is_mo else pay_end) + 4
    actual_end = actual_first + max(1,len(observed)) - 1
    # Queues and the VRI change: below every other table of the sheet.
    block = actual_end + 4
    target_row, switch_row, switch_eff, target_eff = block, block + 1, block + 2, block + 3
    regime_row, shares_row, g_hi_row = block + 4, block + 5, block + 6
    phase_first = block + 9
    phase_count = len(phase_land) if phased else 1
    phase_end = phase_first + phase_count - 1
    g_month_row = phase_end + 2
    phase_month_first = g_month_row + 2
    # Each phase allocates the existing monetary year/month cells on their
    # exact intervals. Never redistribute an already aggregated month: rates
    # or the excluded first year may change within it.
    phase_segment_first = phase_month_first + 5 * phase_count + 3
    cutoff = 'IF(COUNT($F$10)=1,MIN($F$10,$B$15),$B$15)'

    def g_phase(t: str, r: int) -> str:
        """Cumulative base × days of one queue from the project start to t."""
        return (f'$B${r}*($B$9*MAX(0,MIN({t},$D${r},$B${switch_eff})-$B$14)'
                f'+$B${target_eff}*MAX(0,MIN({t},$D${r})-MAX($B${switch_eff},$B$14)))')

    def g(t: str) -> str:
        return "IFERROR(" + "+".join(g_phase(t, r) for r in range(phase_first, phase_end + 1)) + ",0)"
    put(8, "K8", "Исторический импорт аренды")
    put(8, "L8", {"classified":"Факт выделен по статье аренды", "legacy_combined":"Старый импорт: аренда и ВРИ не разделены"}.get(history_mode,"Нет отдельного исторического импорта"))
    put(9, "K9", "Срез факта")
    put(9, "L9", _serial(history.get("cut")), style=styles["date"])
    put(10, "K10", "Подтверждённый диапазон: с")
    put(10, "L10", _serial(history.get("covered_from")), style=styles["date"])
    put(11, "K11", "Подтверждённый диапазон: по")
    put(11, "L11", _serial(history.get("covered_to")), style=styles["date"])
    put(12, "K12", "Жилищные нормативы применимы к типу проекта")
    put(12, "L12", "Да" if not project_types.without_housing(inputs) and result.get("housing_applicable", True) else "Нет")
    put(16, "K16", "Доплата первого года: пресет Москвы")
    premium = result.get("premium") if isinstance(result.get("premium"), dict) else {}
    put(16, "L16", PREMIUMS.get(str(premium.get("status") or inputs.get("land_rent_premium_status") or "unknown"),"Не подтверждена"), style=styles["input_text"])
    put(19, "K19", "Основание учёта доплаты")
    put(19, "L19", str(premium.get("source") or "").strip(), style=styles["input_text"])
    put(20, "K20", "Существующая валовая плата ВРИ, млн ₽")
    put(20, "L20", formula=hostvri_amount_formula, style=styles["amount"])
    cutoff_for_gate = 'IF(COUNT($F$10)=1,MIN($F$10,$B$15),$B$15)'
    premium_gate = "1"
    if preset and preset["region"] == "msk":
        source_text = '$L$19'
        for space in (" ", "\t", "\n", "\r", "\u00a0"):
            source_text = f'SUBSTITUTE({source_text},"{space}","")'
        premium_relevant = f'AND($B$8="{preset["label"]}",MAX(0,MIN(EDATE($B$10,12),{cutoff_for_gate})-MAX($B$10,$B$14))>0)'
        source_amount_gate = "1"
        if premium.get("derived") and premium.get("status") == "in_vri":
            # A source-proved inclusion is bound to the fee it described.
            # Editing the explicit confirmation/source in the workbook is
            # an owner decision; changing only the fee is not such proof.
            proof = premium.get("evidence") or {}
            proof_fee = _numeric(proof.get("fee_mln"))
            proof_source = str(premium.get("source") or "").replace('"', '""')
            source_amount_gate = (f'IF(AND($L$16="Учтена в ВРИ",$L$19="{proof_source}"),'
                                  f'ABS($L$20-{proof_fee if proof_fee is not None else -1})<0.000000001,1)')
        premium_gate = (f'OR($B$8="Не применяется",$I$14="Собственность",{premium_relevant}=0,'
            f'AND(LEN({source_text})>0,OR($L$16="Не применяется по основанию",'
            f'AND($L$16="Учтена в ВРИ",COUNT($L$20)=1,$L$20>0,{source_amount_gate}))))')
    social_dates = result.get("unlinked_social_dates") or {}
    social_serials = [_serial(value) for value in social_dates.values()] if isinstance(social_dates,dict) else []
    social_serials = [value for value in social_serials if value is not None]
    scope_gate = "1"
    if social_serials or result.get("scope_complete") is False:
        covered_social = f'$B$15>={max(social_serials)}' if social_serials else "0"
        scope_gate = (f'OR($B$8="Не применяется",$I$14="Собственность",COUNT($L$15)=1,'
            f'AND(COUNT($F$10)=1,$F$10<=$B$15),{covered_social})')
    conditions_gate = "1"
    if preset:
        conditions_gate = '$F$14="Да"'
        if is_mo:
            conditions_gate = ('AND($F$14="Да",COUNT($I$8)=1,OR($I$9="Областная",$I$9="Неразграниченная"),'
                               '$I$10="Обычное, без торгов")')
    regime_gate = f'$B${regime_row}="Да"'
    put(13, "K13", "Статус финансового результата")
    put(14, "K14", "Ограничение исходного среза")
    original_qualifier = ""
    if not result.get("financial_complete"):
        import developaid_land_rent
        original_qualifier = developaid_land_rent.disclosure(result)
        codes = result.get("financial_missing_codes")
        handled = {"inputs","premium","scope","post_rve","vat","payments","legacy_actuals","payment_periods",
                   "conditions","regime_start"}
        if isinstance(codes,list) and not (set(codes)-handled):
            original_qualifier = ""
    put(14, "L14", original_qualifier)
    cash_mismatch = 'ABS($B$19-$L$17)>0.0000005'
    put(13, "L13", formula=(f'IF(AND($B$17=1,{premium_gate}=0),'
        '"Предварительный расчёт: доплата первого года по 273-ПП не подтверждена",'
        f'IF(AND($B$17=1,{conditions_gate}=0),"Предварительный расчёт: ставки и условия аренды не сверены с договором",'
        f'IF(AND($B$17=1,{regime_gate}=0),"Предварительный расчёт: дата начала аренды принята по старту проекта",'
        f'IF(AND($B$17=1,{scope_gate}=0),"Предварительный расчёт: подтвердите охват арендуемой земли",'
        f'IF(AND($B$17=1,{cash_mismatch}),"Предварительный расчёт: платежи аренды не совпадают с начислением; проверьте периоды авансов",'
        f'IF(AND($B$17=1,$F$18=1,$L$18=1,$L$14="",{scope_gate},'
        'OR($B$8="Не применяется",$I$14="Собственность",'
        'AND($F$16="Ручной график",$F$17=1,$I$18<>"Не уточнён"))),"",'
        '"Предварительный расчёт: аренда земли требует уточнения — см. лист Аренда ЗУ"))))))'))
    raw_rates = inputs.get("land_rent_rates") or []
    rates, invalid = {}, (not preset and str(inputs.get("land_rent_tail_rule") or "unknown") not in TAILS)
    if preset:
        rates = {i + 1: float(rate) for i, rate in enumerate(preset["rates"])}
        rates[len(rates) + 1] = float(preset["tail_rate_pct"])
    elif isinstance(raw_rates, list):
        for item in raw_rates:
            year = _numeric(item.get("year")) if isinstance(item, dict) else None
            if year is None or not year.is_integer() or not 1 <= year <= YEARS or int(year) in rates:
                invalid = True
                if year is not None and year.is_integer() and int(year) in rates:
                    rates[int(year)] = None
                continue
            rates[int(year)] = _numeric(item.get("rate_pct"))
    else:
        invalid = True
    put(16, "H16", "Происхождение ставок")
    if preset:
        same_rates = [f'AND(COUNT(D{FIRST_YEAR_ROW+y-1})=1,ABS(D{FIRST_YEAR_ROW+y-1}-{rate})<0.0000000001)'
                      for y,rate in rates.items()]
        # The source defines a year-to-rate mapping, not an unordered set
        # of percentages. A manual year edit changes that provenance too.
        same_years = [f'A{pre_first+y-1}={y}' for y in range(1,YEARS+1)]
        put(16, "I16", formula=(f'IF(AND(COUNT(D{pre_first}:D{pre_end})={len(rates)},'
            + ",".join([*same_rates,*same_years]) + ',$B$11="Повтор последней ставки"),"По источнику","Ставки изменены вручную")'))
    else:
        put(16, "I16", "Введены вручную по договору")
    put(17, "H17", "Происхождение индексов МО")
    put(17, "I17", str(inputs.get("land_rent_indices_origin") or "Введены пользователем"), style=styles["input_text"])
    indices = {}
    raw_indices = inputs.get("land_rent_calendar_indices") or []
    if is_mo and not isinstance(raw_indices, list):
        invalid = True
    if is_mo and isinstance(raw_indices, list):
        for entry in raw_indices:
            year = _numeric(entry.get("year")) if isinstance(entry, dict) else None
            if year is None or not year.is_integer() or not 1900 <= year <= 2200 or int(year) in indices:
                invalid = True
                if year is not None and year.is_integer() and int(year) in indices:
                    indices[int(year)] = None
                continue
            indices[int(year)] = _numeric(entry.get("index_pct"))
    put(19, "F19", "Нет" if invalid else "Да", style=styles["input_text"])
    preset_gate = "0"
    if preset:
        # Unconfirmed conditions keep the rent counted (preliminary, see
        # conditions_gate); only a contradiction stops the regional rates.
        preset_gate = f'AND($B$8="{preset["label"]}",$I$12="{preset["region"]}",$L$12="Да",$F$13="Кадастровая стоимость")'
        if preset["region"] == "msk":
            preset_gate = f'AND({preset_gate},$I$11="Нет",$I$10<>"Торги",$I$10<>"КРТ",$I$10<>"Специальный договор")'
        if is_mo:
            preset_gate = (f'AND({preset_gate},COUNT($I$13)=1,$I$13>=46024,$I$9<>"Муниципальная или иная",'
                           'OR($I$10="Обычное, без торгов",$I$10="Не подтверждено"),$I$11="Нет")')
    valid = (f'AND(OR($B$8="Ручные ставки",{preset_gate}),'
             'OR($L$15="",AND(COUNT($L$15)=1,YEAR($L$15)>=1900,YEAR($L$15)<=2200)),'
             'OR($F$13="Кадастровая стоимость",$F$13="Годовая сумма договора"),'
             'COUNT($B$9)=1,$B$9>0,COUNT($B$10)=1,YEAR($B$10)>=1900,YEAR($B$10)<=2200,OR($F$10="",COUNT($F$10)=1),OR($B$15>=$B$14,COUNT($L$15)=1),$F$11>=$B$15,'
             'OR($B$12="Первый год отдельно от ВРИ",AND($B$12="Первый год полностью включён в ВРИ",$F$12="Да")),'
             f'COUNT($B${phase_first}:$B${phase_end})={phase_count},COUNTIF($B${phase_first}:$B${phase_end},"<0")=0,'
             f'ABS(SUM($B${phase_first}:$B${phase_end})-1)<0.000000001)')
    put(20, "H20", "Условия расчёта")
    put(20, "I20", formula=(f'IF(OR($B$8="Не применяется",$I$14="Собственность"),"Не требуются",'
        f'IF(IFERROR({valid},0),"Заданы","Не полны"))'))
    valid = '$I$20="Заданы"'
    final = 'IF(COUNT($F$10)=1,MIN($F$10,$F$11),$F$11)'
    coverage = f'AND($F$11<=EDATE($B$10,{YEARS * 12}),$B$14>=$D$3,$F$11<=EDATE($D$3,{months}))'
    put(16, "B16", formula=f"MAX(I{pre_first}:I{pre_end})")
    year_range = f'$A${pre_first}:$A${pre_end}'
    year_checks = [f'AND(COUNT(A{n})=1,A{n}>=1,A{n}<={YEARS},A{n}=ROUND(A{n},0),COUNTIF({year_range},A{n})=1)'
                   for n in range(pre_first,pre_end+1)]
    # Separate the global completeness flag from each row's usable part.
    # Editing one year into a duplicate invalidates both conflicting rows,
    # while the other non-conflicting years remain known monetary parts.
    put(12, "M12", "Целые неповторяющиеся годы")
    live_years = 'IFERROR(AND(' + ','.join(year_checks) + '),0)'
    if len(live_years) > 8192:
        raise ValueError("Аренда ЗУ: проверка годов превышает лимит формулы Excel")
    put(12, "N12", formula=live_years)
    raw_complete = f'AND({valid},{coverage},$F$19="Да",$N$12=1,SUM(D7:{last_col}7)=0)'
    put(17, "B17", formula=f'IF(OR($B$8="Не применяется",$I$14="Собственность"),1,IF({raw_complete},1,0))')
    put(18, "F18", formula=f'IF(OR(OR($B$8="Не применяется",$I$14="Собственность"),{final}<=MAX($B$15,$B$10)),1,0)')
    put(18, "B18", formula=f'IF(AND(B17=1,F18=1),SUM(D4:{last_col}4),"Не рассчитано полностью")', style=styles["amount"])
    put(19, "B19", formula=f"SUM(D6:{last_col}6)", style=styles["amount"])
    put(17, "K17", "Начислено по ставкам: известная часть, млн ₽")
    put(17, "L17", formula=f"SUM(D4:{last_col}4)", style=styles["amount"])
    put(18, "K18", "Денежный поток определён полностью")
    put(18, "L18", formula=f'IF(OR($L$8="Старый импорт: аренда и ВРИ не разделены",SUM(D5:{last_col}5)>0,{premium_gate}=0,{conditions_gate}=0,{regime_gate}=0),0,1)')

    for c, label in enumerate(("Год режима", "Начало года", "Конец года", "Ставка, %", "Применённая ставка, %", "Дни периода", "Дни года", "Известная сумма, млн ₽", "Заданный год"), 1):
        put(21, f"{_col(c)}21", label)
    g_start_col, g_end_col = _col(10 + months), _col(11 + months)
    put(21, f"{g_start_col}21", "База × дни аренды к началу года")
    put(21, f"{g_end_col}21", "База × дни аренды к концу года")
    if is_mo:
        put(index_first-2, f"A{index_first-2}", "МО: календарные индексы с 1 января после года договора; будущий индекс не угадывается")
        for c, label in enumerate(("Календарный год", "Индекс, % прироста", "Накопленный коэффициент"), 1):
            put(index_first-1, f"{_col(c)}{index_first-1}", label)
        contract_raw = inputs.get("land_rent_contract_date") or result.get("regime_start")
        contract_year = dt.date.fromisoformat(str(contract_raw)).year if _serial(contract_raw) is not None else 0
        calendar_start = max(1900, min([contract_year+1 if contract_year else 2026,
            dt.date.fromisoformat(str(result.get("project_start") or "2026-01-01")).year]))
        for offset, row in enumerate(range(index_first, index_end+1)):
            calendar_year = calendar_start + offset
            put(row, f"A{row}", calendar_year)
            put(row, f"B{row}", indices.get(calendar_year), style=styles["input"])
            prior = '""' if row == index_first else f"C{row-1}"
            prior_year = '0' if row == index_first else f"A{row-1}"
            unique_year = f'AND(COUNT(A{row})=1,A{row}=ROUND(A{row},0),A{row}>=1900,A{row}<=2200,COUNTIF($A${index_first}:$A${index_end},A{row})=1)'
            put(row, f"C{row}", formula=(f'IF(IFERROR({unique_year},0),IF(A{row}<=YEAR($I$13),1,IF(AND(COUNT(B{row})=1,B{row}>=0,'
                f'OR(A{row}=YEAR($I$13)+1,AND(COUNT({prior})=1,A{row}={prior_year}+1))),IF(A{row}=YEAR($I$13)+1,1,{prior})*(1+B{row}/100),"")),"")'), style=styles["amount"])
    for year in range(1, YEARS + 1):
        n = pre_first + year - 1
        put(n, f"A{n}", year)
        put(n, f"B{n}", formula=f'IF(COUNT($B$10)=1,EDATE($B$10,12*(A{n}-1)),0)', style=styles["date"])
        put(n, f"C{n}", formula=f'IF(COUNT($B$10)=1,EDATE($B$10,12*A{n}),0)', style=styles["date"])
        put(n, f"D{n}", rates.get(year), style=styles["input"])
        last_rate = f'INDEX($D${pre_first}:$D${pre_end},MATCH($B$16,{year_range},0))'
        row_rate = (f'IF(AND(COUNT(D{n})=1,D{n}>=0),D{n},IF(AND($B$11="Повтор последней ставки",$B$16>0,A{n}>$B$16,'
                    f'COUNTIF({year_range},$B$16)=1),IF(AND(COUNT({last_rate})=1,{last_rate}>=0),{last_rate},""),""))')
        put(n, f"E{n}", formula=f'IF(IFERROR({year_checks[year-1]},0),{row_rate},"")', style=styles["amount"])
        # A declared-but-unknown last year is not permission to repeat an
        # earlier rate. Keep its presence separate from its numeric value.
        put(n, f"I{n}", formula=f'IF(OR(AND(COUNT(D{n})=1,D{n}>=0),{1 if year in rates else 0}),A{n},0)')
        lo, hi = '$B$14', cutoff
        put(n, f"F{n}", formula=f'MAX(0,MIN(C{n},{hi})-MAX(B{n},{lo}))')
        put(n, f"G{n}", formula=f'C{n}-B{n}')
        put(n, f"H{n}", formula=f'SUM(J{n}:{last_matrix_col}{n})', style=styles["amount"])
        put(n, f"{g_start_col}{n}", formula=g(f"B{n}"), style=styles["amount"])
        put(n, f"{g_end_col}{n}", formula=g(f"C{n}"), style=styles["amount"])
        for index in range(months):
            col, month_col = _col(10 + index), _col(4 + index)
            overlap = f'MAX(0,MIN(C{n},EDATE({col}$21,1),{hi})-MAX(B{n},{col}$21,{lo}))'
            excluded = f'AND(A{n}=1,$B$12="Первый год полностью включён в ВРИ",$F$12="Да")'
            factor = "1"
            denominator = f"G{n}"
            if is_mo:
                factor = (f'IF(OR($B$8="Ручные ставки",YEAR({col}$21)<=YEAR($I$13)),1,'
                          f'IFERROR(INDEX($C${index_first}:$C${index_end},MATCH(YEAR({col}$21),$A${index_first}:$A${index_end},0)),""))')
                calendar_start = f"EDATE({col}$21-DAY({col}$21)+1,1-MONTH({col}$21))"
                denominator = f'IF($B$8="Ручные ставки",G{n},EDATE({calendar_start},12)-{calendar_start})'
            # Base × days on the cell's interval: queues still leased, the
            # cadastral value valid on each day (G is monotone, so its ends
            # are the MIN/MAX of G at the interval's bounds).
            leased = (f'MAX(0,MIN({g_end_col}{n},{month_col}${g_month_row+1},$B${g_hi_row})'
                      f'-MAX({g_start_col}{n},{month_col}${g_month_row}))')
            formula = (f'IF(OR(OR($B$8="Не применяется",$I$14="Собственность"),{overlap}=0,{excluded}),0,IF(AND({valid},COUNT(E{n})=1,COUNT({factor})=1),E{n}/100*{factor}*{leased}/({denominator}),"Не рассчитано"))')
            put(n, f"{col}{n}", formula=formula, style=styles["amount"])
    if history_mode:
        put(actual_first-2, f"A{actual_first-2}", "ИСТОРИЧЕСКИЙ ФАКТ АРЕНДЫ — исходные платежи; прогноз после среза не перенормируется")
        if history_mode == "legacy_combined":
            put(actual_first-1, f"A{actual_first-1}", "Прошлая аренда отдельно не определена; прогноз до среза повторно не начисляется")
        for i,(month,amount) in enumerate(sorted(observed.items())):
            row = actual_first+i
            put(row, f"A{row}", _serial(month), style=styles["date"])
            put(row, f"B{row}", amount/1e6, style=styles["amount"])
            put(row, f"C{row}", "Факт из классифицированного импорта")
    switch = result.get("cadastral_switch") if isinstance(result.get("cadastral_switch"), dict) else None
    target_seed = switch["target_mln"] if switch else _numeric(inputs.get("land_rent_cadastral_target_mln"))
    put(block-2, f"A{block-2}", "ОЧЕРЕДИ И СМЕНА ВРИ — земля очереди выходит из аренды при её вводе; со дня смены ВРИ аренда считается от новой кадастровой стоимости")
    put(target_row, f"A{target_row}", "Кадастровая стоимость после смены ВРИ, млн ₽")
    put(target_row, f"B{target_row}", target_seed, style=styles["input"])
    put(switch_row, f"A{switch_row}", "Дата смены ВРИ (дата платы за смену ВРИ)")
    put(switch_row, f"B{switch_row}", _serial(switch["date"]) if switch else None, style=styles["input_date"])
    put(switch_eff, f"A{switch_eff}", "Новая кадастровая стоимость применяется с")
    put(switch_eff, f"B{switch_eff}", formula=(f'IF(AND(COUNT($B${target_row})=1,$B${target_row}>0,COUNT($B${switch_row})=1,'
        f'$F$13="Кадастровая стоимость"),$B${switch_row},2958465)'), style=styles["date"])
    put(switch_eff, f"C{switch_eff}", "31.12.9999 — смены ВРИ в расчёте нет")
    put(target_eff, f"A{target_eff}", "База после смены ВРИ в расчёте, млн ₽")
    put(target_eff, f"B{target_eff}", formula=f'IF(COUNT($B${target_row})=1,$B${target_row},$B$9)', style=styles["amount"])
    put(regime_row, f"A{regime_row}", "Дата начала аренды взята из договора")
    put(regime_row, f"B{regime_row}", "Нет" if result.get("regime_start_assumed") else "Да", style=styles["input_text"])
    put(regime_row, f"C{regime_row}", "«Нет» — дата не указана и принят старт проекта; расчёт предварительный")
    put(shares_row, f"A{shares_row}", "Доли участка очередей в сумме")
    put(shares_row, f"B{shares_row}", formula=f"SUM(B{phase_first}:B{phase_end})", style=styles["amount"])
    put(shares_row, f"C{shares_row}", "Должно быть ровно 1")
    put(g_hi_row, f"A{g_hi_row}", "База × дни аренды к концу расчёта")
    put(g_hi_row, f"B{g_hi_row}", formula=g(cutoff), style=styles["amount"])
    for c, label in enumerate(("Очередь", "Доля участка", "Ввод очереди", "Земля выходит из аренды",
                               "Начислено, млн ₽", "Оплачено, млн ₽", "База × дни к концу расчёта"), 1):
        put(phase_first-1, f"{_col(c)}{phase_first-1}", label)
    phase_cash_rows = []
    for p in range(phase_count):
        r = phase_first + p
        put(r, f"A{r}", f"Очередь {p+1}" if phased else "Весь участок")
        put(r, f"B{r}", float(phase_land[p]["share"]) if phased else 1.0, style=styles["input" if phased else "amount"])
        put(r, f"C{r}", formula=phase_rve_formulas[p] if phased else "$B$15", style=styles["date"])
        # The queue commissioned last holds its land up to the common cutoff
        # (developaid_land_rent.phase_release).
        put(r, f"D{r}", formula=(f'IF(C{r}=MAX($C${phase_first}:$C${phase_end}),$B$15,MIN(C{r},$B$15))'
                                 if phased else "$B$15"), style=styles["date"])
        put(r, f"G{r}", formula="IFERROR(" + g_phase(cutoff, r) + ",0)", style=styles["amount"])
        if phased:
            base = phase_month_first + 5 * p
            put(r, f"E{r}", formula=f"SUM(D{base+3}:{last_col}{base+3})", style=styles["amount"])
            put(r, f"F{r}", formula=f"SUM(D{base+4}:{last_col}{base+4})", style=styles["amount"])
            for k, label in enumerate(("база × дни к началу месяца", "база × дни к концу месяца",
                                       "доля начисления месяца", "начисление, млн ₽", "платёж, млн ₽")):
                put(base+k, f"A{base+k}", f"Очередь {p+1}: {label}")
            phase_cash_rows.append(base + 4)
        else:
            put(r, f"E{r}", formula="$L$17", style=styles["amount"])
            put(r, f"F{r}", formula="$B$19", style=styles["amount"])
    put(g_month_row, f"A{g_month_row}", "База × дни аренды к началу месяца")
    put(g_month_row+1, f"A{g_month_row+1}", "База × дни аренды к началу следующего месяца")
    for index in range(months):
        col = _col(4 + index)
        put(g_month_row, f"{col}{g_month_row}", formula=g(f"{col}$3"), style=styles["amount"])
        put(g_month_row+1, f"{col}{g_month_row+1}", formula=g(f"EDATE({col}$3,1)"), style=styles["amount"])
        if not phased:
            continue
        for p in range(phase_count):
            r, base = phase_first + p, phase_month_first + 5 * p
            put(base, f"{col}{base}", formula="IFERROR(" + g_phase(f"{col}$3", r) + ",0)", style=styles["amount"])
            put(base+1, f"{col}{base+1}", formula="IFERROR(" + g_phase(f"MIN(EDATE({col}$3,1),{cutoff})", r) + ",0)", style=styles["amount"])
            first = phase_segment_first + p * (YEARS + 2)
            last = first + YEARS - 1
            put(base+3, f"{col}{base+3}", formula=f'SUM({col}{first}:{col}{last})', style=styles["amount"])
            put(base+2, f"{col}{base+2}", formula=f'IF({col}$4>0,{col}{base+3}/{col}$4,$B${r})')
            put(base+4, f"{col}{base+4}", formula=(f'IF(AND($F$16="Ручной график",$F$17=1),'
                f'{col}$6*IF($L$17>0,$E${r}/$L$17,$B${r}),{col}$6*{col}{base+2})'), style=styles["amount"])
            matrix = _col(10 + index)
            for year in range(YEARS):
                n, dest = pre_first + year, first + year
                # The source cell already applies the rate, calendar index,
                # unknown-year gate and first-year exclusion. Only its
                # base-times-days integral is divided among the phases.
                hi = f'MIN($C${n},EDATE({col}$3,1),{cutoff})'
                lo = f'MAX($B${n},{col}$3,$B$14)'
                own = f'MAX(0,({g_phase(hi,r)})-({g_phase(lo,r)}))'
                total = (f'MAX(0,MIN(${g_end_col}${n},{col}${g_month_row+1},$B${g_hi_row})'
                         f'-MAX(${g_start_col}${n},{col}${g_month_row}))')
                amount = f'{matrix}{n}'
                put(dest, f'{col}{dest}', formula=(f'IF(AND(COUNT({amount})=1,{total}>0),'
                    f'{amount}*{own}/{total},0)'), style=styles["amount"])
                if index == 0:
                    put(dest, f'A{dest}', f'Очередь {p+1}, год {year+1}: начисление по общему расчёту')
    if layout is not None:
        layout["phase_cash_rows"] = phase_cash_rows
    put(pay_first-2, f"A{pay_first-2}", "РУЧНОЙ ГРАФИК ОПЛАТЫ — сумма должна совпасть с известной полной потребностью")
    for c, label in enumerate(("Месяц от старта", "Дата платежа", "Сумма / доля", "Единица: млн ₽ или %", "Сумма, млн ₽", "Месяц платежа", "Ошибка строки"), 1):
        put(pay_first-1, f"{_col(c)}{pay_first-1}", label)
    parsed = []
    payment_syntax_valid = True
    for item in str(inputs.get("land_rent_payment_schedule") or "").split(";"):
        match = re.fullmatch(r'\s*([0-9]+(?:[.,][0-9]+)?)\s*(%)?\s*@\s*([0-9]+)\s*', item)
        if match:
            value, percent, offset = match.groups()
            parsed.append((int(offset), float(value.replace(",", ".")), "%" if percent else "млн ₽"))
        elif item.strip():
            payment_syntax_valid = False
    if len(parsed) > 500:
        payment_syntax_valid = False
    put(20, "E20", "Исходный график распознан")
    put(20, "F20", "Да" if payment_syntax_valid else "Нет", style=styles["input_text"])
    for i, n in enumerate(range(pay_first, pay_end+1)):
        offset, value, unit = parsed[i] if i < len(parsed) else (None, None, "млн ₽")
        put(n, f"A{n}", offset, style=styles["input"])
        put(n, f"B{n}", formula=f'IF(COUNT(A{n})=1,EDATE($B$14,A{n}),"")', style=styles["date"])
        put(n, f"C{n}", value, style=styles["input"])
        put(n, f"D{n}", unit, style=styles["input_text"])
        put(n, f"E{n}", formula=f'IF(COUNT(C{n})=0,0,IF(D{n}="%",SUM($D$4:${last_col}$4)*C{n}/100,C{n}))', style=styles["amount"])
        put(n, f"F{n}", formula=f'IF(COUNT(A{n})=1,B{n}-DAY(B{n})+1,0)', style=styles["date"])
        put(n, f"G{n}", formula=f'IF(AND(COUNT(A{n})=0,COUNT(C{n})=0),0,IF(AND(COUNT(A{n})=1,A{n}>=0,A{n}<=1200,A{n}=ROUND(A{n},0),COUNT(C{n})=1,C{n}>=0,B{n}>=$B$14,B{n}<$F$11,OR(D{n}="%",D{n}="млн ₽")),0,1))')
    put(17, "F17", formula=(f'IF(AND({raw_complete},$F$20="Да",COUNT(C{pay_first}:C{pay_end})>0,SUM(G{pay_first}:G{pay_end})=0,OR(COUNTIF(D{pay_first}:D{pay_end},"%")=0,AND(COUNTIF(D{pay_first}:D{pay_end},"%")=COUNT(C{pay_first}:C{pay_end}),ABS(SUMIF(D{pay_first}:D{pay_end},"%",C{pay_first}:C{pay_end})-100)<=0.0000001)),ABS(SUM(E{pay_first}:E{pay_end})-SUM($D$4:${last_col}$4))<=0.0000005),1,0)'))
    for index in range(months):
        col, matrix = _col(4 + index), _col(10 + index)
        # All default monthly keys and their period boundaries use day 1.
        # Contract/project/RVE dates above retain their actual source days.
        month_formula = (month_formulas[index] if month_formulas is not None else
                         f"'Ставки'!{col}3-DAY('Ставки'!{col}3)+1")
        put(3, f"{col}3", formula=month_formula, style=styles["date"])
        put(4, f"{col}4", formula=f'SUM({matrix}{pre_first}:{matrix}{pre_end})', style=styles["amount"])
        active = f'AND({col}3<$B$15,EDATE({col}3,1)>$B$14)'
        put(7, f"{col}7", formula=f'IF(OR($B$8="Не применяется",$I$14="Собственность"),0,IF(AND({active},OR({valid}=0,$N$12=0)),1,COUNTIF({matrix}{pre_first}:{matrix}{pre_end},"Не рассчитано")))')
        unknown = f'{col}7+IF(AND(AND($B$8<>"Не применяется",$I$14<>"Собственность"),MAX(0,MIN(EDATE({col}3,1),{final})-MAX({col}3,$B$15,$B$10))>0),1,0)'
        if history_mode == "legacy_combined":
            unknown = f'IF(AND({col}3<$L$9,EDATE({col}3,1)>$B$14),1,{unknown})'
        put(5, f"{col}5", formula=unknown)
        cash = f'IF(AND($F$16="Ручной график",$F$17=1),SUMIF($F${pay_first}:$F${pay_end},{col}3,$E${pay_first}:$E${pay_end}),{col}4)'
        if history_mode == "legacy_combined":
            cash = f'IF({col}3<$L$9,0,{cash})'
        elif history_mode == "classified" and observed:
            cash = f'IF(AND({col}3>=$L$10,{col}3<=$L$11),SUMIF($A${actual_first}:$A${actual_end},{col}3,$B${actual_first}:$B${actual_end}),{cash})'
        put(6, f"{col}6", formula=cash, style=styles["amount"])
        put(21, f"{matrix}21", formula=f'{col}3', style=styles["date"])
    put(7, "A7", "Неопределённые интервалы до ввода")
    put(6, "B6", formula='IF(OR($B$8="Не применяется",$I$14="Собственность"),"Не применяется",IF(AND(F16="Ручной график",F17=1),"По заданному графику","Плановое начисление; сроки оплаты — по договору"))')
    data[:] = sorted(data, key=lambda r: int(r.get("r", "0")))
    for row in data:
        row[:] = sorted(row, key=lambda c: (len(re.match(r"[A-Z]+", c.get("r")).group()), re.match(r"[A-Z]+", c.get("r")).group()))
    choices = {"B8": [*MODES.values(), *([preset["label"]] if preset else [])], "B11": list(TAILS.values()), "B12": list(RELATIONS.values()),
               "I18": ["Облагается НДС", "Без НДС: публичный собственник", "Не уточнён"],
               "F12": ["Да", "Нет"], "F14": ["Да", "Нет"], "F19": ["Да", "Нет"], "F20": ["Да", "Нет"],
               "I9": ["Областная", "Неразграниченная", "Муниципальная или иная", "Не подтверждено"], "I10": ["Обычное, без торгов", "Торги", "КРТ", "Специальный договор", "Не подтверждено"],
               "I11": ["Да", "Нет"], "I12": ["msk", "mo", "other"], f"B{regime_row}": ["Да", "Нет"],
               "L16": list(PREMIUMS.values()), "F13": ["Кадастровая стоимость", "Годовая сумма договора"], "F16": ["Плановое начисление", "Ручной график"]}
    validations = ET.SubElement(root, _tag("dataValidations"), {"count": str(len(choices))})
    for coord, options in choices.items():
        rule = ET.SubElement(validations, _tag("dataValidation"), {"type": "list", "allowBlank": "0", "sqref": coord})
        ET.SubElement(rule, _tag("formula1")).text = '"' + ",".join(options) + '"'
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def apply(content: bytes, inputs: dict[str, Any], result: dict[str, Any], *,
          project_start_formula: str, rve_formula: str,
          phase_shares: list[float], project_end_formula: str | None = None,
          hostvri_amount_formula: str | None = None,
          phase_rve_formulas: list[str] | None = None) -> bytes:
    """Add one project schedule and distribute it once across active phases.

    With several queues on the parcel each CAPEX row takes its queue's own
    payment row of the sheet (the month's rent split among the queues still
    leased); otherwise the shares come from the canonical project allocation,
    never from duplicating the total for each queue. Unknown slices remain
    text in the rent row; known partial slices still enter the existing
    numeric CAPEX/CF totals.
    """
    if len(phase_shares) > 4 or any(not math.isfinite(v) or v < 0 for v in phase_shares) or not math.isclose(sum(phase_shares), 1.0, abs_tol=1e-9):
        raise ValueError("Аренда ЗУ: доли очередей не образуют единый проектный поток")
    with zipfile.ZipFile(io.BytesIO(content)) as original:
        parts = {name: original.read(name) for name in original.namelist()}
    if SHEET_PATH in parts:
        raise ValueError("Аренда ЗУ: лист уже существует")
    styles_xml, styles = _styles(parts["xl/styles.xml"])
    parts["xl/styles.xml"] = styles_xml
    layout: dict[str, Any] = {}
    parts[SHEET_PATH] = build_sheet(inputs, result, styles,
        project_start_formula=project_start_formula, rve_formula=rve_formula, project_end_formula=project_end_formula,
        hostvri_amount_formula=hostvri_amount_formula, phase_rve_formulas=phase_rve_formulas, layout=layout)
    phase_rows = layout.get("phase_cash_rows") or []
    if phase_rows and len(phase_rows) > len(CAPEX_ROWS):
        raise ValueError("Аренда ЗУ: очередей больше, чем строк CAPEX")
    rels = ET.fromstring(parts["xl/_rels/workbook.xml.rels"])
    rid_to_path = {r.get("Id"): r.get("Target", "").lstrip("/") for r in rels}
    wb = ET.fromstring(parts["xl/workbook.xml"])
    sheets = wb.find(_tag("sheets"))
    paths = {}
    for s in sheets:
        path = rid_to_path.get(s.get(f"{{{RNS}}}id"), "")
        paths[s.get("name")] = path if path.startswith("xl/") else "xl/" + path
    parts["xl/workbook.xml"] = _append_xml(parts["xl/workbook.xml"], "sheets",
        f'<PREFIXsheet name="{SHEET}" sheetId="{SHEET_ID}" xmlns:r="{RNS}" r:id="{REL_ID}" />')
    rel_path = "xl/_rels/workbook.xml.rels"
    parts[rel_path] = _append_xml(parts[rel_path], "Relationships",
        f'<PREFIXRelationship Type="{RNS}/worksheet" Target="/{SHEET_PATH}" Id="{REL_ID}" />')
    parts["[Content_Types].xml"] = _append_xml(parts["[Content_Types].xml"], "Types",
        f'<PREFIXOverride PartName="/{SHEET_PATH}" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml" />')
    capex = ET.fromstring(parts[paths["CAPEX"]])
    data = capex.find(_tag("sheetData"))
    for phase, row_number in enumerate(CAPEX_ROWS):
        share = phase_shares[phase] if phase < len(phase_shares) else 0.0
        if phase_rows:
            share = 1 if phase < len(phase_rows) else 0
        own = f"'{SHEET}'!{{col}}{phase_rows[phase]}" if phase < len(phase_rows) else f"'{SHEET}'!{{col}}6*{share}"
        row = data.find(f"{_tag('row')}[@r='{row_number}']")
        if row is not None and len(row):
            raise ValueError(f"Аренда ЗУ: строка CAPEX {row_number} уже занята")
        if row is None:
            row = ET.SubElement(data, _tag("row"), {"r": str(row_number)})
        _cell(row, f"A{row_number}", f"Аренда ЗУ · очередь {phase+1}: план оплаты; неизвестная часть отдельно")
        _cell(row, f"B{row_number}", formula=(f'IF({share}=0,0,IF(\'{SHEET}\'!$B$17=1,SUM(D{row_number}:GA{row_number}),'
            f'IF(SUM(D{row_number}:GA{row_number})<>0,SUM(D{row_number}:GA{row_number}),"Не рассчитано")))'), style=styles["amount"])
        _cell(row, f"C{row_number}", "млн ₽")
        for index in range(MONTHS):
            col = _col(4 + index)
            formula = (f'IF({share}=0,0,IF(AND(\'{SHEET}\'!{col}5>0,\'{SHEET}\'!{col}6=0),'
                       f'"Не рассчитано",{own.format(col=col)}))')
            _cell(row, f"{col}{row_number}", formula=formula, style=styles["amount"])
            total_row = 32 + phase * 34
            total = data.find(f"{_tag('row')}[@r='{total_row}']/{_tag('c')}[@r='{col}{total_row}']/{_tag('f')}")
            if total is None:
                raise ValueError(f"Аренда ЗУ: CAPEX {col}{total_row} не распознана")
            total.text += f"+SUM({col}{row_number})"
        # City land lease is VAT exempt; the canonical engine excludes it
        # from vat_bearing_costs as well. Do not create fictitious input VAT.
        cf = ET.fromstring(parts[paths[f"CF_{phase + 1}"]])
        for cell in cf.findall(f".//{_tag('row')}[@r='21']/{_tag('c')}"):
            formula = cell.find(_tag("f"))
            if formula is not None and "SUM($D$20:$GA$20)-" in (formula.text or ""):
                deduction = f'IF(\'{SHEET}\'!$I$18="Облагается НДС",0,SUM(\'CAPEX\'!$B${row_number}))'
                formula.text = formula.text.replace("SUM($D$20:$GA$20)-", f"SUM($D$20:$GA$20)-{deduction}-", 1)
        cf_path = paths[f"CF_{phase + 1}"]
        parts[cf_path] = _xml(cf, parts[cf_path])
    data[:] = sorted(data, key=lambda r: int(r.get("r", "0")))
    dimension = capex.find(_tag("dimension"))
    if dimension is not None:
        dimension.set("ref", "A1:GA148")
    parts[paths["CAPEX"]] = _xml(capex, parts[paths["CAPEX"]])
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, payload in parts.items():
            archive.writestr(path, payload)
    return output.getvalue()

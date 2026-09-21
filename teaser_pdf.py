"""Тизер проекта — две страницы из модели представления.

Страница 1, «Девелоперский проект» (A4 книжная): карта участка с контурами
ЕГРН, паспорт участка и ограничения, расчётный ТЭП, экономика, удельная
экономика, финансирование, риски. Страница 2, «Итог» (A4 альбомная): показатели
эффективности, ТЭП по продуктам, доходы и себестоимость на метр ГНС и
продаваемой, график кредита и эскроу, сроки строительства и продаж.

Состав снят с двух образцов владельца (тизер+итог от 10.03.2026 и тизер по
ул. Россолимо, 17): базовые показатели, адрес или кадастровый номер, удельная
экономика, соцнагрузка, ВРИ и карта участка обязательно. Собирается из
`presentation.build_project_presentation`, а не из книги и не обрезкой полного
отчёта: тот остаётся как есть. Единица у каждого числа стоит рядом,
форматирование денег — то же, что у полного PDF (передаётся вызывающим: модуль
движка не импортирует, иначе появился бы второй экземпляр ядра).
"""

from __future__ import annotations

import io
from datetime import date
from typing import Any, Callable

from reportlab.graphics.shapes import Drawing, Line, Polygon, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, Image, NextPageTemplate, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

NAVY = colors.HexColor("#17365D")
NAVY_DARK = colors.HexColor("#0B1F33")
LIGHT = colors.HexColor("#EAF2F8")
GREY = colors.HexColor("#666666")
LINE = colors.HexColor("#C9D3DE")
RED = colors.HexColor("#C00000")
GREEN = colors.HexColor("#2E7D32")
BRIDGE_COLOR = colors.HexColor("#171717")
PF_COLOR = colors.HexColor("#A35D00")
ESCROW_COLOR = colors.HexColor("#2D6A4F")

TEASER_TITLE = "DevelopAid · тизер проекта"
PAGE1_TITLE = "Девелоперский проект"
PAGE2_TITLE = "Итог"
NO_MAP_TEXT = "Карта участка не построена"
NOT_SCREENED_TEXT = "Ограничения не проверялись"
CHART_TITLE = "Объём кредита и средств эскроу"
GANTT_TITLE = "Периоды строительства и продаж"

FLAG_MARK = {"killer": "СТОП", "economic": "ВЛИЯЕТ"}
MONTHS_GEN = ("янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _quarter(iso: str) -> str:
    """«2 кв 2029» из даты ISO — подпись оси, как у образца владельца."""
    try:
        d = date.fromisoformat(str(iso)[:10])
    except (TypeError, ValueError):
        return str(iso or "—")
    return f"{(d.month - 1) // 3 + 1} кв {d.year}"


def _month_label(iso: str) -> str:
    try:
        d = date.fromisoformat(str(iso)[:10])
    except (TypeError, ValueError):
        return str(iso or "—")
    return f"{MONTHS_GEN[d.month - 1]} {d.year}"


def _nice_ceiling(value: float) -> float:
    """Верх шкалы — круглое число (1, 2, 5 × 10^k), чтобы деления читались."""
    if value <= 0:
        return 1.0
    import math
    power = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 2.5, 5, 10):
        if step * power >= value:
            return step * power
    return 10 * power


def _months_since(iso: str, origin: date) -> float | None:
    try:
        d = date.fromisoformat(str(iso)[:10])
    except (TypeError, ValueError):
        return None
    return (d.year - origin.year) * 12 + (d.month - origin.month)


class _Styles:
    def __init__(self, fonts: tuple[str, str]) -> None:
        regular, bold = fonts
        self.regular, self.bold = regular, bold
        self.band = ParagraphStyle("band", fontName=bold, fontSize=11, leading=14, textColor=colors.white)
        self.sub = ParagraphStyle("sub", fontName=regular, fontSize=7.5, leading=9.5, textColor=GREY)
        self.h2 = ParagraphStyle("h2", fontName=bold, fontSize=9.5, leading=12, textColor=NAVY)
        self.h3 = ParagraphStyle("h3", fontName=bold, fontSize=8, leading=10, textColor=NAVY)
        self.label = ParagraphStyle("label", fontName=regular, fontSize=7.4, leading=9, textColor=NAVY_DARK)
        self.label_b = ParagraphStyle("label_b", fontName=bold, fontSize=7.4, leading=9, textColor=NAVY_DARK)
        self.value = ParagraphStyle("value", fontName=bold, fontSize=7.4, leading=9, textColor=NAVY_DARK)
        self.value_r = ParagraphStyle("value_r", fontName=regular, fontSize=7.4, leading=9,
                                      textColor=NAVY_DARK, alignment=2)
        self.value_rb = ParagraphStyle("value_rb", fontName=bold, fontSize=7.4, leading=9,
                                       textColor=NAVY_DARK, alignment=2)
        self.unit = ParagraphStyle("unit", fontName=regular, fontSize=6.8, leading=9, textColor=GREY)
        self.note = ParagraphStyle("note", fontName=regular, fontSize=6.8, leading=8.6, textColor=GREY)
        self.th = ParagraphStyle("th", fontName=bold, fontSize=6.8, leading=8.6, textColor=NAVY)
        self.th_r = ParagraphStyle("th_r", fontName=bold, fontSize=6.8, leading=8.6, textColor=NAVY, alignment=2)
        self.risk_on = ParagraphStyle("risk_on", fontName=bold, fontSize=7.4, leading=9.2, textColor=RED)
        self.risk_off = ParagraphStyle("risk_off", fontName=regular, fontSize=7.4, leading=9.2, textColor=GREEN)
        self.big = ParagraphStyle("big", fontName=bold, fontSize=10.5, leading=13, textColor=NAVY_DARK, alignment=2)


class _Formats:
    """Форматирование: единица у каждого числа, деньги — как в полном PDF."""

    def __init__(self, num: Callable[..., str]) -> None:
        self.num = num

    def mln(self, value: Any, digits: int = 1) -> str:
        v = _f(value)
        return "—" if v is None else self.num(v, digits)

    def th(self, value: Any, digits: int = 1) -> str:
        v = _f(value)
        return "—" if v is None else self.num(v, digits)

    def sqm(self, value: Any) -> str:
        v = _f(value)
        return "—" if v is None else self.num(v, 0)

    def pct(self, value: Any, digits: int = 1) -> str:
        v = _f(value)
        return "—" if v is None else self.num(v * 100, digits) + "%"

    def x(self, value: Any) -> str:
        v = _f(value)
        return "—" if v is None else self.num(v, 2) + "x"

    def count(self, value: Any) -> str:
        v = _f(value)
        return "—" if v is None else self.num(v, 0)


def _section(text: str, width: float, st: _Styles) -> Table:
    """Заголовок раздела с синей линией под ним — как в образце по Россолимо."""
    t = Table([[Paragraph(text, st.h2)]], colWidths=[width])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 1.0, NAVY),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                           ("TOPPADDING", (0, 0), (-1, -1), 4)]))
    return t


def _kv(rows: list[tuple[str, str, str]], width: float, st: _Styles,
        label_share: float = 0.50, bold_rows: tuple[int, ...] = ()) -> Table:
    """Таблица «показатель · значение · единица» с тонкими линиями."""
    data = []
    for index, (label, value, unit) in enumerate(rows):
        strong = index in bold_rows
        data.append([Paragraph(label, st.label_b if strong else st.label),
                     Paragraph(value, st.value_rb if strong else st.value_r),
                     Paragraph(unit, st.unit)])
    unit_w = width * 0.17
    label_w = width * label_share
    t = Table(data, colWidths=[label_w, width - label_w - unit_w, unit_w])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("TOPPADDING", (0, 0), (-1, -1), 1.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2),
                           ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
    return t


def _grid(head: list[str], rows: list[list[str]], widths: list[float], st: _Styles,
          bold_last: bool = False) -> Table:
    """Таблица с шапкой: первая колонка подпись, остальные числа справа."""
    data = [[Paragraph(head[0], st.th)] + [Paragraph(h, st.th_r) for h in head[1:]]]
    for index, row in enumerate(rows):
        strong = bold_last and index == len(rows) - 1
        data.append([Paragraph(row[0], st.label_b if strong else st.label)]
                    + [Paragraph(cell, st.value_rb if strong else st.value_r) for cell in row[1:]])
    t = Table(data, colWidths=widths)
    style = [("LINEBELOW", (0, 0), (-1, 0), 0.7, NAVY), ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINE),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("TOPPADDING", (0, 0), (-1, -1), 1.0), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.0),
             ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2)]
    if bold_last and rows:
        style.append(("LINEABOVE", (0, -1), (-1, -1), 0.7, NAVY))
    t.setStyle(TableStyle(style))
    return t


def _band(text: str, width: float, st: _Styles) -> Table:
    t = Table([[Paragraph(text, st.band)]], colWidths=[width])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY_DARK), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return t


def _map_block(map_png: bytes | None, width: float, st: _Styles, site: dict[str, Any]) -> list[Any]:
    """Карта участка: картинка с контурами ЕГРН, а нет её — названная причина,
    не пустое место (пустое читается как «карты у проекта нет»)."""
    numbers = site.get("cadastral_numbers") or []
    if map_png:
        try:
            from PIL import Image as PILImage
            with PILImage.open(io.BytesIO(map_png)) as probe:
                w, h = probe.size
        except Exception:
            w, h = 4, 3
        height = min(width * h / max(w, 1), 78 * mm)
        image = Image(io.BytesIO(map_png), width=width, height=height)
        caption = ("Контур участка по ЕГРН (красная линия) на публичной карте НСПД · "
                   + ", ".join(numbers[:4]) + (" …" if len(numbers) > 4 else ""))
        return [image, Paragraph(caption, st.note)]
    reason = ("кадастровый номер не задан — карта строится по нему" if not numbers
              else "НСПД не отдал контур или подложку на момент сборки")
    box = Table([[Paragraph(f"{NO_MAP_TEXT}: {reason}.", st.note)]], colWidths=[width],
                rowHeights=[28 * mm])
    box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, LINE), ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
                             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 6)]))
    return [box]


def _site_rows(site: dict[str, Any], tep: dict[str, Any], fm: _Formats) -> list[tuple[str, str, str]]:
    numbers = site.get("cadastral_numbers") or []
    rows: list[tuple[str, str, str]] = []
    rows.append(("Адрес", site.get("address") or "не назван", ""))
    rows.append(("Кадастровые номера", ", ".join(numbers) if numbers else "не заданы", ""))
    area_ha = site.get("land_area_ha")
    rows.append(("Площадь участка",
                 (fm.num(area_ha, 2) if area_ha is not None else "—"), "га" if area_ha is not None else ""))
    parcels = [p for p in (site.get("parcels") or []) if p.get("area_sqm")]
    if len(parcels) > 1:
        # Состав из нескольких ЗУ — построчно, как в тизере участка у владельца
        # (Походный, 5): у каждого номера своя площадь.
        for index, parcel in enumerate(parcels[:6], start=1):
            rows.append((f"  ЗУ {index} · {parcel.get('cadastral_number') or '—'}",
                         fm.num(float(parcel["area_sqm"]) / 10000.0, 4), "га"))
        if len(parcels) > 6:
            rows.append((f"  … и ещё {len(parcels) - 6} ЗУ", "", ""))
    rows.append(("Правовой статус", site.get("land_right") or "—", ""))
    if site.get("permitted_use"):
        rows.append(("Текущий ВРИ", site["permitted_use"], ""))
    if site.get("category"):
        rows.append(("Категория земель", site["category"], ""))
    rows.append(("Регион расчёта", site.get("region") or "—", ""))
    return rows


def _restrictions(site: dict[str, Any], st: _Styles, fm: _Formats) -> list[Any]:
    """Ограничения участка: вердикт скрининга и находки на самом участке.
    Не спрашивали — так и сказано; пустой ответ проверкой не является."""
    out: list[Any] = []
    if not site.get("screened"):
        out.append(Paragraph(f"{NOT_SCREENED_TEXT}: границы участка или ответ НСПД не получены.", st.note))
        return out
    if site.get("verdict_headline"):
        out.append(Paragraph(site["verdict_headline"], st.label_b))
    findings = list(site.get("findings") or [])
    for finding in findings[:5]:
        mark = FLAG_MARK.get(finding.get("flag_class") or "", "справка")
        share = finding.get("coverage_pct")
        tail = f" · ~{fm.num(share, 0)}% участка" if share is not None else ""
        out.append(Paragraph(f"• {mark} · {finding.get('name') or '—'}{tail}", st.label))
    if len(findings) > 5:
        out.append(Paragraph(f"… и ещё {len(findings) - 5}, все в полном отчёте", st.note))
    if not findings:
        out.append(Paragraph("В НСПД ограничений на участке не обнаружено.", st.label))
    if site.get("free_pct") is not None:
        out.append(Paragraph(f"Свободно от ограничений ~{fm.num(site['free_pct'], 0)}% площади участка.", st.note))
    return out


def _tep_rows(model: dict[str, Any], fm: _Formats) -> list[tuple[str, str, str]]:
    tep = model.get("tep") or {}
    site = model.get("site") or {}
    profile = model.get("profile") or {}
    land = model.get("land") or {}
    rows: list[tuple[str, str, str]] = [("Класс проекта", profile.get("project_class") or "—", "")]
    density = site.get("density_sqm_per_ha")
    gns = fm.sqm(tep.get("project_gns_sqm"))
    rows.append(("Наземная площадь ГНС", gns, "м²"))
    if density:
        rows.append(("Плотность застройки", fm.num(density, 0), "м²/га"))
    if tep.get("underground_gns_sqm"):
        rows.append(("Подземная часть", fm.sqm(tep.get("underground_gns_sqm")), "м²"))
    rows.append(("Строительный объём", fm.sqm(tep.get("construction_volume_sqm")), "м²"))
    rows.append(("Продаваемая площадь", fm.sqm(tep.get("saleable_sqm")), "м²"))
    apartments = tep.get("residential_saleable_sqm")
    if apartments:
        count = tep.get("apartments_count")
        rows.append(("  квартиры", fm.sqm(apartments)
                     + (f" · {fm.count(count)} шт." if count else ""), "м²"))
    if tep.get("commercial_saleable_sqm"):
        rows.append(("  коммерция 1-х этажей", fm.sqm(tep.get("commercial_saleable_sqm")), "м²"))
    units = tep.get("parking_units")
    if units:
        rows.append(("Машино-места", fm.count(units), "м/м"))
    if tep.get("transfer_sqm"):
        rows.append(("Передаётся (не продаётся)", fm.sqm(tep.get("transfer_sqm")), "м²"))
    places = []
    if land.get("kindergarten_places"):
        places.append(f"ДОО {fm.count(land['kindergarten_places'])} мест")
    if land.get("school_places"):
        places.append(f"школа {fm.count(land['school_places'])} мест")
    social = land.get("social_payment_mln")
    mode = land.get("social_payment_mode") or ""
    if places:
        rows.append(("Социальные объекты", ", ".join(places) + (f" · {mode.lower()}" if mode else ""), ""))
    if social:
        rows.append(("Социальная нагрузка", fm.mln(social), "млн ₽"))
    return rows


def _vri_rows(model: dict[str, Any], fm: _Formats) -> list[tuple[str, str, str]]:
    land = model.get("land") or {}
    rows: list[tuple[str, str, str]] = []
    amount = land.get("vri_amount_mln") or 0.0
    if land.get("vri_required") or amount:
        mode = {"lump": "разовый платёж", "installment": "рассрочка"}.get(land.get("vri_payment_mode") or "", "")
        rows.append(("Плата за смену ВРИ", fm.mln(amount), "млн ₽"))
        if mode:
            rows.append(("Порядок оплаты", mode, ""))
        if land.get("vri_relief_mln"):
            rows.append(("Льгота", fm.mln(land["vri_relief_mln"]), "млн ₽"))
        if land.get("vri_interest_mln"):
            rows.append(("Проценты по рассрочке", fm.mln(land["vri_interest_mln"]), "млн ₽"))
    else:
        rows.append(("Плата за смену ВРИ", "нет", ""))
    return rows


def _economy_rows(model: dict[str, Any], fm: _Formats) -> tuple[list[tuple[str, str, str]], tuple[int, ...]]:
    eff = model.get("efficiency") or {}
    land = model.get("land") or {}
    sales = model.get("sales_stats") or {}
    products = {p["key"]: p for p in (model.get("products") or [])}
    apartments = products.get("apartments") or {}
    costs = {c["label"]: c for c in (model.get("construction_costs") or [])}
    smr = costs.get("СМР наземной части") or {}
    rows: list[tuple[str, str, str]] = []
    rows.append(("Доходная часть", fm.mln(eff.get("revenue_mln")), "млн ₽"))
    if apartments.get("avg_price_th"):
        start = (f" (старт {fm.th(apartments['start_price_th'], 0)})" if apartments.get("start_price_th") else "")
        rows.append(("  ср. цена квартир" + start, fm.th(apartments["avg_price_th"], 0), "тыс ₽/м²"))
    rows.append(("Расходная часть (CAPEX)", fm.mln(eff.get("capex_mln")), "млн ₽"))
    if smr.get("per_gns_th"):
        rows.append(("  СМР наземной части", fm.th(smr["per_gns_th"], 0), "тыс ₽/м² ГНС"))
    rows.append(("Коммерческие расходы", fm.mln(eff.get("commercial_mln")), "млн ₽"))
    rows.append(("Стоимость финансирования", fm.mln(eff.get("financing_mln")), "млн ₽"))
    rows.append(("Налоги (прибыль и НДС)",
                 fm.mln(eff.get("tax_mln")) + " / " + fm.mln(eff.get("vat_mln")), "млн ₽"))
    rows.append(("EBITDA", fm.mln(eff.get("ebitda_mln")), "млн ₽"))
    rows.append(("Чистая прибыль", fm.mln(eff.get("net_profit_mln")), "млн ₽"))
    rows.append(("Маржинальность", fm.pct(eff.get("margin")), ""))
    rows.append(("LLCR (цель банка " + fm.x(model.get("llcr_target")) + ")", fm.x(eff.get("llcr")), ""))
    rows.append(("NPV собственного капитала", fm.mln(eff.get("npv_mln")), "млн ₽"))
    term = eff.get("term_months")
    rows.append(("Срок до РВЭ", fm.count(term) + (f" · {fm.num(term / 12, 2)} года" if term else ""), "мес."))
    entry = land.get("purchase_mln")
    per = land.get("purchase_per_saleable_th")
    rows.append(("Стоимость входа (цена участка)",
                 fm.mln(entry) + (f" · {fm.th(per, 0)} тыс ₽/м² прод." if per else ""), "млн ₽"))
    if sales.get("share_before_rve") is not None:
        rows.append(("Распроданность до ввода", fm.pct(sales.get("share_before_rve"), 0), ""))
    return rows, (8, 10, 13)


def _financing_rows(model: dict[str, Any], fm: _Formats) -> list[tuple[str, str, str]]:
    fin = model.get("financing") or {}
    rows: list[tuple[str, str, str]] = [
        ("Пик БРИДЖа", fm.mln(fin.get("peak_bridge_mln")), "млн ₽"),
        ("Проценты и комиссии БРИДЖа",
         fm.mln((fin.get("bridge_interest_mln") or 0.0) + (fin.get("bridge_fee_mln") or 0.0)), "млн ₽"),
        ("Пик ПФ", fm.mln(fin.get("peak_pf_mln")), "млн ₽"),
        ("Проценты ПФ", fm.mln(fin.get("pf_interest_mln")), "млн ₽"),
        ("Требуемый лимит ПФ", fm.mln(fin.get("pf_limit_required_mln")), "млн ₽"),
    ]
    if fin.get("pf_limit_approved_mln"):
        rows.append(("Одобренный лимит ПФ", fm.mln(fin["pf_limit_approved_mln"]), "млн ₽"))
    rows.append(("Собственные средства до ПФ", fm.mln(fin.get("own_funds_mln")), "млн ₽"))
    rows.append(("Макс. долг ПФ сверх эскроу", fm.mln(fin.get("peak_uncovered_pf_mln")), "млн ₽"))
    rows.append(("Ставки: ключевая / спред БРИДЖ / спред ПФ / спец.",
                 " / ".join([fm.pct(fin.get("current_key_rate")), fm.pct(fin.get("bridge_spread")),
                             (fm.num(fin.get("pf_spread_pp"), 1) + "%" if fin.get("pf_spread_pp") is not None else "—"),
                             fm.pct(fin.get("pf_special_rate"))]), ""))
    rows.append(("Средняя фактическая ставка ПФ", fm.pct(fin.get("avg_pf_effective_rate")), ""))
    return rows


def _risk_lines(model: dict[str, Any], st: _Styles, fm: _Formats) -> list[Any]:
    out: list[Any] = []
    active = [r for r in (model.get("risks") or []) if r.get("active")]
    for risk in active:
        unit = "x" if risk.get("value_key") in ("llcr", "weakest_phase_llcr") else "млн ₽"
        shown = fm.x(risk.get("value")) if unit == "x" else fm.mln(risk.get("value")) + " млн ₽"
        detail = f" ({risk['detail']})" if risk.get("detail") else ""
        out.append(Paragraph(f"• {risk['label']}: {shown}{detail}", st.risk_on))
    if not active:
        out.append(Paragraph("Рисков модель не нашла: дефолта в РВЭ нет, лимита хватает, "
                             "LLCR не ниже цели банка.", st.risk_off))
    return out


def _unit_economics_grid(model: dict[str, Any], width: float, st: _Styles, fm: _Formats) -> Table:
    rows = [[item["label"], fm.mln(item.get("total_mln")), fm.th(item.get("per_gns_th")),
             fm.th(item.get("per_saleable_th"))]
            for item in (model.get("unit_economics") or [])]
    return _grid(["Показатель", "млн ₽", "тыс ₽/м² ГНС", "тыс ₽/м² прод."], rows,
                 [width * 0.40, width * 0.20, width * 0.20, width * 0.20], st)


def _line_chart(rows: list[dict[str, Any]], width: float, height: float, st: _Styles,
                fm: _Formats) -> Drawing | None:
    """Кредит и эскроу по месяцам: три линии, эскроу с заливкой — как у образца.
    Линии не складываются: тело БРИДЖа, тело ПФ и счёт эскроу — три величины
    движка, и «долг» их суммой здесь не считается."""
    if not rows:
        return None
    series = [("bridge_mln", "БРИДЖ", BRIDGE_COLOR), ("pf_mln", "ПФ", PF_COLOR),
              ("escrow_mln", "Эскроу", ESCROW_COLOR)]
    values = [float(row.get(key) or 0.0) for row in rows for key, _, _ in series]
    maximum = max(values or [0.0])
    if maximum <= 0:
        return None
    maximum = _nice_ceiling(maximum * 1.05)
    left, right, bottom, top = 40, 8, 26, 22
    plot_w, plot_h = width - left - right, height - bottom - top
    d = Drawing(width, height)
    d.add(String(left, height - 9, f"{CHART_TITLE}, млн ₽", fontName=st.bold, fontSize=7.5, fillColor=NAVY))
    x_at = lambda i: left + plot_w * i / max(len(rows) - 1, 1)
    y_at = lambda v: bottom + plot_h * max(0.0, v) / maximum
    for tick in range(5):
        value = maximum * tick / 4
        y = y_at(value)
        d.add(Line(left, y, width - right, y, strokeColor=LINE, strokeWidth=0.4))
        d.add(String(left - 4, y - 2, fm.num(value, 0), fontName=st.regular, fontSize=6,
                     textAnchor="end", fillColor=GREY))
    escrow = [(x_at(i), y_at(float(row.get("escrow_mln") or 0.0))) for i, row in enumerate(rows)]
    if len(escrow) >= 2:
        area = [(escrow[0][0], bottom)] + escrow + [(escrow[-1][0], bottom)]
        flat = [c for point in area for c in point]
        d.add(Polygon(flat, fillColor=colors.Color(0.18, 0.42, 0.31, alpha=0.18), strokeColor=None))
    for key, _, color in series:
        points = [(x_at(i), y_at(float(row.get(key) or 0.0))) for i, row in enumerate(rows)]
        if len(points) >= 2:
            d.add(PolyLine(points, strokeColor=color, strokeWidth=1.6, fillColor=None))
    legend_x = left
    for _, label, color in series:
        d.add(Line(legend_x, 6, legend_x + 12, 6, strokeColor=color, strokeWidth=2))
        d.add(String(legend_x + 15, 3.5, label, fontName=st.regular, fontSize=6.3, fillColor=GREY))
        legend_x += 15 + 5 * len(label) + 12
    step = max(1, len(rows) // 6)
    for i in range(0, len(rows), step):
        d.add(String(x_at(i), bottom - 9, _quarter(rows[i].get("month")), fontName=st.regular,
                     fontSize=5.8, textAnchor="middle", fillColor=GREY))
    return d


def _gantt(model: dict[str, Any], width: float, st: _Styles) -> Drawing | None:
    """Сроки строительства и продаж по очередям — полосы на квартальной оси."""
    phases = [p for p in (model.get("phases") or []) if (p.get("dates") or {}).get("permit")]
    if not phases:
        dates = model.get("dates") or {}
        sales = model.get("sales") or {}
        phases = [{"name": "Проект", "dates": {"project_start": dates.get("project_start"),
                                               "permit": dates.get("permit"), "rve": dates.get("rve"),
                                               "sales_start": sales.get("start"), "sales_end": sales.get("end")}}]
    starts = [d for p in phases for d in ((p.get("dates") or {}).get("project_start"),
                                          (p.get("dates") or {}).get("permit")) if d]
    ends = [d for p in phases for d in ((p.get("dates") or {}).get("rve"),
                                        (p.get("dates") or {}).get("sales_end")) if d]
    if not starts or not ends:
        return None
    try:
        origin = date.fromisoformat(min(starts)[:10])
        last = date.fromisoformat(max(ends)[:10])
    except (TypeError, ValueError):
        return None
    total = max(_months_since(last.isoformat(), origin) or 1, 1) + 1
    label_w = 150
    row_h = 9
    left, right, top, bottom = label_w + 6, 8, 18, 14
    height = top + bottom + row_h * 2 * len(phases) + 4
    plot_w = width - left - right
    d = Drawing(width, height)
    d.add(String(2, height - 9, GANTT_TITLE, fontName=st.bold, fontSize=7.5, fillColor=NAVY))
    x_of = lambda m: left + plot_w * m / total
    quarter_step = 3 if total <= 48 else 6
    m = 0
    while m <= total:
        x = x_of(m)
        d.add(Line(x, bottom, x, height - top, strokeColor=LINE, strokeWidth=0.3))
        year = origin.year + (origin.month - 1 + m) // 12
        month = (origin.month - 1 + m) % 12 + 1
        d.add(String(x, bottom - 8, f"{(month - 1) // 3 + 1} кв {year}", fontName=st.regular,
                     fontSize=5.4, textAnchor="middle", fillColor=GREY))
        m += quarter_step
    y = height - top - row_h
    for phase in phases:
        dates = phase.get("dates") or {}
        for key_start, key_end, color, label in (("permit", "rve", NAVY_DARK, "стройка"),
                                                 ("sales_start", "sales_end", RED, "продажи")):
            a = _months_since(dates.get(key_start) or "", origin)
            b = _months_since(dates.get(key_end) or "", origin)
            span = ""
            if a is not None and b is not None and b >= a:
                d.add(Rect(x_of(a), y + 1, max(x_of(b) - x_of(a), 1.5), row_h - 3, fillColor=color,
                           strokeColor=None))
                span = f": {_quarter(dates.get(key_start))} — {_quarter(dates.get(key_end))}"
            d.add(String(2, y + 2, f"{phase.get('name') or 'Проект'} · {label}{span}", fontName=st.regular,
                         fontSize=6.0, fillColor=NAVY_DARK))
            y -= row_h
    return d


def _page_one(model: dict[str, Any], map_png: bytes | None, width: float, st: _Styles,
              fm: _Formats) -> list[Any]:
    site = model.get("site") or {}
    origin = model.get("origin") or {}
    subject = site.get("address") or ", ".join(site.get("cadastral_numbers") or []) or model.get("project_name")
    story: list[Any] = [_band(f"{PAGE1_TITLE} | {subject}", width, st)]
    story.append(Paragraph(
        f"{model.get('project_name') or 'Проект'} · расчёт {origin.get('calculation_id') or '—'} · "
        f"движок DevelopAid {origin.get('engine_version') or '—'} · {origin.get('generated_at') or ''}", st.sub))
    story.append(Spacer(1, 2 * mm))
    gutter = 5 * mm
    left_w = (width - gutter) * 0.47
    right_w = width - gutter - left_w

    left: list[Any] = [_section("Расположение", left_w, st)]
    left += _map_block(map_png, left_w, st, site)
    left.append(_section("Информация по земельному участку", left_w, st))
    left.append(_kv(_site_rows(site, model.get("tep") or {}, fm), left_w, st, label_share=0.36))
    left.append(Paragraph("Ограничения участка", st.h3))
    left += _restrictions(site, st, fm)
    left.append(_section("Смена ВРИ", left_w, st))
    left.append(_kv(_vri_rows(model, fm), left_w, st, label_share=0.48))
    left.append(_section("Финансирование", left_w, st))
    left.append(_kv(_financing_rows(model, fm), left_w, st, label_share=0.56))

    right: list[Any] = [_section("Расчётные ТЭП проекта", right_w, st)]
    right.append(_kv(_tep_rows(model, fm), right_w, st, label_share=0.42))
    right.append(_section("Экономика проекта", right_w, st))
    econ_rows, strong = _economy_rows(model, fm)
    right.append(_kv(econ_rows, right_w, st, label_share=0.56, bold_rows=strong))
    right.append(_section("Удельная экономика", right_w, st))
    right.append(_unit_economics_grid(model, right_w, st, fm))
    right.append(_section("Риски, которые модель нашла сама", right_w, st))
    right += _risk_lines(model, st, fm)

    columns = Table([[left, right]], colWidths=[left_w + gutter, right_w])
    columns.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (0, 0), gutter),
                                 ("RIGHTPADDING", (1, 0), (1, 0), 0),
                                 ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    story.append(columns)
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        "Числа посчитаны движком DevelopAid одним расчётом; тизер их не пересчитывает. "
        f"Отпечаток вводных: {origin.get('inputs_fingerprint') or origin.get('calculation_id') or '—'}. "
        "Подробности — на странице «Итог» и в полном отчёте.", st.note))
    return story


def _page_two(model: dict[str, Any], width: float, st: _Styles, fm: _Formats) -> list[Any]:
    site = model.get("site") or {}
    origin = model.get("origin") or {}
    subject = site.get("address") or ", ".join(site.get("cadastral_numbers") or []) or model.get("project_name")
    story: list[Any] = [_band(f"{PAGE2_TITLE} | {subject}", width, st)]
    story.append(Spacer(1, 2 * mm))
    gutter = 4 * mm
    col_w = (width - 2 * gutter) / 3
    eff = model.get("efficiency") or {}
    fin = model.get("financing") or {}
    tep = model.get("tep") or {}
    products = list(model.get("products") or [])

    # Колонка 1: эффективность и ТЭП по продуктам.
    term = eff.get("term_months")
    col1: list[Any] = [_section("Показатели эффективности проекта", col_w, st)]
    col1.append(_kv([
        ("EBITDA", fm.mln(eff.get("ebitda_mln")), "млн ₽"),
        ("Чистая прибыль", fm.mln(eff.get("net_profit_mln")), "млн ₽"),
        ("Operating margin", fm.pct(eff.get("margin")), ""),
        ("Equity IRR", fm.pct(eff.get("irr_equity")) if eff.get("irr_equity") is not None else "—", ""),
        ("NPV собственного капитала", fm.mln(eff.get("npv_mln")), "млн ₽"),
        ("Длительность до РВЭ", (fm.num(term / 12, 2) if term else "—"), "лет"),
        ("LLCR проекта", fm.x(eff.get("llcr")), ""),
        ("Полные расходы проекта", fm.mln(eff.get("full_project_cost_mln")), "млн ₽"),
    ], col_w, st, label_share=0.56, bold_rows=(6,)))
    col1.append(_section("ТЭП", col_w, st))
    tep_rows = [[p["label"], fm.sqm(p.get("gns")) if p.get("gns") else "—",
                 fm.sqm(p.get("saleable")) if p.get("saleable") else "—",
                 fm.count(p.get("quantity")) if p.get("unit") == "шт." else "—"] for p in products]
    tep_rows.append(["Итого", fm.sqm(tep.get("project_gns_sqm")), fm.sqm(tep.get("saleable_sqm")),
                     fm.count(tep.get("parking_units")) if tep.get("parking_units") else "—"])
    col1.append(_grid(["Продукт", "ГНС, м²", "Продаваемая, м²", "Единиц"], tep_rows,
                      [col_w * 0.40, col_w * 0.22, col_w * 0.22, col_w * 0.16], st, bold_last=True))
    taxes = model.get("taxes") or {}
    col1.append(_section("Финансовая деятельность и налоги", col_w, st))
    col1.append(_kv([
        ("Пик эскроу", fm.mln(fin.get("peak_escrow_mln")), "млн ₽"),
        ("Раскрыто эскроу в РВЭ", fm.mln(fin.get("rve_escrow_release_mln")), "млн ₽"),
        ("Проценты БРИДЖа", fm.mln(fin.get("bridge_interest_mln")), "млн ₽"),
        ("Комиссии БРИДЖа", fm.mln(fin.get("bridge_fee_mln")), "млн ₽"),
        ("Проценты ПФ", fm.mln(fin.get("pf_interest_mln")), "млн ₽"),
        ("Плата за лимит и резервирование ПФ",
         fm.mln((fin.get("pf_limit_fee_mln") or 0.0) + (fin.get("pf_reservation_fee_mln") or 0.0)), "млн ₽"),
        ("Налог на прибыль", fm.mln(taxes.get("profit_tax_mln")), "млн ₽"),
        ("НДС", fm.mln(taxes.get("vat_mln")), "млн ₽"),
    ], col_w, st, label_share=0.6))

    # Колонка 2: доходы, цены, темпы, график.
    col2: list[Any] = [_section("Доходы", col_w, st)]
    income_rows = []
    for p in products:
        if not p.get("revenue_mln"):
            continue
        per = (fm.th(p.get("per_unit_th"), 0) + " /шт." if p.get("per_unit_th") else fm.th(p.get("per_gns_th"), 0))
        income_rows.append([p["label"], fm.mln(p.get("revenue_mln")), per,
                            fm.th(p.get("per_saleable_th"), 0) if p.get("per_saleable_th") else "—"])
    income_rows.append(["Всего", fm.mln(eff.get("revenue_mln")),
                        fm.th(next((u.get("per_gns_th") for u in model.get("unit_economics") or []
                                    if u["label"] == "Выручка"), None), 0),
                        fm.th(next((u.get("per_saleable_th") for u in model.get("unit_economics") or []
                                    if u["label"] == "Выручка"), None), 0)])
    col2.append(_grid(["Продукт", "млн ₽", "тыс ₽/м² ГНС", "тыс ₽/м² прод."], income_rows,
                      [col_w * 0.37, col_w * 0.21, col_w * 0.21, col_w * 0.21], st, bold_last=True))
    col2.append(_section("Цены реализации и темп продаж", col_w, st))
    price_rows = []
    for p in products:
        if not p.get("avg_price_th"):
            continue
        unit = "тыс ₽/шт." if p.get("unit") == "шт." else "тыс ₽/м²"
        pace = p.get("pace_month")
        price_rows.append([p["label"], fm.th(p.get("avg_price_th"), 0), fm.th(p.get("start_price_th"), 0),
                           (fm.num(pace, 0) + ("/мес." if pace else "")) if pace else "—", unit])
    col2.append(_grid(["Продукт", "средняя", "старт", "темп", "ед."], price_rows,
                      [col_w * 0.34, col_w * 0.16, col_w * 0.16, col_w * 0.18, col_w * 0.16], st))
    chart = _line_chart(model.get("chart_rows") or [], col_w, 108, st, fm)
    if chart is not None:
        col2.append(Spacer(1, 2 * mm))
        col2.append(chart)

    # Колонка 3: себестоимость, структура расходов, финансовая деятельность, налоги.
    col3: list[Any] = [_section("Себестоимость строительства", col_w, st)]
    cost_rows = [[c["label"], fm.mln(c.get("total_mln")), fm.th(c.get("per_gns_th")), fm.th(c.get("per_saleable_th"))]
                 for c in (model.get("construction_costs") or [])]
    col3.append(_grid(["Статья", "млн ₽", "тыс ₽/м² ГНС", "тыс ₽/м² прод."], cost_rows,
                      [col_w * 0.49, col_w * 0.17, col_w * 0.17, col_w * 0.17], st))
    col3.append(_section("Структура расходов проекта", col_w, st))
    struct_rows = [[c["label"], fm.mln(c.get("total_mln")), fm.pct(c.get("share"), 0),
                    fm.th(c.get("per_saleable_th"))]
                   for c in (model.get("expense_structure") or [])]
    col3.append(_grid(["Статья", "млн ₽", "доля", "тыс ₽/м² прод."], struct_rows,
                      [col_w * 0.49, col_w * 0.17, col_w * 0.14, col_w * 0.20], st))

    columns = Table([[col1, col2, col3]], colWidths=[col_w + gutter, col_w + gutter, col_w])
    columns.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (1, 0), gutter),
                                 ("RIGHTPADDING", (2, 0), (2, 0), 0),
                                 ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    story.append(columns)
    gantt = _gantt(model, width, st)
    if gantt is not None:
        story.append(Spacer(1, 2 * mm))
        story.append(gantt)
    story.append(Paragraph(
        f"Расчёт {origin.get('calculation_id') or '—'} · движок DevelopAid {origin.get('engine_version') or '—'} "
        f"· {origin.get('generated_at') or ''}. Удельные показатели на метр ГНС (наземная площадь) и "
        "на метр продаваемой площади считает движок; тизер их не выводит сам.", st.note))
    return story


def build_teaser_pdf(presentation: dict[str, Any], fonts: tuple[str, str],
                     num: Callable[..., str], map_png: bytes | None = None) -> bytes:
    """Две страницы: «Девелоперский проект» (книжная) и «Итог» (альбомная).
    Ровно две — это проверяется: страница, уехавшая третьей, значит, что
    блок не влез, а не что тизер стал подробнее."""
    st = _Styles(fonts)
    fm = _Formats(num)
    margin = 10 * mm
    portrait_w = A4[0] - 2 * margin
    land_size = landscape(A4)
    landscape_w = land_size[0] - 2 * margin
    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=A4, rightMargin=margin, leftMargin=margin,
                          topMargin=margin, bottomMargin=margin, title=TEASER_TITLE, author="DevelopAid")
    doc.addPageTemplates([
        PageTemplate(id="portrait", pagesize=A4,
                     frames=[Frame(margin, margin, portrait_w, A4[1] - 2 * margin, id="p",
                                   leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)]),
        PageTemplate(id="landscape", pagesize=land_size,
                     frames=[Frame(margin, margin, landscape_w, land_size[1] - 2 * margin, id="l",
                                   leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)]),
    ])
    story: list[Any] = []
    story += _page_one(presentation, map_png, portrait_w, st, fm)
    story.append(NextPageTemplate("landscape"))
    story.append(PageBreak())
    story += _page_two(presentation, landscape_w, st, fm)
    doc.build(story)
    return buf.getvalue()

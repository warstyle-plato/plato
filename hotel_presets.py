"""Ориентиры эталонных моделей для полей гостиничного проекта — с происхождением.

Решение владельца (05.10.2026): ориентир чужой площадки не подставляется
молча. Поле гостиницы либо пустое с подсказкой-диапазоном (`hint_range`),
либо заполнено явным выбором ориентира — и тогда хранит, откуда число:
«ориентир: Отель 1 5*, Предпосылки!E393». Ручной ввод и ориентир на экране
различимы, а сохранённое значение ориентира не превращается в ручное.

Названия площадок на поверхностях не печатаются (владелец, 07.10.2026):
ориентиры зовутся «Отель 1 5*», «Отель 2 5*». Проект, сохранённый с прежними
ключами (`LEGACY_KEYS`), показывает происхождение по текущему ориентиру
(`current_origins`), а не сохранённым текстом.

Числа — только из `hotel_reference` (каждая ячейка сверена с книгой тестом).
Где поле — не одна ячейка, а расчёт из нескольких (средний ADR по типам
номеров, каналам и сезонам; доля F&B из чеков и посещаемости; расходы
департамента со взносами на ФОТ), формула и ячейки названы в происхождении.
Поле, которого в модели нет, в ориентир не входит и остаётся пустым: Отель 2
не даёт выручку F&B — значит её нет и в его ориентире, а не ноль.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import hotel_reference as ref

ORIGINS_KEY = "hotel_origins"


@dataclass(frozen=True)
class PresetValue:
    value: Any
    how: str                    # формула или ячейка, человеческим языком
    cells: tuple[str, ...]      # ключи `hotel_reference`


@dataclass(frozen=True)
class Preset:
    key: str
    title: str
    stars: str
    model: str
    values: dict[str, PresetValue]

    def origin(self, field: str) -> dict[str, Any]:
        item = self.values[field]
        return {"preset": self.key, "text": f"ориентир: {self.title}, {item.how}",
                "cells": list(item.cells)}


def _v(model: str, address: str) -> float:
    return ref.value(f"{model}:{address}")


def _cell(model: str, address: str, scale: float = 1.0, how: str = "") -> PresetValue:
    return PresetValue(_v(model, address) * scale, how or address, (f"{model}:{address}",))


def _sum(model: str, addresses: tuple[str, ...]) -> float:
    return sum(_v(model, a) for a in addresses)


def _dombai() -> Preset:
    d = ref.DOMBAI
    k = lambda a: f"{d}:{a}"  # noqa: E731
    # Средний ADR (без НДС, цены 2025): стандарт E419 × наценки типов номеров,
    # взвешенные номерным фондом; × каналы продаж (доля × цена к прямой);
    # × сезоны (коэффициент цены × доля дней года). Книга ведёт ADR той же
    # цепочкой (Расчеты!819), сезон — средневзвешенно по дням.
    mix_rooms = ("Предпосылки!E118", "Предпосылки!E119", "Предпосылки!E120", "Предпосылки!E121")
    mix_premia = ("Предпосылки!E422", "Предпосылки!E423", "Предпосылки!E424", "Предпосылки!E425")
    rooms = [_v(d, a) for a in mix_rooms]
    premia = [_v(d, a) for a in mix_premia]
    room_factor = sum(n * (1 + p) for n, p in zip(rooms, premia)) / sum(rooms)
    channels = (("Предпосылки!E435", "Предпосылки!E441"), ("Предпосылки!E436", "Предпосылки!E442"),
                ("Предпосылки!E437", "Предпосылки!E443"))
    channel_factor = sum(_v(d, s) * _v(d, c) for s, c in channels)
    seasons = (("Предпосылки!E446", "Предпосылки!E451"), ("Предпосылки!E447", "Предпосылки!E452"),
               ("Предпосылки!E448", "Предпосылки!E453"))
    season_factor = sum(_v(d, c) * _v(d, s) for c, s in seasons)
    adr_2025 = _v(d, "Предпосылки!E419") * room_factor * channel_factor * season_factor
    cpi = ("Предпосылки!M58", "Предпосылки!N58", "Предпосылки!O58")
    cpi_factor = 1.0
    for a in cpi:
        cpi_factor *= 1 + _v(d, a)
    adr_cells = (("Предпосылки!E419",) + mix_rooms + mix_premia
                 + tuple(a for pair in channels for a in pair)
                 + tuple(a for pair in seasons for a in pair) + cpi)
    # F&B на проданный номер: гостей на номер × Σ(доля гостей × чек), к ADR
    # тех же цен 2025. Банкеты (15 в год) в долю не входят.
    meals = (("Предпосылки!E500", "Предпосылки!E520"), ("Предпосылки!E501", "Предпосылки!E521"),
             ("Предпосылки!E502", "Предпосылки!E522"), ("Предпосылки!E503", "Предпосылки!E523"),
             ("Предпосылки!E507", "Предпосылки!E527"))
    spend = _v(d, "Предпосылки!E398") * sum(_v(d, s) * _v(d, c) for s, c in meals)
    fnb_cells = ("Предпосылки!E398",) + tuple(a for pair in meals for a in pair) + adr_cells[:-3]
    contrib_cells = ("Предпосылки!E808", "Предпосылки!E809", "Предпосылки!E810", "Предпосылки!E811")
    payroll = 1 + _sum(d, contrib_cells)
    rooms_cost = _v(d, "Предпосылки!E615") + _v(d, "Предпосылки!E616") * payroll
    fnb_cost = (_v(d, "Предпосылки!E619") + _v(d, "Предпосылки!E620")
                + _v(d, "Предпосылки!E621") * payroll)
    spa = _v(d, "Предпосылки!E624") + _v(d, "Предпосылки!E625") + _v(d, "Предпосылки!E626") * payroll
    mice = _v(d, "Предпосылки!E629") + _v(d, "Предпосылки!E630") * payroll
    misc = _v(d, "Предпосылки!E633") + _v(d, "Предпосылки!E634") * payroll
    other_cost = ((_v(d, "Предпосылки!E532") * spa + _v(d, "Предпосылки!E533") * mice
                   + _v(d, "Предпосылки!E534") * misc) / _v(d, "Предпосылки!E536"))
    vat = 1 + _v(d, "Предпосылки!E775")
    keys = _v(d, "Предпосылки!E116")
    ffe = _v(d, "Предпосылки!E294")
    building = _v(d, "Предпосылки!E299") - ffe
    reserve = next(x for x in ref.DERIVED if x.numerator == k("Расчеты!I1109"))
    values = {
        "stars": PresetValue("5", "класс модели (5*)", ()),
        "keys": _cell(d, "Предпосылки!E116"),
        "gba_sqm": _cell(d, "Предпосылки!E92", how="Предпосылки!E92 (ГНС с паркингом)"),
        "cost_th_per_sqm": PresetValue(
            building / _v(d, "Предпосылки!E92") * vat,
            "(Предпосылки!E299 − E294) ÷ E92 × (1 + E775): CAPEX отеля без мебели, "
            "базовые цены 2025, с НДС",
            (k("Предпосылки!E299"), k("Предпосылки!E294"), k("Предпосылки!E92"),
             k("Предпосылки!E775"))),
        "ffe_th_per_key": PresetValue(
            ffe / keys * vat, "Предпосылки!E294 ÷ E116 × (1 + E775): базовые цены 2025, с НДС",
            (k("Предпосылки!E294"), k("Предпосылки!E116"), k("Предпосылки!E775"))),
        "adr_rub": PresetValue(
            adr_2025 * cpi_factor,
            "Предпосылки!E419 × типы номеров (E118:E121, E422:E425) × каналы "
            "(E435:E437, E441:E443) × сезоны (E446:E448, E451:E453) × ИПЦ 2026–2028 "
            "(M58:O58); без НДС, цены 01.2029",
            tuple(k(a) for a in adr_cells)),
        "adr_price_date": PresetValue("2029-01-01", "цены на ввод (Предпосылки!E24)", ()),
        "index_pct": _cell(d, "Предпосылки!P58", 100, "Предпосылки!P58 (ИПЦ 2029 и далее)"),
        "occ_start_pct": _cell(d, "Предпосылки!E393", 100),
        "occ_target_pct": _cell(d, "Предпосылки!E392", 100),
        "ramp_months": _cell(d, "Предпосылки!E394", 3, "Предпосылки!E394 кварталов × 3"),
        "fnb_pct": PresetValue(
            spend / adr_2025 * 100,
            "гостей на номер E398 × Σ(доля гостей × чек: E500:E507, E520:E527) ÷ ADR "
            "тех же цен 2025",
            tuple(k(a) for a in fnb_cells)),
        "other_pct": _cell(d, "Предпосылки!E536", 100, "Предпосылки!E536 (SPA + MICE + прочее)"),
        "rooms_cost_pct": PresetValue(
            rooms_cost * 100, "E615 + E616 × (1 + взносы E808:E811)",
            tuple(k(a) for a in ("Предпосылки!E615", "Предпосылки!E616") + contrib_cells)),
        "fnb_cost_pct": PresetValue(
            fnb_cost * 100, "E619 + E620 + E621 × (1 + взносы E808:E811)",
            tuple(k(a) for a in ("Предпосылки!E619", "Предпосылки!E620", "Предпосылки!E621")
                  + contrib_cells)),
        "other_cost_pct": PresetValue(
            other_cost * 100,
            "SPA (E624:E626), MICE (E629:E630), прочее (E633:E634) с взносами E808:E811, "
            "взвешенные долями выручки E532:E534",
            tuple(k(a) for a in ("Предпосылки!E624", "Предпосылки!E625", "Предпосылки!E626",
                                 "Предпосылки!E629", "Предпосылки!E630", "Предпосылки!E633",
                                 "Предпосылки!E634", "Предпосылки!E532", "Предпосылки!E533",
                                 "Предпосылки!E534", "Предпосылки!E536") + contrib_cells)),
        "ag_pct": PresetValue(
            (_v(d, "Предпосылки!E638") + _v(d, "Предпосылки!E639")) * 100,
            "Предпосылки!E638 + E639 (административные + IT)",
            (k("Предпосылки!E638"), k("Предпосылки!E639"))),
        "sm_pct": _cell(d, "Предпосылки!E640", 100),
        "pom_pct": _cell(d, "Предпосылки!E642", 100),
        "utilities_pct": _cell(d, "Предпосылки!E641", 100),
        "base_fee_pct": PresetValue(
            _sum(d, ("Предпосылки!E646", "Предпосылки!E647", "Предпосылки!E648")) * 100,
            "Предпосылки!E646 + E647 + E648 (базовое, маркетинговое, лицензионное)",
            (k("Предпосылки!E646"), k("Предпосылки!E647"), k("Предпосылки!E648"))),
        "incentive_fee_pct": _cell(d, "Предпосылки!E650", 100),
        "ffe_reserve_pct": PresetValue(
            reserve.value * 100, "Расчеты!I1109 ÷ I1102 (среднее за срок; книга — ступенями)",
            (reserve.numerator, reserve.denominator)),
        "vat_relief_years": _cell(d, "Предпосылки!E777"),
        "property_tax_pct": _cell(d, "Предпосылки!E792", 100),
        "insurance_pct": _cell(d, "Предпосылки!E685", 100),
        "building_years": _cell(d, "Предпосылки!E373"),
        "ffe_years": _cell(d, "Предпосылки!E374"),
        "financing": PresetValue("preferential", "Предпосылки!E725:E726 (ставка = доля КС + маржа)",
                                 (k("Предпосылки!E725"), k("Предпосылки!E726"))),
        "loan_share_pct": _cell(d, "Предпосылки!E703", 100),
        "pref_key_share_pct": _cell(d, "Предпосылки!E726", 100),
        "pref_margin_pp": _cell(d, "Предпосылки!E725", 100),
        "loan_limit_th_per_key": PresetValue(
            _v(d, "Контр_панель!J117") / keys, "Контр_панель!J117 ÷ Предпосылки!E116",
            (k("Контр_панель!J117"), k("Предпосылки!E116"))),
        "loan_fee_pct": _cell(d, "Предпосылки!E728", 100),
        "loan_term_years": _cell(d, "Предпосылки!E719"),
        "grace_months": _cell(d, "Предпосылки!E720", 3, "Предпосылки!E720 кварталов × 3"),
        "repayment": PresetValue("sculpted", "скульптурное погашение под DSCR (E712, E730)",
                                 (k("Предпосылки!E730"),)),
        "dscr_target": _cell(d, "Предпосылки!E730"),
        "hold_years": _cell(d, "Предпосылки!E20"),
        "exit_mode": PresetValue("sale", "терминальная стоимость в конце срока (E759)", ()),
        "valuation": PresetValue("ev_ebitda", "EV/EBITDA на выходе (E758)", (k("Предпосылки!E758"),)),
        "exit_multiple": _cell(d, "Предпосылки!E758"),
    }
    return Preset("hotel1", "Отель 1 5*", "5", d, values)


def _uai() -> Preset:
    u = ref.UAI
    values = {
        "stars": PresetValue("5", "класс модели (5*)", ()),
        "keys": _cell(u, "Предпосылки!E111"),
        "adr_rub": _cell(u, "Расчеты!E630", how="Расчеты!E630 (ADR без НДС расчётный)"),
        "occ_start_pct": _cell(u, "Предпосылки!E386", 100),
        "occ_target_pct": _cell(u, "Предпосылки!E385", 100),
        "ramp_months": _cell(u, "Предпосылки!E387", 3, "Предпосылки!E387 кварталов × 3"),
        "ag_pct": _cell(u, "Предпосылки!E504", 100),
        "sm_pct": _cell(u, "Предпосылки!E506", 100),
        "utilities_pct": _cell(u, "Предпосылки!E507", 100),
        "pom_pct": _cell(u, "Предпосылки!E508", 100),
        "base_fee_pct": _cell(u, "Предпосылки!E512", 100),
        "incentive_fee_pct": _cell(u, "Предпосылки!E516", 100),
        "financing": PresetValue("preferential", "Предпосылки!E591:E592 (ставка = доля КС + маржа)",
                                 (f"{u}:Предпосылки!E591", f"{u}:Предпосылки!E592")),
        "pref_key_share_pct": _cell(u, "Предпосылки!E592", 100),
        "pref_margin_pp": _cell(u, "Предпосылки!E591", 100),
        "loan_share_pct": _cell(u, "Контр_панель!J115", 100),
        "loan_term_years": _cell(u, "Предпосылки!E585"),
        "grace_months": _cell(u, "Предпосылки!E586", 3, "Предпосылки!E586 кварталов × 3"),
    }
    return Preset("hotel2", "Отель 2 5*", "5", u, values)


PRESETS: tuple[Preset, ...] = (_dombai(), _uai())
BY_KEY: dict[str, Preset] = {p.key: p for p in PRESETS}
# Ключи ориентиров до обезличивания (07.10.2026) — их несут сохранённые проекты.
LEGACY_KEYS: dict[str, str] = {"dombai": "hotel1", "uai": "hotel2"}


def preset_for(key: Any) -> Preset | None:
    """Ориентир по ключу — текущему или прежнему."""
    key = str(key or "")
    return BY_KEY.get(LEGACY_KEYS.get(key, key))


def current_origins(origins: dict[str, Any] | None) -> dict[str, Any]:
    """Происхождение полей по ТЕКУЩЕМУ ориентиру.

    Сохранённая запись несёт ключ ориентира; текст и ячейки собираются заново
    от него — так подпись ориентира (и его обезличенное имя) одна на все
    поверхности, а проект, сохранённый раньше, не печатает прежний текст.
    Запись без известного ориентира остаётся как есть.
    """
    out: dict[str, Any] = {}
    for field, origin in (origins or {}).items():
        preset = preset_for((origin or {}).get("preset")) if isinstance(origin, dict) else None
        out[field] = preset.origin(field) if preset and field in preset.values else origin
    return out


def apply_preset(inputs: dict[str, Any], key: str, *, only_empty: bool = False
                 ) -> dict[str, Any]:
    """Вводные с ориентиром `key` и его происхождением.

    Каждое заполненное поле получает запись в `hotel_origins`; поле, которого
    в ориентире нет, не трогается. `only_empty` — заполнить только пустые:
    набранное руками ориентир не перетирает.
    """
    preset = preset_for(key)
    if preset is None:
        raise KeyError(key)
    x = dict(inputs or {})
    origins = dict(x.get(ORIGINS_KEY) or {})
    for field, item in preset.values.items():
        name = "hotel_" + field
        if only_empty and x.get(name) not in (None, ""):
            continue
        value = item.value
        if isinstance(value, float):
            value = round(value, 6)
        x[name] = value
        origins[field] = preset.origin(field)
    x[ORIGINS_KEY] = origins
    return x


def hint_range(field: str, stars: str | None = None) -> dict[str, Any] | None:
    """Подсказка пустого поля: диапазон ориентиров (по классу, если задан)."""
    items = [(p, p.values[field]) for p in PRESETS
             if field in p.values and isinstance(p.values[field].value, (int, float))
             and (not stars or p.stars == str(stars))]
    if not items:
        return None
    values = [float(v.value) for _, v in items]
    return {"min": min(values), "max": max(values),
            "sources": [p.title for p, _ in items]}


def presets_for_page() -> list[dict[str, Any]]:
    """Ориентиры для страницы: значения и происхождение, без логики."""
    return [{"key": p.key, "title": p.title, "stars": p.stars,
             "values": {f: v.value if not isinstance(v.value, float) else round(v.value, 6)
                        for f, v in p.values.items()},
             "origins": {f: p.origin(f) for f in p.values}}
            for p in PRESETS]

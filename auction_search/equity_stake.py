"""Лоты о продаже доли в юридическом лице.

Задача владельца (01.09.2026): «надо посмотреть ещё лоты по продаже долей в
юр лицах. С критериями возможными: стартовая цена 100 млн рублей за долю и от
500 за 100% долей. Доп критерий — если в лоте упоминается активы юр лица и там
есть недвижка или ЗУ».

Почему это отдельный вид лота, а не разновидность имущественного комплекса.
Покупая долю, покупают ОБЩЕСТВО — вместе с его обязательствами, историей и
налоговой базой, — а не участок. Сроки, риск и проверка у такой сделки другие,
и складывать её в один вид с продажей самого объекта значит подписать две
разные сделки одним именем. До сих пор так и было: доля со словом «земельный
участок» рядом опознавалась как имущественный комплекс.

Три вещи, которые здесь намеренно НЕ делаются.

Неназванная доля не считается стопроцентной. Порог у неё тогда нижний (100 млн)
и это сказано вслух: выбрать за продавца больший порог значит выбросить лот,
о размере доли которого он просто не написал.

Неопубликованная цена — не «дёшево» и не «дорого», а «не знаем». Такой лот
критерий цены не проходит и не заваливает: у него нет ответа.

Активы — доп. критерий, а не ворота. Их отсутствие в описании значит «не
описаны», а не «их нет»: то же правило, по которому пустой ответ НСПД не
читается как отсутствие ограничений. Поэтому лот без описания активов остаётся
в выдаче с названной пометкой, а не исчезает.
"""

from __future__ import annotations

import re
from typing import Any

# Пороги владельца. Объявлены здесь один раз: вписанные в фильтр на странице,
# они стали бы вторым ответом на тот же вопрос.
PART_STAKE_MIN_RUB = 100_000_000.0
FULL_STAKE_MIN_RUB = 500_000_000.0

# Доля в юрлице названа. Слово «доля» само по себе не годится — «доля в праве
# общей собственности» это про недвижимость, а не про общество.
_EQUITY_RE = re.compile(
    r"(?:дол\w*\s+(?:в\s+)?(?:уставн\w*\s+капитал\w*|ооо|общества)"
    r"|уставн\w*\s+капитал\w*"
    r"|\bакци\w*\b"
    r"|пакет\w*\s+акци\w*"
    r"|100\s*(?:\([^)]{0,40}\)\s*)?%\s*дол\w*)",
    re.I,
)
# «Доля в праве общей долевой собственности» — это недвижимость, а не общество.
_NOT_EQUITY_RE = re.compile(
    r"дол\w*\s+в\s+прав\w*\s+(?:общ\w*|долев\w*|собственност\w*)", re.I)

# Размер доли. Граница числа задана явно: «26,856 млн» уже читалось как 856 —
# шаблон начинал сопоставление с середины, и результат оставался правдоподобным.
_PERCENT_RE = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:[.,]\d{1,4})?)\s*(?:\([^)]{0,40}\)\s*)?%", re.I)
_FRACTION_RE = re.compile(
    r"дол\w*[^.;)]{0,40}?(?<![\d/])(\d{1,3})\s*/\s*(\d{1,3})(?![\d/])", re.I)

# Активы общества. Признак ставится с цитатой — как в разборе публикаций.
_ASSETS_RE = re.compile(
    r"(?:актив\w*|имуществ\w*\s+(?:общества|компании|должника)|на\s+баланс\w*"
    r"|принадлежащ\w*\s+обществу|в\s+собственност\w*\s+общества)", re.I)
_REALTY_RE = re.compile(
    r"(?:недвижим\w*|здани\w*|строени\w*|сооружени\w*|помещени\w*|нежил\w*\s+фонд"
    r"|объект\w*\s+незавершенн\w*\s+строительств\w*|незавершенн\w*\s+строительств\w*)",
    re.I)
_LAND_RE = re.compile(r"(?:земельн\w*\s+участ\w*|\bзу\b|земл\w*\s+в\s+собственност\w*)", re.I)
_CADASTRAL_RE = re.compile(r"\b\d{2}:\d{2}:\d{6,7}:\d+\b")

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+")


def _text(lot: Any) -> str:
    """Всё, что о лоте написано словами. Документы — тоже слова о лоте."""
    if isinstance(lot, dict):
        parts = [lot.get("title") or "", lot.get("procedure_type") or "",
                 lot.get("permitted_use") or "", lot.get("address") or ""]
        parts += [str(d.get("title") or "") for d in (lot.get("documents") or [])
                  if isinstance(d, dict)]
        parts += [str(v) for v in (lot.get("cadastral_numbers") or [])]
        return " ".join(p for p in parts if p)
    parts = [getattr(lot, "title", "") or "", getattr(lot, "procedure_type", "") or "",
             getattr(lot, "permitted_use", "") or "", getattr(lot, "address", "") or ""]
    parts += [getattr(d, "title", "") or "" for d in (getattr(lot, "documents", None) or [])]
    parts += [str(v) for v in (getattr(lot, "cadastral_numbers", None) or [])]
    return " ".join(p for p in parts if p)


def is_equity_lot(text: str) -> bool:
    """Продаётся ли здесь доля в обществе, а не сам объект."""
    flat = re.sub(r"\s+", " ", str(text or ""))
    if not _EQUITY_RE.search(flat):
        return False
    # «Доля в праве общей собственности» — недвижимость. Если о капитале или
    # акциях речи нет вовсе, это не наш лот.
    if _NOT_EQUITY_RE.search(flat) and not re.search(
            r"(?:уставн\w*\s+капитал\w*|\bакци\w*\b)", flat, re.I):
        return False
    return True


def share_percent(text: str) -> float | None:
    """Размер доли в процентах. `None` — не названа, и это не «сто».

    Неназванная доля читается нижним порогом, а не верхним: выбрать за продавца
    больший порог значит выбросить лот, о доле которого он не написал.
    """
    flat = re.sub(r"\s+", " ", str(text or ""))
    best: float | None = None
    for match in _PERCENT_RE.finditer(flat):
        try:
            value = float(match.group(1).replace(",", "."))
        except ValueError:
            continue
        if not 0 < value <= 100:
            continue
        best = value if best is None else max(best, value)
    if best is not None:
        return best
    fraction = _FRACTION_RE.search(flat)
    if fraction:
        top, bottom = float(fraction.group(1)), float(fraction.group(2))
        if bottom > 0 and 0 < top <= bottom:
            return round(top / bottom * 100, 2)
    return None


def _quote(flat: str, pattern: re.Pattern[str]) -> str:
    """Предложение, в котором признак и нашёлся. Без цитаты признака нет."""
    for sentence in _SENTENCE_SPLIT.split(flat):
        if pattern.search(sentence):
            return sentence.strip()[:300]
    found = pattern.search(flat)
    return flat[max(0, found.start() - 60):found.end() + 60].strip()[:300] if found else ""


def assets(lot: Any) -> dict[str, Any]:
    """Что сказано об активах общества.

    Доп. критерий владельца: интересна доля, за которой стоит недвижимость или
    земля. Пустое описание — «активы не описаны», а не «активов нет».
    """
    flat = re.sub(r"\s+", " ", _text(lot))
    cadastral = bool(_CADASTRAL_RE.search(flat)) or bool(
        (lot.get("cadastral_numbers") if isinstance(lot, dict)
         else getattr(lot, "cadastral_numbers", None)) or [])
    realty = bool(_REALTY_RE.search(flat))
    land = bool(_LAND_RE.search(flat)) or cadastral
    mentioned = bool(_ASSETS_RE.search(flat)) or realty or land
    out: dict[str, Any] = {
        "mentioned": mentioned,
        "real_estate": realty,
        "land": land,
        "cadastral": cadastral,
        "quotes": [],
    }
    for label, pattern in (("недвижимость", _REALTY_RE), ("земельный участок", _LAND_RE),
                           ("активы общества", _ASSETS_RE)):
        if pattern.search(flat):
            out["quotes"].append({"label": label, "quote": _quote(flat, pattern)})
    return out


def price_gate(price_rub: float | None, share_pct: float | None) -> dict[str, Any]:
    """Проходит ли лот по цене. Ответов три: да, нет и «цена не опубликована»."""
    full = share_pct is not None and share_pct >= 100
    floor = FULL_STAKE_MIN_RUB if full else PART_STAKE_MIN_RUB
    label = "100% долей" if full else ("доля " + _pct(share_pct) if share_pct is not None
                                       else "доля не названа")
    if price_rub is None:
        return {"ok": None, "floor_rub": floor, "share_label": label,
                "why": "цена не опубликована — критерий цены не применён"}
    ok = float(price_rub) >= floor
    return {
        "ok": ok,
        "floor_rub": floor,
        "share_label": label,
        "why": (f"{label}: порог {_mln(floor)} млн ₽, "
                f"стартовая {_mln(price_rub)} млн ₽ — "
                + ("проходит" if ok else "ниже порога")),
    }


def _pct(value: float | None) -> str:
    if value is None:
        return "не названа"
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{text}%".replace(".", ",")


def _mln(value: float) -> str:
    return f"{value / 1e6:,.0f}".replace(",", " ")


def screen(lot: Any) -> dict[str, Any]:
    """Разбор лота о доле. Не лот о доле — так и сказано, без выдумок."""
    text = _text(lot)
    if not is_equity_lot(text):
        return {"is_equity": False}
    price = lot.get("start_price_rub") if isinstance(lot, dict) else getattr(
        lot, "start_price_rub", None)
    if price is None:
        price = (lot.get("current_price_rub") if isinstance(lot, dict)
                 else getattr(lot, "current_price_rub", None))
    share = share_percent(text)
    gate = price_gate(float(price) if price is not None else None, share)
    found = assets(lot)
    why: list[str] = [gate["why"]]
    if found["real_estate"] or found["land"]:
        why.append("в лоте названы активы общества: "
                   + ", ".join(part for part, on in (("недвижимость", found["real_estate"]),
                                                     ("земельный участок", found["land"])) if on))
    elif found["mentioned"]:
        why.append("активы общества упомянуты, но недвижимости и земли среди них не названо")
    else:
        why.append("активы общества в лоте не описаны — это «не знаем», а не «их нет»")
    return {
        "is_equity": True,
        "share_pct": share,
        "share_named": share is not None,
        "price_ok": gate["ok"],
        "price_floor_rub": gate["floor_rub"],
        "share_label": gate["share_label"],
        "assets": found,
        # Доп. критерий владельца выполнен: за долей стоит недвижимость или земля.
        "asset_match": bool(found["real_estate"] or found["land"]),
        "why": why,
    }

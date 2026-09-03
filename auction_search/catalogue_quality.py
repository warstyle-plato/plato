"""Допуск лота в основную девелоперскую подборку.

Соответствие профилю и полнота карточки отвечают на разные вопросы. Балл
показывает, похож ли измеренный лот на реальные сделки владельца; допуск
проверяет, есть ли вообще что измерять. Раньше карточка без адреса, площади и
понятной цены оставалась в основном списке с ``fit=None``. Это честное
``неизвестно`` в карточке, но ложное ``перспективный лот`` в каталоге.

Неполные лоты не уничтожаются: ``include_noise=true`` возвращает их вместе с
названной причиной. Основная выдача показывает только ``ready``.
"""

from __future__ import annotations

from typing import Any

from auction_search.models import AuctionLot, LotKind
from auction_search.profile_fit import profile_fit


# Нижняя граница взята не с потолка: 0,70 означает, что обе обязательные
# измеренные стороны (масштаб и цена) находятся хотя бы у нижнего края
# фактических сделок. Более крупные лоты не штрафуются.
MIN_PROFILE_FIT = 0.70


def _positive(*values: Any) -> float | None:
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return None


def catalogue_quality(lot: AuctionLot) -> dict[str, Any]:
    """Вернуть воспроизводимый допуск и все причины отказа.

    В discovery документы намеренно разбираются только после выбора лота,
    поэтому их наличие не является обязательным. Обязательны факты, без
    которых нельзя ни сопоставить объект с эталоном, ни начать проверку:
    местоположение, масштаб, цена и признак актуальности процедуры.
    """

    # У доли в юрлице масштаб меряется не метрами. Площади участка у такого
    # лота нет и не бывает, адрес часто тоже — продаётся общество, а не объект.
    # Прежние требования выбросили бы весь вид целиком, то есть ответили бы
    # «таких лотов нет» на «мы их не умеем мерить». Владелец назвал для них
    # свой критерий (01.09.2026): опубликованная цена и её порог — 100 млн ₽ за
    # долю, 500 млн ₽ за 100%. Активы общества остаются доп. критерием и в
    # ворота не идут: «не описаны» значит «не знаем», а не «их нет».
    if lot.lot_kind is LotKind.EQUITY_STAKE:
        return _equity_quality(lot)

    # У лота КРТ продаётся ПРАВО на заключение договора, а не сам актив, и
    # стартовая цена этого права ничего не говорит о масштабе площадки: на
    # живой выдаче 03.09.2026 Шипиловский пр-д, влд. 55 (6,61 га) стоил
    # 4,1 млн ₽, а Нижние Поля (8,97 га) — 9,3 млн, и оба выпадали из
    # подборки «ниже профиля сделок». Эталон снят со 121 сделки ПОКУПКИ
    # недвижимости (48…931 млн ₽) — мерить им цену права значит сравнивать
    # разные величины, ровно как «продукты» отчёта с построенными местами.
    # Масштаб у КРТ меряется гектарами и объёмом строительства, и он у этих
    # лотов известен.
    if lot.lot_kind is LotKind.KRT:
        return _krt_quality(lot)

    missing: list[str] = []
    if not ((lot.address or "").strip() or lot.cadastral_numbers):
        missing.append("нет адреса или кадастрового номера")
    if _positive(lot.land_area_sqm, lot.building_area_sqm) is None:
        missing.append("нет площади земли или строений")
    if _positive(lot.current_price_rub, lot.start_price_rub, lot.min_price_rub) is None:
        missing.append("нет опубликованной цены")
    if not ((lot.application_deadline or "").strip() or (lot.status or "").strip()):
        missing.append("нет срока подачи заявки или статуса торгов")
    if lot.lot_kind is LotKind.OTHER:
        missing.append("не определён девелоперский тип объекта")

    fit = profile_fit(lot.to_dict())
    reasons = list(missing)
    state = "ready"
    accepted = True
    if missing:
        state = "incomplete"
        accepted = False
    elif fit.get("fit") is None or int(fit.get("measured") or 0) < 2:
        state = "incomplete"
        accepted = False
        reasons.append("для сравнения с реальными сделками измерено меньше двух показателей")
    elif float(fit["fit"]) < MIN_PROFILE_FIT:
        state = "outside_profile"
        accepted = False
        reasons.extend(fit.get("misses") or ["масштаб и цена ниже профиля реальных сделок"])

    return {
        "accepted": accepted,
        "state": state,
        "label": {
            "ready": "Основная подборка",
            "incomplete": "Не хватает данных",
            "outside_profile": "Ниже профиля сделок",
        }[state],
        "reasons": reasons,
        "required": ["местоположение", "площадь", "цена", "актуальность"],
        "minimum_profile_fit": MIN_PROFILE_FIT,
        "fit": fit,
    }


def _equity_quality(lot: AuctionLot) -> dict[str, Any]:
    """Допуск лота о доле: цена опубликована и проходит порог владельца."""
    from auction_search import equity_stake

    screened = equity_stake.screen(lot)
    reasons: list[str] = []
    state = "ready"
    accepted = True
    if screened.get("price_ok") is None:
        state, accepted = "incomplete", False
        reasons.append("нет опубликованной цены — порог по цене не применить")
    elif screened.get("price_ok") is False:
        state, accepted = "outside_profile", False
        reasons.extend(screened.get("why") or ["стартовая цена ниже порога"])
    if not ((lot.application_deadline or "").strip() or (lot.status or "").strip()):
        state, accepted = "incomplete", False
        reasons.append("нет срока подачи заявки или статуса торгов")
    return {
        "accepted": accepted,
        "state": state,
        "label": {
            "ready": "Основная подборка",
            "incomplete": "Не хватает данных",
            "outside_profile": "Мимо профиля",
        }[state],
        "reasons": reasons,
        "min_profile_fit": None,
        "fit": None,
        # Мера у этого вида своя, и она названа: не метры, а цена и активы.
        "measured_by": "цена доли и активы общества",
        "equity": screened,
    }


def _krt_quality(lot: AuctionLot) -> dict[str, Any]:
    """Допуск площадки КРТ: местоположение, масштаб и актуальность процедуры.

    Цена в воротах не участвует — она про право, а не про актив. Порогом её
    отсекать нельзя, но и молчать о ней незачем: неопубликованная цена
    называется отдельной причиной и остаётся видимой в карточке.
    """
    missing: list[str] = []
    if not ((lot.address or "").strip() or lot.cadastral_numbers):
        missing.append("нет адреса или кадастрового номера")
    area = _positive(lot.land_area_sqm, lot.building_area_sqm)
    if area is None:
        missing.append("не опубликована площадь территории")
    if not ((lot.application_deadline or "").strip() or (lot.status or "").strip()):
        missing.append("нет срока подачи заявки или статуса торгов")
    reasons = list(missing)
    accepted = not missing
    state = "ready" if accepted else "incomplete"
    return {
        "accepted": accepted,
        "state": state,
        "label": {"ready": "Основная подборка",
                  "incomplete": "Не хватает данных"}[state],
        "reasons": reasons,
        "required": ["местоположение", "площадь территории", "актуальность"],
        "minimum_profile_fit": None,
        "fit": profile_fit(lot.to_dict()),
        # Мера названа своя: цена права порогом сделок не меряется.
        "measured_by": "площадь территории и объём строительства",
    }

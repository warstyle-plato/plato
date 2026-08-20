"""Нормативные справочники Москвы — версионируемые, а не константы в формуле.

Свод норм прислан владельцем 20.08.2026 и лежит в `docs/normative/` вместе с
оригиналом 2118-ПП. Числа здесь не участвуют в действующем пути расчёта — он
берёт ставки из самой выгрузки ГлавАПУ; справочник нужен для участка без
выгрузки и как контроль правильности импорта.

Запуск: python3 -m pytest tests/test_moscow_normative_pack.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core
ROOT = Path(__file__).resolve().parent.parent


def test_the_pack_itself_is_kept():
    """Свод хранится файлом: ссылки на правовые системы протухают, файл — нет."""
    folder = ROOT / "docs" / "normative"
    assert (folder / "DevelopAid_normative_pack_20260820.pdf").is_file()
    digest = (folder / "README.md").read_text(encoding="utf-8")
    assert "2118-ПП" in digest and "593-ПП" in digest and "МКЭ-ОД/26-14" in digest
    # Свод сам оговаривает свой статус — оговорка должна дойти до читателя.
    assert "не заверенная правовая подборка" in digest


def test_the_price_index_is_a_series_not_a_constant():
    """k1 зависит от даты: итог платы считается по редакции на дату
    обязательства, и старое значение затирать нельзя."""
    rows = core.MOSCOW_VRI_PRICE_INDEX
    assert rows and all({"effective_from", "value", "document"} <= set(row) for row in rows)
    current = core.moscow_price_index()
    assert current["value"] == 1.9296
    assert "№ 303" in current["document"]
    # На дату до приказа берётся то, что действовало тогда, а не последнее.
    assert core.moscow_price_index("2026-08-20")["value"] == 1.9296


def test_the_two_k2_are_not_the_same_thing():
    """Функциональный коэффициент ВРИ (0,001) и K2 приобъектной парковки —
    разные таблицы и разный смысл, а зовутся оба «к2»."""
    coeff = core.MOSCOW_VRI_FUNCTION_COEFF
    assert coeff["mkd"] == 1.0 and coeff["hotel"] == 1.0, "гостиница — не обычное нежилое"
    assert coeff["office"] == 0.001 and coeff["trade"] == 0.001
    # У парковки своя таблица нормативов, и она про метры на место.
    assert core.MOSCOW_ATTACHED_PARKING_X2["office"] == 63.0
    assert core.MOSCOW_ATTACHED_PARKING_X2["mall"] == 54.0


def test_the_control_quarter_matches_the_city_export():
    """Контрольный квартал — проверка импорта справочника, а не «вся Москва»."""
    quarter = core.MOSCOW_QUARTER_REFERENCE["77:01:0004023"]
    assert quarter["rent_coeff"] == 0.1497
    bases = quarter["base_costs_rub"]
    assert bases["mkd"] == 287560.46
    assert bases["trade"] == 194737.19
    assert bases["office"] == 187578.99
    assert bases["hotel"] == 206274.93
    assert bases["garage"] == 89143.74
    assert bases["izh"] == 123651.00


def test_the_uupss_column_is_openly_unresolved():
    """С техприсоединением или без — свод не решает и велит сверить по приказу
    № 141. Молча выбрать большее число нельзя."""
    uupss = core.MOSCOW_SOCIAL_UUPSS
    assert uupss["column_unresolved"] is True
    values = uupss["values_th_rub"]
    assert values["kindergarten"]["without_tp"] == 4329.61
    assert values["kindergarten"]["with_tp"] == 4728.76
    assert values["school"]["without_tp"] == 4283.72
    assert values["clinic"]["without_tp"] == 7707.29
    assert uupss["price_level"] == "2026-01-01"


def test_the_old_hardcoded_uupss_are_not_the_current_ones():
    """Прежние зашитые ставки (4799,71 / 4578,69 / 7887,92) — прошлый выпуск.

    Ради этого справочник и заводится: числа стареют, а формула остаётся.
    """
    values = core.MOSCOW_SOCIAL_UUPSS["values_th_rub"]
    assert values["kindergarten"]["without_tp"] != 4799.71
    assert values["school"]["without_tp"] != 4578.69
    assert values["clinic"]["without_tp"] != 7887.92

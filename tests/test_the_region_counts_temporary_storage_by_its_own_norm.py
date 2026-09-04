"""Временные места области: в проекте не строим, и два источника числа разведены.

Владелец, 04.09.2026: «а ты уверен, что временные — это приобъектные, а не
подземные или в гараже места отдельные, которые не продаются?» — не уверен, и
проверка первоисточника показала, что нет. РНГП (п. 5.12 в редакции 774-ПП)
говорит про «места для ВРЕМЕННОГО ХРАНЕНИЯ легковых автомобилей» с размещением
в границах ЖИЛОГО РАЙОНА. Ни приобъектных, ни открытых стоянок там нет:
приобъектные в РНГП — это другое (кратковременная остановка у школ и садиков), а
нехватка мест по соседней норме уходит в многоуровневые сооружения, то есть
временные могут быть и в гараже.

Строить их в проекте не надо — решение владельца: «не строим», район их
закрывает. Значит в паркинге остаются только места постоянного хранения, и все
они продаются: московскую одиннадцатую часть вычитать не из чего.

Число временных мест при этом остаётся спорным, и спор назван вслух: движок
считает их долей 0,18 от уровня автомобилизации (64 на тысячу) и этим
воспроизводит ППТ заказчика, а наш же справочник цитирует «не менее 30 на
тысячу». Противоречия нет — «не менее» это пол, — но пока владелец не сказал,
какое число показывать нормативной потребностью, менять его нельзя.

Запуск: python3 -m pytest tests/test_the_region_counts_temporary_storage_by_its_own_norm.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
import mo_rngp_reference as ref  # noqa: E402


def test_the_two_sources_of_the_rate_are_both_kept_and_named() -> None:
    """Оба числа живы и оба названы: пол норматива и доля, воспроизводящая ППТ."""
    assert core.MO_NORMS_DEFAULT["parking_temporary_share"] == 0.18
    assert ref.PARKING_TEMPORARY_RATE["value"] == 30.0
    assert ref.PARKING_TEMPORARY_RATE["rule_type"] == "MANDATORY_MINIMUM"
    # Расхождение объяснено там, где стоит число, а не в чьей-то голове.
    source = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    place = source.index('"parking_temporary_share": 0.18')
    note = source[max(0, place - 900):place]
    assert "не менее 30" in note and "ППТ заказчика" in note


def test_the_region_builds_only_permanent_places_and_sells_them_all() -> None:
    """Временные не строятся, гостевых нет: продаются все построенные места."""
    assert core.underground_saleable_spaces({"units": 400, "guest_units": 0}) == 400
    # Без явного нуля движок вычел бы московскую одиннадцатую часть.
    assert core.underground_saleable_spaces({"units": 400}) == 364


def test_the_moscow_region_tep_declares_no_guest_places() -> None:
    """Перенос расчёта области в ТЭП объявляет отсутствие гостевых явно."""
    source = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    place = source.index('"units": parking["permanent_spaces"],')
    assert '"guest_units": 0,' in source[place:place + 700], (
        "область не объявляет отсутствие гостевых — движок вычтет московскую 1/11")


def test_the_screen_says_the_temporary_places_are_not_built() -> None:
    """Посчитанное и не построенное названо, а не оставлено числом без смысла."""
    page = core.PAGE
    assert "Паркинг временного хранения" in page
    assert "в проекте не строим" in page
    assert "в границах жилого района" in page

"""Временные места области: норматив числом на тысячу, и в проекте не строим.

Владелец, 04.09.2026: «а ты уверен, что временные — это приобъектные, а не
подземные или в гараже места отдельные, которые не продаются?» — не уверен, и
проверка первоисточника показала, что нет. РНГП (п. 5.12 в редакции 774-ПП)
говорит про «места для ВРЕМЕННОГО ХРАНЕНИЯ легковых автомобилей» с размещением
в границах ЖИЛОГО РАЙОНА. Ни приобъектных, ни открытых стоянок там нет:
приобъектные в РНГП — это другое (кратковременная остановка у школ и садиков), а
нехватка мест по соседней норме уходит в многоуровневые сооружения, то есть
временные могут быть и в гараже.

Число движок брал долей 0,18 от уровня автомобилизации — 64 места на тысячу:
столько дал ППТ заказчика, и модель воспроизводила ЕГО проект. Решение
владельца: «ППТ может быть у всех разное, а норматив один» — считаем норматив
(не менее 30 на тысячу), а конкретное требование вписывают, когда оно известно.

Строить их в проекте не надо — «не строим», район их закрывает. Значит в
паркинге остаются только места постоянного хранения, и все они продаются:
московскую одиннадцатую часть вычитать не из чего.

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


def test_the_engine_takes_the_rate_from_the_primary_source() -> None:
    """Норматив движка — цитата справочника, а доли московского вида больше нет."""
    assert core.MO_NORMS_DEFAULT["parking_temporary_per_1000"] == ref.PARKING_TEMPORARY_RATE["value"]
    assert ref.PARKING_TEMPORARY_RATE["unit"] == ref.UNIT_CARS_PER_1000
    assert ref.PARKING_TEMPORARY_RATE["rule_type"] == "MANDATORY_MINIMUM"
    source = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    assert "parking_temporary_share" not in source, "доля осталась в расчёте"
    # Норма — пол, а не потолок: её правят как любой другой норматив области.
    assert "parking_temporary_per_1000" in core.MO_NORMS_DEFAULT


def test_the_norm_answers_not_the_sample_project() -> None:
    """На 7 143 жителя — 215 мест по норме, а не 458 из ППТ заказчика."""
    program = core.mo_social_program(200000.0)
    assert program["population"] == 7143
    assert program["parking"]["temporary_spaces"] == 215
    # Прежняя доля дала бы 458 — величина названа, чтобы её нельзя было
    # вернуть незаметно.
    assert core._mo_ceil(7143 * 356 / 1000.0 * 0.18) == 458


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

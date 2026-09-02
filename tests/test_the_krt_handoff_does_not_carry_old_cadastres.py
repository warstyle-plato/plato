"""Из карточки КРТ в калькулятор не уезжают чужие кадастровые номера.

«Из КРТ карточки в DevelopAid неверно передаёт КН участков» (владелец,
02.09.2026). Две причины, обе наши.

**У лота КРТ уезжали КН зданий.** ОКС и участок — разные объекты ЕГРН, и в
извещении КРТ зданий больше всего: их сносят, и они перечислены поимённо.
Сужение до земельных участков стояло для всех видов лотов, КРТ было из него
исключено — а калькулятор, получив КН дома, принимает площадь дома за площадь
территории.

**У площадки КРТ номеров нет вовсе**, и поле участка оставалось от ПРОШЛОГО
проекта. Чужой номер хуже пустого поля: он выглядит посчитанным.

Запуск: python3 -m pytest tests/test_the_krt_handoff_does_not_carry_old_cadastres.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

API = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")
PAGE = (ROOT / "auction_search" / "ui.py").read_text(encoding="utf-8")
BRIDGE = (ROOT / "auction_search" / "bridge.py").read_text(encoding="utf-8")


def test_a_krt_lot_is_narrowed_to_land_like_every_other() -> None:
    assert "if lot.cadastral_numbers and core is not None:" in API
    assert "lot.lot_kind != LotKind.KRT and lot.cadastral_numbers" not in API, (
        "КРТ снова исключён из сужения — уедут КН снесённых зданий")
    assert "l.lot_kind!=='krt'" not in PAGE, "то же исключение на странице"


def test_the_narrowing_still_says_what_it_did() -> None:
    """Молча выброшенный номер читается как его отсутствие в извещении."""
    assert "здания/ОКС исключены" in PAGE
    assert "только земельные КН" in API or "земельные участки" in API


def test_the_site_handoff_clears_the_field_and_says_so() -> None:
    """Поле участка чистит подмена проекта (`forgetTerritoryState`), а мост
    объясняет пустое поле в вопросе: у площадки КРТ кадастровых номеров нет."""
    assert "Кадастровых номеров у" in BRIDGE, "пустое поле не объяснено"
    krt = BRIDGE[BRIDGE.index("if(pending.krt_model){"):BRIDGE.index("const preset=pending.project_preset")]
    assert "applyProjectSnapshot(model)" in krt
    # Своего списка полей у моста нет: у лота номера как раз передаются, а
    # территорию площадки забывает та же функция, что грузит любой проект.
    assert "field.value=''" not in krt
    page = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    forget = page[page.index("function forgetTerritoryState("):]
    forget = forget[: forget.index("\n}\n")]
    assert "'cadastralNumbers'" in forget and "field.value=''" in forget

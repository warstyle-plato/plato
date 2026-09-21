"""Пресет в публичном репозитории не несёт переговорную позицию.

Репозиторий открыт по решению владельца 07.09.2026, и видимость репозитория —
не мера защиты данных: всякий добавленный файл читает кто угодно и навсегда.
Цена, которую продавец назвал в переговорах, — это не «число проекта», а
позиция стороны сделки, и в `presets/` ей места нет; метры, сроки и
себестоимость — есть, они и делают пресет эталоном импорта.

Сторож запрещает МЕСТО, а не слово: объяснение выше само называет цену, и
проверка на строку завалилась бы на собственном объяснении.

Запуск: python3 -m pytest tests/test_a_preset_carries_no_negotiating_position.py -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

PRESETS = Path(__file__).resolve().parent.parent / "presets"

# Ключи, которыми переговорная позиция и приезжает. Цена ЛОТА сюда не входит:
# её объявляет сам город в извещении, она публична по построению.
_NEGOTIATED = (
    "seller_indicative_enterprise_value_rub",
    "seller_price_rub",
    "seller_ask_rub",
    "indicative_enterprise_value_rub",
)


def _files() -> list[Path]:
    return sorted(PRESETS.glob("*.json"))


def test_there_are_presets_to_check():
    """Иначе «нарушений нет» значит, что проверка не нашла ни одного файла."""
    assert _files(), "в presets/ нет ни одного .json — сторожу не на что смотреть"


@pytest.mark.parametrize("path", _files(), ids=lambda p: p.name)
def test_a_preset_names_no_seller_price(path: Path):
    found: list[str] = []

    def walk(node, trail: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _NEGOTIATED:
                    found.append(f"{trail}.{key}")
                walk(value, f"{trail}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{trail}[{index}]")

    walk(json.loads(path.read_text(encoding="utf-8")), path.name)
    assert not found, (
        "переговорная позиция продавца в публичном репозитории: "
        + ", ".join(found)
    )

"""Версия объявляется один раз и всюду показывается одна и та же.

Номер версии был размножен по тринадцати литералам в движке плюс копия в
обёртке, и поднимались они порознь. Наружу это выходило так: `/status` бота
показывал 0.13.5, а страница, `/health` и заголовок ответа — 0.13.4. Отличить
«выкатка не доехала» от «версию подняли не везде» по такому стенду нельзя,
и время уходило на проверку деплоя вместо одной строки в коде.

Здесь закреплено само свойство: источник один, остальные места — подстановка.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as wrapper  # noqa: E402

core = wrapper.core
client = TestClient(wrapper.app)


def test_the_wrapper_does_not_keep_its_own_copy():
    assert wrapper._RUNTIME_VERSION == core.VERSION


def test_every_surface_shows_the_same_version():
    """Те самые расходившиеся места: бот, страница, /health и заголовок."""
    assert wrapper.app.version == core.VERSION
    assert client.get("/health").json()["version"] == core.VERSION
    assert f"v{core.VERSION}" in core.PAGE
    assert core.USER_AGENT.endswith(core.VERSION)


def test_the_page_placeholder_is_substituted():
    """Плейсхолдер, доехавший до браузера, — это «v__DEVELOPAID_VERSION__»."""
    assert core.VERSION_PLACEHOLDER not in core.PAGE


@pytest.mark.parametrize("name", ["main.py", "main_legacy.py"])
def test_the_number_is_written_down_exactly_once(name):
    """Главный тест: рецидив — это второй литерал с тем же номером."""
    source = (ROOT / name).read_text(encoding="utf-8")
    occurrences = source.count(f'"{core.VERSION}"')
    expected = 1 if name == "main_legacy.py" else 0
    assert occurrences == expected, (
        f"{name}: номер версии встречается {occurrences} раз, ожидалось {expected}. "
        "Версия объявляется только в main_legacy.VERSION, остальное — подстановка."
    )


# Места, где версия показывалась наружу, — ровно те тринадцать литералов.
# Проверяются формы, а не числа: отставший литерал ловится и тогда, когда
# VERSION уже другая, а сплошной поиск «\d+\.\d+\.\d+» тут не годится — под
# него попадают Chrome/144.0.0.0 и метки миграций `0.12.25`, `0.7.1`, которые
# привязаны к своему моменту и меняться не должны.
VERSION_SURFACES = [
    r'DevelopAid-Development-Model/\d',
    # Три компонента: у нашей версии их всегда три, а «"version": "3.0"» — это
    # версия протокола ASGI в скоупе запроса, и она к выпуску отношения не имеет.
    r'"version"\s*:\s*"\d+\.\d+\.\d+"',
    r'X-DevelopAid-Version"\s*:\s*"\d',
    r'Версия:\s*\d',
    r'FastAPI\([^)]*version\s*=\s*"\d',
    r'>v\d+\.\d+\.\d+',
]


@pytest.mark.parametrize("surface", VERSION_SURFACES)
def test_no_surface_hardcodes_the_number(surface):
    """Ловит отставший литерал даже когда текущая версия уже другая."""
    for name in ("main.py", "main_legacy.py"):
        source = (ROOT / name).read_text(encoding="utf-8")
        found = re.findall(surface, source)
        assert not found, (
            f"{name}: версия вписана числом в {found} — подставляйте VERSION."
        )

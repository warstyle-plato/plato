"""Руководство /guide — обычная страница приложения, сверенная с ним же.

Правила, закреплённые здесь:

- руководство живёт внутри приложения: без iframe и без внешних доменов,
  единственная внешняя ссылка — официальный калькулятор «СтроимПросто»;
- каждое упомянутое название кнопки или вкладки (пометка class="ui")
  существует на странице модели дословно — руководство не имеет права
  рассказывать про интерфейс, которого нет;
- числа классов и сценариев подставляются из движка, а не переписаны в текст;
- версия — та же подстановка, что у страницы модели;
- якоря навигации ведут на существующие разделы;
- в шапке модели есть ссылка «Руководство», в руководстве — возврат в модель.

Запуск: python3 -m pytest tests/test_guide_page.py -q
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402
from guide import install  # noqa: E402

core = wrapper.core
_ROOT = Path(__file__).resolve().parent.parent
_GUIDE_JS = _ROOT / "guide" / "assets" / "guide.js"


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    install(app, core)
    return TestClient(app)


@pytest.fixture(scope="module")
def page(client: TestClient) -> str:
    response = client.get("/guide")
    assert response.status_code == 200, response.text
    return response.text


def test_the_guide_is_native_and_versioned(client: TestClient, page: str):
    assert "<iframe" not in page
    assert f"v{core.VERSION}" in page
    assert "no-store" in client.get("/guide").headers.get("cache-control", "")
    assert client.get("/guide/").text == page


def test_the_only_external_link_is_the_official_calculator(page: str):
    external = set(re.findall(r"https?://[^\s\"'<>]+", page))
    allowed = {url for url in external if url.startswith("https://stroimprosto.mos.ru")}
    assert external == allowed, f"лишние внешние адреса: {external - allowed}"


def test_every_mentioned_control_exists_on_the_page(page: str):
    """Руководство не имеет права рассказывать про интерфейс, которого нет.

    Основной интерфейс — это PAGE плюс слой перестройки, поэтому пометки
    сверяются с обоими: часть кнопок («Нет кадастра — собрать ТЭП вручную»)
    создаёт слой.
    """
    overlay = (_ROOT / "ia_preview" / "assets" / "overlay.js").read_text(encoding="utf-8")
    interface = core.PAGE + overlay
    controls = re.findall(r'class="ui">([^<]+)</b>', page)
    assert len(controls) >= 10, "пометок ui подозрительно мало — текст не сверяется"
    for label in controls:
        assert label in interface, f"в интерфейсе нет «{label}»"


def test_class_and_scenario_numbers_come_from_the_engine(page: str):
    for key in ("comfort", "business", "elite"):
        preset = core.PROJECT_CLASS_PRESETS[key]
        assert preset["label"] in page
        assert str(preset["apartment_price_th"]) in re.sub(r"\s", "", page)
    # Три строки классов и три сценария построены подстановкой, не текстом.
    assert "__GUIDE_CLASS_ROWS__" not in page
    assert "__GUIDE_SCENARIO_ROWS__" not in page
    assert "×1,10" in page and "×0,90" in page


def test_navigation_anchors_lead_to_real_sections(page: str):
    anchors = re.findall(r'href="#([a-z-]+)"', page)
    assert len(set(anchors)) == 8, "в навигации должно быть восемь разделов"
    for anchor in anchors:
        assert f'id="{anchor}"' in page, f"якорь #{anchor} ведёт в никуда"


def test_the_model_page_links_the_guide_and_back():
    assert 'href="/guide"' in core.PAGE, "в шапке модели нет ссылки на руководство"
    assert "Руководство" in core.PAGE
    guide_html = (_ROOT / "guide" / "page.html").read_text(encoding="utf-8")
    assert 'href="/"' in guide_html, "из руководства нет возврата в DevelopAid"
    assert "Вернуться в DevelopAid" in guide_html


def test_the_example_is_marked_as_a_lesson(page: str):
    assert "77:07:0008006:3" in page
    assert "учебный пример" in page
    assert "ГПЗУ" in page and "АГР" in page


def test_the_guide_script_is_valid_javascript():
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    subprocess.run([node, "--check", str(_GUIDE_JS)], check=True)


def test_tabs_are_accessible(page: str):
    assert 'role="tablist"' in page
    assert page.count('role="tab"') == 5, "способов ввода — пять"
    assert 'aria-selected="true"' in page
    for tab_id in re.findall(r'aria-controls="([^"]+)"', page):
        assert f'id="{tab_id}"' in page, f"вкладка ведёт на несуществующую панель {tab_id}"

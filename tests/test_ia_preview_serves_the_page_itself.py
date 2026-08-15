"""Новая архитектура отдаёт ту же страницу, а не её копию.

Форк `PAGE` был бы вторым источником поведения: список полей, умолчания и
весь путь «участок → ТЭП → расчёт» пришлось бы держать в двух местах, и
первое же расхождение выглядело бы как работающий макет. С 15.08.2026 слой —
основной интерфейс на корне (решение владельца); закреплено здесь:

- `PAGE` движка не меняется ни на байт от установки модуля;
- `/` и `/ia` — это `PAGE` плюс подключение слоя и ничего больше;
- `/classic` — `PAGE` как есть, прежний интерфейс;
- в телеграме слой выключает себя сам: поток мини-приложения со слоем не
  проверялся, и WebView получает страницу как есть;
- страница и слой не кешируются: закешированный слой неотличим от
  невыкаченного;
- модуль ничего не считает — арифметики в нём нет, максимум цены входа
  считает движок;
- пример проекта отдаётся файлом, а разбирает его страница своим путём.

Запуск: python3 -m pytest tests/test_ia_preview_serves_the_page_itself.py -q
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402
from ia_preview import install  # noqa: E402

core = wrapper.core
_ROOT = Path(__file__).resolve().parent.parent
_MODULE = _ROOT / "ia_preview" / "__init__.py"
_OVERLAY = _ROOT / "ia_preview" / "assets" / "overlay.js"


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()

    @app.get("/")
    def root() -> str:
        return core.PAGE

    install(app, core)
    return TestClient(app)


def test_the_engine_page_is_untouched(client: TestClient):
    """Установка модуля не должна менять саму строку PAGE."""
    assert core.PAGE == wrapper.core.PAGE
    assert "/ia/assets/overlay.js" not in core.PAGE


def test_the_root_is_the_page_plus_the_layer(client: TestClient):
    """Корень и /ia — ровно PAGE плюс подключение слоя, прежний вид — /classic."""
    page = client.get("/ia").text
    assert page.count("<html") == core.PAGE.count("<html")
    without_layer = (
        page.replace('<link rel="stylesheet" href="/ia/assets/overlay.css">\n', "")
        .replace('<script src="/ia/assets/overlay.js" defer></script>\n', "")
    )
    assert without_layer == core.PAGE
    assert client.get("/ia/").text == page
    assert client.get("/").text == page, "корень отдаёт не тот же слой, что /ia"
    assert client.get("/classic").text == core.PAGE, "/classic — не прежняя страница"


def test_the_root_headers_carry_version_and_surface(client: TestClient):
    """Выкатка корня различима: версия в заголовке, поверхность помечена."""
    response = client.get("/")
    assert response.headers.get("X-DevelopAid-Version") == core.VERSION
    assert response.headers.get("X-DevelopAid-Surface") == "ia-main"
    assert client.get("/classic").headers.get("X-DevelopAid-Version") == core.VERSION


def test_the_layer_stays_out_of_telegram():
    """Поток мини-приложения со слоем не проверялся — слой обязан выключаться.

    Телеграм опознаётся по параметрам запуска в хеше (telegram_session / cad):
    telegram-web-app.js на странице не подключён, window.Telegram не бывает.
    """
    source = _OVERLAY.read_text(encoding="utf-8")
    assert "telegram_session|cad" in source, "в слое нет опознания телеграма"
    guard = source.index("telegram_session|cad")
    assert "boot()" in source[guard:], "опознание телеграма стоит после запуска слоя"


def test_nothing_on_the_preview_is_cached(client: TestClient):
    """Страница правится и смотрится в один заход."""
    for path in ("/", "/classic", "/ia", "/ia/assets/overlay.css", "/ia/assets/overlay.js"):
        cache = client.get(path).headers.get("cache-control", "")
        assert "no-store" in cache or "no-cache" in cache, path


def test_the_layer_is_valid_javascript():
    """Слой не проверяется ничем, кроме браузера, — значит, проверяется здесь."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    subprocess.run([node, "--check", str(_OVERLAY)], check=True)


def test_the_example_is_a_whole_project(client: TestClient):
    """Пример открывается проектом, а не одним ТЭП.

    С умолчаниями по ценам любой участок показывает «экономика не проходит», и
    холодный пользователь первым делом видит отказ по вводным, которых он не
    задавал. Поэтому под кнопкой лежит пресет проекта — с ценами,
    себестоимостью и очередями.
    """
    response = client.get("/ia/example.json")
    assert response.status_code == 200, response.text
    preset = response.json()
    assert preset["schema_version"].startswith("developaid.project_preset")
    assert preset["economics"], "в примере нет экономики — это снова только ТЭП"
    assert preset["planning"], "в примере нет планировки"


def test_the_preview_module_does_not_do_arithmetic():
    """Максимум цены входа считает движок, а не адаптер.

    Правило то же, что у адаптера ProjectResult: первое «просто поделить на
    миллион» — это уже вторая реализация экономики.
    """
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    arithmetic = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
    found = [
        f"строка {node.lineno}: {type(node.op).__name__}"
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, arithmetic)
    ]
    assert not found, "в модуле /ia появилась арифметика: " + "; ".join(found)

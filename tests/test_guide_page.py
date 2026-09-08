"""Руководство /guide — обычная страница приложения, сверенная с ним же.

Правила, закреплённые здесь:

- руководство живёт внутри приложения: без iframe и без случайных внешних
  доменов. Наружу оно ведёт исходниками нормативных актов из реестра движка
  (справочник внизу страницы, с 06.09.2026);
- каждое упомянутое название кнопки или вкладки (пометка class="ui")
  существует на странице модели дословно — руководство не имеет права
  рассказывать про интерфейс, которого нет;
- числа классов и сценариев подставляются из движка, а не переписаны в текст;
- версия — та же подстановка, что у страницы модели;
- якоря навигации ведут на существующие разделы, а состав разделов у Платона
  совпадает с составом страницы — второй копии руководства нет;
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
# Исходник страницы: состав разделов у Платона сверяется с ним, а не с числом,
# записанным в проверку, — число редакция меняет, состав обязан совпадать.
PAGE_HTML = (_ROOT / "guide" / "page.html").read_text(encoding="utf-8")


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


def test_the_only_external_links_are_the_calculator_and_the_acts(page: str):
    """Наружу руководство ведёт в двух случаях, и оба названы.

    Прежде разрешён был один адрес — штатный калькулятор. С 06.09.2026 внизу
    стоит справочник нормативной базы, и у каждой позиции ссылка на
    ОРИГИНАЛЬНЫЙ исходник: «проверять нас нужно по нему» (владелец). Правило
    от этого не ослабло — оно стало точнее: разрешён калькулятор и ровно те
    адреса, что стоят в реестре движка. Вписанный руками внешний адрес
    по-прежнему поломка, и её ловит эта же проверка.
    """
    import html as _html

    import normatives_registry

    external = set(re.findall(r"https?://[^\s\"'<>]+", page))
    acts = {_html.escape(str(row.get("source_url") or "")).rstrip("/")
            for row in normatives_registry._merged_registry()
            if str(row.get("source_url") or "").strip()}
    allowed = {url for url in external
               if url.startswith("https://stroimprosto.mos.ru") or url.rstrip("/") in acts}
    assert external == allowed, f"лишние внешние адреса: {external - allowed}"
    assert acts, "в реестре нет ни одной ссылки — проверять нечего"


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
    assert anchors, "в руководстве нет ни одного якоря"
    for anchor in anchors:
        assert f'id="{anchor}"' in page, f"якорь #{anchor} ведёт в никуда"


def test_the_model_page_links_the_guide_and_back():
    assert 'href="/guide"' in core.PAGE, "в шапке модели нет ссылки на руководство"
    assert "Руководство" in core.PAGE
    guide_html = (_ROOT / "guide" / "page.html").read_text(encoding="utf-8")
    assert 'href="/"' in guide_html, "из руководства нет возврата в DevelopAid"
    assert "Вернуться в DevelopAid" in guide_html


def test_the_example_is_marked_as_a_lesson(page: str):
    assert "Учебный пример" in page, "сквозной пример не помечен учебным"
    assert "ГПЗУ" in page and "АГР" in page


def test_the_guide_script_is_valid_javascript():
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    subprocess.run([node, "--check", str(_GUIDE_JS)], check=True)


def test_the_consent_page_names_the_operator(client: TestClient):
    """Согласие 152-ФЗ: оператор — ИП Ситников, без банковских реквизитов.

    Оператором указан ИП (решение владельца, 15.08.2026); банковские реквизиты
    к согласию не относятся и на страницу не попадают.
    """
    response = client.get("/consent")
    assert response.status_code == 200
    text = response.text
    assert "152-ФЗ" in text
    assert "СИТНИКОВ ВЛАДИСЛАВ ЮРЬЕВИЧ" in text
    assert "772029908709" in text and "323774600713537" in text
    assert "Расчётный счёт" not in text and "БИК" not in text
    assert "Telegram" in text, "в перечне данных нет идентификатора Telegram"


def test_the_model_page_links_the_consent():
    assert 'href="/consent"' in core.PAGE, "внизу страницы модели нет ссылки на согласие"
    login_block = core.PAGE[core.PAGE.index("function renderProjectsLogin"):]
    login_block = login_block[:login_block.index("function hideProjectsLogin")]
    assert "/consent" in login_block, "панель входа не упоминает согласие"


def test_platon_reads_the_same_guide():
    """У Платона нет своей копии руководства — ей негде устареть."""
    data = core._tool_get_user_guide("all")
    assert data["available"]
    on_page = re.findall(r'<section[^>]*\bid="([a-z-]+)"', PAGE_HTML)
    assert [item["id"] for item in data["sections"]] == on_page, (
        "у Платона другой состав разделов, чем на странице")
    inputs_only = core._tool_get_user_guide("inputs")
    assert len(inputs_only["sections"]) == 1
    assert inputs_only["sections"][0]["url"] == "/guide#inputs"
    assert "Получить ТЭП" in inputs_only["sections"][0]["text"], (
        "раздел приехал пустым — Платон читает не тот файл")
    assert not core._tool_get_user_guide("nope")["available"]
    names = [tool["name"] for tool in core._AGENT_TOOLS]
    assert "get_user_guide" in names, "инструмент не объявлен модели"
    assert "get_user_guide" in Path(core.__file__).read_text(encoding="utf-8").split(
        "def _execute_agent_tool", 1)[1][:4000], "инструмент не диспетчеризуется"


def test_queues_explain_manual_distribution(page: str):
    """Очередность — не только сроки: распределение объектов задаётся вручную."""
    queues = re.search(r'<section[^>]*id="queues".*?</section>', page, re.S)
    assert queues, "раздела об очередях в руководстве нет"
    body = queues.group(0)
    assert "оциальная нагрузка" in body and "вручную" in body, (
        "не сказано, что социальная нагрузка распределяется по очередям вручную")
    assert "консолидац" in body, "не сказано, чем опасна хорошая консолидация"


def test_screenshots_exist_and_are_wired(client: TestClient, page: str):
    """Каждый скриншот: файл на месте, отдаётся маршрутом, alt и lazy заданы."""
    sources = re.findall(r'<img src="(/guide/assets/screens/[a-z0-9-]+\.webp)"', page)
    assert len(sources) >= 9, f"скриншотов меньше девяти: {len(sources)}"
    screens_dir = _ROOT / "guide" / "assets" / "screens"
    for src in sources:
        name = src.rsplit("/", 1)[1]
        assert (screens_dir / name).is_file(), f"нет файла {name}"
        response = client.get(src)
        assert response.status_code == 200, f"маршрут не отдаёт {src}"
        assert response.headers.get("content-type") == "image/webp"
        assert response.content[:4] == b"RIFF", f"{name} — не webp"
    figures = re.findall(r'<figure class="gshot">(.*?)</figure>', page, re.S)
    assert len(figures) == len(sources)
    for figure in figures:
        assert 'alt="' in figure and 'alt=""' not in figure, "пустой alt"
        assert 'loading="lazy"' in figure and 'decoding="async"' in figure
        assert "<b>Где:</b>" in figure and "<b>Нажать:</b>" in figure and "<b>Проверить:</b>" in figure
    assert client.get("/guide/assets/screens/../secret.webp").status_code in (404, 400)


def test_the_lightbox_is_wired():
    """Клик открывает крупнее; закрытие — кнопкой, фоном и Escape."""
    source = _GUIDE_JS.read_text(encoding="utf-8")
    assert ".gshot img" in source, "клик по скриншоту никуда не ведёт"
    assert "closeLightbox" in source
    assert "'Escape'" in source
    assert "event.target === lightbox" in source, "клик по фону не закрывает"
    css = (_ROOT / "guide" / "assets" / "guide.css").read_text(encoding="utf-8")
    assert ".glightbox" in css


def test_tabs_are_accessible(page: str):
    assert 'role="tablist"' in page
    assert page.count('role="tab"') == 5, "способов ввода — пять"
    assert 'aria-selected="true"' in page
    for tab_id in re.findall(r'aria-controls="([^"]+)"', page):
        assert f'id="{tab_id}"' in page, f"вкладка ведёт на несуществующую панель {tab_id}"

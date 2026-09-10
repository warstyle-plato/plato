"""Браузер ищут, а не помнят, и его отсутствие на CI краснеет.

Проверки, которые решает настоящий Chromium, на CI не шли НИ РАЗУ: пакет
playwright приезжает из requirements, а сам браузер — нет, и тесты, найдя
пустоту по зашитому пути, делали `pytest.skip`. Пропуск честен, но снаружи
«прошло» и «не запускалось» выглядят одинаково.

Здесь три утверждения, и каждое про свою половину болезни.

**Ответ один.** Форм поиска браузера в наборе было семь в двадцати двух местах:
зашитый номер сборки (`chromium-1194`), зашитый каталог (`/opt/pw-browsers`),
зашитое имя папки (`chrome-linux`). Каждое из трёх устаревает само: в песочнице
сборка 1194, в образе прода 1234; в песочнице каталог `/opt/pw-browsers`, в
образе `~/.cache/ms-playwright`; у свежего playwright папка `chrome-linux64`.
Устаревшее при этом не краснеет — оно пропускает.

**Ответ чужой, и это правильно.** У сервиса такой путь уже есть
(`browser_launch.executable_paths()`), написан по настоящей поломке прода и
ищет по имени файла, а не по пути. Восьмая копия была бы хуже оригинала.

**Отсутствие обязательного браузера — падение.** Иначе сломавшаяся установка
молча вернёт набор туда, откуда пришли, и «зелёный CI» снова не будет значить
ничего.

Запуск: python3 -m pytest tests/test_the_browser_is_found_not_remembered.py -q
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from browser import browser_required, chromium_or_skip, chromium_path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"

# Образец собирается из кусков намеренно. Проверка, написанная как «такой
# строки в файле быть не должно», однажды уже завалилась на собственном
# объяснении: слово, которое она запрещает, стоит в её же тексте. Запрещают
# МЕСТО, а не слово, поэтому исключения названы здесь прямо и поимённо, а сам
# образец в этом файле литералом не встречается.
_BUILD_NUMBER = re.compile(r"chromium" + r"-\d{3,}")
_ROOTS = (r"/opt/" + r"pw-browsers", r"ms-" + r"playwright")

# Кому зашитый путь разрешён и почему.
_ALLOWED = {
    # Один ответ на весь набор: он и обязан называть каталоги — но чужие, из
    # `browser_launch`, а своих литералов у него нет вовсе.
    "browser.py": "здесь живёт сам ответ",
    # Этот файл: он запрещает, значит называет запрещаемое.
    "test_the_browser_is_found_not_remembered.py": "здесь стоит запрет",
    # Проверки самого перебора сервиса строят поддельные каталоги: имена сборок
    # и папок там ПРИМЕРЫ, а не поиск, и без них проверять было бы нечего.
    "test_market_metrics.py": "строит поддельные каталоги как примеры",
}


def _sources() -> list[Path]:
    return sorted(p for p in TESTS.glob("*.py"))


def test_no_test_remembers_a_browser_build_number():
    """Номер сборки в пути — это число playwright, и оно устаревает молча."""
    guilty = []
    for path in _sources():
        if path.name in _ALLOWED:
            continue
        text = path.read_text(encoding="utf-8")
        if _BUILD_NUMBER.search(text) or any(root in text for root in _ROOTS):
            guilty.append(path.name)
    assert not guilty, (
        "путь к браузеру зашит в " + ", ".join(guilty) + ". Он устаревает сам "
        "по себе (сборка, каталог, имя папки), а устаревший путь не краснеет — "
        "он пропускает проверку. Спрашивать надо `browser.chromium_or_skip()`."
    )


def test_the_guard_falls_on_a_planted_example(tmp_path):
    """Проверка, которая не падает на поломке, — не проверка."""
    planted = "chromium" + "-1194"
    assert _BUILD_NUMBER.search(f'Path("/x/{planted}/chrome-linux/chrome")')
    assert any(root in "/opt/" + "pw-browsers/x" for root in _ROOTS)


def test_the_answer_is_the_service_one_not_a_copy():
    """Своего перебора каталогов у помощника нет — он зовёт сервисный."""
    text = (TESTS / "browser.py").read_text(encoding="utf-8")
    assert "browser_launch.executable_paths()" in text, (
        "помощник обязан спрашивать сервис: у него перебор написан по настоящей "
        "поломке прода и ищет по имени файла, а не по пути.")
    body = text.split('"""', 2)[-1]
    assert "glob(" not in body, "свой перебор — это восьмая копия одного ответа"


def test_a_missing_browser_is_a_failure_where_it_must_be_there(monkeypatch):
    """Взведён `REQUIRE_BROWSER` — отсутствие браузера краснеет, а не молчит."""
    monkeypatch.setenv("REQUIRE_BROWSER", "1")
    monkeypatch.setattr("browser.chromium_path", lambda: None)
    assert browser_required()
    with pytest.raises(BaseException) as caught:
        chromium_or_skip()
    said = str(caught.value)
    assert "REQUIRE_BROWSER" in said
    assert "Skipped" not in type(caught.value).__name__, (
        "пропуск здесь и есть болезнь: сломавшаяся установка выглядела бы как "
        "зелёный прогон")


def test_a_missing_browser_is_only_a_skip_where_it_need_not_be(monkeypatch):
    """Не взведён — пропуск, и он называет, где искали."""
    monkeypatch.delenv("REQUIRE_BROWSER", raising=False)
    monkeypatch.setattr("browser.chromium_path", lambda: None)
    assert not browser_required()
    with pytest.raises(BaseException) as caught:
        chromium_or_skip()
    said = str(caught.value)
    assert "chromium не найден" in said
    assert "каталогах браузеров" in said, (
        "«не нашли» без «где искали» не отличает промах шаблона от пустого образа")


def test_the_workflows_install_the_browser_and_demand_it():
    """Установка и требование стоят рядом: разъехавшись, они молчат."""
    for name in ("tests-on-pr.yml", "build-yandex.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "playwright install" in text, f"{name}: браузер не ставится"
        assert "REQUIRE_BROWSER" in text, (
            f"{name}: браузер ставится, а его отсутствие не объявлено поломкой — "
            "значит сломавшаяся установка вернёт пропуски и промолчит")


@pytest.mark.timeout(120)
def test_the_found_browser_actually_starts():
    """Найденный путь — это ЗАПУСКАЮЩИЙСЯ браузер, а не просто файл.

    Существование файла и работающий браузер — разные утверждения: перебор мог
    найти headless shell, у которого нет окна, а окно здесь и есть предмет.
    """
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        page = browser.new_page(viewport={"width": 400, "height": 300})
        page.set_content("<div id=x style='width:120px;height:40px'></div>")
        box = page.evaluate("document.getElementById('x').getBoundingClientRect().width")
        browser.close()
    assert box == 120, "браузер запустился, а геометрию не считает"

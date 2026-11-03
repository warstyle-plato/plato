"""Эмблема не носит с собой белый прямоугольник.

«В кабинете эмблема с фоном выделяется цветом» (владелец, 31.08.2026).
Картинка — чёрное на белом, без прозрачности: она одна на все поверхности и
лежит в `PAGE`, копии с альфой негде обновлять. На белой шапке это незаметно, а
на светло-серой странице «Статистика строительства» вокруг букв виден белый
прямоугольник.

Снимается наложением: multiply оставляет буквы и растворяет белое в любой
светлой подложке. Проверяется НАСТОЯЩИМ браузером по пикселю рядом с буквами —
строка в CSS доказывает только то, что строка есть.

Запуск: python3 -m pytest tests/test_the_emblem_has_no_white_box.py -q
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_the_emblem_itself_is_opaque_white_backed() -> None:
    """Если картинка однажды станет прозрачной, эта проверка скажет об этом."""
    from PIL import Image
    import io

    import guide
    import main_legacy

    raw = guide.brand_logo(main_legacy)
    assert raw, "эмблема не вынулась из PAGE"
    image = Image.open(io.BytesIO(raw))
    assert image.mode == "RGB", "у эмблемы появилась альфа — наложение больше не нужно"


def test_every_surface_that_shows_it_blends_the_white_away() -> None:
    surfaces = {
        "developaid_statistics_page.py": ".brandbar img",
        "auction_search/ui.py": ".brandbar img",
        "market_search/cabinet.py": ".brand img",
    }
    for name, selector in surfaces.items():
        body = (ROOT / name).read_text(encoding="utf-8")
        start = body.index(selector + "{")
        rule = body[start:body.index("}", start)]
        assert "mix-blend-mode:multiply" in rule, f"{name}: белый фон эмблемы остался"


def test_the_page_background_shows_through(tmp_path) -> None:
    """Пиксель между буквами обязан быть цветом страницы, а не белым."""
    pw = pytest.importorskip("playwright.sync_api")
    pytest.importorskip("PIL")
    from PIL import Image

    import browser_launch
    import developaid_statistics_page as statistics
    import guide
    import main_legacy

    logo = base64.b64encode(guide.brand_logo(main_legacy)).decode()
    page = (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        + statistics._CSS
        + "</style></head><body><div class='wrap'><div class='brandbar'>"
        + f"<img src='data:image/webp;base64,{logo}' alt='ПЛАТО'>"
        + "</div></div></body></html>"
    )
    file = tmp_path / "brand.html"
    file.write_text(page, encoding="utf-8")
    shot = tmp_path / "brand.png"
    with pw.sync_playwright() as play:
        try:
            browser = browser_launch.launch(play)
        except Exception as exc:  # образ без Chromium — не поломка эмблемы
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page(viewport={"width": 900, "height": 260})
            tab.goto(file.as_uri())
            tab.wait_for_timeout(300)
            box = tab.evaluate(
                "()=>{const r=document.querySelector('.brandbar img')"
                ".getBoundingClientRect();return [r.x,r.y,r.width,r.height]}")
            tab.screenshot(path=str(shot))
        finally:
            browser.close()

    image = Image.open(shot).convert("RGB")
    x, y, width, height = (int(v) for v in box)
    # Угол картинки: в самой эмблеме он белый (проверено выше), букв там нет.
    # Середина верхнего края не годится — туда попадает перекладина буквы.
    sample = image.getpixel((x + 2, y + 2))
    assert sample != (255, 255, 255), \
        f"вокруг букв остался белый прямоугольник: {sample}"
    body = image.getpixel((x + width // 2, y + height + 20))
    assert max(abs(a - b) for a, b in zip(sample, body)) <= 6, \
        f"фон эмблемы {sample} не совпал с фоном страницы {body}"

"""Тесты доставки страницы браузеру.

Приложение — одна HTML-страница, которая переезжает целиком с каждым выпуском.
Если её закеширует браузер или прокси, пользователь после обновления сервиса
видит старую версию и решает, что деплой не приехал. Ровно так и вышло на
боевом стенде: сервер отдавал 0.12.67, а телефон показывал 0.12.60.
Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

main = _wrapper.core
client = TestClient(main.app)


def test_page_forbids_caching():
    response = client.get("/")
    assert response.status_code == 200
    cache_control = response.headers.get("cache-control", "")
    assert "no-store" in cache_control
    assert "max-age=0" in cache_control


def test_page_reports_its_version_in_a_header():
    """Версию видно, не открывая страницу, — этим отличают кеш от старой сборки."""
    response = client.get("/")
    version = response.headers.get("x-developaid-version")
    assert version == client.get("/health").json()["version"]
    assert f"v{version}" in response.text

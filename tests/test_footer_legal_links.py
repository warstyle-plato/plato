"""Подвал сайта: документы ИП доступны с каждой страницы.

Владелец прислал политику конфиденциальности и согласие на получение
рекламно-информационных материалов (18.08.2026) — оба документа опубликованы
на d-a.ru и должны быть в подвале рядом с согласием на обработку данных.
Здесь закреплено, что ссылки на месте, ведут на документы владельца и
открываются в новой вкладке с `rel="noopener"` — чужая вкладка не должна
получать доступ к нашей странице.

Запуск: python3 -m pytest tests/test_footer_legal_links.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core


def _footer() -> str:
    page = core.PAGE
    return page[page.index("<footer"):page.index("</footer>") + len("</footer>")]


def test_the_footer_carries_the_owner_documents():
    footer = _footer()
    assert "© ИП" in footer, "подвал обязан называть владельца"
    assert "Политика конфиденциальности" in footer
    assert "рекламно-информационные материалы" in footer.replace("\n", " ")
    assert "Согласие на обработку персональных данных" in footer


def test_the_documents_point_to_the_owner_site():
    footer = _footer()
    links = re.findall(r'href="(https://d-a\.ru/upload/[^"]+\.pdf)"', footer)
    assert len(links) == 2, "оба документа берутся с сайта владельца, а не копией"


def test_external_documents_open_safely():
    """Внешняя вкладка не должна получать доступ к открывшей её странице."""
    footer = _footer()
    for match in re.finditer(r'<a href="https://d-a\.ru[^>]*>', footer):
        tag = match.group(0)
        assert 'target="_blank"' in tag and 'rel="noopener"' in tag, tag

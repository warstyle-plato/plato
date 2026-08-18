"""Подвал сайта: документы ИП доступны с каждой страницы.

Документы ИП живут своими страницами, а не ссылками на чужой сайт: ссылаться
на политику другого лица нельзя — это его текст и его обязательства
(замечание владельца, 18.08.2026). Здесь закреплено, что подвал называет
владельца и ведёт на наши собственные страницы, а внешних ссылок на чужие
документы в нём нет.

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
    assert "рекламные материалы" in footer.replace("\n", " ")
    assert "Согласие на обработку персональных данных" in footer


def test_the_documents_are_our_own_pages():
    footer = _footer()
    assert 'href="/privacy"' in footer and 'href="/ads-consent"' in footer
    assert "d-a.ru" not in footer, "чужие документы в подвал не ставим"
    assert not re.search(r'href="https?://', footer), "документы ИП — свои страницы"


def test_the_pages_name_the_entrepreneur():
    import pathlib
    root = pathlib.Path(core.__file__).resolve().parent
    for name in ("privacy.html", "ads_consent.html"):
        text = (root / "guide" / name).read_text(encoding="utf-8")
        assert "СИТНИКОВ ВЛАДИСЛАВ ЮРЬЕВИЧ" in text, name
        assert "772029908709" in text and "323774600713537" in text, name


def test_the_pages_are_served():
    """Страницы отдаются приложением целиком, а не только объявлены в подвале."""
    import main_registry
    from fastapi.testclient import TestClient

    client = TestClient(main_registry.app)
    for path, title in (("/privacy", "Политика конфиденциальности"),
                        ("/ads-consent", "рекламно-информационных материалов")):
        response = client.get(path)
        assert response.status_code == 200, path
        assert title in response.text, path


def _document_pages() -> dict[str, str]:
    root = Path(core.__file__).resolve().parent / "guide"
    return {name: (root / name).read_text(encoding="utf-8")
            for name in ("page.html", "consent.html", "privacy.html", "ads_consent.html")}


def test_every_document_page_carries_the_same_footer():
    """Подвал жил только на главной: со страницы «Руководство» и «Согласие»
    остальные документы были недостижимы, а на самих документах подвала не было
    вовсе (замечание владельца, 18.08.2026)."""
    for name, text in _document_pages().items():
        footer = text[text.index('<footer class="gfoot"'):text.index("</footer>")]
        for link in ('href="/consent"', 'href="/privacy"',
                     'href="/ads-consent"', 'href="/guide"'):
            assert link in footer, f"{name}: нет ссылки {link}"
        assert "© ИП" in footer, name


def test_the_consent_does_not_bundle_advertising():
    """Согласие на обработку не разрешает рассылки: реклама — отдельное
    согласие по ст. 18 ФЗ-38, и склеивать их нельзя."""
    text = _document_pages()["consent.html"]
    body = text[text.index("<main"):text.index('<footer class="gfoot"')]
    assert "информационных рассылок" not in body, "рекламное согласие вшито в обработку ПД"
    assert 'href="/privacy"' in body, "порядок обработки — в политике, на неё ссылаемся"


def test_the_consent_states_one_term_not_two():
    """Прежний текст обещал сразу и «неограниченный срок», и «в течение периода
    хранения» — два разных срока в одном документе."""
    body = _document_pages()["consent.html"]
    assert "Согласие действует до достижения целей обработки или до его отзыва" in body
    assert "неограниченным" not in body


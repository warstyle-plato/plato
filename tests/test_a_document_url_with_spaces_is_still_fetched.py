"""Ссылка на документ с пробелом и кириллицей не роняет разбор лота.

«Не удалось прочитать официальный лот: URL can't contain control characters.
'/file/get/v/LotDocuments/id/5186786/name/Территория,Лотовая документация…pdf'»
(экран владельца, 02.09.2026). Площадка кладёт в ссылку имя файла как есть;
`urllib` на таком адресе не делает запроса вовсе — и лот пропадал целиком.
Читатель тут ни при чём: адрес честный, просто незакодированный.

Запуск: python3 -m pytest tests/test_a_document_url_with_spaces_is_still_fetched.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.documents import safe_url  # noqa: E402

RAW = ("https://catalog.lot-online.ru/file/get/v/LotDocuments/id/5186786/"
       "name/Территория,Лотовая документация.1700483.pdf")


def test_a_space_and_cyrillic_become_percent_codes() -> None:
    got = safe_url(RAW)
    assert " " not in got
    assert "%20" in got and "%D0" in got
    assert got.startswith("https://catalog.lot-online.ru/file/get/v/LotDocuments/id/5186786/")


def test_an_already_encoded_url_is_left_alone() -> None:
    """Двойное кодирование даёт 404: «%20» превратилось бы в «%2520»."""
    encoded = "https://x.ru/a%20b/c.pdf?q=%D0%90&z=1"
    assert safe_url(encoded) == encoded


def test_a_clean_url_is_unchanged() -> None:
    plain = "https://www.roseltorg.ru/procedure/21000005000000033023/1"
    assert safe_url(plain) == plain


def test_the_downloader_uses_it() -> None:
    body = (ROOT / "auction_search" / "documents.py").read_text(encoding="utf-8")
    assert "Request(safe_url(url)" in body, "адрес уходит в запрос как есть"

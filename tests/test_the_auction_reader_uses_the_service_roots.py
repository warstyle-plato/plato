"""Читатель площадок ходит общими корнями, а страницу отказа называет отказом.

Измерено с прода 12.09.2026. Разбор лота Росэлторга отвечал
`CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate`, а потом
шесть таймаутов подряд по трём живым КРТ-лотам; разведка в строке охвата
писала «не прочитано карточек 45 из 51». При этом проба ТОГО ЖЕ хоста в ту же
минуту получала 200 — она одна ходила с `trusted_roots.trust_context()`, а
читатель лота и загрузка вложений звали `urlopen` без контекста. Правило
прежнее и стоило нам каталога КРТ: **модуль не заводит своего пути туда, где у
сервиса уже есть общий.**

Вторая половина — про молчание. Браузерная проба с ядра получает страницу с
заголовком «The URL you requested has been blocked», а её поле `blocked`
отвечало `false`: список примет знал «403» и «Доступ запрещ» и не знал этой
формулировки. Отказ, посчитанный успехом, читается как «на площадке ничего
нет» — ровно то, из-за чего пустой ответ НСПД когда-то выдавался за отсутствие
ограничений.

Запуск: python3 -m pytest tests/test_the_auction_reader_uses_the_service_roots.py -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import documents, reading  # noqa: E402
from auction_search.adapters import roseltorg  # noqa: E402

# Кому чтение мимо общих корней разрешено и почему. Пусто: разрешений нет, а
# список оставлен затем, чтобы следующее исключение пришлось назвать вслух.
_ALLOWED: dict[str, str] = {}

_READERS = ("auction_search/adapters/roseltorg.py", "auction_search/documents.py")


class _Answer(io.BytesIO):
    """Ответ, какой отдаёт `urlopen`: тело, заголовки, адрес."""

    def __init__(self, body: bytes, content_type: str = "text/html; charset=utf-8"):
        super().__init__(body)
        self.status = 200
        self._content_type = content_type

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def geturl(self):
        return "https://www.roseltorg.ru/procedure/1/1"

    @property
    def headers(self):
        holder = self

        class _H:
            @staticmethod
            def get_content_charset():
                return "utf-8"

            @staticmethod
            def get(name, default=""):
                if name.lower() == "content-type":
                    return holder._content_type
                return default

        return _H()


BLOCK_PAGE = (
    "<html><head><title>The URL you requested has been blocked</title></head>"
    "<body>Web Page Blocked! The page cannot be displayed. "
    "URL: www.roseltorg.ru/procedure/1/1 Client IP: 158.160.184.1</body></html>"
).encode("utf-8")


def test_no_auction_reader_opens_a_page_without_the_service_roots() -> None:
    """Запрещается МЕСТО: свой `urlopen` без контекста в читателях площадок."""
    guilty = []
    for name in _READERS:
        if name in _ALLOWED:
            continue
        text = (ROOT / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            if "urlopen(" not in line or line.lstrip().startswith("#"):
                continue
            if "context=" not in line and "reading.fetch" not in line:
                guilty.append(f"{name}: {line.strip()}")
    assert not guilty, (
        "чтение мимо общих корней: " + "; ".join(guilty) + ". Корни объявлены "
        "один раз (`trusted_roots`), и ходивший мимо них читатель получал с "
        "ядра CERTIFICATE_VERIFY_FAILED там, где проба того же хоста получала "
        "200.")


def test_the_refusal_page_is_named_a_refusal_not_an_empty_source() -> None:
    assert reading.refusal_reason("The URL you requested has been blocked")
    assert reading.refusal_reason("", "Web Page Blocked! The page cannot be displayed.")
    assert reading.refusal_reason("403 Forbidden")
    # Ложная примета дороже пропуска: по ней мы вычеркнули бы живую площадку.
    assert not reading.refusal_reason(
        "Купить услуги строительства и развития территорий на торгах на Росэлторг")


def test_the_card_reader_refuses_instead_of_parsing_a_block_page(monkeypatch) -> None:
    """Разобранная как карточка, страница блокировки даёт ноль ссылок.

    На экране это неотличимо от «лотов нет», а лечится совсем иначе.
    """
    monkeypatch.setattr(reading, "urlopen", lambda *a, **k: _Answer(BLOCK_PAGE))
    with pytest.raises(roseltorg.RoseltorgRefused) as refused:
        roseltorg.RoseltorgAdapter._read("https://www.roseltorg.ru/procedure/1/1", 5)
    assert "blocked" in str(refused.value).lower() or "заблок" in str(refused.value).lower()


def test_a_real_page_is_read_as_before(monkeypatch) -> None:
    """Предохранитель: на обычной странице читатель отдаёт её как есть."""
    page = b"<html><head><title>Lot</title></head><body>karta</body></html>"
    monkeypatch.setattr(reading, "urlopen", lambda *a, **k: _Answer(page))
    html = roseltorg.RoseltorgAdapter._read("https://www.roseltorg.ru/procedure/1/1", 5)
    assert "karta" in html


def test_a_block_page_is_not_an_unsupported_document(monkeypatch) -> None:
    """У вложения та же болезнь: 200 с HTML-отказом — это отказ, а не формат."""
    monkeypatch.setattr(documents, "urlopen", lambda *a, **k: _Answer(BLOCK_PAGE))
    with pytest.raises(documents.DocumentExtractionError) as failed:
        documents.download_document("https://www.roseltorg.ru/file/get/1/name/x.pdf")
    assert "отказ" in str(failed.value)

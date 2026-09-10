"""Сторож нормативов не объявляет смену редакции у непрочитанного документа.

Замер прода 09.09.2026: из тринадцати источников семь стояли с результатом
«изменилось», и у шести из них не нашлось НИ ОДНОГО своего слова. Две причины,
обе здесь и проверяются по отдельности.

Первая — кодировка: правовые порталы отдают windows-1251, а разбор читал тело
как utf-8 с `errors="ignore"`, то есть терял кириллицу целиком. Русское слово
документа не находилось никогда, на любой такой странице.

Вторая — порядок ответов: проверка маркеров стояла в `elif` ПОСЛЕ `changed` и
до неё не доходило вовсе. «Ветка `else` — не „всё остальное", а утверждение»:
раз ветка что-то говорит о величине, эта величина обязана входить в её условие.

Цена ошибки не в шуме: переход объявляется один раз (`_changes_between`
пропускает `was == result`), значит источник, застрявший в ложном «изменилось»,
настоящую смену редакции уже не объявит НИКОГДА.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import normatives_registry as registry  # noqa: E402


class _Headers:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def get(self, name: str, default: str = "") -> str:
        return self._values.get(name, default)


class _Response:
    def __init__(self, body: bytes, content_type: str) -> None:
        self._body = body
        self.status = 200
        self.headers = _Headers({"Content-Type": content_type, "Last-Modified": ""})

    def read(self, _limit: int = 0) -> bytes:
        return self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False


def _probe(monkeypatch: pytest.MonkeyPatch, body: bytes, content_type: str,
           terms: list[str], previous: dict[str, object]) -> dict[str, object]:
    monkeypatch.setattr(registry.urllib.request, "urlopen",
                        lambda *a, **k: _Response(body, content_type))
    entry = {"id": "test", "source_url": "https://example.test/doc", "watch_terms": terms}
    return registry._probe(entry, previous)


def test_a_page_is_read_in_the_encoding_the_server_declared(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Слово документа находится и в windows-1251, и в utf-8.

    На прежнем разборе кириллица из cp1251 пропадала при декодировании, и
    «2152-ПП» не находилось на странице, где оно стоит.
    """
    for encoding, header in (("cp1251", "text/html; charset=windows-1251"),
                             ("utf-8", "text/html; charset=utf-8")):
        body = "Постановление 2152-ПП о площади квартир".encode(encoding)
        got = _probe(monkeypatch, body, header, ["2152-ПП", "площади квартир"], {})
        assert got["found_terms"] == ["2152-ПП", "площади квартир"], encoding
        assert got["missing_terms"] == [], encoding
        assert got["result"] == "ok", encoding
        # Чем прочитано — часть ответа: без имени кодировки «слов не нашлось»
        # неотличимо от «читали не тем».
        assert got["charset"], encoding


def test_changed_bytes_without_its_own_words_are_not_a_new_edition(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Скачали не документ — значит о его редакции сказать нечего.

    Прежний разбор в этом случае отвечал «содержимое изменилось — нужна ревизия
    редакции», то есть делал утверждение о документе, которого не видел.
    """
    body = "Запрашиваемая страница не найдена".encode("cp1251")
    got = _probe(monkeypatch, body, "text/html; charset=windows-1251",
                 ["2152-ПП", "площади квартир"], {"sha256": "прежний-отпечаток"})
    assert got["result"] == "review_required"
    assert got["found_terms"] == []
    # Сам факт смены байтов не пропадает — он остаётся полем и называется в тексте.
    assert got["changed"] is True
    assert "другую страницу" in str(got["message"])


def test_changed_bytes_with_its_own_words_stay_a_change(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Починка не должна проглотить настоящую смену редакции."""
    body = "Постановление 2152-ПП, редакция 2026 года".encode("utf-8")
    got = _probe(monkeypatch, body, "text/html; charset=utf-8",
                 ["2152-ПП"], {"sha256": "прежний-отпечаток"})
    assert got["result"] == "changed"
    assert got["changed"] is True


def test_a_document_without_watch_terms_is_judged_by_its_bytes(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """У PDF маркеров не спрашивают: там `is_text` ложно, и «0 из 0» честно.

    Иначе всякий PDF навсегда уходил бы в «маркеры не найдены».
    """
    got = _probe(monkeypatch, b"%PDF-1.4 ...", "application/pdf",
                 ["2152-ПП"], {"sha256": "прежний-отпечаток"})
    assert got["result"] == "changed"
    assert got["found_terms"] == [] and got["missing_terms"] == []

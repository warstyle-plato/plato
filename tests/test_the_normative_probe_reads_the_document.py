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


# --- документ опознаётся собственным именем ----------------------------------
#
# Замер прода 19.09.2026: пять источников из пятнадцати стояли с «контрольные
# маркеры документа не найдены» — и у 214-ФЗ имя акта стоит на странице ПЕРВОЙ
# строкой. Причина не в странице: реестр держит обрывки в своём падеже
# («нормативов»), а документ и все, кто о нём пишет, — в своём («нормативы»), и
# точное совпадение строки не находит такое имя никогда.

_MO_ENTRY = {
    "id": "mo-713-30",
    "source_url": "https://example.test/doc",
    "title": "Постановление Правительства Московской области от 17.08.2015 "
             "№ 713/30 «Об утверждении нормативов градостроительного "
             "проектирования Московской области»",
    "watch_terms": ["713/30"],
}


def _probe_entry(monkeypatch: pytest.MonkeyPatch, entry: dict[str, object],
                 body: bytes, previous: dict[str, object] | None = None) -> dict[str, object]:
    monkeypatch.setattr(registry.urllib.request, "urlopen",
                        lambda *a, **k: _Response(body, "text/html; charset=utf-8"))
    return registry._probe(entry, previous or {})


def test_a_page_is_recognised_by_the_acts_own_name(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Имя в другом падеже — то же имя, и страница опознана.

    Строка взята со страницы публикатора как есть: там стоит имя поправки, а
    номер базового акта не стоит вовсе.
    """
    body = ('Постановление Правительства Московской области от 01.09.2026 '
            '№ 1080-ПП "О внесении изменений в нормативы градостроительного '
            'проектирования Московской области"').encode("utf-8")
    got = _probe_entry(monkeypatch, _MO_ENTRY, body, {"sha256": "прежний"})
    assert got["found_name"] is True
    assert got["found_terms"] == [] and got["missing_terms"] == ["713/30"]
    # Опознан — значит смена байтов снова означает смену редакции, а не
    # «скачали другую страницу».
    assert got["result"] == "changed"


def test_a_wrapper_page_is_still_not_the_document(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Опознание по имени не имеет права проглотить заглушку.

    У 114-Р области по ссылке лежит JS-оболочка со спиннером: ни маркеров, ни
    имени. Такой ответ обязан остаться «нужна ревизия» — иначе починка
    опознания превратила бы антибот-заглушку в подтверждённый документ.
    """
    body = b"<html><div class='spinner-container'></div></html>"
    got = _probe_entry(monkeypatch, _MO_ENTRY, body, {"sha256": "прежний"})
    assert got["found_name"] is False
    assert got["result"] == "review_required"


def test_the_name_of_a_neighbour_act_does_not_recognise_ours() -> None:
    """Опознание — не «похожая тема».

    945-ПП Москвы зовётся «Об утверждении нормативов градостроительного
    проектирования города Москвы в области транспорта…»: с областным 713/30 у
    него совпадают пять слов из шести как МНОЖЕСТВО и только четыре подряд.
    Порог отрезка эту подмену и отсекает — иначе находка о судьбе одного акта
    приезжала бы другому.
    """
    moscow = ("Об утверждении нормативов градостроительного проектирования "
              "города Москвы в области транспорта, автомобильных дорог "
              "регионального или межмуниципального значения")
    words = registry.name_stems(_MO_ENTRY)
    assert registry.name_run(moscow, words) == 4
    assert registry.name_recognised(moscow, _MO_ENTRY,
                                    registry.NAME_SIGNAL_RUN_SHARE) is False


def test_an_entry_without_a_name_is_judged_by_its_terms_only() -> None:
    """Имени нет в реестре — ответа нет, а не «да».

    У приказов ДГИ и ДИиПП заголовок без кавычек, имени взять негде, и
    опознание обязано остаться на обрывках: иначе пустое имя совпадало бы со
    всем подряд.
    """
    entry = {"id": "moscow-dgi-303-vri-index",
             "title": "Приказ Департамента городского имущества города Москвы "
                      "от 30.07.2026 № 303 — коэффициент изменения цен",
             "watch_terms": ["303"]}
    assert registry.name_stems(entry) == []
    assert registry.name_recognised("что угодно", entry, 0.1) is False


def test_our_own_link_change_is_not_the_source_changing(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Ссылку в реестре меняем мы сами — это не «источник изменился».

    Акт переиздан, источником становится публикация новой поправки, и
    отпечаток у неё другой по построению. Без оговорки об адресе наша
    собственная правка реестра уезжала бы сообщением в чат «содержимое
    источника изменилось» — и в следующий раз настоящую смену объявить было бы
    уже нечем: сообщается переход.
    """
    body = "Постановление 1080-ПП о нормативах".encode("utf-8")
    entry = {"id": "mo-713-30", "source_url": "https://example.test/new",
             "watch_terms": ["1080-ПП"]}
    monkeypatch.setattr(registry.urllib.request, "urlopen",
                        lambda *a, **k: _Response(body, "text/html; charset=utf-8"))
    got = registry._probe(entry, {"sha256": "отпечаток старой ссылки",
                                  "url": "https://example.test/old"})
    assert got["result"] == "ok" and got["changed"] is False
    assert got["url"] == "https://example.test/new"
    # Та же ссылка с другим телом — по-прежнему смена содержимого.
    again = registry._probe(entry, {"sha256": "другой", "url": "https://example.test/new"})
    assert again["result"] == "changed" and again["changed"] is True

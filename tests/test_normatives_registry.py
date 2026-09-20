from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from starlette.requests import Request

import normatives_registry as registry

ROOT = Path(__file__).resolve().parents[1]


def _request(query: str = "") -> Request:
    return Request({
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": "/normatives",
        "raw_path": b"/normatives",
        "query_string": query.encode("utf-8"),
        "headers": [],
        "client": ("test", 1),
        "server": ("developaid", 443),
    })


# Заглушка ОБЯЗАНА иметь сигнатуру настоящего гейта движка: `(session, key)`.
# Пока она принимала целиком `Request`, эти проверки были зелёными на коде,
# который не опознавал владельца НИ РАЗУ, — то есть они не «не поймали»
# поломку, а заказали её: единственный способ их позеленить был передать гейту
# то, чего он не принимает. Правило то же, что с `structuredClone`: подделка
# чужого помощника проверяет наш код только тогда, когда повторяет его форму.
def _checker(seen: list | None = None, answer: bool = True):
    def gate(session: str = "", key: str = "") -> bool:
        if seen is not None:
            seen.append((session, key))
        return answer
    return gate


def test_normatives_reuse_the_developaid_admin_checker():
    """Гейт зовётся так, как он объявлен: сессией и ключом, а не запросом."""
    seen: list = []
    core = SimpleNamespace(_is_admin_request=_checker(seen))

    assert registry._is_admin(_request("key=secret"), core) is True
    assert seen == [("", "secret")], seen


def test_the_session_reaches_the_checker_too():
    """Владельца опознают и по сессии — вход через бота, а не только ключом."""
    seen: list = []
    core = SimpleNamespace(_is_admin_request=_checker(seen))

    assert registry._is_admin(_request("session=abc"), core) is True
    assert seen == [("abc", "")], seen


def test_normatives_do_not_invent_a_second_admin_secret(monkeypatch):
    monkeypatch.setenv("NORMATIVES_ADMIN_KEY", "must-not-be-used")
    core = SimpleNamespace(_is_admin_request=_checker(answer=False))

    assert registry._is_admin(_request("key=secret"), core) is False


def _admin_bar(page: str) -> str:
    """Сама панель, а не подстрока с именем кнопки.

    `#checkBtn` стоит ещё и в стилях, то есть присутствует на странице ВСЕГДА:
    проверка по имени кнопки отвечала бы «панель есть» и там, где её нет.
    """
    start = page.find('<div class="adminbar">')
    return "" if start < 0 else page[start:start + 900]


def test_admin_button_is_not_rendered_for_public_user(monkeypatch):
    monkeypatch.setattr(registry, "_merged_registry", lambda: [])
    core = SimpleNamespace(_is_admin_request=_checker(answer=False))

    page = registry._page(_request(), core)

    assert _admin_bar(page) == ""
    assert "NORMATIVES_ADMIN_KEY" not in page


def test_admin_button_is_rendered_for_existing_admin(monkeypatch):
    monkeypatch.setattr(registry, "_merged_registry", lambda: [])
    core = SimpleNamespace(_is_admin_request=_checker())

    bar = _admin_bar(registry._page(_request("key=secret"), core))

    assert "Режим администратора DevelopAid" in bar
    # Вопроса два, и кнопка называет свой: «Проверить источники» обещала и
    # отмену акта, которую отпечаток не видит по построению.
    assert "Проверить ссылки" in bar


def test_registry_does_not_treat_a_mosru_draft_as_current_law():
    rows = {row["id"]: row for row in registry._load_registry()}
    item = rows["moscow-2152-pp"]

    assert "projects/" not in item["source_url"]
    assert "61-ПП" in item["latest_amendment"]
    assert item["status"] == "review_required"


def test_registry_tracks_the_latest_known_depr_index_document():
    rows = {row["id"]: row for row in registry._load_registry()}
    item = rows["moscow-depr-index"]

    assert "ДПР-Р-20/26" in item["title"]
    assert "ДПРР-18-26" not in item["title"]


def test_mpt_card_exposes_the_july_2026_review_gap():
    rows = {row["id"]: row for row in registry._load_registry()}
    item = rows["moscow-1874-pp"]

    assert "2072-ПП" in item["latest_amendment"]
    assert "1965-ПП" in item["latest_amendment"]
    assert item["status"] == "review_required"


def test_a_source_link_carries_no_click_id():
    """Метка перехода в ссылке источника — факт о нашем поиске, а не о документе.

    08.09.2026 ссылка на 214-ФЗ пришла из выдачи Яндекса с хвостом `ysclid`.
    Такой хвост протухает вместе с сессией поиска, а в реестре живёт вечно и
    выглядит частью адреса документа. Хуже того, он рассказывает, где мы искали,
    в публичном репозитории.

    Проверка держит утверждение, а не список: запрещены параметры перехода у
    ЛЮБОЙ карточки, включая те, что появятся позже.
    """
    import urllib.parse

    junk = {"ysclid", "utm_source", "utm_medium", "utm_campaign", "utm_term",
            "utm_content", "gclid", "fbclid", "yclid", "_openstat"}
    found = []
    for row in registry._load_registry():
        query = urllib.parse.urlsplit(row.get("source_url") or "").query
        marks = sorted(set(urllib.parse.parse_qs(query)) & junk)
        if marks:
            found.append((row.get("id"), marks))
    assert not found, f"в ссылке источника осталась метка перехода: {found}"


def test_the_click_id_guard_fails_on_a_forged_link(monkeypatch):
    """Сторож обязан падать на поломке — иначе он не сторож.

    Правило проверяется подделкой: карточка с `ysclid` должна быть найдена.
    Без этого «нарушений нет» означало бы, что не сработал сам обход.
    """
    forged = [{"id": "поддельная", "source_url": "http://example.org/doc?nd=1&ysclid=abc"}]
    monkeypatch.setattr(registry, "_load_registry", lambda: forged)
    import pytest
    with pytest.raises(AssertionError, match="метка перехода"):
        test_a_source_link_carries_no_click_id()


def test_the_card_leads_to_the_act_itself() -> None:
    """Публикация редакции и страница самого акта — разные адреса.

    «Сам 713/30 лежит вообще у нас где-то?» (владелец, 19.09.2026). Публикация
    поправки заморожена днём выхода: консолидированного текста в ней нет, и
    карточка, у которой ссылка одна, на этот вопрос ответить не могла.
    """
    entry = {"id": "mo-713-30", "scope": "Московская область",
             "short_name": "713/30", "title": "Постановление № 713/30 «Об утверждении»",
             "source_url": "http://publication.pravo.gov.ru/document/5000202609020006",
             "source_label": "Официальное опубликование — 1080-ПП",
             "act_page_url": "https://mosreg.ru/dokumenty/act",
             "act_page_label": "Страница самого акта"}
    card = registry._card(entry)
    assert "5000202609020006" in card, "ссылки на публикацию редакции нет"
    assert "https://mosreg.ru/dokumenty/act" in card, "ссылки на сам акт нет"
    assert "Страница самого акта" in card
    # Ссылка на несуществующее — такая же ложь, как подпись под чужим числом.
    assert "Страница самого акта" not in registry._card(
        dict(entry, act_page_url="", act_page_label=""))


def test_the_registry_says_the_base_act_is_not_in_the_library() -> None:
    """Чего в библиотеке НЕТ, сказано в самой карточке.

    У 713/30 лежат только поправки и приложение № 10: пробел этот стоит
    восьми открытых дыр справочника, и молча он читается как «всё есть».
    """
    import json

    rows = {row["id"]: row for row in json.loads(
        (ROOT / "data" / "normatives" / "registry.json").read_text(encoding="utf-8"))}
    row = rows["mo-713-30"]
    assert "Консолидированного текста 713/30 у нас нет" in row["notes"]
    assert row["act_page_url"].startswith("https://mosreg.ru/")
    # Сами поправки при этом лежат файлами — и это проверяется, а не обещается.
    assert (ROOT / "docs" / "normative" / "mo_rngp_1080pp_20260901.pdf").exists()


def test_the_page_takes_its_scopes_from_the_rows(monkeypatch) -> None:
    """Плитки и кнопки отбора считаются по данным, а не перечислены в разметке.

    Перечисленный список отстаёт от реестра: строка с новой областью — а
    «Правовая рамка продукта» появилась именно так — не получила бы ни плитки,
    ни кнопки и читалась бы как отсутствующая.
    """
    rows = registry._load_registry() + [{
        "id": "test-scope",
        "scope": "Проверочная область",
        "title": "Акт проверочной области",
        "cited_as": ["000-ПП"],
        "engine_usage": [{"module": "\u2014", "usage": "проверочная строка, в расчёте не участвует"}],
    }]
    monkeypatch.setattr(registry, "_merged_registry", lambda: rows)
    core = SimpleNamespace(_is_admin_request=_checker(answer=False))

    page = registry._page(_request(), core)

    assert "<div><b>1</b><span>Проверочная область</span></div>" in page
    assert 'data-filter="Проверочная область"' in page


def test_the_page_says_how_much_of_the_contour_is_covered(monkeypatch) -> None:
    """Строка охвата называет числа, а не обещает полноту.

    «Подтверждено» без «требует сверки» читается как проверенный целиком
    реестр, а объявленная цепочка без числа файлов — как полная библиотека.
    """
    rows = registry._load_registry()
    cover = registry.coverage(rows)
    assert cover["acts"] == len(rows)
    assert cover["steps"] >= cover["steps_with_file"] > 0
    assert 0 < cover["chained"] <= cover["acts"]

    monkeypatch.setattr(registry, "_merged_registry", lambda: rows)
    core = SimpleNamespace(_is_admin_request=_checker(answer=False))
    page = registry._page(_request(), core)
    line = page.split('<p class="coverline">', 1)[1].split("</p>", 1)[0]
    for number in (cover["acts"], cover["verified"], cover["review"],
                   cover["chained"], cover["steps"], cover["steps_with_file"]):
        assert str(number) in line, f"строка охвата не называет {number}: {line}"

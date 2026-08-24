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


def _html_surfaces() -> list[str]:
    """Адреса всех страниц приложения — у самого приложения, а не списком.

    Список поверхностей был перечислен руками, и новая в него не попадала: у
    торгов и у кабинета рынка подвала не было вовсе, а проверка оставалась
    зелёной — она сверяла ровно те четыре страницы, ради которых её писали.
    Теперь набор берётся из маршрутов: следующая поверхность попадает в
    проверку тем, что она появилась.
    """
    import main_registry
    from fastapi.routing import APIRoute

    paths = []
    for route in main_registry.app.routes:
        if not isinstance(route, APIRoute) or "GET" not in (route.methods or set()):
            continue
        if route.param_convertors:
            continue  # адрес с параметром — это не страница продукта
        if "HTML" not in getattr(route.response_class, "__name__", ""):
            continue
        paths.append(route.path)
    return sorted(set(paths))


def test_every_page_of_the_product_carries_the_documents():
    """Подвал — на каждой странице, а не на тех, о которых вспомнили.

    Из карточки лота и из кабинета рынка в политику попасть было нельзя:
    подвала там не было ни одного. Правило записано давно — «документ ИП живёт
    не только на главной», — но проверка до этих поверхностей не доходила.
    """
    from fastapi.testclient import TestClient
    import main_registry

    client = TestClient(main_registry.app)
    checked, skipped = [], []
    for path in _html_surfaces():
        response = client.get(path)
        if response.status_code != 200:
            # Молча пропускать нельзя: непроверенная страница и страница без
            # замечаний выглядят одинаково. Причина называется вслух.
            skipped.append(f"{path} → {response.status_code}")
            continue
        text = response.text
        checked.append(path)
        for link in ('href="/consent"', 'href="/privacy"', 'href="/ads-consent"'):
            assert link in text, f"{path}: нет ссылки {link}"
        assert "© ИП" in text, f"{path}: подвал не называет владельца"
    assert checked, f"ни одной страницы не проверено; пропущены: {skipped}"


def test_every_page_wears_the_emblem():
    """Эмблема одна на все поверхности и лежит в `PAGE`.

    У торгов и у кабинета её не было: страницы начинались словом в заголовке.
    Своё нарисованное «ПЛАТО» тут не годится — так уже было на руководстве.
    """
    from fastapi.testclient import TestClient
    import main_registry

    client = TestClient(main_registry.app)
    for path in _html_surfaces():
        response = client.get(path)
        if response.status_code != 200:
            continue
        text = response.text
        assert "/guide/assets/logo.webp" in text or 'class="brandbar"' in text, \
            f"{path}: эмблемы нет"


def test_the_shared_footer_is_taken_from_the_page():
    """Состав подвала объявлен один раз — в `PAGE`; сборщик его оттуда читает."""
    import guide

    links = dict(guide.legal_links(core))
    assert links, "подвал `PAGE` не разобрался — разметка изменилась"
    for href in ("/consent", "/privacy", "/ads-consent", "/guide"):
        assert href in links, href
    assert guide.legal_owner(core).startswith("© ИП")
    html = guide.legal_footer_html(core)
    for href, label in links.items():
        assert f'href="{href}"' in html and label in html
    # «Оценить DevelopAid» зовёт функцию `PAGE`; на чужой поверхности её нет.
    assert "openFeedback" not in html


def test_a_changed_page_footer_is_said_out_loud():
    """Пустой подвал и отсутствующий выглядят одинаково — значит, разошедшуюся
    разметку `PAGE` надо назвать, а не отдать пустую строку."""
    import guide

    class Broken:
        PAGE = "<html><body>без подвала</body></html>"

    assert guide.legal_links(Broken) == []
    assert "не собран" in guide.legal_footer_html(Broken)


def _flat(text: str) -> str:
    """Текст документа без вёрстки: перенос строки в HTML — не разрыв фразы."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))


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


def test_the_pages_wear_the_real_emblem():
    """Эмблема одна на все поверхности. На руководстве и документах вместо неё
    стояло набранное вразрядку слово «ПЛАТО» — своя, придуманная (замечание
    владельца, 18.08.2026). Логотип берётся из шапки `PAGE`, копии нет."""
    import guide

    logo = guide.brand_logo(core)
    assert logo[:4] == b"RIFF" and logo[8:12] == b"WEBP", "эмблема не вынулась из PAGE"
    assert len(logo) > 4000

    for name, text in _document_pages().items():
        head = text[text.index('<header class="gtop"'):text.index("</header>")]
        assert 'src="/guide/assets/logo.webp"' in head, f"{name}: эмблемы нет"
        assert ">ПЛАТО<" not in head, f"{name}: слово вместо эмблемы"


def test_the_emblem_is_served():
    import main_registry
    from fastapi.testclient import TestClient

    response = TestClient(main_registry.app).get("/guide/assets/logo.webp")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    assert response.content[:4] == b"RIFF"



def test_the_documents_declare_what_the_journal_keeps():
    """Документ описывает журнал так, как он устроен, а не уже.

    Политика говорила «дата, время и вид действия», а журнал хранит ещё и
    содержание обращения — искомый адрес или кадастр, текст сообщения боту,
    вопрос Платону — с привязкой к аккаунту. Состав данных обязан быть заявлен
    (152-ФЗ), поэтому расхождение документа с кодом — не мелочь формулировки.
    """
    for name in ("privacy.html", "consent.html"):
        text = _flat(_document_pages()[name])
        assert "содержание обращения" in text, name
        assert "кадастровый номер участка" in text, name
        assert "вопрос агенту Сервиса" in text, name


def test_the_journal_term_is_taken_from_the_engine():
    """Срок хранения журнала подставляется из движка, а не живёт копией."""
    import main_registry
    from fastapi.testclient import TestClient

    for name in ("privacy.html", "consent.html"):
        assert "__JOURNAL_KEEP_DAYS__" in _document_pages()[name], (
            f"{name}: срок должен быть плейсхолдером, а не числом в тексте")

    client = TestClient(main_registry.app)
    days = str(int(core._USAGE_KEEP_DAYS))
    for path in ("/privacy", "/consent"):
        body = client.get(path).text
        assert "__JOURNAL_KEEP_DAYS__" not in body, path
        assert f"{days} дней" in body, (path, days)


def test_the_documents_name_the_model_provider():
    """Вопрос Платону уходит внешнему поставщику модели — это передача данных.

    Политика перечисляла только НСПД, хотя текст вопроса и данные расчёта
    уезжают к поставщику языковой модели, и за пределы страны. Умолчание здесь
    того же рода, что и урезанный состав журнала.
    """
    for name in ("privacy.html", "consent.html"):
        text = _flat(_document_pages()[name])
        assert "языковой модели" in text, name
        assert "за пределы Российской Федерации" in text, name

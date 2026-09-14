"""Любая площадка КРТ разбирается тем же сборщиком, что Нагатино.

«Цель была чтобы все крт с торгов разбирались по образу и подобию Нагатино»
(владелец, 13.09.2026). До этой правки свод территории умела ровно ОДНА
площадка: источники были зашиты в модуль — присланная владельцем выгрузка по
кварталу 77:05:0004001, извещение и проект решения файлами в `reference_data`, —
и вопрос «кто здесь собственник и что снесут» у остальных 529 площадок каталога
не задавался нигде.

Утверждения здесь такие.

**Сборщик свода один.** Его зовут и Нагатино, и площадка с торгов; меняются
только источники. Второй сборки не заводим — разойдясь, две сборки дали бы два
достоверных на вид ответа об одной территории.

**Кэш контуров у площадок разный, а у Нагатино прежний.** Общий кэш смешал бы
контуры двух территорий, а сменившееся имя файла обесценило бы прочитанное.

**Извещение сильнее перечня решения, и чем собран состав — часть ответа.** В
решении нет привязки «объект → участок»: подставленный молча, перечень выглядел
бы полным составом.

**Пустой состав — это «не читали», а не «территория пуста».** У шести КРТ из
одиннадцати с живым лотом перечня нет ни в извещении, ни в решении (замер прода
13.09.2026), и молча показанная пустая карта читалась бы как площадка без
объектов.

**Группы владельца — только у Нагатино.** «Брынцалов красный» — его слова о
конкретных лицах конкретной площадки; приписанная группа выглядит на экране
ровно так же уверенно, как названная.

Запуск: python3 -m pytest tests/test_a_krt_site_is_read_like_nagatino.py -q
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import (  # noqa: E402
    egrn_store, krt_notice, krt_tenders, krt_territory, nagatino_parcels,
)

SITE = {"slug": "nizhnie-polya", "name": "Нижние Поля ул.", "status": "Планируемый",
        "okrug": "ЮВАО", "district": "Люблино", "area_ha": 21.3,
        "total_gfa_sqm": 300_000, "housing_gfa_sqm": 200_000}

LOT = {"title": "21000005000000033023 Лот 1 Аукцион на право заключения договора о КРТ",
       "url": "https://www.roseltorg.ru/procedure/21000005000000033023/1",
       "address": "г. Москва, Нижние Поля ул.",
       "deadline": "2026-12-01", "price_rub": 1_000_000_000,
       "store_key": "21000005000000033023/1"}

LAND = {"kind": "land", "source": "xml", "cadastral_number": "77:04:0004010:1",
        "address": "город Москва, Нижние Поля ул., влд. 1", "area_sqm": 5_000.0,
        "cadastral_value_rub": 12_000_000.0, "area_kind": "Уточнённая площадь",
        "category": "Земли населенных пунктов", "permitted_use": "производство",
        "rights": [{"type": "Собственность", "number": "77:04:0004010:1-77/1",
                    "date": "2021-03-04", "share": "",
                    "holders": [{"kind": "company", "name": "ООО «Полевая»",
                                 "inn": "7712345678", "ogrn": "1127746000000"}]}],
        "restrictions": [], "objects": []}

BUILD = {"kind": "build", "source": "xml", "cadastral_number": "77:04:0004010:77",
         "address": "город Москва, Нижние Поля ул., 1, стр. 1", "area_sqm": 900.0,
         "cadastral_value_rub": 3_000_000.0, "purpose": "Нежилое",
         "rights": [{"type": "Собственность", "number": "77:04:0004010:77-77/2",
                     "date": "2021-03-04", "share": "",
                     "holders": [{"kind": "company", "name": "ООО «Полевая»",
                                  "inn": "7712345678", "ogrn": "1127746000000"}]}],
         "restrictions": [], "objects": []}


def _store(root: Path, *records: dict) -> None:
    egrn_store.save(root, LOT["store_key"],
                    {"records": list(records), "entries": len(records),
                     "read": len(records), "unread": [], "companions": []},
                    "ЕГРН 1.zip")


def _site(root: Path, numbers: list[str] | None = None):
    return krt_territory.site_for(SITE["slug"], SITE["name"],
                                  key=LOT["store_key"],
                                  decision_numbers=numbers or [], root=root)


def test_the_same_builder_answers_for_a_site_from_the_auctions(tmp_path):
    """Свод считает `territory` — тот же, что у Нагатино, и на тех же полях."""
    _store(tmp_path, LAND, BUILD)
    krt_territory.remember_notice(
        LOT["store_key"],
        {"lands": [{"cadastral_number": LAND["cadastral_number"], "part": False,
                    "area_raw": "5 000", "area_sqm": 5_000.0,
                    "objects": [{"cadastral_number": BUILD["cadastral_number"],
                                 "area_sqm": 900.0, "fate": "снос"}]}],
         "objects": [{"cadastral_number": BUILD["cadastral_number"],
                      "area_sqm": 900.0, "fate": "снос",
                      "lands": [LAND["cadastral_number"]]}],
         "rows": 2, "problem": ""},
        document="Извещение.pdf", root=tmp_path)

    view = nagatino_parcels.territory(_site(tmp_path))
    land, = view["lands"]
    assert land["cadastral_number"] == LAND["cadastral_number"]
    assert land["owner"]["name"] == "ООО «Полевая»", land["owner"]
    assert land["area_sqm"] == 5_000.0
    obj, = view["objects"]
    assert obj["fate"] == "снос", "судьба объекта из извещения не доехала"
    assert obj["owner"]["inn"] == "7712345678"
    # Состав собран извещением, и это сказано: у перечня решения привязки
    # «объект → участок» нет вовсе, и подставленный молча он выглядел бы полным.
    assert view["source"]["notice_problem"] == ""
    assert land["objects"], "объект не сел на свой участок"


def test_the_decision_list_is_the_spare_composition_and_says_so(tmp_path):
    """Извещения нет — состав из перечня решения, и он назван своим именем."""
    _store(tmp_path, LAND)
    site = _site(tmp_path, [LAND["cadastral_number"], "77:04:0004010:2"])
    notice = site.documents()["notice"]
    assert notice["source"] == "decision", notice
    assert len(notice["lands"]) == 2
    # Привязки объектов в решении нет — и её не выдумываем.
    assert notice["objects"] == []
    view = nagatino_parcels.territory(site)
    assert len(view["lands"]) == 2
    assert view["objects"] == []


def test_the_notice_beats_the_decision_list(tmp_path):
    """Извещение свежее и оно основание торгов — состав берётся из него."""
    krt_territory.remember_notice(
        LOT["store_key"],
        {"lands": [{"cadastral_number": LAND["cadastral_number"], "part": False,
                    "area_raw": "", "area_sqm": None, "objects": []}],
         "objects": [], "rows": 1, "problem": ""},
        document="Извещение.pdf", root=tmp_path)
    site = _site(tmp_path, ["77:04:0004010:2", "77:04:0004010:3"])
    notice = site.documents()["notice"]
    assert notice["source"] == "notice", notice
    assert [land["cadastral_number"] for land in notice["lands"]] == [
        LAND["cadastral_number"]]


def test_an_empty_composition_is_not_an_empty_territory(tmp_path):
    """Ни извещения, ни перечня — причина названа, а не пустая карта."""
    notice = _site(tmp_path).documents()["notice"]
    assert notice["lands"] == []
    assert notice["problem"], "молчание источников выдано за пустую территорию"
    assert notice["source"] == ""


def test_an_empty_parse_does_not_evict_what_was_read(tmp_path):
    """Таблица состава стоит в ОДНОМ вложении из многих."""
    good = {"lands": [{"cadastral_number": LAND["cadastral_number"], "part": False,
                       "area_raw": "", "area_sqm": None, "objects": []}],
            "objects": [], "rows": 1, "problem": ""}
    krt_territory.remember_notice(LOT["store_key"], good,
                                  document="Извещение.pdf", root=tmp_path)
    krt_territory.remember_notice(LOT["store_key"],
                                  {"lands": [], "objects": [], "rows": 0},
                                  document="Проект договора.pdf", root=tmp_path)
    assert krt_territory.stored_notice(LOT["store_key"], root=tmp_path)["lands"]


def test_each_site_keeps_its_own_outlines_and_nagatino_keeps_its_file(tmp_path):
    """Общий кэш смешал бы контуры двух территорий."""
    one = krt_territory.site_for("alpha", "Альфа", root=tmp_path)
    two = krt_territory.site_for("beta", "Бета", root=tmp_path)
    assert nagatino_parcels.cache_path(one) != nagatino_parcels.cache_path(two)
    # Имя файла Нагатино не менялось: сменившееся обесценило бы прочитанное.
    assert nagatino_parcels.cache_path().name == "nagatino.json"
    assert nagatino_parcels.cache_path(one).name.startswith("site-")


def test_the_owner_groups_belong_to_nagatino_only():
    """«Брынцалов красный» — о конкретных лицах конкретной площадки."""
    empty = nagatino_parcels.empty_registry()
    keys = {str(group.get("key")) for group in empty["groups"]}
    assert "bryntsalov" not in keys, keys
    assert "moscow" in keys, "город остаётся зелёным на любой площадке"
    assert empty["parcels"] == [] and empty["owners"] == []
    # Оттенки владельцам нужны: карта без них одноцветна.
    assert empty["other_shades"]


def test_the_store_key_travels_with_the_link():
    """Без ключа склада свод не знает, где выписки этой площадки."""
    matched = krt_tenders.match(
        [{"title": "Аукцион на право заключения договора о КРТ, площадью 21,3 га",
          "address": "г. Москва, Нижние Поля ул.", "lot_kind": "krt",
          "canonical_key": "roseltorg:33023",
          "source": {"lot_url": LOT["url"], "external_lot_id": "21000005000000033023/1",
                     "catalogue": "roseltorg"}}],
        [dict(SITE)])
    lots = matched["by_site"].get(SITE["slug"]) or matched["unmatched"]
    assert lots, matched
    assert lots[0]["store_key"] == "21000005000000033023/1", lots[0]


def test_the_notice_is_read_from_bytes_the_same_way():
    """Разбор один: вложение приезжает байтами, первоисточник лежит файлом."""
    place = ROOT / "reference_data" / "krt" / "nagatino-auction-notice-2026-08-14.pdf"
    assert krt_notice.read(place) == krt_notice.read_bytes(place.read_bytes())


def _app(tmp_path):
    from fastapi import FastAPI

    from auction_search.api import install
    from market_search.krt_registry import KrtRegistry

    registry = KrtRegistry(tmp_path)
    registry.remember_tender_lots({SITE["slug"]: [dict(LOT)]})
    app = FastAPI()


    def _bomb(*_args, **_kwargs):
        """Каталог внутри запроса страницы не спрашивается — и это проверяется.

        Первая версия брала имя площадки из общего списка, а тот при
        просроченном снимке уходит обходить krt.mos.ru: страница вставала
        насмерть, и пять браузерных проверок Нагатино упали таймаутом.
        """
        raise AssertionError("каталог спрошен внутри запроса страницы")

    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(
            catalogue=_bomb,
            status=lambda: {"complete": True, "refreshing": False},
            find=lambda query: (dict(SITE) if query == f"krt:{SITE['slug']}" else None),
            tender_lots_known=registry.tender_lots_known,
            remember_tender_lots=registry.remember_tender_lots,
        ),
    )
    install(app)
    return app


def test_the_route_answers_for_a_site_and_names_it(tmp_path, monkeypatch):
    """Маршрут есть у любой площадки, и он называет, чья это территория."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    root = tmp_path / "market"
    root.mkdir(parents=True, exist_ok=True)
    _store(root, LAND, BUILD)
    krt_territory.remember_notice(
        LOT["store_key"],
        {"lands": [{"cadastral_number": LAND["cadastral_number"], "part": False,
                    "area_raw": "", "area_sqm": None,
                    "objects": [{"cadastral_number": BUILD["cadastral_number"],
                                 "area_sqm": 900.0, "fate": "снос"}]}],
         "objects": [{"cadastral_number": BUILD["cadastral_number"],
                      "area_sqm": 900.0, "fate": "снос",
                      "lands": [LAND["cadastral_number"]]}],
         "rows": 2, "problem": ""},
        document="Извещение.pdf", root=root)
    # Контуры ЕГРН в запросе не спрашиваются: сеть внутри запроса не трогается.
    monkeypatch.setenv("NAGATINO_EGRN_READ", "0")

    client = TestClient(_app(tmp_path))
    answer = client.get(f"/krt/site/{SITE['slug']}/parcels")
    assert answer.status_code == 200, answer.text
    data = answer.json()
    assert data["site"]["name"] == SITE["name"], data["site"]
    assert data["site"]["slug"] == SITE["slug"]
    view = data["territory"]
    assert [land["cadastral_number"] for land in view["lands"]] == [
        LAND["cadastral_number"]]
    assert view["objects"][0]["fate"] == "снос"
    # Выгрузки владельца у площадки с торгов нет — и это ответ, а не пустота.
    assert data["parcels"] == []
    assert data["owners"], "собственники по выпискам до экрана не доехали"

    # Незнакомая площадка — 404, а не пустой свод: пустой читался бы как
    # территория без объектов.
    assert client.get("/krt/site/no-such-site/parcels").status_code == 404


def test_the_page_is_one_and_the_address_decides_whose_territory(tmp_path):
    """Форка страницы нет: та же разметка по обоим адресам."""
    from fastapi.testclient import TestClient

    client = TestClient(_app(tmp_path))
    one = client.get("/krt/nagatino")
    two = client.get(f"/krt/site/{SITE['slug']}")
    assert one.status_code == two.status_code == 200
    assert one.text == two.text, "у страницы завёлся форк"
    # База адресов берётся из `location`, а не пишется строкой: иначе страница
    # площадки просила бы данные Нагатино.
    assert "location.pathname" in one.text
    assert "/krt/site/" in one.text


# --- то же, но без единого числа, поданного рукой --------------------------
# Прежде разбор загрузчика жил ТОЛЬКО в ответе маршрута: свод территории читать
# его было нечем, и площадка выглядела непрочитанной при двадцати шести
# прочитанных вложениях. Здесь цепочка идёт целиком — вложения лота, склад,
# свод, — потому что проверять надо ту дверь, в которую ходят.

EXTRACTS = ROOT / "reference_data" / "krt" / "egrn"
NOTICE_PDF = ROOT / "reference_data" / "krt" / "nagatino-auction-notice-2026-08-14.pdf"
EGRN_URL = "https://www.roseltorg.ru/file/egrn.zip"
NOTICE_URL = "https://www.roseltorg.ru/file/notice.pdf"


def _zipped(entries: dict[str, bytes]) -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in entries.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def _krt_lot():
    from auction_search.models import (
        AuctionDocument, AuctionLot, AuctionSource, LotKind, SourceKind,
    )

    return AuctionLot(
        source=AuctionSource(platform=SourceKind.ROSELTORG,
                             lot_url="https://www.roseltorg.ru/procedure/33023/1",
                             external_lot_id="21000005000000033023/1",
                             fetched_at="2026-09-13T10:00:00Z"),
        lot_kind=LotKind.KRT,
        title="КРТ: право на заключение договора",
        documents=[
            AuctionDocument(title="Выписки ЕГРН.zip", url=EGRN_URL,
                            document_type="egrn"),
            AuctionDocument(title="Извещение.pdf", url=NOTICE_URL,
                            document_type="notice"),
        ],
    )


def test_the_pipeline_leaves_what_it_read_where_the_territory_reads_it(
        tmp_path, monkeypatch):
    """Разобранное загрузчиком ложится на склад — иначе свода не собрать."""
    from auction_search import krt_pipeline

    land = (EXTRACTS / "77_05_0004001_1.xml").read_bytes()
    build = next(place for place in sorted(EXTRACTS.glob("*.xml"))
                 if place.name != "77_05_0004001_1.xml").read_bytes()
    archive = _zipped({"земля.xml": land, "здание.xml": build})

    def platform(url, **_kwargs):
        if url == EGRN_URL:
            return archive, "application/zip", False
        return NOTICE_PDF.read_bytes(), "application/pdf", False

    monkeypatch.setattr(krt_pipeline, "download_document", platform)
    lot = krt_pipeline.enrich_krt_from_official_documents(
        _krt_lot(), store_dir=tmp_path)
    key = krt_pipeline.store_key(lot)
    assert key == "21000005000000033023/1"

    kept = egrn_store.load(tmp_path, key)
    assert kept["records"], "разобранные выписки до склада не доехали"
    stored = krt_territory.stored_notice(key, root=tmp_path)
    assert stored["lands"], "состав территории из извещения до склада не доехал"

    # И главное: тот же сборщик собирает свод по этим складам, без единого
    # числа, поданного рукой.
    site = krt_territory.site_for("some-krt", "Некая площадка", key=key,
                                  root=tmp_path)
    view = nagatino_parcels.territory(site)
    assert len(view["lands"]) == len(stored["lands"])
    assert view["totals"]["objects"] > 0, view["totals"]
    # У прочитанного объекта видно, что с ним будет: это ответ извещения.
    assert any(item.get("fate") for item in view["objects"])


def test_an_empty_notice_parse_is_named_and_does_not_pretend(tmp_path, monkeypatch):
    """Вложение без таблицы состава не выдаёт себя за прочитанный состав."""
    from auction_search import krt_pipeline

    def platform(url, **_kwargs):
        if url == EGRN_URL:
            return _zipped({"пусто.txt": b"nothing"}), "application/zip", False
        # PDF без таблицы приложения 2: разбор ответит пустым составом.
        return b"%PDF-1.4\n%%EOF\n", "application/pdf", False

    monkeypatch.setattr(krt_pipeline, "download_document", platform)
    lot = krt_pipeline.enrich_krt_from_official_documents(
        _krt_lot(), store_dir=tmp_path)
    key = krt_pipeline.store_key(lot)
    stored = krt_territory.stored_notice(key, root=tmp_path)
    assert stored["lands"] == []
    assert stored["problem"], "молчание склада выдано за пустую территорию"


def test_in_a_real_browser_the_page_asks_its_own_address(tmp_path, monkeypatch):
    """Страница просит данные СВОЕЙ территории, а не Нагатино.

    База адресов берётся из `location`, и проверить это можно только запуском:
    в исходнике страница с зашитым адресом выглядит точно так же. Открытая с
    диска, она живёт в другом мире — её собственные запросы становятся
    `file:///krt/...`, — поэтому страница поднимается по тому адресу, по
    которому её открывает человек.
    """
    import pytest

    from browser import chromium_or_skip, serve

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NAGATINO_EGRN_READ", "0")
    root = tmp_path / "market"
    root.mkdir(parents=True, exist_ok=True)
    _store(root, LAND, BUILD)
    krt_territory.remember_notice(
        LOT["store_key"],
        {"lands": [{"cadastral_number": LAND["cadastral_number"], "part": False,
                    "area_raw": "", "area_sqm": None,
                    "objects": [{"cadastral_number": BUILD["cadastral_number"],
                                 "area_sqm": 900.0, "fate": "снос"}]}],
         "objects": [{"cadastral_number": BUILD["cadastral_number"],
                      "area_sqm": 900.0, "fate": "снос",
                      "lands": [LAND["cadastral_number"]]}],
         "rows": 2, "problem": ""},
        document="Извещение.pdf", root=root)

    with serve(_app(tmp_path), 18797) as base:
        asked: list[str] = []
        with sync_playwright() as play:
            browser = play.chromium.launch(executable_path=str(chrome))
            page = browser.new_page()
            page.on("request", lambda request: asked.append(request.url))
            page.goto(f"{base}/krt/site/{SITE['slug']}", wait_until="networkidle")
            title = page.inner_text("#pageTitle")
            line = page.inner_text("#siteLine")
            rows = page.eval_on_selector_all(
                "#territoryBox tr", "nodes => nodes.length")
            share = page.eval_on_selector("#share", "node => node.innerHTML.trim()")
            browser.close()

    mine = [url for url in asked if "/parcels?" in url]
    assert mine, f"страница не спросила свой свод: {asked}"
    assert f"/krt/site/{SITE['slug']}/parcels" in mine[0], mine
    assert not [url for url in asked if "/krt/nagatino/parcels" in url], (
        "страница площадки спросила данные Нагатино")
    # Имя площадки берётся из ответа: зашитое называло бы чужую территорию.
    assert SITE["name"] in title, title
    assert SITE["district"] in line, line
    assert rows > 1, "таблица территории не нарисовалась"
    # «Поделиться» у площадки с торгов нет: код ссылки один на страницу, и
    # кнопка выдала бы адрес чужой территории.
    assert share == "", share


def test_the_gated_page_says_where_the_other_sites_are(tmp_path, monkeypatch):
    """Ссылки в публичной части нет — значит переход живёт на самой странице.

    Служебную страницу владелец просил не выносить в публичную часть (там
    живые компании с ИНН и кадастровая стоимость), и проверка это держит. Но
    тогда перейти между территориями можно только отсюда: страница без списка
    отвечала бы «а где остальные» молчанием.
    """
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NAGATINO_EGRN_READ", "0")
    client = TestClient(_app(tmp_path))
    data = client.get(f"/krt/site/{SITE['slug']}/parcels").json()
    row, = data["siblings"]
    assert row["slug"] == SITE["slug"]
    # Имя — адрес лота из связки, и подписано тем, чем является: каталог
    # внутри запроса страницы не спрашивается.
    assert row["name"] == LOT["address"], row
    assert row["name_source"] == "адрес лота", row
    assert row["url"] == f"/krt/site/{SITE['slug']}"
    assert row["deadline"] == LOT["deadline"], row
    # Момент считается при ЧТЕНИИ: связка лежит на диске и старше правила.
    assert row["deadline_iso"], row
    # «Торги идут» страница не утверждает: правило живости живёт у каталога, и
    # второе такое правило однажды ответило бы про один лот иначе.
    assert "live" not in row, row
    # Тот же список у Нагатино: с него владелец и заходит.
    assert client.get("/krt/nagatino/parcels",
                      params={"key": ""}).status_code in (200, 403)


def test_the_public_auctions_page_does_not_offer_the_service_page():
    """Публичная страница торгов ссылки на служебную не несёт.

    Правило владельца, и однажды я его уже нарушил кнопкой в карточке: страница
    торгов открыта всем, а за этим адресом лицензионные данные — живые компании
    с ИНН и кадастровая стоимость. Проверка соседняя (в тестах страницы
    Нагатино) держит то же; здесь она стоит рядом с правкой, которая её
    нарушила.
    """
    from auction_search import ui

    page = ui.auctions_page(None)
    assert "/krt/nagatino" not in page
    assert "/krt/site/" not in page


def _seed_outline(root: Path, site, answers: dict) -> None:
    """Ответы ЕГРН по контурам — у каждой площадки свои, в её файле."""
    place = nagatino_parcels.cache_path(site)
    place.parent.mkdir(parents=True, exist_ok=True)
    place.write_text(
        json.dumps({"schema_version": 1, "answers": answers, "problem": ""}),
        encoding="utf-8")


SQUARE = [[[4187000, 7495000], [4187400, 7495000], [4187400, 7495400],
           [4187000, 7495400]]]


def test_in_a_real_browser_the_map_is_drawn_when_only_the_land_has_an_outline(
        tmp_path, monkeypatch):
    """Карта рисуется по участкам, даже когда объектов нет вовсе.

    Гейт карты читал СТРОЕНИЯ выгрузки, а у площадки с торгов выгрузки не
    бывает и в запасном перечне решения объектов нет: карта отвечала «ни одного
    контура пока нет», ИМЕЯ 55 контуров участков из 60 (замер прода 14.09.2026,
    Варшавское ш., вл. 37 — «картинка карты не грузится вообще и пишет что нет
    ЕГРН»). Причина была неверна дважды: ЕГРН как раз спросили, и он ответил.

    Меряется браузером: в исходнике сломанный и починенный гейт выглядят
    одинаково, а «нарисовано ли» — это узлы на экране.
    """
    from browser import chromium_or_skip, serve

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NAGATINO_EGRN_READ", "0")
    root = tmp_path / "market"
    root.mkdir(parents=True, exist_ok=True)
    # Выписка на участок есть, на строения — нет: ровно состояние площадки с
    # торгов, где приложение 2 называет участки, а привязки объектов в нём нет.
    _store(root, LAND)
    krt_territory.remember_notice(
        LOT["store_key"],
        {"lands": [{"cadastral_number": LAND["cadastral_number"], "part": False,
                    "area_raw": "5 000", "area_sqm": 5_000.0, "objects": []}],
         "objects": [], "rows": 1, "problem": ""},
        document="Лотовая документация.pdf", root=root)
    _seed_outline(root, krt_territory.site_for(
        SITE["slug"], SITE["name"], key=LOT["store_key"], root=root),
        {LAND["cadastral_number"]: {"asked_at": time.time(), "rings": SQUARE,
                                    "reason": ""}})

    with serve(_app(tmp_path), 18798) as base:
        with sync_playwright() as play:
            browser = play.chromium.launch(executable_path=str(chrome))
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(f"{base}/krt/site/{SITE['slug']}", wait_until="networkidle")
            seen = page.evaluate("""() => ({
              lands: document.querySelectorAll('#mapFrame path.land').length,
              objects: document.querySelectorAll('#mapFrame path.parcel').length,
              box: (document.getElementById('mapBox').textContent || '').trim(),
              kinds: (document.getElementById('kinds').textContent || '').trim(),
              tiles: [...document.querySelectorAll('#stats .stat')]
                       .map(n => n.textContent.trim()),
              coverage: (document.getElementById('coverage').textContent || '').trim(),
            })""")
            browser.close()

    assert not errors, errors
    assert seen["objects"] == 0, "объектов у этой площадки нет — рисовать нечего"
    assert seen["lands"] == 1, f"участок с контуром не нарисован: {seen['box']!r}"
    assert "контура пока нет" not in seen["box"], seen["box"]
    # Плитка называет, ЧЕГО контуры: «0 из 0» читалось как «пула не знаем».
    assert any("контуров участков получено из ЕГРН" in tile
               and tile.startswith("1 из 1") for tile in seen["tiles"]), seen["tiles"]
    # Блок «что стоит в присланном файле» отвечает на вопрос о файле, которого
    # у этой площадки нет вовсе.
    assert "ещё не спрашивали" not in seen["kinds"], seen["kinds"]
    # И строка охвата не утверждает о строениях выгрузки.
    assert "строений выгрузки" not in seen["coverage"], seen["coverage"]
    assert "Земельные участки нарисованы все 1" in seen["coverage"], seen["coverage"]


def test_the_composition_is_found_in_the_attachment_the_platform_actually_sends(
        tmp_path, monkeypatch):
    """Состав ищет разбор, а не имя вида — его площадка не ставит.

    Гейт стоял на видах «извещение» и «приложение», а тип Росэлторг выводит из
    ИМЕНИ файла по словам «извещ»/«прилож»: у него документ зовётся «Территория.
    Лотовая документация.pdf». Живой счёт по лоту 21000005000000033023
    (14.09.2026): 14 «прочее», 13 «договор», 3 «ЕГРН», ни одного «извещения» —
    гейт не срабатывал ни разу, и состав приезжал запасным перечнем проекта
    решения при прочитанном извещении под рукой.
    """
    from auction_search import krt_pipeline
    from auction_search.models import (
        AuctionDocument, AuctionLot, AuctionSource, LotKind, SourceKind,
    )

    lot = AuctionLot(
        source=AuctionSource(platform=SourceKind.ROSELTORG,
                             lot_url="https://www.roseltorg.ru/procedure/33023/1",
                             external_lot_id="21000005000000033023/1",
                             fetched_at="2026-09-14T06:00:00Z"),
        lot_kind=LotKind.KRT,
        title="КРТ: право на заключение договора",
        # Имя и вид — те, что площадка прислала на самом деле.
        documents=[AuctionDocument(title="Территория.Лотовая документация.pdf",
                                   url=NOTICE_URL, document_type="other")],
    )

    def platform(url, **_kwargs):
        assert url == NOTICE_URL, url
        return NOTICE_PDF.read_bytes(), "application/pdf", False

    monkeypatch.setattr(krt_pipeline, "download_document", platform)
    read = krt_pipeline.enrich_krt_from_official_documents(lot, store_dir=tmp_path)
    stored = krt_territory.stored_notice(krt_pipeline.store_key(read),
                                         root=tmp_path)
    assert stored["lands"], (
        "состав территории не прочитан из вложения, которое площадка присылает")
    assert stored["document"] == "Территория.Лотовая документация.pdf", stored


BUILD2 = {**BUILD, "cadastral_number": "77:04:0004010:78"}
SQUARE2 = [[[4187500, 7495000], [4187700, 7495000], [4187700, 7495200],
            [4187500, 7495200]]]


def _notice_with_two_objects(root: Path) -> None:
    krt_territory.remember_notice(
        LOT["store_key"],
        {"lands": [{"cadastral_number": LAND["cadastral_number"], "part": False,
                    "area_raw": "5 000", "area_sqm": 5_000.0,
                    "objects": [{"cadastral_number": BUILD["cadastral_number"],
                                 "area_sqm": 900.0, "fate": "снос"},
                                {"cadastral_number": BUILD2["cadastral_number"],
                                 "area_sqm": 400.0, "fate": "снос"}]}],
         "objects": [{"cadastral_number": BUILD["cadastral_number"],
                      "area_sqm": 900.0, "fate": "снос",
                      "lands": [LAND["cadastral_number"]]},
                     {"cadastral_number": BUILD2["cadastral_number"],
                      "area_sqm": 400.0, "fate": "снос",
                      "lands": [LAND["cadastral_number"]]}],
         "rows": 3, "problem": ""},
        document="Лотовая документация.pdf", root=root)


def test_the_outline_counters_count_what_the_reader_reads(tmp_path, monkeypatch):
    """Счётчик контуров считает СВОЮ величину, а не строки присланного файла.

    Читатель идёт по объединению номеров (`numbers`): строки выгрузки ПЛЮС
    состав извещения. Счётчики свода при этом были только по выгрузке, которой
    у площадки с торгов не бывает вовсе, — и на экране стояло «контуров
    получено 0 из 0, осталось спросить 0» ровно в те секунды, когда ЕГРН
    спрашивали о тридцати девяти номерах (замер прода 14.09.2026, Варшавское
    ш., вл. 37), а о трёх строениях без контура не говорил никто.

    Число спрашиваемых берётся из ТОГО ЖЕ списка, по которому ходит читатель:
    второй список «что спрашиваем» разошёлся бы с первым молча.
    """
    monkeypatch.setenv("NAGATINO_EGRN_READ", "0")
    root = tmp_path / "market"
    root.mkdir(parents=True, exist_ok=True)
    _store(root, LAND)
    _notice_with_two_objects(root)
    site = krt_territory.site_for(SITE["slug"], SITE["name"],
                                  key=LOT["store_key"], root=root)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed_outline(root, site, {
        LAND["cadastral_number"]: {"asked_at": time.time(), "rings": SQUARE,
                                   "reason": ""},
        BUILD["cadastral_number"]: {"asked_at": time.time(), "rings": SQUARE2,
                                    "reason": ""},
        # Спросили, а контура ЕГРН не дал — это ОТВЕТ, а не наш пробел.
        BUILD2["cadastral_number"]: {"asked_at": time.time(), "rings": [],
                                     "reason": "контура у объекта нет"},
    })

    view = nagatino_parcels.payload(site)
    o = view["outlines"]
    # Спрашивается объединение, и счётчик берёт его у самого читателя.
    assert o["asked"] == len(nagatino_parcels.numbers(site)) == 3, o
    assert o["asked_drawn"] == 2, o
    assert o["asked_unread"] == 0, o
    # Строения СОСТАВА считаются своей парой: у выгрузки их нет вовсе.
    assert (o["objects"], o["objects_drawn"]) == (2, 1), o
    assert (o["objects_empty"], o["objects_unread"]) == (1, 0), o
    assert (o["parcels"], o["drawn"]) == (0, 0), "строк выгрузки здесь нет"
    assert (o["lands"], o["lands_drawn"]) == (1, 1), o
    assert (o["lands_empty"], o["lands_unread"]) == (0, 0), o
    # Три состояния контура — одно правило на выгрузку и на состав.
    states = {item["cadastral_number"]: item["outline_state"]
              for item in view["territory"]["objects"]}
    assert states == {BUILD["cadastral_number"]: "drawn",
                      BUILD2["cadastral_number"]: "empty"}, states
    assert view["territory"]["lands"][0]["outline_state"] == "drawn"


def test_in_a_real_browser_the_progress_counts_the_numbers_it_asks(
        tmp_path, monkeypatch):
    """Прогресс и охват называют состав, а не пустую выгрузку.

    «Читаю ЕГРН: контуров получено 0 из 0, осталось спросить 0» — так строка
    выглядела у площадки с торгов при живом чтении, потому что считала строки
    присланного файла. И охват после первой правки замолчал о строениях
    состава вовсе: 36 из 39 с контуром, а о трёх не говорил никто — молчание
    читается как «всё нарисовано».

    Меряется браузером: в исходнике сломанный и починенный счётчик выглядят
    одинаково, а строка на экране — это то, что видно.
    """
    from browser import chromium_or_skip, serve

    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NAGATINO_EGRN_READ", "0")
    root = tmp_path / "market"
    root.mkdir(parents=True, exist_ok=True)
    _store(root, LAND)
    _notice_with_two_objects(root)
    site = krt_territory.site_for(SITE["slug"], SITE["name"],
                                  key=LOT["store_key"], root=root)
    _seed_outline(root, site, {
        LAND["cadastral_number"]: {"asked_at": time.time(), "rings": SQUARE,
                                   "reason": ""},
        BUILD["cadastral_number"]: {"asked_at": time.time(), "rings": SQUARE2,
                                    "reason": ""},
        BUILD2["cadastral_number"]: {"asked_at": time.time(), "rings": [],
                                     "reason": "контура у объекта нет"},
    })
    # Читатель «в работе»: ровно то состояние, в котором строка и врала.
    monkeypatch.setattr(nagatino_parcels, "_READING", {site.key})

    with serve(_app(tmp_path), 18799) as base:
        with sync_playwright() as play:
            browser = play.chromium.launch(executable_path=str(chrome))
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(f"{base}/krt/site/{SITE['slug']}", wait_until="domcontentloaded")
            page.wait_for_function(
                "() => (document.getElementById('progress').textContent||'').trim()")
            seen = page.evaluate("""() => ({
              progress: (document.getElementById('progress').textContent || '').trim(),
              coverage: (document.getElementById('coverage').textContent || '').trim(),
            })""")
            browser.close()

    assert not errors, errors
    assert "0 из 0" not in seen["progress"], seen["progress"]
    assert "получено 2 из 3" in seen["progress"], seen["progress"]
    # Охват называет строения состава и разводит два состояния: «спросили, а
    # контура нет» — ответ ЕГРН, «не спрашивали» — наш пробел.
    assert "Строений состава нарисовано 1 из 2" in seen["coverage"], seen["coverage"]
    assert "контура у них нет" in seen["coverage"], seen["coverage"]
    assert "строений выгрузки" not in seen["coverage"], seen["coverage"]

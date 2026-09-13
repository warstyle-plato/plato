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
    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(
            catalogue=lambda **_: [dict(SITE)],
            status=lambda: {"complete": True, "refreshing": False},
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
    assert row["slug"] == SITE["slug"] and row["name"] == SITE["name"]
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

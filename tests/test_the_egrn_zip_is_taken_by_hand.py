"""Зип с выписками принимается рукой, разбирается тем же кодом и остаётся на ядре.

«Надо сделать там возможность загружать зип с ЕГРН и распознавать его»
(владелец, 13.09.2026). Загрузчик получает от Росэлторга 503 через раз, и
присланный человеком архив бывает ЕДИНСТВЕННЫМ источником сведений об объектах
площадки.

Проверяется то, на что жалуются: маршрут зовётся, а не пересказывается, и блок
рисуется НАСТОЯЩЕЙ функцией страницы через node — в исходнике сломанная и
починенная страница выглядят одинаково.

Запуск: python3 -m pytest tests/test_the_egrn_zip_is_taken_by_hand.py -q
"""

from __future__ import annotations

import io
import json
import pathlib
import subprocess
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auction_search import api as auction_api
from auction_search import egrn_print_form

import page_blocks

FIXTURE = (pathlib.Path(__file__).parent / "fixtures"
           / "egrn_print_form_77_05_0012007_2054.txt")
LIVE = FIXTURE.read_text(encoding="utf-8")
KEY = "test-cabinet-key"
HEAD = {"X-Market-Key": KEY}


def _xml(number: str) -> bytes:
    return (f"<extract_about_property_build><build_record><object><common_data>"
            f"<cad_number>{number}</cad_number></common_data></object>"
            f"</build_record></extract_about_property_build>").encode("utf-8")


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


@pytest.fixture()
def client(monkeypatch, tmp_path):
    # `DATA_DIR` спрашивается при обращении, а не на импорте: замороженный путь
    # означает, что проверка пишет в рабочее дерево репозитория и находит там
    # снимок соседа — это уже стоило нам проверки, врущей в обе стороны.
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKET_CABINET_KEY", KEY)
    monkeypatch.setenv("AUCTION_KRT_WEEKLY", "0")
    monkeypatch.setenv("AUCTION_KRT_WATCH", "0")
    app = FastAPI()
    auction_api.install(app)
    return TestClient(app)


def test_the_archive_needs_the_cabinet_key_and_the_site_it_belongs_to(client):
    """Отказ называет свою причину: их две, и лечатся они разным.

    Без ключа площадки архивы разных лотов легли бы в одну кучу, и на экране
    это выглядело бы как сведения об этой площадке.
    """
    closed = client.post("/auctions/egrn/archive?key=lot-1", content=b"PK")
    assert closed.status_code == 401

    nameless = client.post("/auctions/egrn/archive", content=b"PK", headers=HEAD)
    assert nameless.status_code == 422
    assert "площадке" in nameless.json()["detail"]

    empty = client.post("/auctions/egrn/archive?key=lot-1", content=b"", headers=HEAD)
    assert empty.status_code == 422


def test_a_handed_archive_is_read_and_stays_on_the_core(client):
    """Загруженное разбирается тем же кодом и переживает закрытие вкладки."""
    archive = _zip({"ЕГРН 1021.xml": _xml("77:05:0012007:1021"),
                    "ЕГРН 1022.xml": _xml("77:05:0012007:1022"),
                    "ЕГРН 1021.sig": b"signature"})
    sent = client.post("/auctions/egrn/archive?key=21000005000000033444"
                       "&file=%D0%B7%D0%B4%D0%B0%D0%BD%D0%B8%D1%8F.zip",
                       content=archive, headers=HEAD)
    assert sent.status_code == 200
    body = sent.json()
    # Имя едет процентным кодированием, потому что заголовок обязан быть ASCII;
    # раскодировать его обязан сервер, иначе на экране двести знаков мусора.
    assert body["file"] == "здания.zip"
    assert body["upload"]["read"] == 2
    assert body["upload"]["added"] == 2
    assert [item["kind"] for item in body["upload"]["companions"]] == ["signature"]
    assert body["egrn"]["records"] == 2

    # Что принёс ИМЕННО этот архив и что лежит на складе ВСЕГО — разные числа.
    second = client.post("/auctions/egrn/archive?key=21000005000000033444&file=u.zip",
                         content=_zip({"ЕГРН 1035.xml": _xml("77:05:0012007:1035")}),
                         headers=HEAD)
    assert second.json()["upload"]["read"] == 1
    assert second.json()["egrn"]["records"] == 3

    stored = client.get("/auctions/egrn/archive?key=21000005000000033444", headers=HEAD)
    assert stored.status_code == 200
    assert {record["cadastral_number"] for record in stored.json()["records"]} == {
        "77:05:0012007:1021", "77:05:0012007:1022", "77:05:0012007:1035"}
    assert [upload["file"] for upload in stored.json()["uploads"]] == ["u.zip", "здания.zip"]

    # Пустой склад — это «не спрашивали», а не «выписок нет»: свода нет вовсе.
    other = client.get("/auctions/egrn/archive?key=lot-без-архива", headers=HEAD)
    assert other.status_code == 200
    assert other.json()["egrn"] is None
    assert other.json()["records"] == []


def test_a_scan_beyond_the_budget_is_named_not_dropped(monkeypatch):
    """Скан без текстового слоя — не пустой документ, а предел назван числом.

    Распознавание стоит до минуты на страницу, и архив приходит с чужой
    машины: четыреста сканов держали бы человека часами. Обрезка без слов
    неотличима от архива без выписок.
    """
    from auction_search import egrn_archive

    pymupdf = pytest.importorskip("pymupdf")
    calls: list[int] = []

    def fake(data, pages=3, dpi=200):
        calls.append(pages)
        number = f"77:05:0012007:{1000 + len(calls)}"
        return LIVE.replace("77:05:0012007:2054", number)

    # Заглушка не мёртвая: число её вызовов и есть проверяемый предел.
    monkeypatch.setattr(egrn_print_form.pdf_ocr, "text", fake)

    blank = pymupdf.open()
    for _ in range(2):
        blank.new_page()
    scan = blank.tobytes()
    archive = _zip({f"скан {index}.pdf": scan for index in range(1, 6)})
    got = egrn_archive.read(archive, name="сканы.zip")

    assert len(calls) == egrn_archive.OCR_BUDGET_DOCUMENTS
    assert calls == [egrn_print_form.OCR_PAGES] * egrn_archive.OCR_BUDGET_DOCUMENTS
    assert got["read"] == egrn_archive.OCR_BUDGET_DOCUMENTS
    assert all(record["text_source"] == "ocr" for record in got["records"])
    assert len(got["unread"]) == 5 - egrn_archive.OCR_BUDGET_DOCUMENTS
    assert "не по бюджету" in got["unread"][0]["reason"]


def test_the_missing_recogniser_is_a_refusal_with_a_reason(monkeypatch):
    """Распознавания нет — это отказ, а не запись без полей."""
    import pdf_ocr as service

    pymupdf = pytest.importorskip("pymupdf")
    blank = pymupdf.open()
    blank.new_page()

    monkeypatch.setattr(egrn_print_form.pdf_ocr, "text",
                        lambda *a, **k: (_ for _ in ()).throw(
                            service.Unavailable("в образе нет tesseract")))
    with pytest.raises(egrn_print_form.NoTextLayer) as refused:
        egrn_print_form.read(blank.tobytes())
    assert "tesseract" in str(refused.value)


def test_the_block_draws_both_sources_by_the_real_page_function(tmp_path):
    """Рисует блок одна функция, и оба источника названы своими именами.

    Смешать вложения лота и присланный рукой архив в одно число значит выдумать
    третье — то же правило, по которому свод бота и ядра стоят отдельными
    блоками. Проверяется НАСТОЯЩЕЙ функцией страницы: в исходнике сломанная и
    починенная выглядят одинаково.
    """
    stand = page_blocks.auctions_function("egrnBlock", "egrnOwnerLine", "egrnKey")
    script = (
        "const esc=s=>String(s??'');\n"
        + stand
        + """
const lot={records:2,lands:1,builds:1,owners:[{name:'ООО "УНИКС"',inn:'9724179743',objects:2,area_sqm:940}],
 refused:[],holders_withheld:0,without_registered_owner:0,unread:0,companions:0,reason:''};
const hand={records:14,lands:0,builds:14,owners:[],refused:[],holders_withheld:1,
 without_registered_owner:13,from_print_form:14,recognised:0,unread:0,companions:0,
 reason:'у 1 объект(ов) право зарегистрировано, а имени правообладателя выписка не раскрывает'};
console.log(JSON.stringify({
 lot:egrnBlock(lot,'Объекты по вложениям лота',''),
 hand:egrnBlock(hand,'Объекты по присланному архиву',''),
 empty:egrnBlock(null,'Объекты по присланному архиву','Выписок ещё не читали.'),
 key:egrnKey({source:{external_lot_id:'21000005000000033444'}}),
 nokey:egrnKey({source:{}}),
}));
"""
    )
    place = tmp_path / "stand.js"
    place.write_text(script, encoding="utf-8")
    done = subprocess.run(["node", str(place)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout)

    assert "Объекты по вложениям лота" in got["lot"]
    assert "УНИКС" in got["lot"] and "9724179743" in got["lot"]
    assert "Объекты по присланному архиву" in got["hand"]
    # Три ответа о собственнике различимы на экране, а не свёрнуты в «нет».
    assert "не раскрывает" in got["hand"]
    assert "Право зарегистрировано, а имени форма не раскрывает: 1" in got["hand"]
    assert "Право собственности не зарегистрировано: 13" in got["hand"]
    assert "из печатной формы 14" in got["hand"]
    # Пустой склад говорит «не читали», а не «выписок нет».
    assert "Выписок ещё не читали." in got["empty"]
    assert got["key"] == "21000005000000033444" and got["nokey"] == ""


def test_the_upload_button_gets_its_handler_and_the_card_has_the_room(tmp_path):
    """Блок рисуется и кнопка получает обработчик — не только объявлены.

    «Функция, написанная объяснять молчание, молчала сама»: `renderEgrn` могли
    объявить и не позвать, а кнопке — не поставить обработчик, и на экране это
    выглядит как пустое место и мёртвая кнопка. Проверяется вызовом настоящей
    функции страницы на простейшем DOM, а не поиском строки в исходнике.
    """
    from auction_search import ui

    page = ui.auctions_page()
    # Комната для блока объявлена в самой карточке лота, а не дорисовывается
    # после разбора: склад читается при выборе лота.
    assert 'id="egrnBox"' in page

    stand = page_blocks.auctions_function(
        "egrnBlock", "egrnOwnerLine", "egrnKey", "renderEgrn", "uploadEgrn")
    script = (
        "const esc=s=>String(s??'');\n"
        "const nodes={};\n"
        "function $(id){return nodes[id]||(nodes[id]={innerHTML:'',onclick:null,className:'',textContent:''})}\n"
        "const state={selected:{source:{external_lot_id:'21000005000000033444'}},"
        "ingested:{screening:{egrn:{records:2,owners:[],refused:[],unread:0,companions:0,reason:''}}},"
        "egrnStore:{view:null,note:'Выписок ещё не читали.'}};\n"
        "function krtWhenExact(){return '13 сентября, 12:00'}\n"
        + stand
        + """
$('egrnBox');
renderEgrn();
console.log(JSON.stringify({
 html:nodes.egrnBox.innerHTML,
 wired:typeof (nodes.egrnUpload||{}).onclick,
 status:(nodes.egrnStatus||{}).innerHTML||'',
}));
"""
    )
    place = tmp_path / "stand.js"
    place.write_text(script, encoding="utf-8")
    done = subprocess.run(["node", str(place)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout)

    assert "Объекты по вложениям лота" in got["html"]
    assert "Объекты по присланному архиву" in got["html"]
    assert 'id="egrnFile"' in got["html"] and 'id="egrnUpload"' in got["html"]
    # Кнопка без обработчика неотличима от сломанной: обработчик ставит тот, кто
    # рисует кнопку, — иначе он достаётся узлу, которого ещё нет.
    assert got["wired"] == "function"

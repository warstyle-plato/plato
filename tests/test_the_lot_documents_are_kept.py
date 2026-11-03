"""Склад скачанных вложений: качаем один раз, разбираем сколько нужно.

Байты вложений разбирались и выбрасывались, перечитать их было нечем — только
качать заново, а площадка отдаёт файл через раз (владелец, 13.09.2026: «может
ли твой алгоритм скачивать все документы из ссылки росэлторг и загружать их а
потом разбирать»).

Здесь лежат САМИ ФАЙЛЫ, и это исключение из правила «хранится разобранное»:
разборов у одного вложения несколько и они разные — программа, обязательства,
собственники, распознавание скана, — и следующий разбор появится позже файла.
Цена исключения — диск, поэтому она названа числами: предел лота, предел
склада, порог свободного места; выселенное называется, а не исчезает молча.

Что закреплено здесь:

- **второй разбор не идёт к площадке за прочитанным.** Иначе «разобрать лот»
  второй раз — это заново десятки мегабайт и заново её рулетка;
- **неотданное спрашивается снова.** Это и есть второй проход: прочитанное
  лежит на складе, заново едет только то, чего площадка не отдала;
- **отказ склада разбор не рвёт и не молчит.** Байты уже в руках, а место на
  диске — числом в своде;
- **выселение идёт по давности ЧТЕНИЯ.** Вложение, которое перечитывают
  каждый разбор, дороже скачанного однажды и забытого.

Запуск: python3 -m pytest tests/test_the_lot_documents_are_kept.py -q
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import krt_pipeline, lot_documents  # noqa: E402
from auction_search.documents import DocumentTemporaryRefusal  # noqa: E402
from auction_search.models import (  # noqa: E402
    AuctionDocument,
    AuctionLot,
    AuctionSource,
    LotKind,
    SourceKind,
)

EXTRACTS = ROOT / "reference_data" / "krt" / "egrn"
LAND = "77:05:0004001:15"
BUILD = "77:05:0004001:1098"
GIVEN = "https://www.roseltorg.ru/file/get/1/name/Выписки ЕГРН.zip"
REFUSED = "https://www.roseltorg.ru/file/get/2/name/Схема границ.pdf"


def extract(number: str) -> bytes:
    return (EXTRACTS / f"{number.replace(':', '_')}.xml").read_bytes()


def zipped(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in entries.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def lot() -> AuctionLot:
    return AuctionLot(
        source=AuctionSource(
            platform=SourceKind.ROSELTORG,
            lot_url="https://www.roseltorg.ru/procedure/33444",
            external_lot_id="21000005000000033444",
            fetched_at="2026-09-13T10:00:00Z",
        ),
        lot_kind=LotKind.KRT,
        title="КРТ: право на заключение договора",
        documents=[
            AuctionDocument(title="Выписки ЕГРН.zip", url=GIVEN,
                            document_type="egrn"),
            AuctionDocument(title="Схема границ.pdf", url=REFUSED,
                           document_type="annex"),
        ],
    )


class Platform:
    """Площадка: первое вложение отдаёт, второе — 503. Считает запросы."""

    def __init__(self, data: bytes):
        self.data = data
        self.asked: list[str] = []

    def __call__(self, url, **kwargs):
        self.asked.append(url)
        if url == REFUSED:
            raise DocumentTemporaryRefusal("площадка ответила HTTP 503; попыток: 3 из 3")
        return self.data, "application/zip", False


@pytest.fixture
def platform(monkeypatch):
    answer = Platform(zipped({"земля.xml": extract(LAND),
                              "здание.xml": extract(BUILD)}))
    monkeypatch.setattr(krt_pipeline, "download_document", answer)
    return answer


def test_the_second_parse_asks_only_for_what_was_not_given(tmp_path, platform):
    first = krt_pipeline.enrich_krt_from_official_documents(
        lot(), store_dir=tmp_path)
    assert platform.asked == [GIVEN, REFUSED]
    view = krt_pipeline.documents_summary(first)
    assert (view["read"], view["total"]) == (1, 2)
    assert view["from_store"] == 0
    assert [row["url"] for row in view["ask_again"]] == [REFUSED]

    second = krt_pipeline.enrich_krt_from_official_documents(
        lot(), store_dir=tmp_path)
    # Прочитанное взято со склада: к площадке поехало только неотданное.
    assert platform.asked == [GIVEN, REFUSED, REFUSED]
    again = krt_pipeline.documents_summary(second)
    assert (again["read"], again["from_store"]) == (1, 1)
    # И собственники на месте — склад отвечает теми же байтами.
    assert len(second.raw["egrn"]["records"]) == 2


def test_without_a_store_every_parse_goes_to_the_platform(platform):
    """Предохранитель: без склада вложение качается заново — иначе проверка
    выше зелена и на коде, который к площадке не ходит вовсе."""
    krt_pipeline.enrich_krt_from_official_documents(lot())
    krt_pipeline.enrich_krt_from_official_documents(lot())
    assert platform.asked == [GIVEN, REFUSED, GIVEN, REFUSED]


def test_the_store_keeps_the_bytes_and_the_content_type(tmp_path):
    lot_documents.save(tmp_path, "лот-1", GIVEN, data=b"%PDF-1.4 file",
                       content_type="application/pdf", title="Схема.pdf")
    got = lot_documents.load(tmp_path, "лот-1", GIVEN)
    assert got is not None
    data, content_type, entry = got
    assert (data, content_type) == (b"%PDF-1.4 file", "application/pdf")
    assert entry["title"] == "Схема.pdf"
    assert entry["bytes"] == len(b"%PDF-1.4 file")
    # Дата есть и у записи, и у чтения: «скачано» и «читали» — разные ответы.
    assert entry["saved_at"] and entry["read_at"]
    assert lot_documents.load(tmp_path, "лот-1", REFUSED) is None


def test_a_record_without_the_file_is_not_a_store(tmp_path):
    """Файл могли выселить или снести руками: «есть в манифесте» без байтов —
    обещание, и по нему разбор получил бы пустоту вместо документа."""
    lot_documents.save(tmp_path, "лот-1", GIVEN, data=b"%PDF", content_type="")
    kept = lot_documents.manifest(tmp_path, "лот-1")
    place = tmp_path / lot_documents.DIRNAME / lot_documents.slug("лот-1")
    (place / kept["files"][GIVEN]["file"]).unlink()
    assert lot_documents.load(tmp_path, "лот-1", GIVEN) is None


def test_a_full_disk_refuses_the_store_by_name(tmp_path, monkeypatch):
    monkeypatch.setattr(lot_documents, "free_mb", lambda _dir: 100.0)
    with pytest.raises(lot_documents.Refused) as refused:
        lot_documents.save(tmp_path, "лот-1", GIVEN, data=b"%PDF")
    said = str(refused.value)
    assert "100" in said and str(lot_documents.FLOOR_FREE_MB) in said


def test_a_full_disk_does_not_break_the_parse(tmp_path, monkeypatch, platform):
    """Склад — ускорение, а не источник истины: не принял — разбираем дальше."""
    monkeypatch.setattr(lot_documents, "free_mb", lambda _dir: 10.0)
    enriched = krt_pipeline.enrich_krt_from_official_documents(
        lot(), store_dir=tmp_path)
    assert len(enriched.raw["egrn"]["records"]) == 2
    view = krt_pipeline.documents_summary(enriched)
    assert view["read"] == 1
    # И свод склада называет, сколько места осталось, а не молчит.
    assert view["store"]["free_mb"] == 10.0
    assert view["store"]["floor_mb"] == lot_documents.FLOOR_FREE_MB
    # Не положенное на склад названо поимённо: иначе «второй разбор снова
    # качает» выглядит поломкой без причины.
    assert [row["document"] for row in view["store"]["not_kept"]] == [
        "Выписки ЕГРН.zip"]
    assert "склад не пишем" in view["store"]["not_kept"][0]["why"]


def test_the_lot_budget_evicts_the_least_recently_read_and_names_it(tmp_path, monkeypatch):
    monkeypatch.setattr(lot_documents, "LOT_BUDGET_BYTES", 300)
    lot_documents.save(tmp_path, "лот-1", "https://e/1", data=b"a" * 200,
                       title="старое")
    lot_documents.save(tmp_path, "лот-1", "https://e/2", data=b"b" * 200,
                       title="свежее")
    kept = lot_documents.manifest(tmp_path, "лот-1")
    assert list(kept["files"]) == ["https://e/2"]
    assert lot_documents.load(tmp_path, "лот-1", "https://e/1") is None
    # Выселенное названо: молча вычищенный файл читается как «его не качали».
    again = lot_documents.save(tmp_path, "лот-1", "https://e/3", data=b"c" * 200)
    assert [row["title"] for row in again["evicted"]] == ["свежее"]
    assert again["evicted"][0]["why"] == "предел лота"


def test_the_store_budget_evicts_a_whole_lot(tmp_path, monkeypatch):
    """Лот выселяется целиком: половина вложений на складе — это склад,
    который отвечает «скачано» на часть вопроса."""
    lot_documents.save(tmp_path, "лот-старый", "https://e/1", data=b"a" * 100)
    lot_documents.save(tmp_path, "лот-новый", "https://e/2", data=b"b" * 100)
    # Читаем старый лот позже — и выселен должен быть уже не он.
    lot_documents.load(tmp_path, "лот-старый", "https://e/1")
    swept = lot_documents.sweep(tmp_path, budget=150)
    assert [row["lot"] for row in swept["evicted"]] == [lot_documents.slug("лот-новый")]
    assert swept["evicted"][0]["why"] == "предел склада"
    assert lot_documents.state(tmp_path)["lots"] == 1


def test_the_store_key_is_the_procedure_number(tmp_path, platform):
    """Ключ лота — номер процедуры: адрес у Росэлторга меняется со строкой
    запроса, а номер — то, чем лот зовут и люди, и сама площадка."""
    assert krt_pipeline.store_key(lot()) == "21000005000000033444"
    krt_pipeline.enrich_krt_from_official_documents(lot(), store_dir=tmp_path)
    places = sorted(place.name for place in (tmp_path / lot_documents.DIRNAME).iterdir())
    assert places == [lot_documents.slug("21000005000000033444")]


def test_the_store_names_what_it_holds(tmp_path, platform):
    krt_pipeline.enrich_krt_from_official_documents(lot(), store_dir=tmp_path)
    state = lot_documents.state(tmp_path)
    assert (state["lots"], state["files"]) == (1, 1)
    assert state["bytes"] > 0
    assert state["budget_bytes"] == lot_documents.STORE_BUDGET_BYTES
    assert state["free_mb"] is not None


def test_the_store_budget_is_enforced_by_the_parse_itself(tmp_path, platform, monkeypatch):
    """Предел, объявленный и никем не проверяемый, — не предел.

    `sweep` написан сводить склад к пределу, и позвать его обязан тот, кто на
    склад пишет: иначе число в объявлении есть, а диск кончается молча.
    """
    ours = len(zipped({"земля.xml": extract(LAND), "здание.xml": extract(BUILD)}))
    # Предел ровно под наш лот: чужому места нет, нашему — есть.
    monkeypatch.setattr(lot_documents, "STORE_BUDGET_BYTES", ours)
    lot_documents.save(tmp_path, "лот-чужой", "https://e/1", data=b"a" * 100)
    enriched = krt_pipeline.enrich_krt_from_official_documents(
        lot(), store_dir=tmp_path)
    view = krt_pipeline.documents_summary(enriched)
    assert [row["lot"] for row in view["store"]["evicted"]] == [
        lot_documents.slug("лот-чужой")]
    # Свой лот при этом на складе остался: его читали только что.
    assert lot_documents.load(tmp_path, krt_pipeline.store_key(lot()), GIVEN)

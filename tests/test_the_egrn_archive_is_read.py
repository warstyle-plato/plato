"""Архив выписок ЕГРН → собственники лота. Проверка идёт на живых выписках.

«Собственники участков и зданий это важно и оно есть в документации на
росэлторг», следом «выписки из ЕГРН так и называются и лежат в зипах»
(владелец, 12.09.2026). Между нами и этими собственниками стояло две двери, и
обе закрыты здесь: `.zip` разбор не открывал вовсе, а вложение с типом `egrn`
пайплайн пропускал одной строкой вместе с ГПЗУ.

Разбор одной выписки не повторяется — он уже написан по 59 живым файлам
квартала 77:05:0004001, и архив собирается из них же: выдуманная выписка
подтвердила бы только сама себя.

Что закреплено здесь:

- **спутник выписки — не наша неудача.** Подпись и таблица стилей лежат в
  архиве по построению; свалить их в один список с непрочитанным значило бы
  обвинить архив там, где всё на месте;
- **непрочитанное называется.** Молча выброшенная выписка читается как
  отсутствие собственника — а это худший вид молчания;
- **один номер дважды — выбор, и делаем его не мы.** Порядок записей в архиве
  не вправе решать, чей ответ верен.

Запуск: python3 -m pytest tests/test_the_egrn_archive_is_read.py -q
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import egrn_archive, egrn_extracts, krt_pipeline  # noqa: E402
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


def extract(number: str) -> bytes:
    return (EXTRACTS / f"{number.replace(':', '_')}.xml").read_bytes()


def zipped(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in entries.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def lot(*documents: AuctionDocument) -> AuctionLot:
    return AuctionLot(
        source=AuctionSource(
            platform=SourceKind.ROSELTORG,
            lot_url="https://www.roseltorg.ru/procedure/1",
            external_lot_id="RT-TEST",
            fetched_at="2026-09-12T10:00:00Z",
        ),
        lot_kind=LotKind.KRT,
        title="КРТ: право на заключение договора",
        documents=list(documents),
    )


def test_an_archive_of_extracts_gives_the_records_of_every_extract():
    data = zipped({
        "Выписки ЕГРН/земля.xml": extract(LAND),
        "Выписки ЕГРН/здание.xml": extract(BUILD),
    })
    found = egrn_archive.read(data, name="Выписки ЕГРН.zip")
    assert found["read"] == 2
    kinds = sorted(record["kind"] for record in found["records"])
    assert kinds == ["build", "land"]
    numbers = sorted(record["cadastral_number"] for record in found["records"])
    assert numbers == sorted([LAND, BUILD])
    # Из какой записи архива взята выписка — часть ответа.
    assert all(record["source_entry"] for record in found["records"])


def test_the_owner_comes_out_of_the_archive_the_same_way_as_out_of_a_file():
    """Разбор выписки один: архив не заводит второго ответа о собственнике."""
    data = zipped({"здание.xml": extract(BUILD)})
    from_archive = egrn_archive.read(data)["records"][0]
    from_file = egrn_extracts.read(extract(BUILD))
    assert egrn_extracts.owner_of(from_archive) == egrn_extracts.owner_of(from_file)


def test_a_signature_and_a_stylesheet_are_named_companions_not_failures():
    data = zipped({
        "земля.xml": extract(LAND),
        "земля.xml.sig": b"\x30\x82\x00\x01",
        "стиль.xsl": b"<?xml version='1.0'?><xsl:stylesheet/>",
    })
    found = egrn_archive.read(data)
    assert found["read"] == 1
    assert not found["unread"]
    names = sorted(item["name"] for item in found["companions"])
    assert names == ["земля.xml.sig", "стиль.xsl"]


def test_a_broken_extract_is_named_and_the_rest_is_still_read():
    data = zipped({
        "земля.xml": extract(LAND),
        "битая.xml": b"<extract_about_property_land><details",
    })
    found = egrn_archive.read(data)
    assert found["read"] == 1
    assert [item["name"] for item in found["unread"]] == ["битая.xml"]


def test_one_number_twice_is_named_and_both_records_stay():
    data = zipped({"первая.xml": extract(LAND), "вторая.xml": extract(LAND)})
    found = egrn_archive.read(data)
    assert found["read"] == 2
    assert found["duplicates"] == [LAND]


def test_a_single_extract_without_an_archive_is_read_too():
    found = egrn_archive.read(extract(LAND), name="Выписка.xml")
    assert found["read"] == 1
    assert found["archives"] == 0


def test_the_lot_gets_the_owners_of_the_extracts_instead_of_skipping_them(monkeypatch):
    """Вложение с типом `egrn` больше не пропускается — оно и несёт владельцев."""
    data = zipped({"земля.xml": extract(LAND), "здание.xml": extract(BUILD)})
    monkeypatch.setattr(krt_pipeline, "download_document",
                        lambda url, **kwargs: (data, "application/zip", False))
    enriched = krt_pipeline.enrich_krt_from_official_documents(lot(
        AuctionDocument(title="Выписки ЕГРН.zip",
                        url="https://www.roseltorg.ru/file/get/1.zip",
                        document_type="egrn")))
    egrn = enriched.raw["egrn"]
    assert (egrn["lands"], egrn["builds"]) == (1, 1)
    owners = [egrn_extracts.owner_of(record) for record in egrn["records"]]
    assert any(owner and owner["name"] for owner in owners)
    assert enriched.documents[0].access_status == "public"


def test_an_unread_entry_of_the_egrn_archive_is_a_named_warning(monkeypatch):
    data = zipped({"битая.xml": b"<extract_about_property_land><details"})
    monkeypatch.setattr(krt_pipeline, "download_document",
                        lambda url, **kwargs: (data, "application/zip", False))
    enriched = krt_pipeline.enrich_krt_from_official_documents(lot(
        AuctionDocument(title="Выписки ЕГРН.zip",
                        url="https://www.roseltorg.ru/file/get/1.zip",
                        document_type="egrn")))
    warnings = enriched.raw["krt_document_warnings"]
    assert [item["kind"] for item in warnings] == ["egrn_unread"]
    assert "битая.xml" in warnings[0]["error"]
    assert enriched.raw["krt_extraction_complete"] is False


def test_the_extracts_are_not_searched_for_the_krt_programme(monkeypatch):
    """Выписка отвечает на свой вопрос: программы и обязательств в ней не ищут."""
    data = zipped({"земля.xml": extract(LAND)})
    monkeypatch.setattr(krt_pipeline, "download_document",
                        lambda url, **kwargs: (data, "application/zip", False))
    called: list[str] = []
    monkeypatch.setattr(krt_pipeline, "extract_document_paragraphs",
                        lambda document: called.append(document.title) or [])
    enriched = krt_pipeline.enrich_krt_from_official_documents(lot(
        AuctionDocument(title="Выписки ЕГРН.zip",
                        url="https://www.roseltorg.ru/file/get/1.zip",
                        document_type="egrn")))
    assert called == []
    assert not enriched.krt_program and not enriched.obligations
    # И при этом выписка прочитана: «не искали программу» не значит «пропустили».
    assert len(enriched.raw["egrn"]["records"]) == 1


def whole_quarter_archive() -> bytes:
    return zipped({f"Выписки ЕГРН/{path.name}": path.read_bytes()
                   for path in sorted(EXTRACTS.glob("*.xml"))})


def test_the_summary_names_the_owners_of_the_whole_quarter(monkeypatch):
    """Свод по 59 живым выпискам: девять владельцев и 17 объектов без права.

    Числа сняты с самих выписок, а не назначены: 20 участков и 39 строений,
    собственность не зарегистрирована у семнадцати — это ответ документа, и он
    стоит своим числом, а не подмешивается к владельцам.
    """
    data = whole_quarter_archive()
    monkeypatch.setattr(krt_pipeline, "download_document",
                        lambda url, **kwargs: (data, "application/zip", False))
    enriched = krt_pipeline.enrich_krt_from_official_documents(lot(
        AuctionDocument(title="Выписки ЕГРН.zip",
                        url="https://www.roseltorg.ru/file/get/1.zip",
                        document_type="egrn")))
    summary = krt_pipeline.egrn_summary(enriched)
    assert (summary["records"], summary["lands"], summary["builds"]) == (59, 20, 39)
    assert summary["without_registered_owner"] == 17
    assert (summary["unread"], summary["documents"]) == (0, 1)
    assert len(summary["owners"]) == 9
    # Порядок — по числу объектов: у города их четырнадцать.
    assert summary["owners"][0]["name"] == "Москва"
    assert summary["owners"][0]["objects"] == 14


def test_one_company_in_two_spellings_is_one_owner(monkeypatch):
    """Личность — это ИНН: «УНИКС» приходит и капсом, и обычным письмом."""
    raw_names = set()
    for path in sorted(EXTRACTS.glob("*.xml")):
        owner = egrn_extracts.owner_of(egrn_extracts.read(path.read_bytes()))
        if owner and "УНИКС" in owner["name"].upper():
            raw_names.add(owner["name"])
    # Предохранитель: без двух написаний сводить нечего и проверка пуста.
    assert len(raw_names) == 2

    data = whole_quarter_archive()
    monkeypatch.setattr(krt_pipeline, "download_document",
                        lambda url, **kwargs: (data, "application/zip", False))
    enriched = krt_pipeline.enrich_krt_from_official_documents(lot(
        AuctionDocument(title="Выписки ЕГРН.zip",
                        url="https://www.roseltorg.ru/file/get/1.zip",
                        document_type="egrn")))
    unics = [row for row in krt_pipeline.egrn_summary(enriched)["owners"]
             if "УНИКС" in row["name"].upper()]
    assert len(unics) == 1
    assert unics[0]["objects"] == 10
    assert unics[0]["inn"] == "9724179743"


def test_a_lot_without_extracts_has_no_summary_instead_of_an_empty_one():
    """Свод без выписок — это «не спрашивали», а не «владельцев нет»."""
    assert krt_pipeline.egrn_summary(lot()) is None

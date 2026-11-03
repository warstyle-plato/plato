"""Архив вложения: что прочитано, что нет и почему.

Выписки ЕГРН на Росэлторге лежат в зипах (владелец, 12.09.2026), а читателя у
`.zip` не было вовсе: разбор отвечал «unsupported document format» — то есть
наш пробел выглядел как чужой формат.

Здесь закреплено то, на чём такой читатель ломается.

**DOCX — тоже зип.** Открой его как архив вложений, и вместо текста письма
человек получит `word/document.xml`. Отличает их содержимое, а не расширение.

**Что не прочитано — называется.** Молча выброшенная запись читается как её
отсутствие, и у выписки это худший вид молчания: собственника нет.

**Предел объявлен числом.** Десять килобайт архива разворачиваются в гигабайты,
а диск у нас уже кончался молча — упёршийся в предел архив говорит, во что упёрся.

**Имя записи бывает не в UTF-8**: архиватор старой школы пишет его кодовой
страницей DOS, и `zipfile` отдаёт псевдографику вместо кириллицы.

Запуск: python3 -m pytest tests/test_the_archive_is_opened.py -q
"""

from __future__ import annotations

import io
import struct
import sys
import zipfile
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import archives, documents  # noqa: E402
from auction_search.models import AuctionDocument  # noqa: E402


def zipped(entries: dict[str, bytes], *, utf8: bool = True) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in entries.items():
            info = zipfile.ZipInfo(name if utf8 else "x")
            if utf8:
                archive.writestr(name, body)
            else:
                archive.writestr(info, body)
    return buffer.getvalue()


def legacy_zip(name_bytes: bytes, body: bytes) -> bytes:
    """Архив, у которого имя записи лежит байтами и флага UTF-8 нет.

    Собрать такой через `zipfile` нельзя: он сам ставит флаг 0x800, как только
    в имени встречается не ASCII. Архиватор старой школы флага не ставит, и
    ровно такие архивы приходят с площадки, поэтому запись собрана руками.
    """
    crc = zlib.crc32(body) & 0xFFFFFFFF
    length, size = len(name_bytes), len(body)
    local = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 0, 0, 0x21,
                        crc, size, size, length, 0) + name_bytes
    central = struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0, 0, 0, 0x21,
                          crc, size, size, length, 0, 0, 0, 0, 0, 0) + name_bytes
    head = local + body
    return head + central + struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 1, 1,
                                        len(central), len(head), 0)


def docx(text: str) -> bytes:
    body = (
        '<?xml version="1.0"?><w:document '
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    return zipped({
        "[Content_Types].xml": b"<Types/>",
        "word/document.xml": body.encode("utf-8"),
    })


def test_an_office_package_is_a_document_not_an_archive_of_attachments():
    """DOCX устроен архивом, но остаётся документом — его читает свой читатель."""
    data = docx("Проект договора о комплексном развитии территории")
    assert archives.looks_like_zip(data) is True
    assert archives.is_office_package(data) is True
    paragraphs = documents.extract_document_paragraphs(
        AuctionDocument(title="Договор.docx", url="https://www.roseltorg.ru/d.docx"),
        data=data, content_type="application/zip")
    assert paragraphs == ["Проект договора о комплексном развитии территории"]


def test_an_archive_gives_the_text_of_every_readable_entry_named_by_its_file():
    data = zipped({
        "лотовая документация/условия.txt": "Площадь территории 14,62 га.".encode("utf-8"),
        "лотовая документация/протокол.csv": "номер;значение\n1;2".encode("utf-8"),
    })
    paragraphs = documents.extract_document_paragraphs(
        AuctionDocument(title="Документация.zip", url="https://www.roseltorg.ru/d.zip"),
        data=data, content_type="application/zip")
    assert any("Площадь территории 14,62 га." in item for item in paragraphs)
    # В каком файле это сказано — часть ответа: архив несёт по десятку записей.
    assert all(item.startswith("[") for item in paragraphs)
    assert any("условия.txt" in item for item in paragraphs)


def test_an_unreadable_entry_is_named_and_not_dropped():
    data = zipped({
        "условия.txt": "Площадь территории 14,62 га.".encode("utf-8"),
        "подпись.sig": b"\x30\x82\x00\x01",
    })
    paragraphs = documents.extract_document_paragraphs(
        AuctionDocument(title="Документация.zip", url="https://www.roseltorg.ru/d.zip"),
        data=data, content_type="application/zip")
    note = [item for item in paragraphs if item.startswith("[архив]")]
    assert note and "подпись.sig" in note[0]


def test_an_archive_without_readable_text_refuses_and_says_what_was_inside():
    data = zipped({"подпись.sig": b"\x30\x82", "печать.bin": b"\x00\x01"})
    with pytest.raises(documents.DocumentExtractionError) as refusal:
        documents.extract_document_paragraphs(
            AuctionDocument(title="Подписи.zip", url="https://www.roseltorg.ru/d.zip"),
            data=data, content_type="application/zip")
    # Пустой список абзацев читался бы как пустой документ.
    assert "подпись.sig" in str(refusal.value)


def test_an_office_package_inside_an_archive_stays_a_document():
    """Вложенный DOCX не разбирается на части: он документ, а не второй архив."""
    data = zipped({"договор.docx": docx("Условия договора о КРТ"), "опись.txt": b"1"})
    opened = archives.open_zip(data)
    assert sorted(entry.name for entry in opened.entries) == ["договор.docx", "опись.txt"]
    paragraphs = documents.extract_document_paragraphs(
        AuctionDocument(title="Документация.zip", url="https://www.roseltorg.ru/d.zip"),
        data=data, content_type="application/zip")
    assert any("Условия договора о КРТ" in item for item in paragraphs)


def test_a_mislabelled_pdf_is_read_as_a_pdf_not_refused_as_an_archive():
    """Подпись площадки врёт: PDF приходит с типом `application/zip`."""
    assert archives.looks_like_zip(b"%PDF-1.4 ...") is False


def test_a_nested_archive_is_opened_and_its_entries_keep_the_outer_name():
    inner = zipped({"выписка.xml": b"<extract_about_property_land/>"})
    data = zipped({"участки.zip": inner, "опись.txt": b"1"})
    opened = archives.open_zip(data)
    assert opened.archives == 2
    names = sorted(entry.name for entry in opened.entries)
    assert names == ["опись.txt", "участки.zip/выписка.xml"]


def test_a_deeper_nesting_is_named_not_opened(monkeypatch):
    monkeypatch.setattr(archives, "MAX_DEPTH", 2)
    deepest = zipped({"выписка.xml": b"<extract_about_property_land/>"})
    middle = zipped({"второй.zip": deepest})
    data = zipped({"первый.zip": middle})
    opened = archives.open_zip(data)
    assert not opened.entries
    assert opened.refused and "глубже" in opened.refused[0]["reason"]


def test_a_swollen_archive_says_what_it_hit(monkeypatch):
    monkeypatch.setattr(archives, "MAX_TOTAL_BYTES", 64)
    data = zipped({"условия.txt": b"a" * 4096})
    opened = archives.open_zip(data)
    assert not opened.entries
    assert opened.refused and "объём" in opened.refused[0]["reason"]


def test_too_many_entries_stop_the_reading_with_a_named_reason(monkeypatch):
    monkeypatch.setattr(archives, "MAX_ENTRIES", 3)
    data = zipped({f"файл{index}.txt": b"1" for index in range(10)})
    opened = archives.open_zip(data)
    assert len(opened.entries) == 3
    assert opened.refused and "записей" in opened.refused[0]["reason"]


@pytest.mark.parametrize("encoding", ["cp866", "cp1251"])
def test_a_name_written_without_the_utf8_flag_is_read_back(encoding):
    """Имя без флага приходит кодовой страницей, а `zipfile` даёт псевдографику.

    Между cp866 и cp1251 выбирают по тому, чего в строке больше: у cp866 байты
    0xB0–0xDF — рамки, у cp1251 те же байты — кириллица.
    """
    data = legacy_zip("Выписка.xml".encode(encoding), b"<extract_about_property_land/>")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        # Проверка стоит на том, что ломается: `zipfile` сам имя не вернёт.
        assert archive.infolist()[0].filename != "Выписка.xml"
    opened = archives.open_zip(data)
    assert [entry.name for entry in opened.entries] == ["Выписка.xml"]


def test_a_broken_archive_refuses_with_its_own_error():
    with pytest.raises(archives.ArchiveProblem):
        archives.open_zip(b"PK\x03\x04not an archive at all")

"""Печатная форма выписки ЕГРН читается, и три ответа о собственнике разведены.

Проверки идут на ТЕКСТЕ живого документа — `tests/fixtures/egrn_print_form_*`,
снимок текстового слоя выписки из публичной документации лота
21000005000000033444 (Задонский пр-д, влд. 1А). Нарисовать PDF самим было бы
проверкой наших же подписей: у своей подделки подписи ровно те, под которые
написан разбор.

Запуск: python3 -m pytest tests/test_the_print_form_is_read.py -q
"""

from __future__ import annotations

import json
import pathlib

import pytest

from auction_search import archives, egrn_archive, egrn_extracts, egrn_print_form
from auction_search import egrn_store, krt_pipeline

from egrn_fixtures import LIVE, print_form_pdf, without_rights


def _without_rights() -> str:
    return without_rights()


def test_the_print_form_gives_the_same_record_as_the_machine_extract():
    """Поля читаются по подписям, а подпись переносится по словам.

    Падало на прежнем коде дважды: подписи искались строкой (а
    «Кадастровые номера иных объектов недвижимости, в пределах\\nкоторых
    расположен объект недвижимости:» — это две строки), и дробное число
    выбрасывалось вместе с нумерацией пунктов.
    """
    record = egrn_print_form.read_text(LIVE)
    assert record["cadastral_number"] == "77:05:0012007:2054"
    assert record["kind"] == "build"
    assert record["source"] == "print_form"
    assert record["text_source"] == "layer"
    assert record["quarter"] == "77:05:0012007"
    assert "проезд Задонский" in record["address"]
    assert record["area_sqm"] == pytest.approx(95.0)
    # Копейки кадастровой стоимости — то самое дробное число, которое прежний
    # образец нумерации съедал целиком.
    assert record["cadastral_value_rub"] == pytest.approx(12599979.2)
    assert record["name"] == "Автомоечный пост"
    assert record["purpose"] == "Нежилое"
    assert (record["floors"], record["underground_floors"]) == ("2", "1")
    assert record["year_built"] == "2016"
    assert record["lands"] == ["77:05:0012007:1009"]
    assert record["extract_number"] == "КУВИ-001/2026-115340102"
    assert record["formed_at"] == "26.08.2026"
    assert "актуальные" in record["status"]


def test_a_registered_right_without_a_name_is_not_an_unregistered_one():
    """Три ответа о собственнике, и слить их нельзя.

    У 77:05:0012007:2054 право собственности ЗАРЕГИСТРИРОВАНО — вид, номер и
    дата стоят, — а клетка «Правообладатель» пуста: так устроен вид выписки «об
    объекте недвижимости». Сказать по этому «право не зарегистрировано» значит
    соврать о реестре, а лечится оно своим запросом в ЕГРН, а не перечитыванием
    того же файла.
    """
    withheld = egrn_print_form.read_text(LIVE)
    assert withheld["rights_section"] == "present"
    assert [right["type"] for right in withheld["rights"]] == ["Собственность"]
    assert withheld["rights"][0]["number"] == "77-77/005-77/009/277/2016-603/2"
    assert withheld["rights"][0]["date"] == "23.12.2016"
    assert withheld["rights"][0]["holders"] == []
    assert egrn_extracts.owner_state(withheld) == "withheld"

    unregistered = egrn_print_form.read_text(_without_rights())
    assert unregistered["rights_section"] == "absent"
    assert egrn_extracts.owner_state(unregistered) == "unregistered"

    named = {"rights": [{"type": "Собственность",
                         "holders": [{"name": 'ООО "УНИКС"', "inn": "9724179743"}]}]}
    assert egrn_extracts.owner_state(named) == "named"


def test_a_foreign_document_is_refused_not_read_as_an_empty_record():
    with pytest.raises(ValueError):
        egrn_print_form.read_text("Договор аренды земельного участка")
    # Форма без вида объекта — отказ, а не запись без вида: угадывать вид по
    # набору заполненных полей нельзя, у здания и участка общие подписи.
    assert "Выписка из Единого государственного реестра недвижимости" in LIVE
    with pytest.raises(ValueError):
        egrn_print_form.read_text(LIVE.replace("Здание\nвид объекта", "Ничто\nвид объекта"))


def test_the_archive_reads_a_print_form_instead_of_only_naming_it():
    """Печатная форма в архиве — запись, а не спутник.

    На прежнем коде `.pdf` попадал в `companions` по расширению, и архив лота
    отвечал «записей ноль»: у Росэлторга выписки лотовой документации приходят
    печатными формами, то есть до лота не доезжало НИЧЕГО.
    """
    # Текст берётся у живого документа: свой был бы проверкой наших подписей.
    got = egrn_archive.read(print_form_pdf(), name="ЕГРН 2054.pdf")
    assert got["read"] == 1, got["unread"]
    assert got["records"][0]["cadastral_number"] == "77:05:0012007:2054"
    assert got["records"][0]["source"] == "print_form"
    assert got["companions"] == []


def test_a_print_form_does_not_displace_the_machine_extract_of_the_same_object():
    """Два документа на один объект — выбор не за порядком записей в архиве.

    КУВИ отвечает на то, чего печатная форма не раскрывает вовсе (имя
    правообладателя), поэтому она остаётся, а печатная форма названа спутником
    с причиной, а не выброшена молча.
    """
    pdf = print_form_pdf()
    xml = ("<extract_about_property_build><build_record><object><common_data>"
           "<cad_number>77:05:0012007:2054</cad_number></common_data></object>"
           "</build_record></extract_about_property_build>").encode("utf-8")

    import io
    import zipfile
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ЕГРН 2054.xml", xml)
        archive.writestr("ЕГРН 2054.pdf", pdf)
    got = egrn_archive.read(buffer.getvalue(), name="Выписки.zip")

    assert [record["source"] for record in got["records"]] == ["xml"]
    assert got["duplicates"] == []
    companions = [item for item in got["companions"] if item["kind"] == "print_form"]
    assert companions and "77:05:0012007:2054" in companions[0]["reason"]


def test_the_summary_names_the_withheld_holder_instead_of_calling_it_absent():
    """Свод различает «имени не раскрывает форма» и «права нет».

    Прежняя причина говорила «машинной выписки в лоте нет … а разбор написан по
    XML» — верно до 0.23.41 и неверно после. Оговорка «мы этого не читаем»
    устаревает молча и продолжает читаться как правда.
    """
    withheld = egrn_print_form.read_text(LIVE)
    unregistered = egrn_print_form.read_text(_without_rights())
    unregistered["cadastral_number"] = "77:05:0012007:1021"
    view = krt_pipeline.egrn_view({
        "records": [withheld, unregistered], "lands": 0, "builds": 2,
        "documents": [{"document": "Выписки.zip", "entries": 2, "read": 2,
                       "unread": [], "companions": []}],
    })
    assert view["holders_withheld"] == 1
    assert view["without_registered_owner"] == 1
    assert view["from_print_form"] == 2
    assert view["owners"] == []
    assert "не раскрывает" in view["reason"]
    assert "не зарегистрировано" in view["reason"]
    assert "разбор написан по XML" not in view["reason"]


def test_the_store_adds_a_second_archive_instead_of_replacing_the_first(tmp_path):
    """Второй зип дополняет первый: выписки приходят порознь.

    Запись файла целиком теряет то, что принесли прежним — это уже стоило нам
    рейтинга КРТ, затёртого снимком памяти воркера.
    """
    first = egrn_print_form.read_text(LIVE)
    second = dict(first, cadastral_number="77:05:0012007:1021")
    egrn_store.save(tmp_path, "lot-1", {"records": [first], "entries": 1, "read": 1},
                    "здания.zip")
    kept = egrn_store.save(tmp_path, "lot-1",
                           {"records": [second], "entries": 1, "read": 1}, "участки.zip")
    numbers = {record["cadastral_number"] for record in kept["records"]}
    assert numbers == {"77:05:0012007:2054", "77:05:0012007:1021"}
    assert [upload["file"] for upload in kept["uploads"]] == ["участки.zip", "здания.zip"]
    assert kept["uploads"][0]["added"] == 1

    # Печатная форма не вытесняет машинную выписку, и вытесненное названо числом.
    machine = dict(first, source="xml")
    egrn_store.save(tmp_path, "lot-2", {"records": [machine]}, "куви.zip")
    kept = egrn_store.save(tmp_path, "lot-2", {"records": [first]}, "печатная.zip")
    assert [record["source"] for record in kept["records"]] == ["xml"]
    assert kept["uploads"][0]["superseded"] == 1

    # Блок для свода собирается ЗДЕСЬ, а сводит его один `egrn_view`: два
    # сборщика на один вопрос однажды ответят про одну площадку разное.
    view = krt_pipeline.egrn_view(egrn_store.block(kept))
    assert view["records"] == 1 and view["documents"] == 2

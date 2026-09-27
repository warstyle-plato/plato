"""Цепочка поправок к 713/30 лежит в библиотеке — файлами, а не памятью.

Консолидированного текста РНГП МО у нас нет и взять его негде: mosreg.ru
отвечает 403, а сегмент Московской области официального опубликования
начинается 19.02.2019. Поэтому в библиотеке лежит РЯД его поправок, и у ряда
два свойства, которые нельзя проверить чтением: он объявлен преамбулой самого
акта (а не нашей памятью), и у каждой его строки либо есть файл с совпадающим
отпечатком, либо названа причина, почему файла нет.

Три состояния строки ряда — «разобран», «в библиотеке, содержание не
разобрано» и «не получен» — разные ответы, и слить их нельзя: первое значит,
что норма из акта доехала до справочника, второе — что доехал только файл,
третье — что у нас нет и файла.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import normatives_registry as registry

ROOT = Path(__file__).resolve().parents[1]
CHAIN_DIR = ROOT / "docs" / "normative" / "mo_rngp_chain"
# Преамбула 1080-ПП — первичный перечень поправок. Распознавание испортило в
# ней один год: «от 22.12.2010 № 996/41» — это 22.12.2020, и та же поправка с
# 2020 годом стоит в преамбуле 1480/45. Исключение названо здесь, а не снято
# молча: иначе проверка перестанет ловить настоящий пропуск.
OCR_YEAR_SLIPS = {"22.12.2010": "22.12.2020"}
BASE_ACT_DATE = "17.08.2015"


def _row() -> dict:
    data = json.loads((ROOT / "data" / "normatives" / "registry.json").read_text("utf-8"))
    rows = data["entries"] if isinstance(data, dict) and "entries" in data else data
    return next(row for row in rows if row.get("id") == "mo-713-30")


def test_the_chain_is_the_one_the_act_itself_declares() -> None:
    row = _row()
    steps = registry.chain_steps(row)
    assert steps, "ряд поправок к 713/30 в реестре пуст"

    numbers = [str(step.get("number") or "") for step in steps]
    assert all(numbers), "в ряду есть строка без номера акта"
    assert len(numbers) == len(set(numbers)), "номер акта встречается в ряду дважды"

    preamble = (CHAIN_DIR / "2026-09-01_1080-ПП.ocr.txt").read_text("utf-8")
    declared = {
        OCR_YEAR_SLIPS.get(date, date)
        for date in re.findall(r"от (\d{2}\.\d{2}\.\d{4})", preamble)
    } - {BASE_ACT_DATE}
    ours = {str(step.get("act_date") or "") for step in steps}
    assert declared <= ours, f"акт назвал поправки, которых нет в ряду: {sorted(declared - ours)}"


def test_every_step_either_carries_its_file_or_names_the_reason() -> None:
    """Строка ряда — либо у нас (файлом или распознанным текстом), либо с причиной.

    Сканы официальных публикаций в репозитории не хранятся (решение владельца
    27.09.2026). Вместо PDF у строки: распознанный текст на диске, ссылка на
    сам PDF официального опубликования и отпечаток оригинала — чтобы скачанный
    по ссылке файл можно было сверить с тем, с которого снят текст.
    """
    steps = registry.chain_steps(_row())
    in_library = 0
    for step in steps:
        if not registry.step_in_library(step):
            assert str(step.get("status") or "") == "не получен", step.get("number")
            assert str(step.get("reason") or "").strip(), (
                "у ненайденной поправки нет причины: %s" % step.get("number"))
            continue
        in_library += 1
        where = step.get("file")
        if where:
            pdf = ROOT / str(where)
            assert pdf.exists(), f"файла поправки нет на диске: {where}"
            digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
            if step.get("sha256"):
                assert digest == step.get("sha256"), f"отпечаток не совпал: {where}"
        else:
            link = str(step.get("file_url") or "")
            assert link == ("http://publication.pravo.gov.ru/file/pdf?eoNumber=%s"
                            % step.get("eo_number")), step.get("number")
            assert re.fullmatch(r"[0-9a-f]{64}", str(step.get("sha256") or "")), (
                "у поправки без файла нет отпечатка оригинала: %s" % step.get("number"))
        text = ROOT / str(step.get("text_file") or "")
        assert text.is_file() and text.stat().st_size > 500, (
            "у поправки нет распознанного текста: %s" % step.get("number"))
    assert in_library >= 20, "в библиотеке должен лежать весь доступный ряд"


def test_the_chain_scans_are_not_stored() -> None:
    """Решение владельца: код и текст — да, сканы — нет. Проверка падает, если
    PDF официальной публикации снова положат в репозиторий."""
    assert not list(CHAIN_DIR.glob("*.pdf")), "в библиотеке снова лежат сканы ряда"
    assert not (ROOT / "docs" / "normative" / "mo_rngp_1080pp_20260901.pdf").exists()

def test_the_latest_edition_is_declared_once() -> None:
    row = _row()
    last = registry.chain_steps(row)[-1]
    assert str(last.get("number")) in str(row.get("latest_amendment")), (
        "последняя строка ряда и «текущая учтённая редакция» разошлись")


def test_a_step_counts_as_accounted_only_when_it_is_studied() -> None:
    row = _row()
    accounted = registry.accounted_numbers(row)
    studied = [s for s in registry.chain_steps(row)
               if str(s.get("status") or "").startswith("разобран")]
    shelved = [s for s in registry.chain_steps(row)
               if str(s.get("status") or "").startswith("в библиотеке")]
    assert studied and shelved, "пример без обоих состояний ничего не проверяет"
    for step in studied:
        assert str(step.get("number")).lower() in accounted, (
            "разобранная поправка не считается учтённой: %s" % step.get("number"))
    for step in shelved:
        assert str(step.get("number")).lower() not in accounted, (
            "поправка, у которой лежит только файл, объявлена учтённой: %s" % step.get("number"))


def test_the_card_names_the_chain_with_its_silence() -> None:
    row = _row()
    counts = registry.chain_counts(row)
    assert counts["all"] > counts["in_library"] > counts["studied"] > 0
    assert counts["missing"] > 0, "пример без ненайденных поправок не проверяет молчание"
    card = registry._card(row, True)
    head = re.search(r"<summary>Ряд поправок — (\d+), из них в библиотеке (\d+),"
                     r" разобрано (\d+), не получено (\d+)</summary>", card)
    assert head, "карточка не называет ряд поправок"
    assert [int(x) for x in head.groups()] == [
        counts["all"], counts["in_library"], counts["studied"], counts["missing"]]
    assert "1480/45" in card, "карточка не называет приложение № 10 его актом"


def test_the_appendix_ten_is_cited_by_the_number_printed_in_it() -> None:
    """Номер акта — часть утверждения, и у нас он был неверным.

    Приложение № 10 было подписано «1400/45»; преамбула 1080-ПП и первая
    страница самого файла говорят «1480/45». Норма при этом та же — она снята с
    этого документа, — но ссылаться надо на существующий акт.
    """
    import parking_norms

    source = parking_norms.MO_APP10_SPORT["source"] if hasattr(parking_norms, "MO_APP10_SPORT") else ""
    if not source:
        source = (ROOT / "parking_norms.py").read_text("utf-8")
    assert "1480/45" in source
    assert "1400/45" not in source
    assert (ROOT / "docs" / "normative"
            / "mo_rngp_app10_parking_1480-45_20211229.pdf").exists()

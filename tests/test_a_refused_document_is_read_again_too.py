"""Склад, где отказали ВСЕ документы, обязан устареть вместе с читателем.

Версия правил у разобранной выписки заведена 14.09.2026 затем, что свод
территории считается из РАЗОБРАННОГО: починка читателя до уже прочитанного лота
сама не доезжает. Считались при этом только ЗАПИСИ — а у склада, где отказали
все документы, записей ноль, значит отставать нечему, и перечитан он не будет
никогда. Замер прода 15.09.2026: так стояли оба Прожектора (печатная форма) и
Шипиловский (архив RAR) — 154 позиции состава без собственника при живых байтах
на складе.

То же правило, что завело версию у записи, только с другой стороны: до
НЕпрочитанного починка тоже не доезжает сама.

Запуск: python3 -m pytest tests/test_a_refused_document_is_read_again_too.py -q
"""

from __future__ import annotations

from typing import Any

from auction_search import egrn_archive, egrn_store

KEY = "21000005000000031472/1"


def _store_with(tmp_path, refusals: list[dict[str, Any]],
                records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Склад с такими отказами и записями — тем же путём, каким его пишет разбор."""
    return egrn_store.save(
        tmp_path, KEY,
        {"records": list(records or []), "unread": list(refusals),
         "companions": [], "entries": len(refusals) + len(records or []),
         "archives": 0, "duplicates": []},
        "Территория.Выписка ЕГРН для здания.pdf")


def test_a_refusal_carries_the_version_it_was_made_by() -> None:
    """Отказ несёт версию читателя так же, как запись.

    Без неё «отказано прежними правилами» и «отказано нынешними» на складе
    неразличимы, а счётчик устаревшего разбора считать их не может.
    """
    parsed = egrn_archive.read(b"not a zip and not an xml", name="чужое.bin")
    assert parsed["unread"], parsed
    assert all(item["reader_version"] == egrn_archive.READER_VERSION
               for item in parsed["unread"]), parsed["unread"]


def test_a_store_of_only_refusals_is_behind_and_asked_again(tmp_path) -> None:
    """Ноль записей и отказы прежних правил — склад устарел, и его спрашивают."""
    old = egrn_archive.READER_VERSION - 1
    kept = _store_with(tmp_path, [
        {"name": "Выписка ЕГРН для здания.pdf", "reason": "немой отказ",
         "reader_version": old},
        {"name": "Выписка ЕГРН для участка.pdf", "reason": "немой отказ",
         "reader_version": old},
    ])
    behind = egrn_store.stale(kept)
    assert behind["records"] == 0, behind
    assert behind["refusals"] == 2 and behind["refusals_behind"] == 2, behind
    assert behind["behind"] == 2, behind
    assert egrn_store.reread_due(kept) is True, behind


def test_a_store_refused_by_the_current_reader_is_not_asked_again(tmp_path) -> None:
    """Предохранитель: отказ НЫНЕШНИХ правил перечитывать незачем.

    Иначе проверка выше зеленела бы на коде, который спрашивает площадку каждый
    круг за ответ, который не изменится.
    """
    kept = _store_with(tmp_path, [
        {"name": "Выписка ЕГРН для здания.pdf", "reason": "архив RAR",
         "reader_version": egrn_archive.READER_VERSION},
    ])
    behind = egrn_store.stale(kept)
    assert behind["refusals"] == 1 and behind["refusals_behind"] == 0, behind
    assert behind["behind"] == 0, behind
    assert egrn_store.reread_due(kept) is False, behind


def test_records_and_refusals_are_counted_apart(tmp_path) -> None:
    """«Прочитано прежним читателем» и «отказано прежним» — разные числа."""
    old = egrn_archive.READER_VERSION - 1
    kept = _store_with(
        tmp_path,
        [{"name": "участок.pdf", "reason": "немой отказ", "reader_version": old}],
        [{"cadastral_number": "77:05:0012007:17", "source": "print_form",
          "reader_version": egrn_archive.READER_VERSION}])
    behind = egrn_store.stale(kept)
    assert behind["records"] == 1 and behind["records_behind"] == 0, behind
    assert behind["refusals"] == 1 and behind["refusals_behind"] == 1, behind
    assert behind["behind"] == 1, behind


def test_the_same_file_refused_twice_counts_once(tmp_path) -> None:
    """Отказы считаются по ПОСЛЕДНЕМУ заходу, а не по всем.

    Журнал заходов держит до двадцати записей, и один файл лежит в нём столько
    раз, сколько его разбирали: сложенные подряд, отказы дают число втрое
    больше настоящего — на этом я уже ошибся в замере 15.09.2026 (216 вместо 58).
    """
    old = egrn_archive.READER_VERSION - 1
    refusal = [{"name": "здание.pdf", "reason": "немой отказ", "reader_version": old}]
    _store_with(tmp_path, refusal)
    _store_with(tmp_path, refusal)
    kept = _store_with(tmp_path, refusal)
    assert len(kept["uploads"]) == 3, kept["uploads"]
    behind = egrn_store.stale(kept)
    assert behind["refusals"] == 1, behind


def test_a_refusal_without_the_field_is_the_first_version(tmp_path) -> None:
    """Отказ без поля сделан до того, как версию завели, — не «не знаем»."""
    kept = _store_with(tmp_path, [{"name": "здание.pdf", "reason": "немой отказ"}])
    behind = egrn_store.stale(kept)
    assert behind["refusal_versions"] == {
        str(egrn_archive.READER_VERSION_BEFORE): 1}, behind
    assert behind["refusals_behind"] == 1, behind

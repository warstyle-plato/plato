"""Владелец подтверждает и выбирает связи позиций с ГПР; выбор переходит в новую редакцию.

Связь принадлежит позиции (номер, название, единица), а не файлу, и переходит
в соглашение, только пока выбранные строки остались в действующем графике с
тем же кодом и названием. Удалённый из карточки файл не стирается и
возвращается. Документы выдуманы: репозиторий публичный.
"""
from __future__ import annotations

import copy

import pytest

import developaid_contract_files as files
import developaid_contract_link_choices as choices
import developaid_contract_schedule_links as links
import developaid_monitor as monitor
from test_contract_positions_are_linked_to_schedule_lines import ESTIMATE, SCHEDULE
from tests.test_contract_documents_are_read_from_their_tables import TITLE, estimate_pdf, schedule_pdf
from tests.test_contract_files_are_kept_per_contract import CONTRACT, KEY, ROW, _finished

NOW = "2026-11-10T10:00:00+00:00"


def _item(result, number):
    return next(p for p in result["positions"] if p["number"] == number)


def _choose(number, lines=None, shares=None, schedule=SCHEDULE):
    item = _item(links.propose(ESTIMATE, schedule), number)
    return {item["key"]: choices.decide(item, schedule, lines, shares, NOW)}


def test_a_confirmed_proposal_follows_the_new_dates_and_hand_shares_stay():
    chosen = _choose("3.1")
    result = choices.apply(links.propose(ESTIMATE, SCHEDULE), chosen, SCHEDULE)
    walls = _item(result, "3.1")
    assert walls["status"] == "confirmed" and walls["origin"] == "duration" and not walls["chosen"]
    assert result["counts"] == {"confirmed": 1, "proposed": 3, "review": 5, "extra": 0}
    later = copy.deepcopy(SCHEDULE)
    next(line for line in later["lines"] if line["code"] == "3.1.3")["finish"] = "2026-03-25"
    moved = _item(choices.apply(links.propose(ESTIMATE, later), chosen, later), "3.1")
    assert [round(line["share"], 4) for line in moved["lines"]] == [round(10 / 20, 4), round(10 / 20, 4)]
    hand = _choose("3.1", ["3.1.1", "3.1.3"], [70, 30])
    kept = _item(choices.apply(links.propose(ESTIMATE, later), hand, later), "3.1")
    assert [line["share"] for line in kept["lines"]] == [0.7, 0.3] and kept["assumption"] == choices.MANUAL_NOTE


def test_a_review_position_gets_the_lines_the_owner_chose():
    chosen = _choose("4.1", ["4.1.1"])
    result = choices.apply(links.propose(ESTIMATE, SCHEDULE), chosen, SCHEDULE)
    walls = _item(result, "4.1")
    assert walls["status"] == "confirmed" and walls["chosen"] and walls["reason"] == ""
    assert [line["share"] for line in walls["lines"]] == [1.0]
    assert "4.1.1" not in [line["code"] for line in result["lines_without_positions"]]


def test_a_choice_whose_line_was_renamed_is_not_carried_and_says_why():
    chosen = _choose("3.1")
    renamed = copy.deepcopy(SCHEDULE)
    next(line for line in renamed["lines"] if line["code"] == "3.1.3")["name"] = "Устройство кровли"
    walls = _item(choices.apply(links.propose(ESTIMATE, renamed), chosen, renamed), "3.1")
    assert walls["status"] == "proposed" and walls["carry"] == (
        "Подтверждённая ранее связь не перенесена: в действующем графике нет строки 3.1.3 «Возведение "
        "вертикальных конструкций 2-ого этажа». Подтвердите связь заново.")


@pytest.mark.parametrize("number, lines, shares, reason", [
    ("4.1", None, None, "У позиции 4.1 нет предложенной связи: выберите строки графика."),
    ("4.1", ["3.1"], None, "Строк 3.1 нет среди работ действующего графика"),
    ("4.1", [], None, "Выберите хотя бы одну строку графика."),
    ("3.1", ["3.1.1", "3.1.3"], [60, 30], "в сумме давать 100 %"),
    ("3.1", ["3.1.1", "3.1.3"], [100, 0], "больше нуля"),
])
def test_a_wrong_choice_is_refused_with_the_reason(number, lines, shares, reason):
    with pytest.raises(choices.LinkChoiceProblem, match=reason.replace(".", r"\.")):
        _choose(number, lines, shares)
    with pytest.raises(choices.LinkChoiceProblem, match="Сначала загрузите график"):
        _choose(number, lines, shares, schedule=None)


# --- карточка договора ------------------------------------------------------------

AGREEMENT_5 = ("Приложение № 1.2 к Дополнительному соглашению № 5 от 01.03.2026",) + TITLE[1:]


@pytest.fixture
def card(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    schedule = files.store("Учебный", ROW, "ГПР.pdf", schedule_pdf())
    fourth = files.store("Учебный", ROW, "ДС4.pdf", estimate_pdf())
    fifth_pdf = estimate_pdf(title=AGREEMENT_5)
    fifth = files.store("Учебный", ROW, "ДС5.pdf", fifth_pdf)
    return {"schedule": schedule["sha256"], "fourth": fourth["sha256"], "fifth": fifth["sha256"], "pdf": fifth_pdf}


def _walls(listed, sha):
    document = next(d for d in listed["documents"] if d["sha256"] == sha)
    return next(p for p in document["estimates"][0]["links"]["positions"] if p["name"] == "Бетонирование стен")


def test_a_choice_in_one_edition_holds_in_the_next_and_is_cleared(card):
    before = files.listing("Учебный", CONTRACT)
    walls = _walls(before, card["fourth"])
    assert walls["status"] == "review"
    saved = files.save_links("Учебный", CONTRACT, card["fourth"], 0, [{"index": walls["index"], "lines": ["2.3"]}])
    assert _walls(saved, card["fourth"])["status"] == "confirmed"
    carried = _walls(saved, card["fifth"])
    assert carried["status"] == "confirmed" and [line["code"] for line in carried["lines"]] == ["2.3"]
    cleared = files.save_links("Учебный", CONTRACT, card["fifth"], 0, [{"index": walls["index"]}], clear=True)
    assert {_walls(cleared, sha)["status"] for sha in (card["fourth"], card["fifth"])} == {"review"}


def test_one_bad_choice_saves_nothing(card):
    walls = _walls(files.listing("Учебный", CONTRACT), card["fourth"])
    with pytest.raises(files.ContractFilesProblem, match="нет предложенной связи"):
        files.save_links("Учебный", CONTRACT, card["fourth"], 0,
                         [{"index": walls["index"], "lines": ["2.3"]}, {"index": walls["index"]}])
    assert _walls(files.listing("Учебный", CONTRACT), card["fourth"])["status"] == "review"
    with pytest.raises(files.ContractFilesProblem, match="Расчёт не найден"):
        files.save_links("Учебный", CONTRACT, card["schedule"], 0, [{"index": 0}])


def test_a_removed_file_leaves_the_card_and_comes_back(card):
    listed = files.remove("Учебный", CONTRACT, card["fifth"])
    assert [d["filename"] for d in listed["documents"]] == ["ГПР.pdf", "ДС4.pdf"]
    (removed,) = listed["removed"]
    assert removed["filename"] == "ДС5.pdf" and removed["title"] == "Дополнительное соглашение № 5 от 01.03.2026"
    twin = files.store("Учебный", ROW, "ДС4 без штампа.pdf", estimate_pdf(stamp=False))["sha256"]
    fourth = next(d for d in files.remove("Учебный", CONTRACT, twin)["documents"] if d["sha256"] == card["fourth"])
    assert fourth["warnings"] == [], "удалённый файл не считается вторым файлом редакции"
    back = files.remove("Учебный", CONTRACT, card["fifth"], restore=True)
    assert [d["filename"] for d in back["documents"]] == ["ГПР.pdf", "ДС4.pdf", "ДС5.pdf"]
    assert [d["filename"] for d in back["removed"]] == ["ДС4 без штампа.pdf"]
    files.remove("Учебный", CONTRACT, twin, restore=True)
    files.remove("Учебный", CONTRACT, card["fifth"])
    again = files.store("Учебный", ROW, "ДС5 ещё раз.pdf", card["pdf"])
    assert again["already"] and again["restored"]
    assert files.listing("Учебный", CONTRACT)["removed"] == []
    files.remove("Учебный", CONTRACT, card["schedule"])
    walls = _walls(files.listing("Учебный", CONTRACT), card["fourth"])
    assert walls["reason"].startswith("График производства работ этой или прежней редакции не загружен")
    with pytest.raises(files.ContractFilesProblem, match="не найден"):
        files.remove("Учебный", CONTRACT, "f" * 64)


@pytest.fixture
def api(monkeypatch, card):
    from fastapi.testclient import TestClient
    import developaid_monitor_contracts as contracts
    import main as wrapper
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", KEY)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(contracts, "build", lambda project, cut="", **_: {"rows": [ROW]})
    return TestClient(wrapper.core.app)


def test_links_and_removal_go_through_the_routes(api, card):
    base = {"key": KEY, "project": "Учебный", "cut": "2026-11-06", "contract_id": CONTRACT}
    walls = _walls(files.listing("Учебный", CONTRACT), card["fourth"])
    for path, body in (("document-links", {"sha256": card["fourth"], "estimate": 0,
                                           "choices": [{"index": walls["index"]}]}),
                       ("document-remove", {"sha256": card["fifth"]})):
        refused = api.post("/monitor/contracts/" + path, json={**base, **body, "key": "wrong-key"})
        assert refused.status_code == 403 and refused.headers["cache-control"] == "private, no-store"
    done = _finished(api, api.post("/monitor/contracts/document-links", json={
        **base, "sha256": card["fourth"], "estimate": 0,
        "choices": [{"index": walls["index"], "lines": ["2.3"], "shares": [100]}]}))
    assert done["ok"] and _walls(done, card["fourth"])["origin"] == "manual"
    wrong = _finished(api, api.post("/monitor/contracts/document-links", json={
        **base, "sha256": card["fourth"], "estimate": 0, "choices": [{"index": walls["index"], "lines": ["2"]}]}))
    assert wrong["ok"] is False and wrong["detail"].startswith("Строк 2 нет среди работ действующего графика")
    removed = _finished(api, api.post("/monitor/contracts/document-remove", json={**base, "sha256": card["fifth"]}))
    assert [d["filename"] for d in removed["removed"]] == ["ДС5.pdf"]

"""Номер договора и файла в карточке — только 64 знака hex: путь к чужой карточке не проходит.

Проверены оба слоя по отдельности: маршрут отказывает до фоновой задачи (422), а модуль
карточки отказывает сам, если до него дошёл чужой путь. Снятие любого слоя краснит свой тест.
Попутно: два воркера, перечитывающий разбор и убирающий файл, не теряют отметку «убран».
"""
from __future__ import annotations

import base64
import json
import threading

import pytest

import developaid_contract_documents as documents
import developaid_contract_files as files
from tests.test_contract_documents_are_read_from_their_tables import estimate_pdf
from tests.test_contract_files_are_kept_per_contract import CONTRACT, KEY, ROW, api, store  # noqa: F401

OTHER = "d" * 64
OTHER_ROW = {**ROW, "id": OTHER}
SHA = "a" * 64
# Нули, чужая карточка, абсолютный путь, нулевой байт, не-hex, заглавные и перевод строки в конце.
BAD = [f"../{OTHER}", f"{CONTRACT}/../{OTHER}", "/etc", "/" + "a" * 63, "a" * 63 + "\x00", "g" * 64,
       "A" * 64, "a" * 64 + "\n", "a" * 65, ""]


@pytest.mark.parametrize("bad", BAD)
def test_the_module_refuses_a_contract_id_that_is_no_card(store, bad):  # noqa: F811
    files.store("Учебный", OTHER_ROW, "ДС4.pdf", estimate_pdf())
    for call in (lambda: files.listing("Учебный", bad),
                 lambda: files.store("Учебный", {**ROW, "id": bad}, "ДС4.pdf", estimate_pdf()),
                 lambda: files.save_links("Учебный", bad, SHA, 0, [{"index": 0}]),
                 lambda: files.remove("Учебный", bad, SHA)):
        with pytest.raises(files.ContractFilesProblem, match="Выберите договор из списка."):
            call()
    assert sorted(p.name for p in (store / "Учебный" / "contract_documents").iterdir()) == [OTHER]


@pytest.mark.parametrize("bad", ["../{other}/{sha}", "{sha}/../{sha}", "/{sha}", "{sha}\x00", "{sha}\n"])
def test_the_module_refuses_a_file_id_that_leads_to_another_card(store, bad):  # noqa: F811
    files.store("Учебный", ROW, "ДС4.pdf", estimate_pdf())
    sha = files.store("Учебный", OTHER_ROW, "ДС4.pdf", estimate_pdf())["sha256"]
    with pytest.raises(files.ContractFilesProblem, match="Документ не найден в карточке"):
        files.remove("Учебный", CONTRACT, bad.format(other=OTHER, sha=sha))
    assert [d["sha256"] for d in files.listing("Учебный", OTHER)["documents"]] == [sha], "чужой файл не убран"


def test_links_for_a_contract_without_a_card_make_no_folder(store):  # noqa: F811
    with pytest.raises(files.ContractFilesProblem, match="Расчёт не найден среди документов карточки"):
        files.save_links("Учебный", CONTRACT, SHA, 0, [{"index": 0}])
    assert not (store / "Учебный" / "contract_documents" / CONTRACT).exists()


ROUTES = {
    "documents": {},
    "document-upload": {"filename": "ДС4.pdf", "content_base64": base64.b64encode(b"%PDF-1.7").decode()},
    "document-links": {"sha256": SHA, "estimate": 0, "choices": [{"index": 0}]},
    "document-remove": {"sha256": SHA},
}


@pytest.fixture
def untouched(monkeypatch):
    """The card module must not be reached: any call is recorded."""
    calls = []
    for name in ("listing", "store", "save_links", "remove"):
        monkeypatch.setattr(files, name, lambda *a, _name=name, **k: calls.append(_name) or {})
    return calls


@pytest.mark.parametrize("route", sorted(ROUTES))
@pytest.mark.parametrize("bad", BAD)
def test_the_route_refuses_a_contract_id_before_the_job(api, untouched, route, bad):  # noqa: F811
    body = {"key": KEY, "project": "Учебный", "cut": "2026-11-06", "contract_id": bad, **ROUTES[route]}
    response = api.post("/monitor/contracts/" + route, json=body)
    assert response.status_code == 422 and untouched == []
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("route", ["document-links", "document-remove"])
@pytest.mark.parametrize("bad", [f"../{OTHER}/{SHA}"[:64], "/" + "a" * 63, "a" * 63 + "\x00", "g" * 64,
                                 "a" * 64 + "\n"])
def test_the_route_refuses_a_file_id_before_the_job(api, untouched, route, bad):  # noqa: F811
    body = {"key": KEY, "project": "Учебный", "cut": "2026-11-06", "contract_id": CONTRACT,
            **ROUTES[route], "sha256": bad}
    assert api.post("/monitor/contracts/" + route, json=body).status_code == 422 and untouched == []


def test_a_reread_by_one_worker_keeps_the_removal_written_by_the_other(store, monkeypatch):  # noqa: F811
    sha = files.store("Учебный", ROW, "ДС4.pdf", estimate_pdf())["sha256"]
    monkeypatch.setattr(documents, "READER_VERSION", documents.READER_VERSION + 1)
    record, removal = files._record, threading.Thread(target=lambda: files.remove("Учебный", CONTRACT, sha))

    def slow_read(*args):
        # While this worker reads the PDF again, the other one takes the file out of the card.
        if removal.ident is None:
            removal.start()
            removal.join(timeout=1)
        return record(*args)

    monkeypatch.setattr(files, "_record", slow_read)
    files.listing("Учебный", CONTRACT)
    removal.join(timeout=10)
    assert not removal.is_alive()
    kept = json.loads((store / "Учебный" / "contract_documents" / CONTRACT / f"{sha}.json").read_text())
    assert kept["removed_at"] and kept["reader"] == documents.READER_VERSION
    listed = files.listing("Учебный", CONTRACT)
    assert listed["documents"] == [] and [r["sha256"] for r in listed["removed"]] == [sha]


@pytest.fixture
def opened(monkeypatch):
    """Every PDF the reader opens, to see that it is closed after the reading."""
    import pymupdf
    kept, real = [], pymupdf.open
    monkeypatch.setattr(pymupdf, "open", lambda *a, **k: kept.append(real(*a, **k)) or kept[-1])
    return kept


def test_a_pdf_longer_than_the_limit_is_refused_and_closed(store, opened, monkeypatch):  # noqa: F811
    monkeypatch.setattr(documents, "MAX_PAGES", 1)
    pdf = estimate_pdf()
    opened.clear()
    with pytest.raises(files.ContractFilesProblem, match="В документе страниц: 2, а читается не больше 1. "
                                                         "Загрузите договор, соглашения и акты отдельными файлами."):
        files.store("Учебный", ROW, "ДС4.pdf", pdf)
    assert opened and all(document.is_closed for document in opened)
    assert not list((store / "Учебный" / "contract_documents" / CONTRACT).glob("*.pdf"))


def test_a_pdf_within_the_limit_is_read_and_closed(store, opened):  # noqa: F811
    pdf = estimate_pdf()
    opened.clear()
    assert files.store("Учебный", ROW, "ДС4.pdf", pdf)["sha256"]
    assert opened and all(document.is_closed for document in opened)

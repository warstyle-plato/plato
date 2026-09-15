"""Рисунок границ города: либо картинка, либо названная причина.

«И почему контура карты нет нигде» (владелец, 14.09.2026, снимок экрана:
раскрытие «▼ Контур площадки, как его напечатал город» и под ним ничего).
Карта при этом была в порядке — замер настоящим Chromium на проде дал 57
фигур у Варшавского ш., вл. 37, 65 у Прожектора, 28 у Ясеневой. Пусто было
раскрытие: оно стоит в разметке у ВСЕХ площадок, а картинку отдавал маршрут,
который существовал только у Нагатино (`/krt/nagatino/decision-outline.png`).

Рисунок у площадки с торгов есть — в её же лотовой документации лежит
«Схема границ». Извлекатель здесь один на все площадки: второй разошёлся бы с
первым, а порог «крупная картинка» пришлось бы держать в двух местах.

Запуск: python3 -m pytest tests/test_the_city_outline_is_never_an_empty_fold.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import page_blocks  # noqa: E402
from auction_search import api, lot_documents, nagatino_parcels, nagatino_ui  # noqa: E402

DECISION = ROOT / "reference_data" / "krt" / "nagatino-decision-draft.pdf"
KEY = "21000005000000032802/1"
SLUG = "kurkinskoe"


def _client(tmp_path: Path, monkeypatch, *, lots: dict) -> TestClient:
    """Приложение на настоящем складе и настоящей связке — как на проде.

    Связка пишется ФАЙЛОМ, а не заглушкой метода: её читает `tender_lots_known`
    с диска, и подменённый метод проверял бы заглушку, а не путь до склада.
    """
    # Каталог данных рынка — `DATA_DIR/market`: он выбирается при установке
    # приложения, и подменять надо его, а не имя, которого код не знает.
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "ключ-владельца")
    place = tmp_path / "market" / "krt" / "tender_lots.json"
    place.parent.mkdir(parents=True, exist_ok=True)
    place.write_text(json.dumps({"schema_version": 1, "sites": lots},
                                ensure_ascii=False), encoding="utf-8")
    app = FastAPI()
    api.install(app)
    return TestClient(app)


def _store(tmp_path: Path, name: str, raw: bytes) -> None:
    tmp_path = tmp_path / "market"
    lot_documents.save(tmp_path, KEY, f"https://178fz.roseltorg.ru/file/{name}",
                       data=raw, content_type="application/pdf", title=name)


def test_the_picture_comes_from_the_lot_documentation(tmp_path, monkeypatch):
    """Схема границ лота — тот же рисунок города, и извлекается он тем же кодом."""
    _store(tmp_path, "Территория.Схема границ.16995741.pdf", DECISION.read_bytes())
    client = _client(tmp_path, monkeypatch,
                     lots={SLUG: {"lots": [{"store_key": KEY}]}})
    got = client.get(f"/krt/site/{SLUG}/decision-outline.png?key=ключ-владельца")
    assert got.status_code == 200, got.text[:300]
    assert got.content[:4] == b"\x89PNG"
    # Чем найдено — часть ответа: подпись называет документ.
    assert "%D0%A1%D1%85%D0%B5%D0%BC%D0%B0" in got.headers.get("X-Outline-Source", "")


def test_a_site_without_a_lot_says_so_instead_of_an_empty_fold(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, lots={})
    got = client.get(f"/krt/site/{SLUG}/decision-outline.png?key=ключ-владельца")
    assert got.status_code == 404
    said = got.json().get("detail", "")
    assert "лота" in said and "не знаем" in said


def test_an_empty_store_is_named_as_our_gap(tmp_path, monkeypatch):
    """«Склад пуст» и «схемы в документах нет» — разные ответы."""
    client = _client(tmp_path, monkeypatch,
                     lots={SLUG: {"lots": [{"store_key": KEY}]}})
    got = client.get(f"/krt/site/{SLUG}/decision-outline.png?key=ключ-владельца")
    assert got.status_code == 404
    assert "склад" in got.json().get("detail", "").casefold()


def test_a_document_without_a_big_picture_is_named_too(tmp_path, monkeypatch):
    _store(tmp_path, "Территория.Схема границ.pdf", b"%PDF-1.4\n%%EOF\n")
    client = _client(tmp_path, monkeypatch,
                     lots={SLUG: {"lots": [{"store_key": KEY}]}})
    got = client.get(f"/krt/site/{SLUG}/decision-outline.png?key=ключ-владельца")
    assert got.status_code == 404
    said = got.json().get("detail", "")
    assert "Схема границ" in said or "не открылся" in said


def test_the_extractor_is_one_for_every_site():
    """Два извлекателя разошлись бы, а порог «крупная картинка» — тем более."""
    source = (ROOT / "auction_search" / "nagatino_parcels.py").read_text(encoding="utf-8")
    assert source.count("pix.width >=") == 1, "второй порог крупной картинки"
    assert "outline_picture_from(DECISION_PATH.read_bytes()" in source


def test_the_fold_of_a_site_points_at_its_own_route():
    """Пустого раскрытия не бывает: у площадки свой маршрут картинки."""
    page = nagatino_ui.nagatino_page(None)
    prelude = ("const BASE='/krt/site/kurkinskoe';const IS_NAGATINO=false;"
               "const S={data:{territory:{totals:{}}}};"
               "function auth(){return {session:'',key:'k',share:''}}"
               "function escapeHtml(s){return String(s==null?'':s)}"
               "function m2(v){return String(v)}"
               "function landNum(v){return String(v)}")
    tail = ("const html=decisionOutlineMarkup();"
            "console.log(JSON.stringify({empty:!html.trim(),html:html.slice(0,400)}));")
    said = page_blocks.run_json(prelude, tail, page=page)
    assert not said["empty"], "раскрытие у площадки пусто — читается как поломка"
    assert "/krt/site/kurkinskoe/decision-outline.png" in said["html"]
    assert "outlinePictureFailed" in said["html"], "причина отказа печатается словами маршрута"

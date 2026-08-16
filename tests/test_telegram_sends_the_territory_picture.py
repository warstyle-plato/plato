"""Бот присылает картинку территории — как карточка участка на сайте.

Контур с подложкой НСПД жил только на сайте; в чате бота участок оставался
числами (замечание владельца, 16.08.2026). Теперь после «Территория
сформирована» (Москва) и карточки Подмосковья в чат уходит фото: контуры
ЕГРН поверх публичной карты НСПД. Закреплено:

- контуры берутся из /land/lookup (contour_merc), подложка — из
  /land/map-image; оба на Render пересылают на ядро сами;
- без карты фото не отправляется вовсе: голый контур на белом фоне в чате —
  шум, а не информация (владелец, 16.08.2026, скриншот);
- нет контуров — нет фото, и ничего не падает: картинка украшение;
- сбор ходит в НСПД, поэтому уходит фоном, не держа ответ вебхука.

Запуск: python3 -m pytest tests/test_telegram_sends_the_territory_picture.py -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException, Response

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core
CHAT_ID = 515151

MERC_RING = [[4200000.0, 7550000.0], [4200100.0, 7550000.0],
             [4200100.0, 7550100.0], [4200000.0, 7550100.0], [4200000.0, 7550000.0]]


def _lookup_payload(with_contour: bool = True) -> dict:
    return {"results": [{
        "found": True, "kind": "land", "cadastral_number": "77:07:0008006:3",
        "contour_merc": [MERC_RING] if with_contour else [],
    }, {
        "found": True, "kind": "land", "cadastral_number": "77:07:0008006:25",
        "contour_merc": [[[p[0] + 150, p[1]] for p in MERC_RING]] if with_contour else [],
    }]}


def _map_png() -> bytes:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (640, 640), (200, 210, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture()
def photo(monkeypatch):
    sent: list[dict] = []

    def fake_photo(chat_id, content, filename, caption=""):
        sent.append({"chat_id": chat_id, "content": content,
                     "filename": filename, "caption": caption})
        return {}

    monkeypatch.setattr(core, "_telegram_send_photo_bytes", fake_photo)
    return sent


def test_the_photo_carries_contours_over_the_map(photo, monkeypatch):
    monkeypatch.setattr(core, "land_lookup", lambda req: _lookup_payload())
    monkeypatch.setattr(core, "land_map_image",
                        lambda bbox: Response(_map_png(), media_type="image/png"))
    assert core._telegram_territory_photo(CHAT_ID, ["77:07:0008006:3", "77:07:0008006:25"])
    from PIL import Image
    sent = photo[-1]
    assert sent["content"][:4] == b"\x89PNG"
    image = Image.open(io.BytesIO(sent["content"]))
    assert min(image.size) >= 64
    assert "Территория из 2 участков" in sent["caption"]
    assert "77:07:0008006:3" in sent["caption"]
    assert "подложка — публичная карта НСПД" in sent["caption"]


def test_a_dead_map_means_no_photo_at_all(photo, monkeypatch):
    """Голый контур на белом фоне в чате не нужен — лучше ничего."""
    monkeypatch.setattr(core, "land_lookup", lambda req: _lookup_payload())

    def broken(bbox):
        raise HTTPException(status_code=502, detail="НСПД молчит")

    monkeypatch.setattr(core, "land_map_image", broken)
    assert core._telegram_territory_photo(CHAT_ID, ["77:07:0008006:3"]) is False
    assert photo == []


def test_no_contours_means_no_photo_and_no_crash(photo, monkeypatch):
    monkeypatch.setattr(core, "land_lookup", lambda req: _lookup_payload(with_contour=False))
    assert core._telegram_territory_photo(CHAT_ID, ["77:07:0008006:3"]) is False
    assert photo == []


def test_a_failed_send_is_swallowed(monkeypatch):
    """Картинка украшение: отказ Telegram не должен уронить поток расчёта."""
    monkeypatch.setattr(core, "land_lookup", lambda req: _lookup_payload())
    monkeypatch.setattr(core, "land_map_image",
                        lambda bbox: Response(_map_png(), media_type="image/png"))

    def boom(*args, **kwargs):
        raise RuntimeError("Telegram API недоступен")

    monkeypatch.setattr(core, "_telegram_send_photo_bytes", boom)
    assert core._telegram_territory_photo(CHAT_ID, ["77:07:0008006:3"]) is False


def test_both_bot_flows_send_the_photo_in_the_background():
    source = Path(core.__file__).read_text(encoding="utf-8")
    moscow = source[source.index("def _telegram_handle_cadastral_numbers"):]
    moscow = moscow[:moscow.index("\ndef ")]
    assert "_telegram_territory_photo_async(chat_id, recognized)" in moscow
    mo = source[source.index("def _telegram_handle_mo_numbers"):]
    mo = mo[:mo.index("\ndef cadastral_route")]
    assert "_telegram_territory_photo_async(chat_id, numbers)" in mo
    background = source[source.index("def _telegram_territory_photo_async"):]
    background = background[:background.index("\ndef ")]
    assert "threading.Thread" in background and "daemon=True" in background

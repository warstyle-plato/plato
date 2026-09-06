"""404 от сервиса — это «сервис не отдал», а не «объекта нет».

06.09.2026 НСПД отвечал 404 по ВСЕМ своим адресам: поиск, слои карты,
GetFeatureInfo. Замер на проде в тот час: `/land/map-probe` — 404 по всем
четырём вариантам, `/land/screen-probe` в точке Кремля — ноль объектов на всех
восьми слоях, четыре настоящих кадастровых номера (77:01:0004621:72,
77:09:0004014:13, 77:04:0001019:173, 50:21:0120316:1221) — «не найден».

Наша половина беды жила одной строкой: `if exc.code == 404: return None`.
Тёмный источник выглядел как отрицательный ответ источника, и на экране это
читалось как плохо введённый адрес (экран владельца). Правило «отсутствие
ответа внешнего источника нельзя показывать как его отрицательный ответ» было
записано давно — эта ветка его обходила.

Ни один вызов `_land_fetch_json` не адресует объект по идентификатору: это
поиск, WMS и геокодеры. У них 404 означает, что адреса нет у СЕРВИСА.

Запуск: python3 -m pytest tests/test_a_404_from_the_portal_is_not_an_empty_answer.py -q
"""

from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def _raise_404(*_args, **_kwargs):
    raise urllib.error.HTTPError(
        core._NSPD_BASE_URL + "/api/geoportal/v2/search/geoportal",
        404, "Not Found", {}, None)  # type: ignore[arg-type]


def test_a_404_is_reported_not_swallowed(monkeypatch) -> None:
    monkeypatch.setattr(core.urllib.request, "urlopen", _raise_404)
    with pytest.raises(HTTPException) as fail:
        core._land_fetch_json(core._NSPD_BASE_URL + "/api/geoportal/v2/search/geoportal?query=x",
                              service="Сервис НСПД")
    said = str(fail.value.detail)
    assert "404" in said, said
    assert "не отдал" in said, said


def test_the_search_does_not_report_an_empty_result(monkeypatch) -> None:
    """Тёмный поиск обязан сказать о себе, а не вернуть пустой список."""
    monkeypatch.setattr(core.urllib.request, "urlopen", _raise_404)
    core._land_cache_clear() if hasattr(core, "_land_cache_clear") else None
    with pytest.raises(HTTPException):
        core._nspd_search_features("77:01:0004621:72")


@pytest.mark.parametrize("query", ["77:01:0004621:72", "г Москва, ул Мишина, 46"])
def test_the_lookup_names_the_reason_instead_of_not_found(monkeypatch, query: str) -> None:
    """На экране вместо «участок не найден» стоит ответ сервиса.

    Причина лежит в разных местах: по адресу — в предупреждениях поиска, по
    номеру — в примечании своей строки (у каждого номера ответ свой, и общий
    список их бы слил). Читателю нужна одна фраза, и `reason` берёт её оттуда,
    где она есть, — поэтому спрашиваем обе формы запроса.
    """
    monkeypatch.setattr(core.urllib.request, "urlopen", _raise_404)
    if hasattr(core, "_land_cache_clear"):
        core._land_cache_clear()
    answer = core.land_lookup(core.LandLookupRequest(query=query, limit=5))
    assert answer.get("found_count") == 0
    assert answer.get("reason"), f"причина не названа: {answer.get('warnings')}"
    assert "404" in answer["reason"], answer["reason"]
    assert answer["reason"] not in core._LAND_LOOKUP_STANDING_NOTES


def test_no_call_site_asks_for_an_object_by_id() -> None:
    """404 читалось бы как «нет такого объекта» только у ресурса по номеру.

    Пока все вызовы — поиск, WMS и геокодеры, молчаливое 404 → None неверно
    везде. Появится вызов по идентификатору — эта проверка о нём скажет.
    """
    source = Path(core.__file__).read_text(encoding="utf-8")
    assert "if exc.code == 404:\n            return None" not in source, (
        "404 снова превращается в пустой ответ")
    assert source.count("_land_fetch_json(") == 7, (
        "появился новый вызов — проверьте, не адресует ли он объект по номеру")

"""Владение — такой же адрес, как дом, и подсказка обязана его показывать.

На «г Москва, ул Маршала Воробьёва, влд 12» список подсказок предлагал дома:
«д 12 к 3», «д 12 к 3 стр 1». Выглядело это как «владения в базе нет», а на
деле его выбрасывал наш собственный отсев.

Причин оказалось две, и по отдельности каждая давала тот же экран.

Первая: подсказки собирал геокодер. `_geocode_dadata` пропускает только то, у
чего есть координаты, — ему без точки отвечать нечем. Но у владения точки в
базе часто нет вовсе: DaData ставит её дому, а владение остаётся объектом
ФИАС без координат. Подсказка отвечает за АДРЕС, а не за точку, и отсев
геокодера ей не подходит.

Вторая: клик. Уровень объекта опознавался перечислением типов ФИАС, и в нём
стояло `вл`, а ФИАС пишет `влд`. Даже дойди владение до списка, клик по нему
не запустил бы поиск — дописал бы запятую и стал ждать уточнения, как по
клику на «Мытищи». Перечисление в регулярке выглядит правдоподобно и молчит,
поэтому проверяется настоящим шаблоном из слоя, а не его пересказом.

Запуск: python3 -m pytest tests/test_a_holding_is_an_address_too.py -q
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

OVERLAY = (ROOT / "ia_preview" / "assets" / "overlay.js").read_text(encoding="utf-8")

# Так отвечает DaData на «ул Маршала Воробьёва, влд 12»: у владения координат
# нет, у домов есть. Ключи — те же, что читает движок.
_ANSWER = {
    "suggestions": [
        {"value": "г Москва, ул Маршала Воробьёва, влд 12",
         "data": {"geo_lat": None, "geo_lon": None}},
        {"value": "г Москва, ул Маршала Воробьёва, д 12 к 3",
         "data": {"geo_lat": "55.712", "geo_lon": "37.489"}},
    ],
}


@pytest.fixture()
def dadata(monkeypatch):
    monkeypatch.setenv("DADATA_API_KEY", "тест")
    monkeypatch.setattr(core, "_land_fetch_json", lambda *a, **k: _ANSWER)


def test_a_holding_without_a_point_stays_in_the_suggestions(dadata) -> None:
    """Точка — не признак существования адреса."""
    labels = [item["label"] for item in core._dadata_suggest("влд 12", 8)]
    assert "г Москва, ул Маршала Воробьёва, влд 12" in labels
    assert len(labels) == 2


def test_the_geocoder_still_answers_only_with_points(dadata) -> None:
    """Геокодеру без координат отвечать нечем — его отсев остаётся на месте."""
    found = core._geocode_dadata("влд 12", 8)
    assert [item["label"] for item in found] == ["г Москва, ул Маршала Воробьёва, д 12 к 3"]
    assert all(item["lat"] is not None and item["lng"] is not None for item in found)


def test_the_suggestion_route_does_not_call_the_geocoder() -> None:
    """Подсказку зовёт подсказка. Геокодер здесь и был причиной пропажи."""
    source = (ROOT / "ia_preview" / "__init__.py").read_text(encoding="utf-8")
    block = source[source.index("async def ia_suggest("):source.index("@app.post(\"/ia/goal-seek\")")]
    assert "core._dadata_suggest" in block
    assert "core._geocode_dadata" not in block


def _house_level(label: str) -> bool:
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    match = re.search(r"var HOUSE_LEVEL_RE = (/.*/);", OVERLAY)
    assert match, "в слое нет шаблона уровня объекта"
    script = (f"var re = {match.group(1)};\n"
              f"console.log(JSON.stringify(re.test({json.dumps(label)})));\n")
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.parametrize("label", [
    "г Москва, ул Маршала Воробьёва, влд 12",
    "г Москва, ул Мишина, двлд 46",
    "г Москва, ул Мишина, д 46",
    "г Москва, ул Мишина, зд 4",
    "обл Московская, г Мытищи, уч 3",
])
def test_a_named_object_starts_the_search(label: str) -> None:
    """Владение, домовладение, дом, здание, участок — по клику считаем."""
    assert _house_level(label) is True


@pytest.mark.parametrize("label", [
    "г Москва",
    "г Москва, ул Маршала Воробьёва",
    "обл Московская, г Мытищи",
])
def test_a_city_or_a_street_only_refines_the_query(label: str) -> None:
    """Клик по «Мытищи» вставлял координаты центра, и точечный поиск собирал
    двадцать случайных участков вокруг. Такой клик обязан уточнять, а не искать."""
    assert _house_level(label) is False


def test_the_longer_type_wins_over_the_shorter_one() -> None:
    """`влд` не должно съедаться `вл`, а `двлд` — `д`: порядок в переборе
    не косметический, и именно на нём ошибка и жила."""
    match = re.search(r"var HOUSE_LEVEL_RE = /.*?\((.*?)\)", OVERLAY)
    assert match, "в слое нет шаблона уровня объекта"
    types = match.group(1).split("|")
    for longer, shorter in (("двлд", "д"), ("влд", "вл"), ("корп", "к")):
        assert longer in types and shorter in types, (longer, shorter)
        assert types.index(longer) < types.index(shorter), f"{longer} должен стоять раньше {shorter}"

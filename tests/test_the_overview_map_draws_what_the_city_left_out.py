"""Обзорная карта КРТ рисует и то, чего нет в файле карты города.

Владелец, 04.09.2026: «На карте крт Нагатино так и нет. Хотя контур в карточке
верный». Карточка умеет собирать контур из участков ЕГРН по перечню проекта
решения; обзорная карта рисовала только записи файла `map2025.json`, а он —
не весь реестр. Площадки, которых там нет, не было на карте вовсе, и это
читалось как её отсутствие в реестре.

Три состояния здесь разные, и слить их нельзя: **нарисовано по решению**,
**перечень ещё не читали** (наш пробел, дочитывает фон) и **спросили, а
контура нет** (ответ документа). Первое рисуется пунктиром — это состав
территории по документу, а не официальный полигон города.

И правило совпадения одно на обе поверхности: карточка спрашивает про одну
площадку, карта — про весь каталог. Второе правило разошлось бы с первым
молча.

Запуск: python3 -m pytest tests/test_the_overview_map_draws_what_the_city_left_out.py -q
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.ui import auctions_page  # noqa: E402
from market_search import krt_registry  # noqa: E402

# Площадка, которая ЕСТЬ в файле карты города, и площадка, которой там нет:
# на живом реестре второй случай — это Нагатино и ещё три десятка строк.
IN_MAP = {"slug": "in-map", "name": "Кунцевская ул., вл. 1", "status": "Планируемый",
          "okrug": "ЗАО", "district": "Кунцево", "area_ha": 5.0,
          "rings_merc": [[[4172000, 7509000], [4172400, 7509000],
                          [4172400, 7509400], [4172000, 7509400]]],
          "centre_merc": [4172200, 7509200]}
OFF_MAP = {"slug": "nagatino", "name": "Нагатинская ул., влд. 3А/6", "status": "Планируемый",
           "okrug": "ЮАО", "district": "Нагатино", "area_ha": 14.0,
           "housing_gfa_sqm": 95180}
NO_DECISION = {"slug": "silent", "name": "Тихая ул., вл. 2", "status": "Планируемый",
               "okrug": "ЮВАО", "district": "Тихий", "area_ha": 3.0}


def registry(tmp_path: Path) -> krt_registry.KrtRegistry:
    reg = krt_registry.KrtRegistry(tmp_path)
    reg.map_dataset = lambda **_: {"sites": [dict(IN_MAP)], "bbox_merc": None}  # type: ignore[assignment]
    reg.catalogue = lambda **_: [dict(IN_MAP), dict(OFF_MAP), dict(NO_DECISION)]  # type: ignore[assignment]
    return reg


def put_outline(reg: krt_registry.KrtRegistry, slug: str, payload: dict) -> None:
    reg.outline_dir.mkdir(parents=True, exist_ok=True)
    (reg.outline_dir / f"{slug}.json").write_text(
        json.dumps({"schema_version": 1, "slug": slug, "retrieved_at": int(time.time()),
                    **payload}), encoding="utf-8")


DRAWN = {"rings_merc": [[[4185000, 7495000], [4185500, 7495000],
                         [4185500, 7495500], [4185000, 7495500]]],
         "centre_merc": [4185250, 7495250], "area_ha": 13.7, "problem": ""}


def test_a_site_missing_from_the_city_file_is_drawn_from_its_decision(tmp_path) -> None:
    reg = registry(tmp_path)
    put_outline(reg, "nagatino", DRAWN)
    out = reg.map_supplement()
    assert [site["slug"] for site in out["sites"]] == ["nagatino"]
    site = out["sites"][0]
    assert site["rings_merc"] == DRAWN["rings_merc"]
    # Подписан своим происхождением: официальный полигон и состав по документу
    # нарисованные одинаково выглядели бы одним источником.
    assert site["outline_source"] == "decision"
    assert site["name"] == OFF_MAP["name"] and site["area_ha"] == 14.0


def test_the_three_states_are_not_one(tmp_path) -> None:
    """«Не нарисовано» — это три разных ответа, и слитые они читаются как
    отсутствие площадки в реестре."""
    reg = registry(tmp_path)
    put_outline(reg, "nagatino", DRAWN)
    put_outline(reg, "silent", {"rings_merc": [], "centre_merc": None,
                                "problem": "в проекте решения нет кадастровых номеров участков"})
    out = reg.map_supplement()
    counts = out["counts"]
    assert counts == {"catalogue": 3, "in_map": 1, "drawn": 1, "unread": 0, "no_outline": 1}
    kinds = {gap["slug"]: gap["kind"] for gap in out["gaps"]}
    assert kinds == {"silent": "no_outline"}
    assert "кадастровых номеров" in out["gaps"][0]["reason"], "причина документа названа"


def test_an_unread_list_is_our_gap_and_not_the_documents_answer(tmp_path) -> None:
    reg = registry(tmp_path)
    out = reg.map_supplement()
    assert out["counts"]["unread"] == 2 and out["counts"]["no_outline"] == 0
    assert {gap["kind"] for gap in out["gaps"]} == {"unread"}
    # Именно по этому признаку фон берёт работу — не по словам причины.
    assert all("kind" in gap for gap in out["gaps"])


def test_the_map_file_not_being_read_is_not_no_sites(tmp_path) -> None:
    """Молчание источника нельзя показывать как его отрицательный ответ."""
    reg = registry(tmp_path)

    def boom(**_):
        raise OSError("сертификат")

    reg.map_dataset = boom  # type: ignore[assignment]
    out = reg.map_supplement()
    assert out["sites"] == [] and out["gaps"] == []
    assert "не прочитан" in out["problem"]


def test_the_match_rule_is_one_for_the_card_and_for_the_map(tmp_path) -> None:
    """Карточка спрашивает про одну площадку, карта — про весь каталог.
    Второе правило разошлось бы с первым молча."""
    reg = registry(tmp_path)
    # Имя в файле карты записано иначе — сокращением: карточка находит такую
    # площадку по адресу, значит и карта обязана считать её нарисованной.
    reg.map_dataset = lambda **_: {  # type: ignore[assignment]
        "sites": [dict(IN_MAP, name="Кунцевская улица, владение 1")], "bbox_merc": None}
    assert reg.map_lookup("in-map", IN_MAP["name"], dict(IN_MAP))["site"], "карточка нашла"
    out = reg.map_supplement()
    assert out["counts"]["in_map"] == 1, "карта обязана найти её тем же правилом"
    assert "in-map" not in {gap["slug"] for gap in out["gaps"]}


def test_the_background_fill_only_takes_what_is_not_read(tmp_path) -> None:
    reg = registry(tmp_path)
    put_outline(reg, "nagatino", DRAWN)
    asked: list[list[str]] = []

    def lookup(numbers):
        asked.append(list(numbers))
        return []

    # Уже прочитанную не перечитываем: перечень стоит обхода ЕГРН.
    assert reg.fill_outlines_in_background(["nagatino"], lookup=lookup) is False
    assert asked == []


def test_the_page_names_what_is_not_drawn() -> None:
    """Молча пропущенная площадка читается как её отсутствие в реестре."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    script = auctions_page()
    script = script[script.rindex("<script>") + len("<script>"):script.rindex("</script>")]
    start = script.index("function krtMapCoverage(")
    depth = 0
    for position in range(script.index("{", start), len(script)):
        if script[position] == "{":
            depth += 1
        elif script[position] == "}":
            depth -= 1
            if depth == 0:
                body = script[start:position + 1]
                break
    else:  # pragma: no cover — функция обязана быть целой
        raise AssertionError("krtMapCoverage не найдена")
    payload = {"supplement": {
        "counts": {"catalogue": 268, "in_map": 233, "drawn": 20, "unread": 10, "no_outline": 5},
        "gaps": [{"slug": "silent", "name": "Тихая ул., вл. 2", "kind": "no_outline",
                  "reason": "в проекте решения нет кадастровых номеров участков"}],
        "problem": ""}}
    body = ("function esc(v){return String(v)}\n" + body
            + f"\nconsole.log(krtMapCoverage({json.dumps(payload)},[]));")
    done = subprocess.run([node, "-e", body], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:600]
    text = done.stdout
    assert "268" in text and "233" in text
    for expected in ("20 нарисованы пунктиром", "10 ещё не прочитаны",
                     "5 не нарисованы"):
        assert expected in text, text
    assert "Тихая ул., вл. 2" in text, "ненарисованную называют поимённо"


def test_a_full_map_says_nothing_extra() -> None:
    """Строка о неполноте нужна там, где неполнота есть: постоянная приписка
    перестаёт читаться."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен")
    script = auctions_page()
    script = script[script.rindex("<script>") + len("<script>"):script.rindex("</script>")]
    start = script.index("function krtMapCoverage(")
    depth = 0
    for position in range(script.index("{", start), len(script)):
        if script[position] == "{":
            depth += 1
        elif script[position] == "}":
            depth -= 1
            if depth == 0:
                body = script[start:position + 1]
                break
    payload = {"supplement": {"counts": {"catalogue": 263, "in_map": 263, "drawn": 0,
                                         "unread": 0, "no_outline": 0},
                              "gaps": [], "problem": ""}}
    body = ("function esc(v){return String(v)}\n" + body
            + f"\nconsole.log(JSON.stringify(krtMapCoverage({json.dumps(payload)},[])));")
    done = subprocess.run([node, "-e", body], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[:600]
    assert json.loads(done.stdout) == ""

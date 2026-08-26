"""Свод источников себестоимости: один модуль, одни классы, одна база.

Слоёв было три — `statistics_feature`, `_v2`, `_v3`, — и каждый снимал
маршруты предыдущего. Живой набор приходилось выводить из порядка установки, а
два мёртвых рендерера страницы выглядели ровно так же настояще, как живой.
Здесь проверяется, что осталось ровно то, что работает, и что числа, у которых
есть хозяин в движке, взяты у него, а не объявлены вторично.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import developaid_statistics_page as page  # noqa: E402
import main_registry  # noqa: E402

core = main_registry.core

LIVE_ROUTES = {
    "/statistics",
    "/api/statistics/construction-cost",
    "/api/statistics/sources",
    "/api/statistics/index-sources",
    "/api/statistics/class-adjustments",
    "/api/statistics/cost-structure",
    "/api/statistics/cost-recommendation",
    "/api/statistics/normalized-matrix",
}


def _client() -> TestClient:
    app = FastAPI()
    page.install(app, core)
    return TestClient(app)


def test_module_installs_every_route_once_and_removes_nothing():
    """Маршрут ставится один раз: снимать с приложения нечего.

    Прежде установка шла лесенкой — v1 вешал семь маршрутов, v2 снимал три и
    вешал два, v3 снимал два и вешал один. Такой набор нельзя прочитать, его
    можно только выполнить.
    """
    app = FastAPI()
    page.install(app, core)
    paths = [route.path for route in app.routes
             if getattr(route, "path", "").startswith(("/statistics", "/api/statistics"))]
    assert sorted(paths) == sorted(LIVE_ROUTES)
    assert len(paths) == len(set(paths)), f"маршрут объявлен дважды: {paths}"
    assert "_remove_route" not in inspect.getsource(page), \
        "снятие чужого маршрута вернулось — значит вернулась и лесенка"


def test_every_route_answers():
    client = _client()
    for path in sorted(LIVE_ROUTES):
        params = {"region": "Москва"} if "construction-cost" in path else {}
        response = client.get(path, params=params)
        assert response.status_code == 200, f"{path} → {response.status_code}"


def test_classes_are_the_engine_classes_and_nothing_else():
    """Список классов — у движка, копии на странице нет.

    Класс, показанный в своде, но не существующий в расчёте, обещает
    настройку, которой нет: так на странице жил «Стандарт», которого в
    `PROJECT_CLASS_PRESETS` никогда не было.
    """
    options = page.class_options(core)
    assert [key for key, _ in options] == list(core.PROJECT_CLASS_PRESETS)
    assert [label for _, label in options] == \
        [preset["label"] for preset in core.PROJECT_CLASS_PRESETS.values()]

    text = _client().get("/statistics").text
    for key, label in options:
        assert f'value="{key}"' in text, f"класса {key} нет в форме"
        assert label in text
    assert "Стандарт" not in text


def line_hint(code: list[str]) -> str:
    return "своё отношение объявлено в модуле: " + "; ".join(
        line.strip() for line in code if "0.915" in line)


def test_building_area_ratio_is_the_engine_ratio():
    """Отношение общей площади здания к ГНС объявлено один раз — в движке.

    Модуль держал своё 0,915 «середина рабочего диапазона», движок — 0,90 из
    двух выгрузок ГлавАПУ. Ставка на общую площадь здания переводится к ГНС
    именно этим числом, и два разных под одним смыслом разошлись бы молча.
    """
    ratio = core.TEP_RATIOS["apartments"]["total_of_gns"]
    assert page.building_total_ratio(core) == ratio

    # Своей константы у модуля нет — число берётся у движка на каждом вызове.
    assert not hasattr(page, "BUILDING_TOTAL_TO_GBA")
    code = [line for line in inspect.getsource(page).splitlines()
            if "=" in line and not line.lstrip().startswith("#")]
    assert not [line for line in code if "0.915" in line], line_hint(code)

    payload = _client().get("/api/statistics/normalized-matrix").json()
    assert payload["building_total_ratio"] == ratio
    assert payload["areas"]["building_total_sqm"] == pytest.approx(
        payload["areas"]["gba_sqm"] * ratio)


def test_default_example_is_not_a_real_project():
    """Пустая форма подставляет условный пример, а не чей-то проект.

    Прежде на первом открытии подставлялась «Гродненская, 18» — реальный
    объект владельца — и её же метры стояли ссылкой «быстрая проверка».
    Демонстрационные числа не обязаны быть ничьими.
    """
    areas, example = page._areas(core, None, None, None, None)
    assert example is True
    assert areas["gba_sqm"] == page.EXAMPLE_AREAS["gba_sqm"]

    text = _client().get("/statistics").text
    assert "условный пример" in text
    assert "Гродненская, 18" not in text
    assert "Профсоюзная" not in text

    # Введённый ТЭП пример не подменяет.
    areas, example = page._areas(core, "22 032,9", "13710", "3629", "")
    assert example is False
    assert areas["above_ground_gns_sqm"] == pytest.approx(18403.9)


def test_underground_rate_is_declared_in_the_reference_file_only():
    """Ставка подземной части живёт в справочнике, а не заплаткой в коде.

    Правка 592 526 → 210 000 стояла тремя копиями: в загрузчике справочника и
    двумя заплатками поверх уже собранной матрицы и уже посчитанной
    рекомендации. Такую поправку негде обновлять, потому что копий три.
    """
    data = json.loads(Path("reference_data/statistics/developaid_cost_structure.json")
                      .read_text(encoding="utf-8"))
    source = next(row for row in data["sources"]
                  if row["source_id"] == "developaid-grodnenskaya-structure-2026-07")
    assert source["components"]["main_under"]["value_rub_m2"] == 210000.0

    import developaid_cost_structure as structure
    assert "210000" not in inspect.getsource(structure.load_cost_structure)

    payload = _client().get("/api/statistics/normalized-matrix").json()
    row = next(x for x in payload["rows"] if x["key"] == "main_under")
    assert row["aggregate"] == pytest.approx(210000.0)


def test_normalized_matrix_keeps_all_source_groups_and_their_grades():
    payload = _client().get("/api/statistics/normalized-matrix", params={
        "gba_sqm": "22032,9", "sellable_sqm": "13710", "underground_gns_sqm": "3629",
    }).json()
    labels = {group["label"] for group in payload["groups"]}
    assert {"CORE.XP", "Москомэкспертиза / НЦСМ", "АЦ Москвы / декларации",
            "СИС / ЕРЗ"} <= labels

    by_key = {row["key"]: row for row in payload["rows"]}

    def cell(key: str, label: str) -> dict:
        return next(x for x in by_key[key]["values"] if x["label"] == label)

    # СИС раскрывает ТУ, землю и совместную строку «сети + благоустройство»;
    # порознь сети и благоустройство он не даёт — и ячейки остаются пустыми.
    assert cell("technical_connection", "СИС / ЕРЗ")["grade"] == "C"
    assert cell("networks_landscaping", "СИС / ЕРЗ")["value"] is not None
    assert cell("land", "СИС / ЕРЗ")["value"] is not None
    assert cell("external_utilities", "СИС / ЕРЗ")["value"] is None
    assert cell("landscaping", "СИС / ЕРЗ")["value"] is None

    total = by_key["construction_capex"]
    assert total["n"] >= 4
    for label in ("Москомэкспертиза / НЦСМ", "АЦ Москвы / декларации"):
        assert cell("construction_capex", label)["grade"] == "C"


def test_page_shows_the_normalized_table_and_no_manual_building_area():
    response = _client().get("/statistics", params={
        "region": "Москва", "class": "business", "gba_sqm": "22 032,9",
        "sellable_sqm": "13710", "underground_gns_sqm": "3629",
        "above_ground_gns_sqm": "",
    })
    assert response.status_code == 200
    text = response.text
    assert "Приведённая таблица" in text
    assert "Наружные сети + благоустройство (совместно)" in text
    assert "Общая площадь здания</label>" not in text
    assert "18 403,9" in text   # наземная посчитана, а не спрошена
    assert "210,0" in text      # ставка подземной части из справочника


def test_internal_project_identity_never_reaches_a_public_surface():
    """Адрес собственного проекта — коммерческая информация, наружу не выходит.

    Страница /statistics и её API открыты без входа, и адрес внутреннего
    источника уже один раз утёк на пользовательскую поверхность (окно настроек
    классов, 26.08.2026 — решение владельца убрать). Сырые данные в
    reference_data остаются как есть; маскируется выдача: имя источника —
    «Внутренний проект DevelopAid», идентификаторы — детерминированный хэш.
    """
    client = _client()
    for path in sorted(LIVE_ROUTES):
        params = {"region": "Москва"} if "construction-cost" in path else {}
        text = client.get(path, params=params).text
        lowered = text.lower()
        assert "гродненск" not in lowered, f"{path}: адрес внутреннего проекта в выдаче"
        assert "grodnensk" not in lowered, f"{path}: идентификатор с адресом в выдаче"

    payload = client.get("/api/statistics/cost-structure").json()
    internal = [x for x in payload["sources"]
                if x.get("source_kind") == "internal_project"]
    assert internal, "внутренний источник пропал из матрицы вовсе"
    assert all(x["source"] == "Внутренний проект DevelopAid" for x in internal)
    assert all(str(x["source_id"]).startswith("developaid-internal-")
               for x in internal)


def test_aggregate_shows_the_spread_of_the_sources_behind_it():
    """N — это сколько источников ответило, а не насколько они согласны.

    За агрегатом строительного CAPEX стояли 90,7 и 265,8 тыс ₽/м² — втрое, —
    а подпись «N 4» читалась как согласие четырёх источников. Разброс входящих
    чисел печатается под агрегатом, когда он больше полутора раз.
    """
    payload = _client().get("/api/statistics/normalized-matrix").json()
    total = next(row for row in payload["rows"] if row["key"] == "construction_capex")
    assert total["n"] >= 4
    assert total["spread_low"] < total["aggregate"] < total["spread_high"]
    assert total["spread_ratio"] > page._SPREAD_WIDE

    text = _client().get("/statistics").text
    assert "spread wide" in text, "широкий разброс не помечен"
    assert "N — это сколько источников ответило" in text

    # Строка с одним источником разброса не печатает — печатает «1 источник».
    alone = next(row for row in payload["rows"] if row["n"] == 1)
    assert _aggregate_note_of(alone) == '<div class="small">1 источник</div>'


def _aggregate_note_of(row: dict) -> str:
    return page._aggregate_note(row)

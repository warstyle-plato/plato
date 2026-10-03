"""ОКС и ЗУ в контуре КРТ находятся по карте НСПД, а не только по перечню решения.

«Для любой площадки КРТ найти ОКС и ЗУ по контуру КРТ и считать по ним снос и
выкуп» (владелец, 29.09.2026). До этого здания площадки мы знали только из
перечня проекта решения: не прочитан перечень — зданий в контуре не видно, и
снос с выкупом считались по тому, что успел назвать документ.

Проверяется на сохранённом ответе НСПД (`fixtures/nspd_contour_krt_sample.json`),
без сети: настоящий движок разбирает ответ GetFeatureInfo, модуль режет контур
рамками, сверяет с перечнем, считает снос, а выкуп считает тот же
`_cached_cadastral_buyout`, что и денежная нагрузка.

Запуск: python3 -m pytest tests/test_krt_contour_objects.py -q
"""

from __future__ import annotations

import copy
import io
import json
import sys
import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402
from auction_search import krt_contour_objects as contour  # noqa: E402
from auction_search import krt_investment_score  # noqa: E402

SAMPLE = json.loads((ROOT / "tests" / "fixtures" / "nspd_contour_krt_sample.json")
                    .read_text(encoding="utf-8"))
RINGS = SAMPLE["contour_rings_merc"]
DECISION = SAMPLE["decision"]


def _feature_bounds(feature: dict) -> tuple[float, float, float, float]:
    points = [p for ring in feature["geometry"]["coordinates"] for p in ring]
    south, west = contour.merc_to_wgs84(min(p[0] for p in points), min(p[1] for p in points))
    north, east = contour.merc_to_wgs84(max(p[0] for p in points), max(p[1] for p in points))
    return west, south, east, north


def _portal(asked: list | None = None, fail_layers: tuple[int, ...] = ()):
    """НСПД из образца: слой и рамка — из адреса запроса, как у настоящего портала."""
    def fetch_json(url: str, **_kwargs):
        layer = int(url.split("/aeggis/v3/")[1].split("/")[0])
        query = dict(urllib.parse.parse_qsl(url.split("?", 1)[1]))
        west, south, east, north = (float(v) for v in query["BBOX"].split(","))
        if asked is not None:
            asked.append(layer)
        if layer in fail_layers:
            raise core.HTTPException(status_code=502, detail="Сервис НСПД: Forbidden")
        features = []
        for feature in SAMPLE["layers"][str(layer)]["features"]:
            w, s, e, n = _feature_bounds(feature)
            if w <= east and e >= west and s <= north and n >= south:
                features.append(feature)
        return {"type": "FeatureCollection", "features": copy.deepcopy(features)}
    return fetch_json


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(core, "_nspd_screen_blocked_until", 0.0)
    monkeypatch.setattr(core, "_nspd_screen_failures", 0)
    monkeypatch.delenv("CORE_API_URL", raising=False)
    monkeypatch.setattr(core, "_MO_CALC_API_URL", "")


def _collected(monkeypatch, **kwargs):
    monkeypatch.setattr(core, "_land_fetch_json", _portal(kwargs.pop("asked", None),
                                                          kwargs.pop("fail", ())))
    return core._land_contour_objects(RINGS) if not kwargs else contour.collect(
        RINGS, core._nspd_layer_in_bounds, **kwargs)


def _by_number(result: dict) -> dict:
    return {row["cadastral_number"]: row for row in result["objects"]}


def test_a_building_outside_the_list_but_inside_the_contour_is_found(monkeypatch):
    result = _collected(monkeypatch)
    rows = _by_number(result)
    # Здание, которого перечень решения не называет, найдено картой.
    assert "77:05:0001001:1002" not in DECISION["cadastral_numbers"]
    assert rows["77:05:0001001:1002"]["kind"] == "building"
    assert rows["77:05:0001001:1002"]["share"] == pytest.approx(1.0)
    assert rows["77:05:0001001:1002"]["area_sqm"] == 2300.0
    assert rows["77:05:0001001:1002"]["cadastral_value_rub"] == 70_000_000.0
    assert rows["77:05:0000000:5001"]["kind"] == "structure"
    # Сосед, задевший контур краем, — на границе, а не «в контуре».
    assert rows["77:05:0001001:12"]["share"] < contour.IN_CONTOUR_SHARE

    rec = contour.reconcile(result["objects"], DECISION)
    assert set(rec["both"]) == {"77:05:0001001:10", "77:05:0001001:1001", "77:05:0001001:1003"}
    assert "77:05:0001001:1002" in rec["contour_only"]
    assert "77:05:0001001:11" in rec["contour_only"]
    assert rec["list_only"] == ["77:05:0001001:1004"]
    assert rec["border"] == ["77:05:0001001:12"]
    assert not result["failures"] and not result["problem"]


def test_a_portal_refusal_is_named_not_an_empty_contour(monkeypatch):
    result = _collected(monkeypatch, fail=(36049,))
    assert result["failures"] and "Forbidden" in result["problem"]
    assert not any(row["kind"] == "building" for row in result["objects"])


def test_a_capped_answer_splits_the_frame_and_says_when_it_is_still_incomplete(monkeypatch):
    asked: list = []
    result = _collected(monkeypatch, asked=asked, cap=2, max_depth=1)
    # Рамка, отдавшая потолок, делится: запросов больше, чем рамок × слоёв.
    assert result["requests"] > result["cells"] * len(contour.LAYERS)
    assert result["truncated"], "урезанный ответ назван, а не выдан за полный"


def test_demolition_follows_the_decision_and_names_the_assumption(monkeypatch):
    result = _collected(monkeypatch)
    dem = contour.demolition(result["objects"], DECISION)
    # 1001 — снос по решению, площадь решения 1500 (а не 1480 ЕГРН);
    # 1002 — в контуре, решение молчит → допущение, 2300;
    # 1003 — сохранение, не сносится; 1004 — снос по решению, в контуре не найден.
    assert dem["area_sqm"] == pytest.approx(1500 + 2300 + 700)
    assert (dem["objects"], dem["by_decision"], dem["assumed"]) == (3, 2, 1)
    assert dem["label"] == "контур КРТ, 3 ОКС"
    assert any("допущ" in row["basis"] for row in dem["rows"]
               if row["cadastral_number"] == "77:05:0001001:1002")
    assert not any(row["counted"] for row in dem["rows"]
                   if row["cadastral_number"] == "77:05:0001001:1003")
    assert dem["assumptions"] and "решение не называет" in dem["assumptions"][0]
    # Сооружение (кабельная линия) в площадь сноса не идёт.
    assert all(row["cadastral_number"] != "77:05:0000000:5001" for row in dem["rows"])


def test_a_manual_demolition_area_is_not_overwritten():
    summary = {"area_sqm": 4500.0, "label": "контур КРТ, 3 ОКС"}
    # Пусто — ставится с происхождением.
    auto = contour.apply_demolition({"demolition_area_sqm": 0.0}, summary)
    assert auto["demolition_area_sqm"] == 4500.0
    assert auto["_demolition_source"]["by"] == "контур КРТ, 3 ОКС"
    # Прежнее автоматическое число (решение) — перекрывается контуром.
    decision = {"demolition_area_sqm": 1250.0,
                "_demolition_source": {"value": 1250.0, "kind": "krt_decision", "by": "решение"}}
    assert contour.apply_demolition(decision, summary)["demolition_area_sqm"] == 4500.0
    # Вписанное руками — без отметки или с отметкой другого числа — не трогается.
    manual = contour.apply_demolition({"demolition_area_sqm": 999.0}, summary)
    assert manual["demolition_area_sqm"] == 999.0 and "_demolition_source" not in manual
    assert "вручную" in manual["_demolition_source_skipped"]["reason"]
    edited = {"demolition_area_sqm": 3000.0,
              "_demolition_source": {"value": 4500.0, "kind": "krt_contour", "by": "контур"}}
    assert contour.apply_demolition(edited, summary)["demolition_area_sqm"] == 3000.0


def _egrn_lookup(numbers):
    """ЕГРН по номеру — из того же образца: собственник и стоимость объекта."""
    features = [f for layer in SAMPLE["layers"].values() for f in layer["features"]]
    by_number = {f["properties"]["options"]["cad_num"]: f for f in features}
    out = []
    for number in numbers:
        feature = by_number.get(number)
        if feature is None:
            out.append({"found": False, "cadastral_number": number,
                        "note": "в ЕГРН по этому номеру сведений не найдено"})
            continue
        out.append(core._normalize_nspd_feature(feature))
    return out


def test_buyout_gives_moscow_zero_with_a_reason_and_names_unknown_owners(monkeypatch, tmp_path):
    result = _collected(monkeypatch)
    numbers = contour.buyout_numbers(result["objects"], DECISION)
    assert "77:05:0000000:5001" not in numbers, "сети не выкупаются"
    state = {}
    for _ in range(10):
        state = krt_investment_score._cached_cadastral_buyout(
            {"slug": "sample"}, numbers, _egrn_lookup)
        if not state.get("pending"):
            break
    rows = {row["cadastral_number"]: row for row in state["rows"]}
    city = rows["77:05:0001001:1002"]
    assert city["owner"] == "moscow" and city["counted_rub"] == 0.0
    assert "Москвы" in city["reason"]
    unknown = rows["77:05:0001001:11"]
    # «Не определён собственник» — не ноль.
    assert unknown["owner"] == "unknown" and unknown["counted_rub"] is None
    assert "77:05:0001001:11" in state["unknown_numbers"]
    assert state["available"] is False
    assert rows["77:05:0001001:10"]["reason"] == "кадастровая стоимость, не цена сделки"
    # Сумма по доказанным: участок 10 (100 млн), здания 1001 (50) и 1003 (30).
    assert state["known_paid_mln"] == pytest.approx(180.0)


def test_the_card_view_reads_the_disk_and_one_buyout(monkeypatch):
    monkeypatch.setattr(core, "_land_fetch_json", _portal())
    contour.gather("sample", find_site=lambda: {"rings_merc": RINGS, "source": "образец"},
                   contour_objects=core._land_contour_objects, requirements=DECISION,
                   lookup=_egrn_lookup, buyout=krt_investment_score._cached_cadastral_buyout)
    view = contour.view("sample", DECISION, krt_investment_score._cached_cadastral_buyout)
    assert view["available"] and view["demolition"]["area_sqm"] == pytest.approx(4500)
    assert view["buyout"]["basis"] == "кадастровая стоимость, не цена сделки"
    assert view["buyout"]["moscow_zero_count"] == 1
    assert view["counts"]["building"] == 3 and view["counts"]["land"] == 2


def test_render_asks_the_core_instead_of_the_portal(monkeypatch):
    monkeypatch.setenv("CORE_API_URL", "https://core.example")
    sent = {}

    def post(url, payload, timeout):
        sent.update(url=url, payload=payload)
        return {"objects": [], "requests": 0}

    monkeypatch.setattr(core, "_core_post", post)
    monkeypatch.setattr(core, "_land_fetch_json",
                        lambda *a, **k: pytest.fail("Render не ходит в НСПД сам"))
    core._land_contour_objects(RINGS)
    assert sent["url"] == "https://core.example/land/contour-objects"
    assert sent["payload"] == {"rings_merc": RINGS}


def test_screening_takes_the_contour_demolition_into_the_model(monkeypatch):
    from auction_search.krt_screening import build_krt_model_screening
    from test_krt_screening import PROJECT, _market

    monkeypatch.setattr(core, "_land_fetch_json", _portal())
    contour.gather(PROJECT["slug"], find_site=lambda: {"rings_merc": RINGS},
                   contour_objects=core._land_contour_objects, requirements=DECISION,
                   lookup=None)
    result = build_krt_model_screening(PROJECT, _market(680_000), core,
                                       requirements=DECISION)
    inputs = result["model_inputs"]["inputs"]
    assert inputs["demolition_area_sqm"] == pytest.approx(4500)
    assert inputs["_demolition_source"] == {"value": 4500.0, "by": "контур КРТ, 3 ОКС",
                                            "kind": "krt_contour"}
    assert any("Снос по контуру КРТ" in item for item in result["exclusions"])


def test_the_book_and_the_engine_agree_on_the_contour_demolition():
    """Одно число: вводная из контура → движок → книга v4, строка CAPEX «Снос»."""
    openpyxl = pytest.importorskip("openpyxl")
    from test_book_interest_horizon_follows_the_engine import BASE, tep_of_a_real_project
    from xlsx_eval import Evaluator

    inputs = contour.apply_demolition({**BASE, "demolition_area_sqm": 0.0,
                                       "demolition_cost_th_per_sqm": 13.5},
                                      {"area_sqm": 4500.0, "label": "контур КРТ, 3 ОКС"})
    engine = core.build_operating_model(dict(inputs), tep_of_a_real_project(), [])
    engine_mln = engine["capex_amounts"]["demolition"] / 1e6
    assert engine_mln == pytest.approx(4500 * 13.5 / 1000)
    content, _, _ = core.build_project_workbook(inputs, tep_of_a_real_project(), [], {},
                                                project_name="П")
    sys.setrecursionlimit(400000)
    book = Evaluator(openpyxl.load_workbook(io.BytesIO(content)))
    assert book.cell("CAPEX", "B36") == pytest.approx(engine_mln, rel=1e-6)


def test_the_inputs_page_names_where_the_demolition_area_came_from():
    """Страница вводных: число контура подписано, исправленное — уже ручное."""
    from page_blocks import run_json

    out = run_json(
        "let inputs={demolition_area_sqm:4500,"
        "_demolition_source:{value:4500,by:'контур КРТ, 3 ОКС',kind:'krt_contour'}};",
        "const a=classFieldUnitText('demolition_area_sqm','м²');"
        "inputs.demolition_area_sqm=3000;"
        "const b=classFieldUnitText('demolition_area_sqm','м²');"
        "console.log(JSON.stringify([a,b]));")
    assert "контур КРТ, 3 ОКС" in out[0]
    assert out[1] == "м²"


def test_the_card_lists_contour_objects_and_says_what_is_not_counted():
    """Карточка КРТ: настоящий `renderContour` над ответом маршрута."""
    from auction_search.krt_investment_card import krt_investment_card_page
    from page_blocks import run_json

    view = {
        "available": True, "in_contour_share": 0.5,
        "objects": [{"cadastral_number": "77:05:0001001:1002", "kind": "building",
                     "share": 1.0, "area_sqm": 2300, "cadastral_value_rub": 7e7}],
        "counts": {"building": 1},
        "reconcile": {"both": [], "contour_only": ["77:05:0001001:1002"],
                      "list_only": ["77:05:0001001:1004"], "border": [], "no_shape": [],
                      "listed_available": True},
        "demolition": {"area_sqm": 2300, "label": "контур КРТ, 1 ОКС", "assumptions": [],
                       "rows": [{"cadastral_number": "77:05:0001001:1002", "counted": True,
                                 "basis": "судьбу решение не называет — считаем под снос (допущение)"}]},
        "buyout": {"available": False, "moscow_zero_count": 1,
                   "unknown_numbers": ["77:05:0001001:11"],
                   "rows": [{"cadastral_number": "77:05:0001001:1002", "owner": "moscow",
                             "value_rub": 7e7, "counted_rub": 0}],
                   "reason": "Выкуп не собран полностью"},
    }
    html = run_json(
        "const EL={innerHTML:''};const $=()=>EL;",
        f"renderContour({json.dumps(view, ensure_ascii=False)});"
        "console.log(JSON.stringify(EL.innerHTML));",
        page=krt_investment_card_page("sample"))
    assert "Только в контуре" in html and "77:05:0001001:1002" in html
    assert "Только в перечне" in html and "77:05:0001001:1004" in html
    assert "Москва — 0" in html and "выкупать не надо" in html
    assert "Не определён собственник" in html and "77:05:0001001:11" in html
    assert "не цена сделки" in html

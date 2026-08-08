import pytest
from fastapi.testclient import TestClient

import main_registry
from mpt_extension import (
    _MENU_TEXT,
    _MPT_FRAGMENT,
    _append_query,
    _main_menu_with_mpt,
    inject_mpt_panel,
)


@pytest.fixture(scope="module")
def client():
    return TestClient(main_registry.app, raise_server_exceptions=False)


def test_query_keeps_existing_session_and_adds_mpt_section():
    url = _append_query("https://example.test/app?session=abc", section="mpt")
    assert "session=abc" in url
    assert "section=mpt" in url


def test_mpt_is_added_only_to_main_reply_keyboard():
    main = {"keyboard": [[{"text": "Посчитать ВРИ и ТЭП"}]], "resize_keyboard": True}
    updated = _main_menu_with_mpt(main)
    assert updated is not main
    assert updated["keyboard"][-1][0]["text"] == _MENU_TEXT
    assert _MENU_TEXT not in str(main)

    temporary = {"keyboard": [[{"text": "Да"}], [{"text": "Нет"}]]}
    assert _main_menu_with_mpt(temporary) is temporary


def test_mpt_menu_is_not_duplicated():
    markup = {"keyboard": [[{"text": "Посчитать ВРИ и ТЭП"}], [{"text": _MENU_TEXT}]]}
    assert _main_menu_with_mpt(markup) is markup


def test_page_injection_is_idempotent():
    source = "<html><body><main>ВРИ</main></body></html>"
    once = inject_mpt_panel(source)
    twice = inject_mpt_panel(once)
    assert 'id="mpt-benefit-template"' in once
    assert once == twice


# --- пропорция по графам и квартал Кзатр --------------------------------------

def test_the_panel_asks_for_areas_not_a_checkbox():
    """Примечание к таблице приложения 3 требует пропорции по площади. Флажок
    «несколько ВРИ» её дать не мог: он только поднимал порог до 5 000 м², а
    Кмест оставался коэффициентом выбранного типа."""
    assert 'id="mpt-area-business"' in _MPT_FRAGMENT
    assert 'id="mpt-area-social"' in _MPT_FRAGMENT
    assert 'id="mpt-mixed"' not in _MPT_FRAGMENT


def test_the_quarter_field_stays_empty_by_default():
    """Кзатр пересматривается с первого числа каждого квартала. Подставленный
    текущий квартал делал бы прошлогоднее число похожим на действующее."""
    assert 'id="mpt-kzatr-quarter"' in _MPT_FRAGMENT
    assert "q('mpt-kzatr-quarter').placeholder" in _MPT_FRAGMENT


def test_the_split_reaches_the_api(client):
    response = client.post("/api/mpt/calculate", json={
        "category": "office", "district": "Ясенево", "ttk_position": "outside",
        "area_sqm": 10_000, "area_business_sqm": 6_000, "area_social_sqm": 4_000,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["kmest"] == pytest.approx((6_000 * 0.75 + 4_000 * 0.3) / 10_000)
    assert [row["column"] for row in data["kmest_mix"]] == ["business", "social"]


def test_the_old_mixed_use_flag_is_refused_not_ignored(client):
    """Сохранённый проект со старым флагом должен получить объяснение, а не
    молча посчитаться по одной графе."""
    response = client.post("/api/mpt/calculate", json={
        "category": "office", "district": "Ясенево", "ttk_position": "outside",
        "area_sqm": 10_000, "mixed_use": True,
    })
    assert response.status_code == 400
    assert "area_business_sqm" in response.json()["detail"]


def test_the_meta_names_the_order_behind_the_kzatr(client):
    meta = client.get("/api/mpt/meta").json()
    assert meta["kzatr_base"] == 138.11132
    assert "ДИПП-ПР-35/25" in meta["kzatr_source"]
    assert meta["current_quarter"]

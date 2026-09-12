from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source() -> str:
    return (ROOT / "frontend_v2" / "entry_layout.js").read_text(encoding="utf-8")


def test_v2_has_scenarios_tab_before_sensitivity():
    source = _source()

    assert 'data-view="scenarios"' in source
    assert "sensitivityDesktop.before(button)" in source
    assert "sensitivityMobile.before(button)" in source
    assert "view-scenarios" in source
    assert "Класс проекта и сценарии" in source


def test_scenarios_are_calculated_by_the_same_v2_engine():
    source = _source()

    assert "fetch('/api/v2/form'" in source
    assert "fetch('/api/v2/calculate'" in source
    assert "payloadFor(key, false)" in source
    assert "window.DevelopAidV2.calculateProject(payloadFor(key, true))" in source
    assert "scenario_revenue_multiplier" in source
    assert "scenario_cost_multiplier" in source


def test_project_classes_are_read_from_the_live_engine_not_duplicated():
    source = _source()

    assert "const PROJECT_CLASS_PRESETS=" in source
    assert "scenarioState.classPresets = JSON.parse(match[1])" in source
    assert "Object.keys(preset).filter((field) => field !== 'label')" in source
    assert "draft.inputs.project_class = key" in source
    # Business/elite prices must not be copied into the v2 script.
    assert "650" not in source
    assert "300 тыс." not in source


def test_land_section_reuses_existing_egrn_screening_and_map_sources():
    source = _source()

    assert "Участок и ограничения" in source
    assert "Живое окружение" in source
    assert "'/land/lookup'" in source
    assert "/land/screening?cad=" in source
    assert "/land/map-image?bbox=" in source
    assert "/land/basemap?bbox=" in source
    assert "contour_merc" in source
    assert "outline_merc" in source
    assert "coverage_pct" in source


def test_surroundings_map_is_interactive_not_a_static_export():
    source = _source()

    assert "data-map-zoom=\"in\"" in source
    assert "data-map-zoom=\"out\"" in source
    assert "pointerdown" in source
    assert "pointerup" in source
    assert "addEventListener('wheel'" in source
    assert "© OpenStreetMap" in source

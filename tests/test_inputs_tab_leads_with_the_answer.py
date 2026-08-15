"""Результат стоит под действием, а не в конце карточки.

Человек вводит кадастровый номер и ждёт ТЭП. В разметке между сведениями
ЕГРН и посчитанным ТЭП стояли параметры Подмосковья и загрузка готового
файла, и ответ оказывался в самом низу — экраном ниже кнопки, которой его
запросили. Порядок в разметке был порядком, в котором её писали.

Заодно предупреждения перестали тонуть. Шесть абзацев справки о том, как
читается файл, печатались на каждый импорт в одном списке с
«ВНИМАНИЕ: продаваемая площадь не прочитана»; предупреждение, которое видно
всегда, не видно никогда. Справка — отдельно и по требованию, предупреждения
— только когда есть о чём предупреждать.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core
PAGE = core.PAGE


def at(marker: str) -> int:
    index = PAGE.find(marker)
    assert index > 0, f"не найдено: {marker}"
    return index


def test_the_calculated_tep_follows_the_registry_data():
    """Между ЕГРН и результатом не должно стоять ничего постороннего."""
    registry = at('id="cadastralPreview"')
    result = at('id="glavapuPreview"')
    fallback = at('class="import-fallback"')
    assert registry < result < fallback


def test_the_moscow_region_parameters_live_on_the_tep_tab():
    """Два поля из шести — та же плотность и та же площадь участка, что на
    вкладке ТЭП. Рядом видно, что правится одно и то же."""
    tep_tab = at('<div id="tep" class="panel">')
    inputs_tab = at('<div id="inputs" class="panel active">')
    params = at('id="moParamsBox"')
    assert inputs_tab < tep_tab < params


def test_the_moscow_region_result_stays_where_it_was_asked_for():
    """Параметры уехали, результат остался: считают по кадастровому номеру на
    «Вводных», там же его и ждут."""
    inputs_tab = at('<div id="inputs" class="panel active">')
    tep_tab = at('<div id="tep" class="panel">')
    preview = at('id="moPreview"')
    assert inputs_tab < preview < tep_tab


def test_the_upload_is_a_fallback_not_the_first_step():
    """Загрузка готового файла свёрнута: она для тех, у кого файл уже на
    руках, и не должна разрывать «ввёл участок — получил ТЭП»."""
    fallback = PAGE[at('class="import-fallback"'):]
    fallback = fallback[:fallback.index("</details>")]
    assert "<summary>" in fallback
    assert 'id="glavapuFile"' in fallback
    assert 'id="presetFile"' in fallback
    # Готовые примеры уехали в «Мои проекты» — здесь разбирают принесённый файл.
    assert 'id="serverPresetSelect"' not in fallback


def test_the_status_line_is_not_hidden_with_the_upload():
    """В строку статуса пишет и автоматический расчёт по кадастру, и разбор
    файла. Спрятать её вместе с загрузкой — потерять ответ на главный путь."""
    status = at('id="glavapuStatus"')
    fallback = at('class="import-fallback"')
    assert status < fallback


# --- предупреждения ----------------------------------------------------------

def test_the_boilerplate_is_no_longer_a_warning():
    """Справка печаталась всегда и в том же списке, что и настоящие беды."""
    result = core.parse_glavapu_xlsx(_workbook(), "тест.xlsx")
    assert result["warnings"] == []
    assert any("нормализованы по русскому формату" in note
               for note in result["notes"])


def test_a_real_problem_is_still_a_warning():
    """ГНС есть, продаваемой площади нет: расходы посчитаются полностью,
    выручки не будет, и проект окажется убыточным по несуществующей причине."""
    result = core.parse_glavapu_xlsx(_workbook("н/д"), "тест.xlsx")
    assert any("продаваемая площадь" in warning for warning in result["warnings"])
    assert all("нормализованы" not in warning for warning in result["warnings"])


def test_the_page_hides_an_empty_warning_block():
    assert "glavapuWarnings.style.display=gw.length?'block':'none'" in PAGE
    assert "data.notes" in PAGE


def _workbook(apartment_area: str = "160,0") -> bytes:
    """Настоящий файл ГлавАПУ: жилая застройка есть, строка 10 — под вопросом."""
    rows = [
        ["1", "Площадь территории", "га", "10,58"],
        ["7.1", "СПП жилая", "тыс. кв. м", "250,0"],
        ["9.1.1", "НП жилая", "тыс. кв. м", "220,0"],
        ["10", "Площадь квартир", "тыс. кв. м", apartment_area],
    ]
    return core._build_glavapu_xlsx_from_rows(rows, [["Район", "Даниловский"]])

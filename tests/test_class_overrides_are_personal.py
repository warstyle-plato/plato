"""Личные значения классов: перекрышка поверх общей базы, живёт на ядре.

База классов одна и общая (решение владельца, 24.08.2026), а свои значения
человек держит перекрышкой: они применяются при выборе класса вместо базы, но
отклонения проекта в PDF и книгах по-прежнему считаются от общей базы. Хранится
только дельта — равное базе значение не пишется, чтобы файл не костенел, когда
база меняется выпуском. Поля валидируются по самому пресету: списка-копии нет.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_PROJECTS_DIR", tmp_path / "projects")


def test_only_positive_deltas_from_known_fields_are_kept(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    base = float(core.PROJECT_CLASS_PRESETS["comfort"]["main_above_th_per_sqm"])
    saved = core.class_overrides_write(555, {
        "comfort": {
            "main_above_th_per_sqm": base + 90,   # настоящая дельта
            "apartment_price_th": core.PROJECT_CLASS_PRESETS["comfort"]["apartment_price_th"],  # равно базе
            "parking_price_th": -1,                # не положительное
            "made_up_field": 100,                  # нет в пресете
            "label": "Комфорт",                   # подпись — не ставка
        },
        "no_such_class": {"main_above_th_per_sqm": 200},
    })
    assert saved["overrides"] == {"comfort": {"main_above_th_per_sqm": base + 90}}
    assert core.class_overrides_read(555) == saved["overrides"]
    # Чужой владелец своих перекрышек не видит.
    assert core.class_overrides_read(556) == {}


def test_returning_to_the_base_removes_the_file(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    core.class_overrides_write(555, {"comfort": {"main_above_th_per_sqm": 200}})
    path = core._class_overrides_path(555)
    assert path.exists()
    # Все значения вернулись к базе — хранить нечего, файл уходит целиком.
    core.class_overrides_write(555, {"comfort": {
        "main_above_th_per_sqm": core.PROJECT_CLASS_PRESETS["comfort"]["main_above_th_per_sqm"]}})
    assert not path.exists()
    assert core.class_overrides_read(555) == {}


def test_broken_file_reads_as_empty_not_as_error(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    path = core._class_overrides_path(555)
    path.write_text("не json", encoding="utf-8")
    assert core.class_overrides_read(555) == {}


def test_the_page_applies_personal_values_and_saves_them_on_the_core():
    page = core.PAGE
    # Применение класса берёт эффективное значение: перекрышка ?? база.
    assert "inputs[k]=classValue(key,k)" in page
    # Все колонки классов — редактируемые, правка уходит на ядро тем же
    # projectsCall, что и проекты (session + key подставляются сами).
    assert "setClassBase(" in page
    assert "'/classes/overrides/get'" in page
    assert "'/classes/overrides/save'" in page
    # Отклонение проекта в окне меряется от ОБЩЕЙ базы — как на сервере.
    assert "classBase(cur,k)" in page
    # Без входа честно говорится, что правка не переживёт перезагрузку.
    assert "сохраняются после входа через бота" in page


def test_the_dialog_puts_the_consensus_next_to_the_rate_it_belongs_to():
    """Свод стоит строкой под ставкой, а не отдельной таблицей рядом.

    Первая версия выгружала в окно таблицу из тринадцати статей и внутренние
    правила модуля: связать это со ставками класса читатель не мог (замечание
    владельца, 26.08.2026). Число обязано стоять там, где ставка, к которой
    оно относится; методика словами — за кнопкой «Как считаются класс и
    сценарий»; таблица источников — на странице «Статистика».
    """
    page = core.PAGE
    # Свод спрашивается у модуля «Статистика» — у числа не бывает двух жизней.
    assert "/api/statistics/cost-recommendation" in page
    # Строка свода — в самой таблице классов, по числу на класс, с подстановкой.
    assert "classStatsRow" in page
    assert "свод „Статистики“" in page
    assert "Клик подставит это число классу" in page
    # Внутренние правила модуля в окно не выгружаются: они для нас, а не для
    # читателя, и как объяснение не работают.
    assert "d.rules" not in page
    # Неответ модуля называется вслух, а не выглядит отсутствием свода.
    assert "не загрузился" in page
    # Дорога к полной картине названа.
    assert 'href="/statistics"' in page


def test_the_class_button_explains_where_the_rates_come_from():
    """«Как считаются класс и сценарий» отвечает и про происхождение ставок."""
    overlay = (Path(__file__).resolve().parent.parent
               / "ia_preview" / "assets" / "overlay.js").read_text(encoding="utf-8")
    assert "Как считаются класс и сценарий" in overlay
    assert "Откуда себестоимость СМР" in overlay
    assert "к её базе площади" in overlay
    assert "/statistics" in overlay

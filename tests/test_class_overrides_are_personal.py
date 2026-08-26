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


def test_the_dialog_shows_the_statistics_consensus_not_a_local_copy():
    page = core.PAGE
    # Свод строительной себестоимости спрашивается у модуля «Статистика» —
    # у числа не бывает двух жизней, своей таблицы источников страница не держит.
    assert "/api/statistics/cost-recommendation" in page
    assert "renderClassStats" in page
    # Методика — нормализация и агрегирование — объяснена человеку словами.
    assert "нормализована к своей базе площади" in page
    assert "взвешенное среднее допущенных источников" in page
    # Правила методики приезжают из ответа модуля, а не копией в разметке.
    assert "(d.rules||[])" in page
    # Неответ модуля называется вслух, а не выглядит пустым сводом.
    assert "Свод не загрузился" in page

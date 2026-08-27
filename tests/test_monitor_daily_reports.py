"""Ежедневные отчёты с площадки: разбор живого текста, численность, живость.

КС показывает темп с опозданием на месяц; ежедневник говорит, что происходит
сегодня. Текст приходит из мессенджера с кривой нумерацией и десятью
написаниями «Итр- 3чел.» — разбор проверяется на настоящем отчёте владельца
(27.08.2026), а не на причёсанном примере.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import developaid_monitor as monitor  # noqa: E402
import developaid_monitor_daily as daily  # noqa: E402
import developaid_monitor_page as monitor_page  # noqa: E402
import developaid_monitor_scenarios as scenarios  # noqa: E402

REPORT = """Добрый день.
1. СПМ : Итр- 3чел., Рабочие - 6 чел.
2. НУР:ИТР- 11чел.;
Рабочие - 54чел.;
3. Клодо ( кладка) - Итр- 2 чел.Рабочие - 12чел.
5. Бизнес Инжиниринг ( отделка тех.пом) - Итр - 1 чел., Рабочие - 5чел.
6. Сталко Итр - 3 чел., Рабочие-31 чел.
7. Термоформ ( ИТП)  Итр-1 , Рабочие- 3чел.
8. Альтитьюд  Итр- 2 , Рабочие- 9чел.
9.Центринжиниринг (вк) - Итр-1. Рабочие. - 7 чел.
10. Стройсервис ( кровля) Итр- 1 , Рабочие- 2чел.
По работам:
1. НУР:
Корпус 3
Устройство опалубки ПП 24 эт.(1,2зах)
Армирование и бетонирование  лестницы - 3 м3
Демонтаж БК#1 и БК#2
4. Клодо( кладка):
Устройство стен из пеноблока
8.Альтитьюд- Нанесение изоляции и монтаж ветиляции на Корпусе 1 и 2 со 2 по 13эт..
Поставка :
Фасадная минвата- 1маш.
Вывоз:
Пристежка крана БК#1- 1 маш."""


def test_the_parser_survives_the_real_messenger_text():
    parsed = daily.parse_daily_report(REPORT)
    # В отчёте девять подрядчиков при нумерации до десяти: пункт 4 пропущен.
    # Число берётся из разобранных строк, а не из последней цифры списка.
    assert len(parsed["contractors"]) == 9
    assert parsed["itr_total"] == 25
    assert parsed["workers_total"] == 129
    # Перенос «Рабочие - 54» на свою строку — продолжение НУР, а не «без имени».
    nur = next(c for c in parsed["contractors"] if c["name"] == "НУР")
    assert nur == {"name": "НУР", "itr": 11, "workers": 54}
    assert not any(c["name"] == "без имени" for c in parsed["contractors"])
    # Работы держат подрядчика; заголовок «4. Клодо( кладка):» — не работа.
    lines = {w["line"] for w in parsed["works"]}
    assert "Устройство опалубки ПП 24 эт.(1,2зах)" in lines
    assert "Устройство стен из пеноблока" in lines
    kladka = next(w for w in parsed["works"] if "пеноблока" in w["line"])
    assert "Клодо" in kladka["contractor"]
    # Строка без двоеточия и без номера подрядчика («8.Альтитьюд- …») —
    # работа, а не заголовок: текст живой, точной формы у него нет.
    assert any("изоляции" in w["line"] for w in parsed["works"])
    assert parsed["supplies"] == ["Фасадная минвата- 1маш."]
    assert parsed["removals"] == ["Пристежка крана БК#1- 1 маш."]
    assert parsed["unparsed"] == []


@pytest.fixture()
def project_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    return tmp_path


def test_store_and_summary_with_gap(project_dir):
    daily.store_daily_report("Тест", REPORT, "2026-08-25")
    saved = daily.store_daily_report("Тест", REPORT, "2026-08-27")
    assert saved["replaced"] is False and saved["contractors"] == 9
    # Повтор того же дня заменяет отчёт, а не копит второй.
    again = daily.store_daily_report("Тест", REPORT, "2026-08-27")
    assert again["replaced"] is True

    summary = daily.daily_summary("Тест")
    assert summary["available"] is True
    assert [r["date"] for r in summary["rows"]] == ["2026-08-25", "2026-08-27"]
    assert summary["rows"][-1]["workers"] == 129
    # Молчание — тоже сигнал: разрыв в днях перед последним отчётом назван.
    assert summary["gap_days"] == 2
    assert summary["latest"]["date"] == "2026-08-27"
    assert summary["latest"]["contractors"][0]["name"] == "НУР"


def test_not_a_report_is_rejected_aloud(project_dir):
    with pytest.raises(ValueError):
        daily.store_daily_report("Тест", "привет, как дела?", "2026-08-27")


def test_empty_project_reports_reason_not_emptiness(project_dir):
    summary = daily.daily_summary("Пусто")
    assert summary["available"] is False
    assert "не загружались" in summary["reason"]


def test_liveness_finds_the_work_by_word_overlap(project_dir):
    daily.store_daily_report("Тест", REPORT, "2026-08-27")
    live = daily.work_liveness(
        "Тест", "Устройство опалубки перекрытия типового этажа", cut="2026-08-27")
    assert live["checked"] is True
    assert live["mention"] is not None
    assert live["mention"]["date"] == "2026-08-27"
    assert "опалубки" in live["mention"]["line"]
    # Работа, которой в отчётах нет, честно не упоминается — а не «нет данных».
    silent = daily.work_liveness("Тест", "Пусконаладка лифтового хозяйства",
                                 cut="2026-08-27")
    assert silent["checked"] is True and silent["mention"] is None


def test_doubts_consult_the_daily_reports():
    import inspect
    source = inspect.getsource(scenarios.doubts)
    assert "work_liveness" in source
    assert "не упоминалась" in source


def test_the_monitor_page_carries_the_daily_ui():
    page = monitor_page.MONITOR_PAGE
    assert 'id="dailyText"' in page
    assert "/monitor/daily" in page
    assert 'id="peopleCard"' in page
    assert "Фото не обязательны" in page
    # Живость в сомнениях рисуется, когда сервер её прислал.
    assert "r.daily" in page

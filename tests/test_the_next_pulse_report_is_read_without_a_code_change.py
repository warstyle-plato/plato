"""Месячный отчёт «Пульс» приезжает файлом рядом с прежним.

Имя июльского файла было зашито в `dynamics.py` строкой: августовский лёг бы в
тот же каталог, а читался бы всё равно июльский — и заметить это было бы негде,
потому что ряды на экране выглядят одинаково при любой дате. То же правило, что
у `VERSION`: копию негде обновлять, потому что копии нет.
"""

from __future__ import annotations

import json
from pathlib import Path

from market_search.dynamics import SalesDynamics
from market_search.market_reference import MoscowMarket


def _write(folder: Path, name: str, payload: dict) -> None:
    (folder / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_the_newest_monthly_file_wins(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "moscow-dynamics-2026-07.json",
        {"source": "июль", "last_month": "2026-07", "months": ["2026-07"], "projects": {"1": {"sold": [4]}}},
    )
    _write(
        tmp_path,
        "moscow-dynamics-2026-08.json",
        {"source": "август", "last_month": "2026-08", "months": ["2026-08"], "projects": {"1": {"sold": [7]}}},
    )
    dynamics = SalesDynamics.bundled(tmp_path)
    assert dynamics.last_month == "2026-08"
    assert dynamics.series(1, keys=("sold",)) == [{"month": "2026-08", "sold": 7}]


def test_a_broken_file_does_not_take_the_history_down(tmp_path: Path) -> None:
    """Битый файл — это «прежний ряд», а не «рядов нет»."""
    _write(
        tmp_path,
        "moscow-dynamics-2026-07.json",
        {"source": "июль", "last_month": "2026-07", "months": ["2026-07"], "projects": {"1": {"sold": [4]}}},
    )
    (tmp_path / "moscow-dynamics-2026-08.json").write_text("{ не json", encoding="utf-8")
    dynamics = SalesDynamics.bundled(tmp_path)
    assert dynamics.last_month == "2026-07"


def test_no_month_is_written_into_the_code() -> None:
    """Дата отчёта живёт в имени файла, а не в исходнике."""
    source = (Path(__file__).resolve().parent.parent / "market_search" / "dynamics.py").read_text(
        encoding="utf-8"
    )
    body = source[source.index("class SalesDynamics") :]
    assert "2026-" not in body, "имя выпуска вернулось в код"


def test_the_city_summary_follows_the_same_rule(tmp_path: Path) -> None:
    _write(tmp_path, "moscow-market-2026-07.json", {"last_month": "2026-07", "current": {"Бизнес": {}}})
    _write(tmp_path, "moscow-market-2026-08.json", {"last_month": "2026-08", "current": {"Бизнес": {}}})
    assert MoscowMarket.bundled(tmp_path).observed_at == "2026-08"

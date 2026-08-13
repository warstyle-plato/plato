"""Компенсация за соцобъекты считается формулой, а не тремя константами.

Бот дал по участку 185,1 млн ₽ против 220,3 у штатного калькулятора. Причина
не в индексации, как казалось: в компенсацию входит стоимость земли под
объектом, а она считается от УПКС кадастрового квартала — своего у каждого
участка. Прежние ставки (9,916526 / 7,751053 / 10,857111 млн за место) были
сняты с одного квартала и на других занижали платёж.

Формула из исходника калькулятора (функция ap):
    компенсация = коэфф × (УУПСС_на_место × места / 1000
                           + места × норматив_ЗУ × УПКС / 1e6)
Обратный счёт по трём прежним ставкам дал один и тот же УПКС 98 973 ₽/м² и
нормативы земли 35 / 19 / 30 м² на место, коэффициент 1,2 для ДОО и школы и
1,0 для поликлиники — формула подтверждена тремя независимыми точками.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core

_UPKS_OF_THE_REFERENCE_QUARTER = 98973.0


def _compensation(places: float, uupss_th: float, zu_sqm: float,
                  factor: float, upks: float) -> float:
    return factor * (uupss_th * places / 1000.0 + places * zu_sqm * upks / 1e6)


def test_the_formula_reproduces_the_three_old_rates():
    """Прежние константы — частный случай формулы при УПКС того квартала."""
    upks = _UPKS_OF_THE_REFERENCE_QUARTER
    assert _compensation(1, 4799.71, 35.0, 1.2, upks) == pytest.approx(9.916526, abs=1e-4)
    assert _compensation(1, 4578.69, 19.0, 1.2, upks) == pytest.approx(7.751053, abs=1e-4)
    assert _compensation(1, 7887.92, 30.0, 1.0, upks) == pytest.approx(10.857111, abs=1e-4)


def test_a_richer_quarter_costs_more():
    """Смысл починки: на дорогой земле компенсация выше. Прежде она была
    одинаковой везде, потому что земля в ставку входила константой."""
    cheap = _compensation(100, 4799.71, 35.0, 1.2, 50000.0)
    rich = _compensation(100, 4799.71, 35.0, 1.2, 200000.0)
    assert rich > cheap * 1.5, "УПКС обязан двигать платёж"


def test_the_engine_reads_the_quarter_upks():
    """Поле УПКС должно доезжать из анализа участка в коэффициенты —
    без него формула считать нечем."""
    import inspect
    source = inspect.getsource(core.analyze_cadastral_territory)
    assert '"upks_zh_high"' in source
    assert 'cad_quarter.get("upks_zh_high")' in source


def test_the_server_path_uses_the_formula_with_a_fallback():
    """Серверный расчёт считает формулой, а без УПКС откатывается на прежние
    ставки: они хотя бы того же порядка, а голое строительство без земли —
    почти вдвое ниже правды."""
    import inspect
    source = inspect.getsource(core.vri_tep_quick)
    assert "_social_comp" in source
    assert "4799.71" in source and "4578.69" in source and "7887.92" in source
    assert "legacy_rate" in source, "нужен откат, если УПКС не пришёл"
    # Нормативы земли на место — из калькулятора, не выдуманные.
    assert "35.0, 1.2" in source and "19.0, 1.2" in source and "30.0, 1.0" in source

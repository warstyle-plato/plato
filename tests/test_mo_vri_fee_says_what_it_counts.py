"""МО: плата за смену ВРИ и подпись к ней говорят одно.

Ночная проверка «Посадка ↔ нормативы» 25.10.2026 (В1): на участке ИЖС в
Рублёво (50:20:0010101:1) в модель уходило 200,8 млн ₽, а рядом стояло «плата
по методике не определяется». Кадастровая стоимость ИЖС выше целевой для
многоэтажной застройки — разница отрицательная, но в формуле 1745-ПП она
сокращается, и плата всё равно считается. Методика не меняется (её вопрос —
у «Нормативки»); меняется подпись: она называет взятую сумму и откуда она.

Числа — ответ прода 25.10.2026 по этому участку.

Запуск: python3 -m pytest tests/test_mo_vri_fee_says_what_it_counts.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core

RUBLYOVO = [{"cadastral_number": "50:20:0010101:1", "area_sqm": 3000.0,
             "permitted_use": "Для индивидуального жилищного строительства",
             "cadastral_value_rub": 50064840.0}]


def _rublyovo(**over):
    args = dict(upks_target=8747.63, upks_average_oks=116541.94,
                apartments_sqm=9000.0, market_price_rub_per_sqm=223135.0, kd=0.1)
    args.update(over)
    return core.mo_vri_payment(RUBLYOVO, **args)


def test_a_counted_fee_is_not_called_undetermined():
    vri = _rublyovo()
    assert vri["delta_rub"] < 0
    assert vri["payment_used_mln"] and vri["payment_used_mln"] > 0
    text = " ".join(vri["warnings"])
    assert "не определяется" not in text, \
        "в модель уходит сумма, а подпись говорит, что платы нет"
    shown = f"{vri['payment_used_mln']:,.1f}".replace(",", " ").replace(".", ",")
    assert f"{shown} млн ₽" in text, "подпись обязана назвать взятую сумму"


def test_without_data_for_the_formula_the_caption_says_nothing_was_counted():
    vri = _rublyovo(kd=None, kd_missing_reason="Кд для округа не установлен.")
    assert vri["payment_used_mln"] is None
    assert any("не рассчитана" in w for w in vri["warnings"])
    assert not any("в расчёт взята" in w for w in vri["warnings"])

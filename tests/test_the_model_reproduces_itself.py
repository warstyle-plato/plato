"""Один и тот же расчёт на одних вводных даёт одни и те же числа.

09.09.2026: приёмка перекладки «ни одно число не сдвинулось» показала семь
расхождений — и они оказались не правкой. Два прогона ОДНОГО кода расходились
в последнем разряде у `tax_margin_by_product`.

Причина — обход МНОЖЕСТВА строк: ключи расписания это строки, порядок множества
строк меняет `PYTHONHASHSEED` от процесса к процессу, и сумма float'ов
складывалась каждый раз иначе. Мест было два — общий пул `core` и продукты.

Ловится это только двумя ПРОЦЕССАМИ: внутри одного процесса семя одно, порядок
один и тот же, и поломка невидима. Поэтому проверка и запускает подпроцессы, а
не зовёт функцию дважды — тест, зовущий её дважды, был бы зелёным на сломанном
коде.

Цена невоспроизводимости не в последнем разряде: пока модель не сходится сама с
собой, никакая сверка «числа не сдвинулись» не значит ничего — ни у перекладки,
ни у паритета с книгой.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Считаем в подпроцессе и печатаем числа: важен не весь отчёт, а то, что он
# один и тот же. Объекты включены — у них своя строка в налоговой марже.
SCRIPT = """
import json, sys
sys.path.insert(0, %r)
import main_legacy as core
inputs = dict(core.DEFAULT_INPUTS)
inputs.update({
    "offices_enabled": True, "offices_gba_sqm": 40000, "offices_saleable_sqm": 34000,
    "retail_enabled": True, "retail_gba_sqm": 25000, "retail_saleable_sqm": 21000,
    "above_parking_enabled": True, "above_parking_spaces": 300,
    "sports_enabled": True, "sports_gba_sqm": 8000, "sports_saleable_sqm": 6500,
})
result = core.calculate(core.CalcRequest(inputs=inputs, tep=core.TEP_DEFAULT, rates=[]))
finance = result.get("finance") or {}
print(json.dumps({
    "margin": finance.get("tax_margin_by_product") or {},
    "llcr": finance.get("llcr"),
    "financing_cost": finance.get("financing_cost"),
}, sort_keys=True))
""" % (str(ROOT),)


def _run(seed: str) -> dict:
    env = dict(os.environ, PYTHONHASHSEED=seed)
    out = subprocess.run([sys.executable, "-c", SCRIPT], capture_output=True,
                         text=True, env=env, cwd=str(ROOT), timeout=900)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_the_same_inputs_give_the_same_numbers_under_any_hash_seed() -> None:
    """Разные семена — один ответ.

    На прежнем коде расходился `tax_margin_by_product`: в общем пуле и у
    продуктов месяцы обходились порядком множества.
    """
    first = _run("0")
    for seed in ("1", "12345"):
        other = _run(seed)
        assert other == first, (seed, first, other)


def test_the_check_would_notice_an_unordered_walk() -> None:
    """Проверка, которая не падает на поломке, — не проверка.

    Множество строк обходится в разном порядке при разных семенах: если бы это
    было не так, соседний тест был бы зелёным на любом коде и не значил бы
    ничего. Утверждение здесь ровно об этом — про сам приём, а не про движок.
    """
    script = ("import json;"
              "print(json.dumps(list({'2027-01','2027-02','2027-03','2027-04',"
              "'2027-05','2027-06','2027-07','2027-08','2027-09','2027-10'})))")
    orders = set()
    for seed in ("0", "1", "12345", "777", "31337"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        out = subprocess.run([sys.executable, "-c", script], capture_output=True,
                             text=True, env=env, timeout=120)
        orders.add(tuple(json.loads(out.stdout)))
    assert len(orders) > 1, "семя не меняет порядок множества — приём не работает"

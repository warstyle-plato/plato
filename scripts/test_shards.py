#!/usr/bin/env python3
"""Разбиение набора на доли — объявлено ОДИН раз и читается всеми, кто гоняет.

Набор дошёл до 5324 тестов и 1:38:43 при потолке 120 минут (замер прогона 440,
09.09.2026). Времени при этом нет у отдельных тестов: двадцать два самых
дорогих дают 1053 с — 17,8% прогона, — а остальные 5302 идут по 0,92 с.
Значит удешевлять нечего, а поднимать потолок — откладывать: его поднимали
45 → 75 → 120, и дважды он кусал в тот же день. Четыре доли дают около
двадцати пяти минут и НЕ СНИМАЮТ НИ ОДНОЙ ПРОВЕРКИ.

Почему доли, а не `pytest-xdist` в одном процессе: наши тесты пишут на диск, и
правило про изоляцию `DATA_DIR` выведено из настоящей поломки — проверка
находила в рабочем каталоге снимок соседа и врала в обе стороны. Отдельные
раннеры дают ту изоляцию, на которую мы уже опираемся; воркеры xdist делят
файловую систему.

Список долей не хранится: он СЧИТАЕТСЯ от того, что лежит в `tests/`. Файл,
заведённый завтра, попадает в долю тем, что он появился, — а не тем, что о нём
вспомнили. Ровно поэтому у `VERSION` нет копии.

Вес файла — его размер. Это грубая мера (самый долгий тест здесь ждёт
таймаута сети и весит мало), и она нарочно не точная: точная потребовала бы
хранить замеры, то есть завести число, которое стареет молча. Раскладка
жадная — самые тяжёлые первыми, каждый в самую лёгкую долю: перекос она даёт
в минуты, а не в разы.

Запуск:
    python3 scripts/test_shards.py --shards 4 --shard 1   # файлы доли 1
    python3 scripts/test_shards.py --shards 4 --plan      # что в какой доле
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"

# `conftest.py` подхватывается сам и тестом не является: переданный явно, он
# попал бы в долю как файл без единого теста.
NOT_A_TEST = {"conftest.py", "__init__.py"}


def test_files() -> list[Path]:
    """Тот же набор, что собирает `pytest tests`, — файлами и по порядку."""
    return sorted(
        path for path in TESTS.glob("test_*.py")
        if path.name not in NOT_A_TEST
    )


def plan(shards: int) -> list[list[Path]]:
    """Раскладка по долям: тяжёлые первыми, каждый — в самую лёгкую долю."""
    if shards < 1:
        raise SystemExit("долей должно быть хотя бы одна")
    files = test_files()
    if shards > len(files):
        raise SystemExit(
            f"долей {shards}, а файлов {len(files)}: пустая доля — это "
            "«тестов не собрано», и pytest ответит на неё отказом")
    # Порядок раскладки: по весу вниз, при равном весе — по имени, чтобы
    # раскладка не зависела от порядка файловой системы.
    ordered = sorted(files, key=lambda path: (-path.stat().st_size, path.name))
    buckets: list[list[Path]] = [[] for _ in range(shards)]
    weights = [0] * shards
    for path in ordered:
        lightest = min(range(shards), key=lambda i: (weights[i], i))
        buckets[lightest].append(path)
        weights[lightest] += path.stat().st_size
    return [sorted(bucket) for bucket in buckets]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shards", type=int, required=True)
    parser.add_argument("--shard", type=int, help="номер доли, считая с единицы")
    parser.add_argument("--plan", action="store_true", help="показать раскладку")
    args = parser.parse_args()

    buckets = plan(args.shards)
    if args.plan:
        total = sum(path.stat().st_size for path in test_files())
        for number, bucket in enumerate(buckets, start=1):
            weight = sum(path.stat().st_size for path in bucket)
            print(f"доля {number}: файлов {len(bucket)}, "
                  f"вес {weight / 1024:.0f} КБ ({weight / total * 100:.1f}%)")
        return 0
    if args.shard is None:
        raise SystemExit("нужен --shard или --plan")
    if not 1 <= args.shard <= args.shards:
        raise SystemExit(f"доля {args.shard} вне 1..{args.shards}")
    for path in buckets[args.shard - 1]:
        print(path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

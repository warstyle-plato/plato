#!/usr/bin/env python3
"""Версия на main обязана строго расти.

Две параллельные сессии взяли номер от одного и того же main и обе объявили
0.18.45 — разные правки под одним номером. Общей памяти у сессий нет, общий у
них репозиторий, поэтому проверяет он: если движок изменился, а `VERSION` не
выросла, сборка красная.

Второй случай той же болезни (19.08.2026): ветка взяла 0.18.77, пока соседняя
сессия довела main до 0.18.81. Проверка на main это ловит — но уже после
слияния, красной сборкой и без образа. Поэтому та же проверка идёт на ветке
против базы (`--base origin/main`), а номер не выбирается на глаз: `--next`
печатает первый свободный над базой, с переходом через сотню (x.y.99 → x.(y+1).1).

Запуск:
    python3 scripts/check_version_grows.py [предыдущий_коммит]
    python3 scripts/check_version_grows.py --base origin/main
    python3 scripts/check_version_grows.py --next --base origin/main
"""

from __future__ import annotations

import re
import subprocess
import sys

ENGINE = "main_legacy.py"
_VERSION = re.compile(r'^VERSION = "([^"]+)"', re.M)


def _version(text: str) -> tuple[int, ...]:
    found = _VERSION.search(text)
    if not found:
        raise SystemExit(f"В {ENGINE} не нашлась строка VERSION = \"…\"")
    parts = found.group(1).split(".")
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        raise SystemExit(f"Версия не разбирается на числа: {found.group(1)}")


def _show(ref: str) -> str:
    data = subprocess.run(
        ["git", "show", f"{ref}:{ENGINE}"],
        capture_output=True,
        check=True,
    ).stdout
    # A release guard must still be able to reject or recover from a damaged
    # previous revision. VERSION is ASCII; replacement keeps that line readable
    # without treating invalid source bytes as valid application code.
    return data.decode("utf-8", errors="replace")


def _next_version(base: tuple[int, ...]) -> str:
    """Первый свободный номер над базой.

    Патч за сотню не уходит — после x.y.99 растёт средний разряд. Правило было
    в знании о проекте и держалось на памяти: утро 16.08.2026 успело выпустить
    0.17.100–105.
    """
    parts = list(base) or [0, 0, 0]
    parts[-1] += 1
    if parts[-1] > 99 and len(parts) > 1:
        parts[-1] = 1
        parts[-2] += 1
    return ".".join(str(part) for part in parts)


def main() -> int:
    argv = [arg for arg in sys.argv[1:]]
    show_next = "--next" in argv
    argv = [arg for arg in argv if arg != "--next"]
    base_ref = ""
    if "--base" in argv:
        index = argv.index("--base")
        try:
            base_ref = argv[index + 1]
        except IndexError:
            raise SystemExit("--base без ссылки: укажите ветку или коммит.")
        argv = argv[:index] + argv[index + 2:]
    if show_next:
        reference = base_ref or "origin/main"
        try:
            print(_next_version(_version(_show(reference))))
        except subprocess.CalledProcessError:
            raise SystemExit(f"Не удалось прочитать {ENGINE} в {reference}.")
        return 0
    previous_ref = base_ref or (argv[0] if argv else "HEAD~1")
    try:
        before_text = _show(previous_ref)
    except subprocess.CalledProcessError:
        # Первый коммит или мелкая история: сравнивать не с чем — это не повод
        # ронять сборку.
        print(f"Предыдущей версии нет ({previous_ref}) — сравнение пропущено.")
        return 0
    after_text = _show("HEAD")
    if before_text == after_text:
        print("Движок не менялся — версия может остаться прежней.")
        return 0
    if ("\x00" in before_text or "\ufffd" in before_text) and not (
        "\x00" in after_text or "\ufffd" in after_text
    ):
        print("Повреждённое ядро восстановлено — сравнение версии пропущено.")
        return 0
    before, after = _version(before_text), _version(after_text)
    if after > before:
        print(f"Версия выросла: {'.'.join(map(str, before))} → {'.'.join(map(str, after))}")
        return 0
    print(f"Версия не выросла: было {'.'.join(map(str, before))}, "
          f"стало {'.'.join(map(str, after))}.", file=sys.stderr)
    print("Движок изменился, значит выпуск другой. Поднимите VERSION в "
          f"{ENGINE} — она объявляется там один раз.", file=sys.stderr)
    print(f"Свободный номер над этой базой: {_next_version(before)}. "
          "Его же печатает `python3 scripts/check_version_grows.py --next "
          "--base origin/main`.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
